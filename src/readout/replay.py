"""Replay a period as the pipeline would have lived it.

Campaigns are read out in the order in which their outcome windows close. Each
readout sees the snapshot cut at its own readout day and the record left by
the readouts before it, and nothing else. This is the difference between
analysing a year in December and having operated through it.

The same machinery runs the audits: with ``shift = k`` every campaign is read
out as if it had been launched k windows earlier, when it had not been sent.

A replay can be interrupted and run again: what is already in the registry is
not computed a second time.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .bootstrap import HouseholdBootstrap
from .contract import Contract
from .pipeline import Unit, Workbench, assess, refuse_without_feed
from .programme import programme_readout
from .registry import Registry, readout_key
from .snapshot import Snapshot


class NotDue(RuntimeError):
    """The outcome window of a readout closes after the snapshot ends."""


@dataclass(frozen=True)
class ReplaySummary:
    read_out: tuple[int, ...]
    pending: tuple[int, ...]  # campaigns whose outcome window closes after the snapshot ends


def units(snapshot: Snapshot, contract: Contract, shift: int = 0) -> list[Unit]:
    """All campaigns of the snapshot, in the order their readouts fall due."""
    desc = snapshot.tables["descriptions"]
    all_units = [
        Unit(int(row.campaign_id), pd.Timestamp(row.start_date), str(row.campaign_type), shift)
        for row in desc.itertuples()
    ]
    return sorted(all_units, key=lambda u: (u.readout_day(contract), u.campaign))


def read_out(
    snapshot: Snapshot,
    contract: Contract,
    registry: Registry,
    unit: Unit,
    boot: HouseholdBootstrap | None = None,
    benches: dict | None = None,
) -> None:
    """Read out one unit on its readout day, with every method of the contract, and record it.

    The readout always uses the snapshot cut at the day the outcome window
    closes, however much later it is run, so running it late changes nothing.
    Methods already recorded for this unit are left as they are.
    """
    day = unit.readout_day(contract)
    if day > snapshot.end:
        raise NotDue(f"the readout of campaign {unit.campaign} falls due on {day.date()}, after the snapshot ends")
    todo = [
        m for m in contract.methods if not registry.recorded(readout_key(contract, m.name, unit.campaign, unit.shift))
    ]
    if not todo:
        return
    primary = contract.method.name
    if day <= snapshot.first_day:  # the readout falls due before the feed starts
        for method in todo:
            refusal = refuse_without_feed(unit, contract, method, snapshot.snapshot_id, day)
            registry.record(refusal, contract, publish=(unit.shift == 0 and method.name == primary))
        return
    boot = boot or HouseholdBootstrap(contract.bootstrap.replications, contract.bootstrap.seed)
    view = snapshot.as_of(day)
    # The membership list comes from the full snapshot: in an audit the
    # campaign has not been launched yet on the readout day.
    membership = snapshot.tables["campaigns"]
    member_ids = membership.loc[membership["campaign_id"] == unit.campaign, "household_id"].to_numpy()
    benches = {} if benches is None else benches
    key = Workbench.key(view, unit, contract)
    if key not in benches:
        benches[key] = Workbench(view, unit, contract, boot, member_ids)
    bench = benches[key]
    bench.view = view
    for method in todo:
        history = registry.record_history(contract, method, unit)
        assessment = assess(view, unit, contract, method, boot, history, member_ids, bench)
        registry.record(assessment, contract, publish=(unit.shift == 0 and method.name == primary))
    bench.view = None  # the numbers are kept for a later replay; the data they came from is not


def replay(
    snapshot: Snapshot,
    contract: Contract,
    registry: Registry,
    shift: int = 0,
    progress: bool = True,
    benches: dict | None = None,
) -> ReplaySummary:
    """Read out every campaign of the snapshot under ``contract`` and record the results.

    ``benches`` lets several replays of the same snapshot share their
    estimates: contracts that differ only in what the gates require, such as
    whether the assignment rule is documented, compute the same numbers.
    """
    boot = HouseholdBootstrap(contract.bootstrap.replications, contract.bootstrap.seed)
    benches = {} if benches is None else benches
    done, pending = [], []
    due: dict[pd.Timestamp, list[Unit]] = {}
    for unit in units(snapshot, contract, shift):
        due.setdefault(unit.readout_day(contract), []).append(unit)
    for day, todays in due.items():
        if day > snapshot.end:
            pending += [unit.campaign for unit in todays]
            continue
        for unit in todays:
            read_out(snapshot, contract, registry, unit, boot, benches)
            done.append(unit.campaign)
            if progress:
                print(f"{contract.tag} shift {shift}: campaign {unit.campaign} read out as of {day.date()}", flush=True)
        # One programme readout per day, after every campaign due that day.
        for method in contract.methods:
            if not registry.programme_recorded(contract, method.name, shift, day):
                result = programme_readout(registry, contract, method, day, snapshot.snapshot_id, shift)
                registry.record_programme(result, contract, shift)
    return ReplaySummary(tuple(done), tuple(pending))
