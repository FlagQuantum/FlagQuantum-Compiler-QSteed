# QSteed compiler core provenance

- Upstream: <https://github.com/BAQIS-Quantum/qsteed>
- Commit: `46584efde731aea9eec27b5466919b76fe5f3184`
- Upstream version: `0.2.3+quafu.sqc`
- License: Apache License 2.0 (see `LICENSE` in this directory)
- Imported: 2026-10-10

This directory contains only the transitive source closure used by the
FlagQuantum compiler plugin: circuit unrolling, DAG conversion, SABRE layout
and routing, topology selection, and their supporting data models. QSteed's
database, web API, task scheduler, compiler service, and visualization layers
are intentionally excluded.

Local modifications are limited to:

1. rewriting absolute `qsteed.*` imports into this private package namespace;
2. replacing eager package exports with minimal `__init__.py` files; and
3. requiring the explicit pass flow supplied by the plugin instead of loading
   QSteed's unused preset-pass-flow stack; and
4. normalizing trailing whitespace in copied source files.

Every copied source file retains its upstream copyright and Apache-2.0 header.
