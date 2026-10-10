"""CircuitIR adapter for QSteed's circuit transpiler."""

from __future__ import annotations

import random
from collections import deque
from numbers import Integral, Real
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
TARGET_FIELDS = frozenset(
    {
        "basis_gates",
        "coupling_map",
        "provider",
        "backend",
        "chip_info",
        "target_qubits",
    }
)
_QSTEED_RANDOM_LOCK = Lock()


class QSteedCompiler:
    """Compile static FlagQuantum circuits with QSteed."""

    manifest = ExtensionManifest(
        name="qsteed",
        version="0.1.2",
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

        basis, edges, execution_target = _validate(program, target)
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
        metadata = dict(program.metadata)
        if execution_target is not None:
            metadata["execution_target"] = execution_target
        result = CircuitIR(
            n_wires=program.n_wires,
            instructions=tuple(instructions),
            version=program.version,
            dtype=program.dtype,
            shape=program.shape,
            metadata=metadata,
        )
        _check_topology(result, edges)
        return result

    def close(self) -> None:
        self.active = False


def create_extension() -> QSteedCompiler:
    """Return a fresh extension instance for FlagQuantum discovery."""

    return QSteedCompiler()


def _validate(program: CircuitIR, target: Mapping[str, Any] | None) -> tuple[
    tuple[str, ...],
    tuple[tuple[int, int], ...],
    Mapping[str, Any] | None,
]:
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

    chip_info = target.get("chip_info")
    if chip_info is not None:
        if "basis_gates" in target or "coupling_map" in target:
            raise ValueError(
                "chip_info cannot be combined with basis_gates or coupling_map"
            )
        provider = str(target.get("provider", "")).strip().lower()
        backend = str(target.get("backend", "")).strip()
        if provider != "quafu" or not backend or not isinstance(chip_info, Mapping):
            raise ValueError(
                "QSteed chip_info targets require provider='quafu' and backend"
            )
        if "target_qubits" in target:
            edges, target_qubits = _validate_quafu_subgraph(
                chip_info, target["target_qubits"], program.n_wires
            )
        else:
            edges, target_qubits = _select_quafu_subgraph(chip_info, program.n_wires)
        execution_target: Mapping[str, Any] | None = {
            "provider": provider,
            "backend": backend,
            "compiler": None,
            "target_qubits": list(target_qubits),
        }
        raw_basis = tuple(sorted(SUPPORTED_GATES))
    else:
        if "target_qubits" in target:
            raise ValueError("target_qubits requires Quafu chip_info")
        if "provider" in target or "backend" in target:
            raise ValueError("provider and backend require chip_info")
        edges = ()
        execution_target = None
        raw_basis = target.get("basis_gates", tuple(sorted(SUPPORTED_GATES)))
    basis = tuple(dict.fromkeys(str(gate).strip().lower() for gate in raw_basis))
    if not basis or any(gate not in SUPPORTED_GATES for gate in basis):
        raise ValueError("basis_gates must be a non-empty subset of h/x/rx/ry/rz/cx")

    if chip_info is None:
        raw_edges = target.get("coupling_map", ())
        parsed_edges = []
        for raw_edge in raw_edges:
            if not isinstance(raw_edge, Sequence) or isinstance(raw_edge, (str, bytes)):
                raise TypeError("each coupling_map edge must contain two wire indices")
            edge = tuple(raw_edge)
            if len(edge) != 2:
                raise ValueError(
                    "each coupling_map edge must contain exactly two wires"
                )
            left, right = (int(edge[0]), int(edge[1]))
            if (
                left == right
                or min(left, right) < 0
                or max(left, right) >= program.n_wires
            ):
                raise ValueError(f"invalid coupling_map edge {(left, right)!r}")
            normalized = tuple(sorted((left, right)))
            if normalized not in parsed_edges:
                parsed_edges.append(normalized)
        edges = tuple(parsed_edges)
    if edges and set().union(*(set(edge) for edge in edges)) != set(
        range(program.n_wires)
    ):
        raise ValueError("coupling_map must cover every circuit wire")
    if edges and not _connected(program.n_wires, tuple(edges)):
        raise ValueError("coupling_map must be connected")
    if edges and set(basis) != SUPPORTED_GATES:
        raise ValueError("topology routing requires the fixed h/x/rx/ry/rz/cx basis")
    return basis, tuple(sorted(edges)), execution_target


def _validate_quafu_subgraph(
    chip_info: Mapping[str, Any], raw_qubits: Any, n_wires: int
) -> tuple[tuple[tuple[int, int], ...], tuple[int, ...]]:
    """Validate an ordered physical mapping and express its topology logically."""

    if not isinstance(raw_qubits, Sequence) or isinstance(raw_qubits, (str, bytes)):
        raise TypeError("target_qubits must be an ordered sequence")
    if any(
        isinstance(qubit, bool) or not isinstance(qubit, Integral)
        for qubit in raw_qubits
    ):
        raise TypeError("target_qubits must contain physical qubit integers")
    target_qubits = tuple(int(qubit) for qubit in raw_qubits)
    if len(target_qubits) != n_wires or len(set(target_qubits)) != n_wires:
        raise ValueError(
            "target_qubits must contain one unique physical qubit per logical wire"
        )

    available = set()
    for label, info in dict(chip_info.get("qubits_info", {})).items():
        index = info.get("index") if isinstance(info, Mapping) else None
        if index is None:
            digits = "".join(
                character for character in str(label) if character.isdigit()
            )
            index = int(digits) if digits else None
        if index is not None:
            available.add(int(index))
    missing = tuple(qubit for qubit in target_qubits if qubit not in available)
    if missing:
        raise ValueError(f"target_qubits are absent from chip_info: {missing}")
    if n_wires == 1:
        return (), target_qubits

    logical_wire = {qubit: wire for wire, qubit in enumerate(target_qubits)}
    edges = set()
    for coupler in dict(chip_info.get("couplers_info", {})).values():
        if not isinstance(coupler, Mapping):
            continue
        raw_edge = coupler.get("qubits_index")
        if not isinstance(raw_edge, Sequence) or len(raw_edge) < 2:
            continue
        left, right = int(raw_edge[0]), int(raw_edge[1])
        if (
            left in logical_wire
            and right in logical_wire
            and float(coupler.get("fidelity", 0.0)) > 0
        ):
            edges.add(tuple(sorted((logical_wire[left], logical_wire[right]))))
    logical_edges = tuple(sorted(edges))
    if not logical_edges or not _connected(n_wires, logical_edges):
        raise ValueError("target_qubits must form a connected calibrated subgraph")
    return logical_edges, target_qubits


def _select_quafu_subgraph(
    chip_info: Mapping[str, Any], n_wires: int
) -> tuple[tuple[tuple[int, int], ...], tuple[int, ...]]:
    """Use QSteed's resource manager to select a connected physical subgraph."""

    if n_wires == 1:
        candidates = []
        for label, info in dict(chip_info.get("qubits_info", {})).items():
            index = info.get("index") if isinstance(info, Mapping) else None
            if index is None:
                digits = "".join(
                    character for character in str(label) if character.isdigit()
                )
                index = int(digits) if digits else None
            if index is not None:
                fidelity = (
                    float(info.get("fidelity", 0.0))
                    if isinstance(info, Mapping)
                    else 0.0
                )
                candidates.append((fidelity, -int(index), int(index)))
        if not candidates:
            raise ValueError("Quafu chip_info contains no usable physical qubit")
        return (), (max(candidates)[2],)

    structure = []
    seen = set()
    for coupler in dict(chip_info.get("couplers_info", {})).values():
        if not isinstance(coupler, Mapping):
            continue
        raw_qubits = coupler.get("qubits_index")
        if not isinstance(raw_qubits, Sequence) or len(raw_qubits) < 2:
            continue
        left, right = int(raw_qubits[0]), int(raw_qubits[1])
        edge = tuple(sorted((left, right)))
        fidelity = float(coupler.get("fidelity", 0.0))
        if left == right or fidelity <= 0 or edge in seen:
            continue
        seen.add(edge)
        structure.append([edge[0], edge[1], fidelity])
    if not structure:
        raise ValueError("Quafu chip_info contains no usable coupler")

    from ._vendor.qsteed.resourcemanager.build_library import BuildLibrary
    from ._vendor.qsteed.resourcemanager.utils import virtual_qubits

    selector = BuildLibrary(fidelity_threshold=0.0)
    connected = selector.connected_substructure(structure)
    selected = selector.substructure(structure, connected, n_wires, max_iterations=1)[
        0
    ][1]
    coupling, virtual_to_physical = virtual_qubits(selected)
    target_qubits = tuple(int(virtual_to_physical[index]) for index in range(n_wires))
    edges = tuple(
        sorted({tuple(sorted((int(edge[0]), int(edge[1])))) for edge in coupling})
    )
    return edges, target_qubits


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
    from ._vendor.qsteed.backends.backend import Backend
    from ._vendor.qsteed.passes.mapping.baselayout import Layout
    from ._vendor.qsteed.passes.mapping.layout.sabre_layout import SabreLayout
    from ._vendor.qsteed.passes.model import Model
    from ._vendor.qsteed.passes.unroll.unroll_to_2qubit import UnrollTo2Qubit
    from ._vendor.qsteed.passes.unroll.unroll_to_basis import UnrollToBasis
    from ._vendor.qsteed.passflow.passflow import PassFlow
    from ._vendor.qsteed.transpiler.transpiler import Transpiler

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
        _expose_idle_wires_to_qsteed(circuit, n_wires)
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


def _expose_idle_wires_to_qsteed(circuit, n_wires: int) -> None:
    """Prevent QSteed SABRE from omitting state for idle topology vertices."""

    used_wires = {wire for gate in circuit.gates for wire in gate.pos}
    for wire in sorted(set(range(n_wires)) - used_wires):
        circuit.x(wire)
        circuit.x(wire)


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
