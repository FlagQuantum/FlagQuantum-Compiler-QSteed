# Release preparation

Distribution: `flagquantum-compiler-qsteed` 0.1.1.
Entry point: `flagquantum.extensions` / `compiler.qsteed`.

## Prerequisites

- Install the published FlagQuantum baseline with
  `python -m pip install flagquantum==0.2.0`.
- The verified QSteed build is 0.2.3+quafu.sqc at the commit in
  `requirements-qsteed.txt`. PyPI 0.2.2 failed the offline compilation suite
  with an upstream `NameError` during import in the Python 3.12 check.
- For now, users must install the pinned QSteed build separately. A complete
  index-only installation requires an upstream indexed release that passes
  these same tests. Do not widen the dependency just to make resolution succeed.
- Use the existing GitHub repository and PyPI project for this plugin. Never
  commit publishing credentials.
- Complete Python 3.10 and 3.11 compatibility runs before claiming that the
  entire declared range is verified. Python 3.12 is the current tested baseline.

## Validate and build

Use a fresh environment with the compatible FlagQuantum release installed:

```bash
python -m pip install -r requirements-qsteed.txt
python -m pip install -e '.[test]' build twine
python -m pytest -q
python -m build
python -m twine check --strict dist/*
```

Install the wheel in another environment with the same dependencies. Run the
README offline circuit compilation example from outside the source tree and
confirm discovery through `fq.compile(..., compiler="qsteed")`. Check the
sdist contains the license, README, dependency file, and tests. Inspect wheel
metadata for the correct version, dependency constraints, and entry point.
No test or release check needs to submit a real QPU task.

Publish only the exact validated wheel and sdist for the intended version.
The separately installed QSteed prerequisite remains required.
