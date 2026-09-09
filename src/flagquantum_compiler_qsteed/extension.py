"""CircuitIR adapter for QSteed's circuit transpiler."""

from __future__ import annotations

import random
from collections import deque
from numbers import Real
from threading import Lock
from typing import Any, Mapping, Sequence

from flagquantum import CircuitIR, Instruction
from flagquantum.ecosystem.extensions import (
    CapabilityRequest,
    CapabilityResponse,
    ExtensionConfig,
    ExtensionManifest,
)

SUPPORTED_GATES = frozenset({"h", "x", "rx", "ry", "rz", "cx"})
PARAMETERIZED_GATES = frozenset({"rx", "ry", "rz"})
TARGET_FIELDS = frozenset({"basis_gates", "coupling_map"})
_QSTEED_RANDOM_LOCK = Lock()


class QSteedCompiler:
    """Compile static FlagQuantum circuits with QSteed."""

    manifest = ExtensionManifest(
        name="qsteed",
        version="0.1.0",
        kind="compiler",
        capabilities=frozenset(
            {"circuit_ir", "static_circuit", "basis_gates", "coupling_map"}
        ),
    )

    def __init__(self) -> None:
        self.active = False

    def negotiate(self, request: CapabilityRequest) -> CapabilityResponse:
        missing = request.required - self.manifest.capabilities
        blockers = []
        if missing:
            blockers.append("missing capabilities: " + ", ".join(sorted(missing)))
        if request.require_gradients:
            blockers.append("QSteed circuit compilation does not compute gradients")
        return CapabilityResponse(
            accepted=not blockers,
            supported=self.manifest.capabilities,
            blockers=tuple(blockers),
        )

    def start(self, config: ExtensionConfig) -> None:
        if config.values:
            raise ValueError("the QSteed compiler plugin has no runtime configuration")
        self.active = True

    def compile(
        self,
        program: CircuitIR,
        *,
        target: Mapping[str, Any] | None = None,
    ) -> CircuitIR:
        if not self.active:
            raise RuntimeError("QSteed compiler is not active")
        if not isinstance(program, CircuitIR):
            raise TypeError("QSteed compilation requires a FlagQuantum CircuitIR")

        basis, edges = _validate(program, target)
        circuit = _to_quafu(program)
        compiled, final_layout = _transpile(
            circuit,
            n_wires=program.n_wires,
            basis=tuple(basis),
            edges=edges,
        )
        instructions = list(_from_quafu(compiled, basis))
        if final_layout is not None:
            for left, right in _restoring_swaps(final_layout, edges):
                instructions.extend(
                    (
                        Instruction("cx", (left, right)),
                        Instruction("cx", (right, left)),
                        Instruction("cx", (left, right)),
                    )
                )
        result = CircuitIR(
            n_wires=program.n_wires,
            instructions=tuple(instructions),
            version=program.version,
            dtype=program.dtype,
            shape=program.shape,
            metadata=program.metadata,
        )
        _check_topology(result, edges)
        return result

    def close(self) -> None:
        self.active = False


def create_extension() -> QSteedCompiler:
    """Return a fresh extension instance for FlagQuantum discovery."""

    return QSteedCompiler()


def _validate(
    program: CircuitIR, target: Mapping[str, Any] | None
) -> tuple[tuple[str, ...], tuple[tuple[int, int], ...]]:
    target = dict(target or {})
    unknown = sorted(set(target) - TARGET_FIELDS)
    if unknown:
        raise ValueError("unsupported QSteed target field(s): " + ", ".join(unknown))
    if program.observables or program.measurements:
        raise ValueError("the QSteed static compiler does not accept result semantics")

    for instruction in program.instructions:
        if instruction.name not in SUPPORTED_GATES:
            raise ValueError(f"unsupported QSteed instruction {instruction.name!r}")
        if instruction.matrix is not None or instruction.metadata:
            raise ValueError(
                f"instruction {instruction.name!r} contains unsupported custom semantics"
            )
        expected = {"theta"} if instruction.name in PARAMETERIZED_GATES else set()
        if set(instruction.params) != expected:
            raise ValueError(
                f"instruction {instruction.name!r} requires parameters {sorted(expected)}"
            )
        for value in instruction.params.values():
            if isinstance(value, bool) or not isinstance(value, Real):
                raise TypeError("QSteed static circuit angles must be real numbers")

    raw_basis = target.get("basis_gates", tuple(sorted(SUPPORTED_GATES)))
    basis = tuple(dict.fromkeys(str(gate).strip().lower() for gate in raw_basis))
    if not basis or any(gate not in SUPPORTED_GATES for gate in basis):
        raise ValueError("basis_gates must be a non-empty subset of h/x/rx/ry/rz/cx")

    raw_edges = target.get("coupling_map", ())
    edges = []
    for raw_edge in raw_edges:
        if not isinstance(raw_edge, Sequence) or isinstance(raw_edge, (str, bytes)):
            raise TypeError("each coupling_map edge must contain two wire indices")
        edge = tuple(raw_edge)
        if len(edge) != 2:
            raise ValueError("each coupling_map edge must contain exactly two wires")
        left, right = (int(edge[0]), int(edge[1]))
        if left == right or min(left, right) < 0 or max(left, right) >= program.n_wires:
            raise ValueError(f"invalid coupling_map edge {(left, right)!r}")
        normalized = tuple(sorted((left, right)))
        if normalized not in edges:
            edges.append(normalized)
    if edges and set().union(*(set(edge) for edge in edges)) != set(
        range(program.n_wires)
    ):
        raise ValueError("coupling_map must cover every circuit wire")
    if edges and not _connected(program.n_wires, tuple(edges)):
        raise ValueError("coupling_map must be connected")
    if edges and set(basis) != SUPPORTED_GATES:
        raise ValueError("topology routing requires the fixed h/x/rx/ry/rz/cx basis")
    return basis, tuple(sorted(edges))


def _to_quafu(program: CircuitIR):
    from quafu import QuantumCircuit

    circuit = QuantumCircuit(program.n_wires)
    for instruction in program.instructions:
        wires = instruction.wires
        if instruction.name == "h":
            circuit.h(wires[0])
        elif instruction.name == "x":
            circuit.x(wires[0])
        elif instruction.name in PARAMETERIZED_GATES:
            getattr(circuit, instruction.name)(
                wires[0], float(instruction.params["theta"])
            )
        else:
            circuit.cnot(wires[0], wires[1])
    return circuit


def _transpile(circuit, *, n_wires: int, basis: tuple[str, ...], edges):
    from qsteed.backends.backend import Backend
    from qsteed.passes.mapping.baselayout import Layout
    from qsteed.passes.mapping.layout.sabre_layout import SabreLayout
    from qsteed.passes.model import Model
    from qsteed.passes.unroll.unroll_to_2qubit import UnrollTo2Qubit
    from qsteed.passes.unroll.unroll_to_basis import UnrollToBasis
    from qsteed.passflow.passflow import PassFlow
    from qsteed.transpiler.transpiler import Transpiler

    passes = [UnrollTo2Qubit()]
    if edges:
        coupling = [
            (left, right, 1.0)
            for edge in edges
            for left, right in (edge, tuple(reversed(edge)))
        ]
        backend = Backend(
            name="flagquantum-target",
            qubits_num=n_wires,
            coupling_list=coupling,
            basis_gates=list(basis),
        )
        model = Model(backend=backend)
        layout = Layout()
        layout.generate_trivial_layout(n_wires)
        used_wires = {wire for gate in circuit.gates for wire in gate.pos}
        for wire in sorted(set(range(n_wires)) - used_wires):
            circuit.x(wire)
            circuit.x(wire)
        passes.append(
            SabreLayout(
                heuristic="distance",
                max_iterations=0,
                sabre_initial_layout=layout,
            )
        )
    else:
        model = Model(
            backend=Backend(
                name="flagquantum-basis-target",
                qubits_num=n_wires,
                basis_gates=list(basis),
            )
        )
    passes.append(UnrollToBasis(basis_gates=list(basis)))

    transpiler = Transpiler(PassFlow(passes), model)
    with _QSTEED_RANDOM_LOCK:
        python_state = random.getstate()
        try:
            random.seed(0)
            result = transpiler.transpile(circuit)
        finally:
            random.setstate(python_state)

    if not edges:
        return result, None
    final_layout = dict(transpiler.model.get_layout()["final_layout"].v2p)
    return result, final_layout


def _from_quafu(circuit, basis: tuple[str, ...]) -> tuple[Instruction, ...]:
    instructions = []
    for gate in circuit.gates:
        name = str(gate.name).lower()
        if name not in basis or name not in SUPPORTED_GATES:
            raise RuntimeError(f"QSteed emitted unsupported gate {gate.name!r}")
        wires = tuple(int(wire) for wire in gate.pos)
        params = {"theta": float(gate.paras[0])} if name in PARAMETERIZED_GATES else {}
        instructions.append(Instruction(name, wires, params=params))
    return tuple(instructions)


def _restoring_swaps(
    final_v2p: Mapping[int, int], edges: tuple[tuple[int, int], ...]
) -> tuple[tuple[int, int], ...]:
    current = {int(virtual): int(physical) for virtual, physical in final_v2p.items()}
    if set(current) != set(current.values()):
        raise RuntimeError("QSteed returned an invalid final layout")
    swaps = []
    for virtual in sorted(current):
        physical = current[virtual]
        if physical == virtual:
            continue
        displaced = next(key for key, value in current.items() if value == virtual)
        path = _shortest_path(physical, virtual, edges)
        path_edges = list(zip(path, path[1:]))
        adjacent = path_edges + list(reversed(path_edges[:-1]))
        swaps.extend(adjacent)
        current[virtual], current[displaced] = current[displaced], current[virtual]
    if any(virtual != physical for virtual, physical in current.items()):
        raise RuntimeError("failed to restore QSteed's final layout")
    return tuple(swaps)


def _shortest_path(
    source: int, target: int, edges: tuple[tuple[int, int], ...]
) -> tuple[int, ...]:
    neighbors: dict[int, list[int]] = {}
    for left, right in edges:
        neighbors.setdefault(left, []).append(right)
        neighbors.setdefault(right, []).append(left)
    queue = deque([(source, (source,))])
    seen = {source}
    while queue:
        node, path = queue.popleft()
        if node == target:
            return path
        for neighbor in sorted(neighbors.get(node, ())):
            if neighbor not in seen:
                seen.add(neighbor)
                queue.append((neighbor, path + (neighbor,)))
    raise RuntimeError(f"no coupling path from wire {source} to {target}")


def _connected(n_wires: int, edges: tuple[tuple[int, int], ...]) -> bool:
    neighbors: dict[int, set[int]] = {}
    for left, right in edges:
        neighbors.setdefault(left, set()).add(right)
        neighbors.setdefault(right, set()).add(left)
    seen = {0}
    pending = [0]
    while pending:
        node = pending.pop()
        for neighbor in neighbors.get(node, ()):
            if neighbor not in seen:
                seen.add(neighbor)
                pending.append(neighbor)
    return len(seen) == n_wires


def _check_topology(program: CircuitIR, edges: tuple[tuple[int, int], ...]) -> None:
    if not edges:
        return
    allowed = set(edges)
    illegal = [
        instruction.wires
        for instruction in program.instructions
        if len(instruction.wires) == 2
        and tuple(sorted(instruction.wires)) not in allowed
    ]
    if illegal:
        raise RuntimeError(f"QSteed emitted non-local two-wire gates: {illegal!r}")
