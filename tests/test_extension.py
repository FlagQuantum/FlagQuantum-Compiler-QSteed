from flagquantum import CircuitIR, Instruction
from flagquantum.ecosystem.extensions import (
    CapabilityRequest,
    ExtensionConfig,
    discover_extensions,
    run_compiler_conformance,
)

from flagquantum_compiler_qsteed import create_extension


def test_official_compiler_conformance():
    report = run_compiler_conformance(create_extension())

    assert report.extension == "qsteed"
    assert "deterministic" in report.checks


def test_installed_entry_point_is_discoverable():
    registry = discover_extensions("compiler")
    handle = registry.negotiate(
        "compiler",
        "qsteed",
        CapabilityRequest(required=frozenset({"circuit_ir"})),
    )
    handle.start(ExtensionConfig())
    try:
        result = handle.invoke(
            "compile",
            CircuitIR(1, (Instruction("x", (0,)),)),
            target={"basis_gates": ("x",)},
        )
    finally:
        handle.close()

    assert result.instructions == (Instruction("x", (0,)),)
