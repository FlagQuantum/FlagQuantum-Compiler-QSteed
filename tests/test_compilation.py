import pytest
import torch
from flagquantum import Circuit, CircuitIR, Instruction
from flagquantum.ecosystem.extensions import ExtensionConfig

from flagquantum_compiler_qsteed import create_extension

BASIS = ("h", "x", "rx", "ry", "rz", "cx")
LINE = ((0, 1), (1, 2))


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

    assert _compile(source).content_hash == _compile(source).content_hash


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
