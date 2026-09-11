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
- Quafu calibration targets with automatic or explicitly ordered physical
  subgraph selection and a `target_qubits` result; physical identifiers never
  replace logical QASM wires.

Measurements, observables, symbolic parameters, custom matrices, dynamic
operations, additional target fields, and larger physical topologies are
rejected. There is no compiler substitution or fallback. Omitting
`coupling_map` explicitly requests basis compilation without topology routing.
For a Quafu `chip_info` target, omitting `target_qubits` lets QSteed choose the
subgraph. Supplying it locks the logical-to-physical order after existence,
uniqueness, and connectivity validation; the plugin never substitutes another
mapping.

## Installation

This release candidate requires FlagQuantum `>=0.2,<0.3` and the verified
QSteed build `0.2.3+quafu.sqc`. It is not yet a one-command PyPI installation:
FlagQuantum 0.2 and this QSteed build must be installed first. PyPI QSteed 0.2.2
is not a supported substitute. Python 3.12 was used for the release checks;
the declared Python 3.10–3.12 range still needs a full compatibility matrix.

From this repository, after installing a compatible FlagQuantum checkout:

```bash
python -m pip install -r requirements-qsteed.txt
python -m pip install -e ".[test]"
python -m pytest -q
```

The dependency file pins the verified upstream commit. The wheel declares its
exact package version without embedding a Git URL. Once the plugin is published,
users with both prerequisites already installed can use
`python -m pip install flagquantum-compiler-qsteed==0.1.0`.

## Compile a circuit

This offline example needs no provider credentials and submits no hardware job:

```python
import flagquantum as fq

circuit = fq.Circuit(3).h(0).cx(0, 2)
compiled = fq.compile(
    circuit,
    compiler="qsteed",
    target={
        "basis_gates": ("h", "x", "rx", "ry", "rz", "cx"),
        "coupling_map": ((0, 1), (1, 2)),
    },
)
print(compiled.instructions)
```

See [release preparation](RELEASING.md) for publication prerequisites and
artifact checks.

## Advanced extension lifecycle

```python
from flagquantum.ecosystem.extensions import (
    CapabilityRequest,
    ExtensionConfig,
    discover_extensions,
)

import flagquantum as fq

source_ir = fq.Circuit(3).h(0).cx(0, 2).to_ir()
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
