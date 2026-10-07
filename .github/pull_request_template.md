## What and why



## Checks

- [ ] `ruff check src tests` and `ruff format --check src tests` pass
- [ ] `python -m pytest` passes with the source files present (`readout fetch`)
- [ ] The results are unchanged (`make check` passes), or they are regenerated and committed, and the numbers that moved are named above
- [ ] A changed rule is a new contract version, not an edit to an existing one
