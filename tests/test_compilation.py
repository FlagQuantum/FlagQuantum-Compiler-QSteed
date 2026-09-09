import random

import pytest
import torch
from flagquantum import Circuit, CircuitIR, Instruction
from flagquantum.ecosystem.extensions import ExtensionConfig

from flagquantum_compiler_qsteed import create_extension

BASIS = ("h", "x", "rx", "ry", "rz", "cx")
LINE = ((0, 1), (1, 2))
TOPOLOGIES = (
    ((0, 1), (1, 2), (2, 3)),
    ((0, 1), (1, 2), (2, 3), (3, 0)),
    ((0, 1), (0, 2), (0, 3)),
)


def _compile(program, *, coupling_map=LINE):
    extension = create_extension()
    extension.start(ExtensionConfig())
    try:
        return extension.compile(
            program,
            target={"basis_gates": BASIS, "coupling_map": coupling_map},
        )
    finally:
        extension.close()


def test_routed_circuit_obeys_topology_and_preserves_statevector():
    source = CircuitIR(
        3,
        (
            Instruction("h", (0,)),
            Instruction("x", (1,)),
            Instruction("rx", (0,), {"theta": 0.23}),
            Instruction("ry", (1,), {"theta": -0.41}),
            Instruction("rz", (2,), {"theta": 0.67}),
            Instruction("cx", (0, 2)),
            Instruction("cx", (2, 0)),
        ),
        dtype="complex128",
    )

    compiled = _compile(source)
    allowed = {tuple(sorted(edge)) for edge in LINE}

    assert all(instruction.name in BASIS for instruction in compiled.instructions)
    assert all(
        tuple(sorted(instruction.wires)) in allowed
        for instruction in compiled.instructions
        if len(instruction.wires) == 2
    )
    torch.testing.assert_close(
        Circuit.from_ir(compiled).state(),
        Circuit.from_ir(source).state(),
        rtol=1e-12,
        atol=1e-12,
    )


def test_routing_is_deterministic():
    source = CircuitIR(3, (Instruction("cx", (0, 2)),))

    first = _compile(source)
    second = _compile(source)

    assert first.content_hash == second.content_hash
    torch.testing.assert_close(
        Circuit.from_ir(first).state(),
        Circuit.from_ir(source).state(),
        rtol=1e-12,
        atol=1e-12,
    )


def test_quafu_target_keeps_logical_wires_and_records_physical_order():
    source = CircuitIR(3, (Instruction("cx", (0, 2)),), dtype="complex128")
    chip_info = {
        "qubits_info": {"Q10": {}, "Q11": {}, "Q12": {}, "Q20": {}},
        "couplers_info": {
            "C0": {"qubits_index": [10, 11], "fidelity": 0.999},
            "C1": {"qubits_index": [11, 12], "fidelity": 0.998},
            "C2": {"qubits_index": [12, 20], "fidelity": 0.7},
        },
    }
    extension = create_extension()
    extension.start(ExtensionConfig())
    try:
        compiled = extension.compile(
            source,
            target={
                "provider": "quafu",
                "backend": "ScQ-P10",
                "chip_info": chip_info,
            },
        )
    finally:
        extension.close()

    assert compiled.n_wires == 3
    assert compiled.metadata["execution_target"] == {
        "provider": "quafu",
        "backend": "ScQ-P10",
        "compiler": None,
        "target_qubits": [10, 11, 12],
    }
    assert all(max(instruction.wires) < 3 for instruction in compiled.instructions)
    torch.testing.assert_close(
        Circuit.from_ir(compiled).state(),
        Circuit.from_ir(source).state(),
        rtol=1e-12,
        atol=1e-12,
    )


def test_quafu_target_honors_explicit_ordered_physical_qubits():
    source = CircuitIR(3, (Instruction("cx", (0, 2)),), dtype="complex128")
    chip_info = {
        "qubits_info": {"Q10": {}, "Q11": {}, "Q12": {}, "Q20": {}},
        "couplers_info": {
            "C0": {"qubits_index": [10, 11], "fidelity": 0.999},
            "C1": {"qubits_index": [11, 12], "fidelity": 0.998},
            "C2": {"qubits_index": [12, 20], "fidelity": 0.997},
        },
    }
    extension = create_extension()
    extension.start(ExtensionConfig())
    try:
        compiled = extension.compile(
            source,
            target={
                "provider": "quafu",
                "backend": "Dongling",
                "chip_info": chip_info,
                "target_qubits": [20, 12, 11],
            },
        )
    finally:
        extension.close()

    assert compiled.metadata["execution_target"]["target_qubits"] == [20, 12, 11]
    torch.testing.assert_close(
        Circuit.from_ir(compiled).state(),
        Circuit.from_ir(source).state(),
        rtol=1e-12,
        atol=1e-12,
    )


@pytest.mark.parametrize(
    "target_qubits,error",
    [
        ([10, 10], "one unique physical qubit"),
        ([10, 20], "connected calibrated subgraph"),
        ([10, 99], "absent from chip_info"),
        ([10, 11.5], "physical qubit integers"),
    ],
)
def test_quafu_explicit_physical_qubits_fail_closed(target_qubits, error):
    chip_info = {
        "qubits_info": {"Q10": {}, "Q11": {}, "Q20": {}},
        "couplers_info": {
            "C0": {"qubits_index": [10, 11], "fidelity": 0.999},
        },
    }
    extension = create_extension()
    extension.start(ExtensionConfig())
    try:
        with pytest.raises((TypeError, ValueError), match=error):
            extension.compile(
                CircuitIR(2, (Instruction("cx", (0, 1)),)),
                target={
                    "provider": "quafu",
                    "backend": "Dongling",
                    "chip_info": chip_info,
                    "target_qubits": target_qubits,
                },
            )
    finally:
        extension.close()


@pytest.mark.parametrize("coupling_map", TOPOLOGIES, ids=("line", "ring", "star"))
@pytest.mark.parametrize("seed", (3, 17, 41))
def test_random_supported_circuits_preserve_semantics(seed, coupling_map):
    source = _random_circuit(seed)
    compiled = _compile(source, coupling_map=coupling_map)
    allowed = {tuple(sorted(edge)) for edge in coupling_map}

    assert all(instruction.name in BASIS for instruction in compiled.instructions)
    assert all(
        tuple(sorted(instruction.wires)) in allowed
        for instruction in compiled.instructions
        if len(instruction.wires) == 2
    )
    torch.testing.assert_close(
        Circuit.from_ir(compiled).state(),
        Circuit.from_ir(source).state(),
        rtol=1e-12,
        atol=1e-12,
    )


def _random_circuit(seed):
    generator = random.Random(seed)
    instructions = []
    for _ in range(16):
        name = generator.choice(BASIS)
        if name == "cx":
            wires = tuple(generator.sample(range(4), 2))
            instructions.append(Instruction(name, wires))
        elif name in {"rx", "ry", "rz"}:
            instructions.append(
                Instruction(
                    name,
                    (generator.randrange(4),),
                    {"theta": generator.uniform(-2.0, 2.0)},
                )
            )
        else:
            instructions.append(Instruction(name, (generator.randrange(4),)))
    return CircuitIR(4, tuple(instructions), dtype="complex128")


@pytest.mark.parametrize(
    "program,target,error",
    [
        (
            CircuitIR(1, (Instruction("z", (0,)),)),
            {"basis_gates": BASIS},
            "unsupported QSteed instruction",
        ),
        (
            CircuitIR(3, (Instruction("h", (0,)),)),
            {"basis_gates": BASIS, "coupling_map": ((0, 1),)},
            "cover every circuit wire",
        ),
        (
            CircuitIR(1, (Instruction("h", (0,)),)),
            {"basis_gates": BASIS, "optimization_level": 3},
            "unsupported QSteed target field",
        ),
    ],
)
def test_unsupported_inputs_fail_closed(program, target, error):
    extension = create_extension()
    extension.start(ExtensionConfig())
    try:
        with pytest.raises((TypeError, ValueError), match=error):
            extension.compile(program, target=target)
    finally:
        extension.close()
