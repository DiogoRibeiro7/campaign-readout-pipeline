"""Command line. Options that apply to every command go before the command.

    readout fetch      download the pinned source files and verify them
    readout snapshot   build the snapshot the pipeline reads
    readout parity     compare the pipeline with the prototype's published numbers
    readout run        read out one campaign and print what consumers would receive
    readout replay     read out every campaign in the order the readouts fell due
    readout worlds     run the pipeline on synthetic retailers with a known effect
    readout report     tables and figures from the registry
    readout schema     JSON Schema of what the pipeline publishes
    readout all        fetch, snapshot, parity, replay, worlds and report, in that order
    readout check      compare result tables with a reference copy

Exit status of ``readout run``: 0 published, 3 refused, 4 not due yet (the
outcome window closes after the data ends; nothing is recorded). Status 2 is
an error, from any command.
"""

from __future__ import annotations

import os

for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

import argparse  # noqa: E402
import json  # noqa: E402
import multiprocessing  # noqa: E402
import sys  # noqa: E402
from concurrent.futures import ProcessPoolExecutor  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from . import parity, source, worlds  # noqa: E402
from .contract import Contract, load_contract  # noqa: E402
from .estimators import EstimatorError  # noqa: E402
from .registry import Registry, RegistryConflict, readout_key  # noqa: E402
from .replay import NotDue, read_out, replay, units  # noqa: E402
from .result import RESULT, json_schemas  # noqa: E402
from .snapshot import Snapshot, build  # noqa: E402

EXIT_PUBLISHED, EXIT_ERROR, EXIT_REFUSED, EXIT_NOT_DUE = 0, 2, 3, 4
SHIFTS = (0, 1, 2)  # 0 is the real readout; the others are the readouts on earlier windows
DEFAULT_CONTRACTS = ("contracts/campaign_readout_v1.toml", "contracts/campaign_readout_v2.toml")


def _contracts(args) -> list[Contract]:
    """The contract in force, followed by the later versions replayed and reported next to it."""
    contracts = []
    for path in args.contract or DEFAULT_CONTRACTS:
        contract = load_contract(path)
        if args.replications:
            contract = contract.model_copy(
                update={"bootstrap": contract.bootstrap.model_copy(update={"replications": args.replications})}
            )
        contracts.append(contract)
    return contracts


def _contract(args) -> Contract:
    return _contracts(args)[0]


def cmd_fetch(args) -> int:
    source.fetch(_contract(args).source, args.raw)
    print(f"source files verified in {args.raw}")
    return 0


def cmd_snapshot(args) -> int:
    contract = _contract(args)
    source.verify(contract.source, args.raw)
    manifest = build(args.raw, args.snapshot, contract.source)
    print(
        f"snapshot {manifest['snapshot_id']}: {manifest['households']} households, {manifest['first_day']} to {manifest['last_day']}"
    )
    return 0


def cmd_parity(args) -> int:
    table = parity.compare(Snapshot.load(args.snapshot), _contract(args), args.prototype)
    gap = parity.largest_difference(table)
    out = Path(args.results) / "parity.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(out, index=False, float_format="%.10g", lineterminator="\n")
    print(f"largest difference from the prototype's published numbers: {gap:.3g}")
    return 0 if gap <= args.parity_tolerance else EXIT_ERROR


def cmd_run(args) -> int:
    """One campaign, with every method of the contract. Running it again changes nothing."""
    contract, snapshot = _contract(args), Snapshot.load(args.snapshot)
    unit = next((u for u in units(snapshot, contract) if u.campaign == args.campaign), None)
    if unit is None:
        print(f"readout: campaign {args.campaign} is not in the snapshot", file=sys.stderr)
        return EXIT_ERROR
    registry = Registry(args.registry)
    try:
        read_out(snapshot, contract, registry, unit)
    except NotDue as pending:
        print(f"readout: {pending}", file=sys.stderr)
        return EXIT_NOT_DUE
    result = registry.stored(readout_key(contract, contract.method.name, unit.campaign, unit.shift))
    print(json.dumps(RESULT.dump_python(result, mode="json"), indent=2))
    return EXIT_PUBLISHED if result.kind == "published" else EXIT_REFUSED


def cmd_replay(args) -> int:
    snapshot, registry = Snapshot.load(args.snapshot), Registry(args.registry)
    for contract in _contracts(args):
        for shift in getattr(args, "shift", SHIFTS):
            summary = replay(snapshot, contract, registry, shift=shift)
            print(
                f"{contract.tag} shift {shift}: {len(summary.read_out)} campaigns read out, {len(summary.pending)} pending"
            )
    return 0


def _run_world(job) -> str:
    world, contract, root, replications = job
    worlds.run_world(world, contract, root, replications)
    return f"{world.name} seed {world.seed}"


def cmd_worlds(args) -> int:
    contract = _contract(args)
    root = Path(args.registry) / "worlds"
    chosen = worlds.audit_worlds(args.households, args.campaigns, tuple(args.seeds))
    only = getattr(args, "only", None)
    if only:
        unknown = set(only) - {world.name for world in chosen}
        if unknown:
            raise ValueError(f"unknown worlds: {sorted(unknown)}; choose from {sorted({w.name for w in chosen})}")
        chosen = [world for world in chosen if world.name in only]
    jobs = [(world, contract, str(root), args.world_replications) for world in chosen]
    if args.jobs > 1:
        # Fresh interpreters: forking a process that already holds threads is fragile.
        with ProcessPoolExecutor(max_workers=args.jobs, mp_context=multiprocessing.get_context("spawn")) as pool:
            for name in pool.map(_run_world, jobs):
                print(f"world {name}: read out", flush=True)
    else:
        for job in jobs:
            print(f"world {_run_world(job)}: read out", flush=True)
    return 0


def cmd_report(args) -> int:
    from . import report

    prototype = args.prototype if Path(args.prototype).exists() else None
    report.write(
        _contracts(args),
        Snapshot.load(args.snapshot),
        Registry(args.registry),
        Path(args.results),
        Path(args.figures),
        prototype,
    )
    print(f"tables in {args.results}, figures in {args.figures}")
    return 0


def cmd_schema(args) -> int:
    schemas = json_schemas()
    if args.out:
        Path(args.out).mkdir(parents=True, exist_ok=True)
        for name, schema in schemas.items():
            text = json.dumps(schema, indent=2, sort_keys=True) + "\n"
            (Path(args.out) / f"{name}.schema.json").write_text(text, encoding="utf-8", newline="\n")
    else:
        sys.stdout.write(json.dumps(schemas, indent=2, sort_keys=True) + "\n")
    return 0


def cmd_all(args) -> int:
    for step in (cmd_fetch, cmd_snapshot, cmd_parity, cmd_replay, cmd_worlds, cmd_report):
        status = step(args)
        if status != 0:
            return status
    return 0


def cmd_check(args) -> int:
    """Compare freshly written tables with a reference copy, within a tolerance."""
    new_dir, ref_dir = Path(args.results), Path(args.reference)
    new_names, ref_names = ({p.name for p in d.glob("*.csv")} for d in (new_dir, ref_dir))
    if not ref_names:
        raise ValueError(f"no reference tables in {ref_dir}")
    failures = 0
    for name in sorted(new_names ^ ref_names):
        print(f"{name}: only in {new_dir if name in new_names else ref_dir}")
        failures += 1
    for name in sorted(new_names & ref_names):
        new, ref = pd.read_csv(new_dir / name), pd.read_csv(ref_dir / name)
        if list(new.columns) != list(ref.columns) or len(new) != len(ref):
            print(f"{name}: shape or columns differ")
            failures += 1
            continue
        worst, where = 0.0, ""
        for column in new.columns:
            gap = 0.0
            if pd.api.types.is_numeric_dtype(new[column]) and pd.api.types.is_numeric_dtype(ref[column]):
                a, b = new[column].to_numpy(float), ref[column].to_numpy(float)
                same_gaps = np.array_equal(np.isnan(a), np.isnan(b)) and np.array_equal(np.isinf(a), np.isinf(b))
                finite = np.isfinite(a) & np.isfinite(b)
                if not same_gaps or not np.array_equal(a[np.isinf(a)], b[np.isinf(b)]):
                    gap = np.inf
                elif finite.any():
                    gap = float(np.max(np.abs(a[finite] - b[finite]) / np.maximum(1.0, np.abs(b[finite]))))
            elif not new[column].astype(str).equals(ref[column].astype(str)):
                gap = np.inf
            if gap > worst:
                worst, where = gap, column
        ok = worst <= args.tolerance
        failures += not ok
        print(f"{name}: largest relative difference {worst:.2e} {'ok' if ok else f'DIFFERS in {where}'}")
    return EXIT_ERROR if failures else 0


def _positive(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("must be a positive whole number")
    return value


def _at_least_two(text: str) -> int:
    value = int(text)
    if value < 2:
        raise argparse.ArgumentTypeError("must be at least 2")
    return value


def _not_negative(text: str) -> int:
    value = int(text)
    if value < 0:
        raise argparse.ArgumentTypeError("must not be negative")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="readout", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter, allow_abbrev=False
    )
    parser.add_argument(
        "--contract",
        action="append",
        default=None,
        help="contract file; repeat to replay and report later versions next to the first (default: v1 and v2). "
        "Commands that work on one contract use the first",
    )
    parser.add_argument("--raw", default="data/raw", help="directory of the pinned source files")
    parser.add_argument("--snapshot", default="data/snapshot", help="directory of the snapshot")
    parser.add_argument("--registry", default="registry", help="directory of the registry")
    parser.add_argument("--results", default="results", help="directory the tables are written to")
    parser.add_argument("--figures", default="figures", help="directory the figures are written to")
    parser.add_argument(
        "--prototype", default="prototype/placebo_results.json", help="the prototype's published results"
    )
    parser.add_argument(
        "--replications",
        type=_at_least_two,
        default=None,
        help="override the contract's bootstrap replications, for trials. The override is part of the contract's hash, "
        "so a trial never mixes with the real record",
    )
    parser.add_argument(
        "--households", type=_positive, default=worlds.HOUSEHOLDS, help="households of each synthetic retailer"
    )
    parser.add_argument(
        "--campaigns", type=_positive, default=worlds.CAMPAIGNS, help="campaigns of each synthetic retailer"
    )
    parser.add_argument(
        "--seeds",
        type=_not_negative,
        nargs="+",
        default=list(worlds.SEEDS),
        help="seeds each synthetic retailer is drawn with",
    )
    parser.add_argument(
        "--world-replications",
        type=_at_least_two,
        default=worlds.REPLICATIONS,
        help="bootstrap replications on the synthetic retailers",
    )
    parser.add_argument(
        "--jobs", type=_positive, default=os.cpu_count() or 1, help="synthetic retailers run in parallel"
    )
    parser.add_argument("--parity-tolerance", type=float, default=1e-6)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("fetch", allow_abbrev=False)
    sub.add_parser("snapshot", allow_abbrev=False)
    sub.add_parser("parity", allow_abbrev=False)
    p = sub.add_parser("run", allow_abbrev=False)
    p.add_argument("--campaign", type=int, required=True)
    p = sub.add_parser("replay", allow_abbrev=False)
    p.add_argument(
        "--shift", type=_not_negative, nargs="+", default=list(SHIFTS), help="windows before the launch to read out at"
    )
    p = sub.add_parser("worlds", allow_abbrev=False)
    p.add_argument("--only", nargs="+", default=None, help="names of the worlds to run")
    sub.add_parser("report", allow_abbrev=False)
    p = sub.add_parser("schema", allow_abbrev=False)
    p.add_argument("--out", default=None, help="directory to write one file per schema to; printed if omitted")
    sub.add_parser("all", allow_abbrev=False)
    p = sub.add_parser("check", allow_abbrev=False)
    p.add_argument("--reference", required=True, help="directory holding the tables to compare with")
    p.add_argument("--tolerance", type=float, default=1e-4, help="largest relative difference accepted in a number")
    return parser


HANDLERS = {
    "fetch": cmd_fetch, "snapshot": cmd_snapshot, "parity": cmd_parity, "run": cmd_run, "replay": cmd_replay,
    "worlds": cmd_worlds, "report": cmd_report, "schema": cmd_schema, "all": cmd_all, "check": cmd_check,
}  # fmt: skip
EXPECTED = (OSError, ValueError, ValidationError, source.SourceIntegrityError, RegistryConflict, EstimatorError)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return HANDLERS[args.command](args)
    except EXPECTED as error:
        print(f"readout: {type(error).__name__}: {error}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
