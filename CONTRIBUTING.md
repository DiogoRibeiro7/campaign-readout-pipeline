# Contributing

Issues and pull requests are welcome. The issue forms ask for what is needed
to act on a report: the command, its output, and where it ran.

## Setting up

Python 3.11 or later.

```sh
python -m venv .venv
source .venv/bin/activate          # .venv\Scripts\activate on Windows
pip install -e ".[dev]" -c constraints.txt
readout fetch                      # the pinned source files, verified by SHA-256
readout snapshot
```

`constraints.txt` holds the versions of the numerical libraries the committed
results were produced with. Without the source files the tests marked `data`
are skipped, parity with the prototype among them.

## Before a pull request

```sh
ruff check src tests
ruff format --check src tests
python -m pytest
```

CI runs the same on Python 3.11 to 3.14, and once more on the oldest versions
of the dependencies that `pyproject.toml` admits.

## Changes that move a number

`results/` and `figures/` are written by the pipeline and are not edited by
hand. A change to `src/`, `contracts/` or `prototype/` may move them, and so
may a change to the definition of a covariate or to the propensity model,
which live in the code and not in the contract.

```sh
make check      # the whole pipeline into fresh/, then its tables compared with results/
```

If the tables differ and the change is meant to move them, regenerate them
with `readout all` (about an hour on two cores), commit `results/` and
`figures/` with the change, and say in the pull request which numbers moved
and why. Label it `results change`. On every push to `main` that touches the
code, the contracts or the results, the `reproduce` workflow runs the pipeline
again and fails if the committed tables do not match.

## Changing a rule

A contract is not edited once results have been recorded under it. A change to
a rule, whether a threshold, a window, the adjustment set or the method, is a
new file in `contracts/`, added to `DEFAULT_CONTRACTS` in `src/readout/cli.py`
(a test checks that the two agree). Results are keyed by the contract's hash,
so a new version starts with an empty record. Label the pull request
`contract change`.

## Releases

A release is cut by changing the version on `main` in `pyproject.toml`,
`src/readout/__init__.py` and `CITATION.cff`, which a test requires to agree.
The `release` workflow runs the checks, tags the commit and creates the
release. Nobody pushes a tag by hand.

## Conduct

Everyone taking part is expected to follow the
[code of conduct](CODE_OF_CONDUCT.md).
