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

Install the published FlagQuantum release, the verified QSteed build, and
this plugin in order:

```bash
python -m pip install "flagquantum>=0.2"
python -m pip install "qsteed @ git+https://github.com/BAQIS-Quantum/qsteed.git@46584efde731aea9eec27b5466919b76fe5f3184"
python -m pip install flagquantum-compiler-qsteed==0.1.2
```

The plugin requires FlagQuantum `>=0.2` and QSteed
`0.2.3+quafu.sqc`. FlagQuantum and the plugin are available on PyPI;
the verified QSteed build still requires the pinned Git installation above.
PyPI QSteed 0.2.2 is not a supported substitute. Installing FlagQuantum alone
or its `quafu` extra does not install this compiler plugin.

The plugin requires Python 3.12. FlagQuantum itself supports additional Python
versions, but the verified QSteed build depends on a QuarkCircuit release that
is unavailable on Python 3.10 and 3.11. The plugin metadata rejects those
environments instead of allowing an installation that its dependency resolver
cannot satisfy.

For development from this repository, install FlagQuantum as above, then run:

```bash
python -m pip install -r requirements-qsteed.txt
python -m pip install -e ".[test]"
python -m pytest -q
```

Version 0.1.2 removes the FlagQuantum upper bound after compatibility testing
against FlagQuantum 0.3. Compiler behavior is unchanged.

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
