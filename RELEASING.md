# Release preparation

Distribution: `flagquantum-compiler-qsteed` 0.1.2.
Entry point: `flagquantum.extensions` / `compiler.qsteed`.

## Prerequisites

- Install the FlagQuantum version being validated, which must satisfy
  `flagquantum>=0.2`. Release checks for 0.1.2 include FlagQuantum 0.3.
- The verified QSteed build is 0.2.3+quafu.sqc at the commit in
  `requirements-qsteed.txt`. PyPI 0.2.2 failed the offline compilation suite
  with an upstream `NameError` during import in the Python 3.12 check.
- For now, users must install the pinned QSteed build separately. A complete
  index-only installation requires an upstream indexed release that passes
  these same tests. Do not widen the dependency just to make resolution succeed.
- Use the existing GitHub repository and PyPI project for this plugin. Never
  commit publishing credentials.
- Pull requests run the offline suite on Python 3.10, 3.11, and 3.12 against
  both the published FlagQuantum 0.2.0 baseline and FlagQuantum main. The
  distribution job also verifies that release metadata retains
  `flagquantum>=0.2` without restoring the obsolete `<0.3` upper bound.

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
