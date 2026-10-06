.PHONY: install test lint fetch snapshot parity replay worlds report all check clean

export OMP_NUM_THREADS ?= 1
export OPENBLAS_NUM_THREADS ?= 1
export MKL_NUM_THREADS ?= 1

install:
	python -m pip install -e ".[dev]"

test:
	python -m pytest

lint:
	ruff check src tests
	ruff format --check src tests

fetch:
	readout fetch

snapshot: fetch
	readout snapshot

parity:
	readout parity

replay:
	readout replay

worlds:
	readout worlds

report:
	readout report

# Fetch, snapshot, parity, replay, synthetic retailers, report. About an hour and a half on two cores.
all:
	readout all

# Regenerate everything from nothing, next to the committed results, and compare the two.
check:
	rm -rf fresh
	readout --registry fresh/registry --results fresh/results --figures fresh/figures all
	readout --results fresh/results check --reference results

clean:
	rm -rf registry fresh logs .pytest_cache .ruff_cache
