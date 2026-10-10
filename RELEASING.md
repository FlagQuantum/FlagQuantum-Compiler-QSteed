# Release preparation

Distribution: `flagquantum-compiler-qsteed` 0.2.0.
Entry point: `flagquantum.extensions` / `compiler.qsteed`.

## Prerequisites

- Validate against both the oldest supported FlagQuantum (`0.2.0`) and current
  FlagQuantum `main` on every supported Python version.
- The vendored QSteed source must remain pinned to the commit recorded in
  `src/flagquantum_compiler_qsteed/_vendor/qsteed/UPSTREAM.md`. Preserve every
  source header, the bundled Apache-2.0 license, and `THIRD_PARTY_NOTICES.md`.
- Any QSteed refresh must regenerate the compiler-only transitive closure,
  review local namespace changes, and pass behavioral comparison tests before
  changing the recorded commit.
- Use the existing GitHub repository and PyPI project for this plugin. Never
  commit publishing credentials.
- The supported Python matrix is 3.10, 3.11, and 3.12.

## Validate and build

Use a fresh environment with the compatible FlagQuantum release installed:

```bash
python -m pip install -e '.[test]' build twine
python -m pytest -q
python -m build
python -m twine check --strict dist/*
```

Install the wheel in another environment with the same dependencies. Run the
README offline circuit compilation example from outside the source tree and
confirm discovery through `fq.compile(..., compiler="qsteed")`. Check the
sdist contains the project license, README, third-party notices, vendored
QSteed license/provenance, and tests. Inspect wheel metadata for the correct
version, dependency constraints, entry point, and vendored files. Confirm a
clean index-only install does not install the external `qsteed`, `quarkcircuit`,
or `quarkstudio` distributions. No test or release check needs to submit a real
QPU task.

Publish only the exact validated wheel and sdist for the intended version.

## Trusted publishing

The PyPI project must configure a GitHub Trusted Publisher with these exact
values:

- Owner: `FlagQuantum`
- Repository: `FlagQuantum-Compiler-QSteed`
- Workflow: `cd.yml`
- Environment: leave blank (`Any`)

Create a GitHub Release whose tag is either the package version or the same
version prefixed with `v` (for example, `0.2.0` or `v0.2.0`). Publishing the
release builds one wheel and one source archive, validates them, publishes the
same files to PyPI through OIDC, and attaches them to the GitHub Release. No
PyPI token is stored in GitHub.
