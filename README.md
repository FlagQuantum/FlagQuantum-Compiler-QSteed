# FlagQuantum Compiler QSteed

`flagquantum-compiler-qsteed` is an independently installed circuit compiler
plugin for FlagQuantum. It translates FlagQuantum `CircuitIR` to a PyQuafu
`QuantumCircuit`, invokes QSteed's real transpiler, and translates the compiled
circuit back to `CircuitIR`.

The first release deliberately supports one closed, testable slice:

- static `h`, `x`, `rx`, `ry`, `rz`, and `cx` instructions with numeric angles;
- basis lowering to a selected subset of those gates, with topology routing on
  the fixed six-gate basis;
- an optional undirected coupling map over the circuit's existing wires;
- deterministic QSteed basis lowering and SABRE routing;
- restoration of QSteed's final physical layout to FlagQuantum's logical wire
  order.
- Quafu calibration targets with QSteed subgraph selection and an ordered
  `target_qubits` result; physical identifiers never replace logical QASM wires.

Measurements, observables, symbolic parameters, custom matrices, dynamic
operations, additional target fields, and larger physical topologies are
rejected. There is no compiler substitution or fallback. Omitting
`coupling_map` explicitly requests basis compilation without topology routing.

## Install for development

The QSteed dependency is pinned to commit `46584ef` from the
`qsteed-for-quafu-sqc` line used to implement and verify this plugin.

```bash
python -m pip install -e ".[test]"
```

## Use

```python
from flagquantum.ecosystem.extensions import (
    CapabilityRequest,
    ExtensionConfig,
    discover_extensions,
)

registry = discover_extensions("compiler")
handle = registry.negotiate(
    "compiler",
    "qsteed",
    CapabilityRequest(required=frozenset({"circuit_ir"})),
)
handle.start(ExtensionConfig())
try:
    compiled = handle.invoke(
        "compile",
        source_ir,
        target={
            "basis_gates": ("h", "x", "rx", "ry", "rz", "cx"),
            "coupling_map": ((0, 1), (1, 2)),
        },
    )
finally:
    handle.close()
```

QSteed treats the coupling graph as bidirectional in this compiler path. The
plugin therefore validates two-wire instructions against undirected edges.
