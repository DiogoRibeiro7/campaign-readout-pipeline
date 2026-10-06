"""End to end on a synthetic retailer: what is refused, what is published, and what a readout may depend on."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from conftest import with_updates
from readout.bootstrap import HouseholdBootstrap
from readout.pipeline import Unit, assess, refuse_without_feed
from readout.registry import Registry
from readout.replay import NotDue, read_out, replay, units
from readout.result import RESULT, Refused
from readout.simulate import WORLDS, synthetic_snapshot
from readout.snapshot import Snapshot


def test_units_are_read_out_in_the_order_they_fall_due(snapshot, contract):
    ordered = units(snapshot, contract)
    days = [unit.readout_day(contract) for unit in ordered]
    assert days == sorted(days)
    assert days[0] == ordered[0].launch + pd.Timedelta(days=28)
    shifted = Unit(ordered[0].campaign, ordered[0].launch, "Type B", shift=2)
    assert shifted.anchor(28) == ordered[0].launch - pd.Timedelta(days=56)
    assert shifted.readout_day(contract) == ordered[0].launch - pd.Timedelta(days=28)


def test_targeting_on_recent_spending_is_refused_when_the_rule_is_unknown(replayed):
    """The shifted placebo's outcome is what the retailer targeted on, so it fails; the gate says why."""
    audit = replayed.audit()
    assert (audit["verdict"] == "refused").all()
    judged = audit[audit["valid_placebo"] & (audit["method"] == "regression")]
    assert len(judged) >= 4
    for _, row in judged.iterrows():
        assert any(code.startswith("ASSIGNMENT_UNDOCUMENTED") for code in row["codes"])
        assert row["shifted_placebo"]["low"] > 5.0  # each one shown to lie beyond the tolerance
    shifted = np.mean([row["estimate"] for row in judged["shifted_placebo"]])
    prehistory = np.mean([row["estimate"] for row in judged["prehistory_placebo"]])
    assert shifted > 40 and abs(prehistory) < shifted / 4


def test_the_same_numbers_pass_the_assignment_gate_when_the_rule_is_documented(
    replayed, snapshot, documented, tmp_path
):
    registry = Registry(tmp_path)
    replay(snapshot, documented, registry, progress=False)
    before, after = replayed.audit(), registry.audit()
    for role in ("effect", "prehistory_placebo", "shifted_placebo"):
        assert [r and r["estimate"] for r in after[role]] == [r and r["estimate"] for r in before[role]]
    assert not any(code.startswith("ASSIGNMENT") for codes in after["codes"] for code in codes)
    # What remains is overlap and the pre-history placebo, which a panel this small cannot pin down.
    assert all(code.startswith(("PREHISTORY", "OVERLAP")) for codes in after["codes"] for code in codes)
    assert any(code.startswith("PREHISTORY") for codes in after["codes"] for code in codes)


def test_a_readout_does_not_depend_on_anything_dated_after_it(snapshot, contract):
    """Replace every purchase from the readout day on, and drop the later campaigns: the result is identical."""
    ordered = units(snapshot, contract)
    unit, day = ordered[3], ordered[3].readout_day(contract)
    tables = {name: frame.copy() for name, frame in snapshot.tables.items()}
    tables["daily"].loc[tables["daily"]["day"] >= day, "sales_value"] *= 5.0
    later = [u.campaign for u in ordered[4:]]
    tables["campaigns"] = tables["campaigns"][~tables["campaigns"]["campaign_id"].isin(later)]
    tables["descriptions"] = tables["descriptions"][~tables["descriptions"]["campaign_id"].isin(later)]
    changed = Snapshot.from_tables(tables, snapshot.manifest["source"])
    boot = HouseholdBootstrap(contract.bootstrap.replications, contract.bootstrap.seed)

    def result(source: Snapshot) -> dict:
        record = RESULT.dump_python(
            assess(source.as_of(day), unit, contract, contract.method, boot, {}).result, mode="json"
        )
        record["provenance"].pop("snapshot_id"), record["provenance"].pop("view_id")  # the snapshots differ by design
        return record

    assert result(changed) == result(snapshot)


def test_a_readout_run_early_estimates_nothing(snapshot, contract):
    unit = units(snapshot, contract)[3]
    boot = HouseholdBootstrap(contract.bootstrap.replications, contract.bootstrap.seed)
    view = snapshot.as_of(unit.readout_day(contract) - pd.Timedelta(days=1))
    early = assess(view, unit, contract, contract.method, boot, {})
    assert isinstance(early.result, Refused) and early.result.reasons[0].code == "DATA_OUTCOME_INCOMPLETE"
    assert not early.estimates and not early.valid_placebo


def test_a_readout_run_late_is_the_readout_of_its_day(snapshot, contract, tmp_path):
    """However much later it is run, the readout is cut at the day its outcome window closed."""
    ordered = units(snapshot, contract)
    unit = ordered[2]
    day = unit.readout_day(contract)
    on_time = Snapshot.from_tables(
        {n: (t[t["day"] < day] if "day" in t else t).copy() for n, t in snapshot.tables.items()},
        {"cut": str(day.date())},
    )
    first, second = Registry(tmp_path / "on_time"), Registry(tmp_path / "late")
    read_out(on_time, contract, first, unit)
    read_out(snapshot, contract, second, unit)
    a, b = first.audit().iloc[0], second.audit().iloc[0]
    assert a["as_of"] == b["as_of"] == str(day.date())
    for role in ("effect", "prehistory_placebo", "shifted_placebo"):
        assert a[role] == b[role]
    assert a["codes"] == b["codes"]


def test_a_readout_that_is_not_due_records_nothing(snapshot, contract, tmp_path):
    registry = Registry(tmp_path)
    last = units(snapshot, contract)[-1]
    day = last.readout_day(contract) - pd.Timedelta(days=2)
    short = Snapshot.from_tables(
        {n: (t[t["day"] < day] if "day" in t else t).copy() for n, t in snapshot.tables.items()}, {"cut": "short"}
    )
    with pytest.raises(NotDue):
        read_out(short, contract, registry, last)
    assert registry.audit().empty and registry.readouts() == []
    summary = replay(short, contract, registry, progress=False)
    assert summary.pending == (last.campaign,) and last.campaign not in set(registry.audit()["campaign"])


def test_campaigns_without_enough_history_are_refused_before_any_estimate(contract, tmp_path):
    short = synthetic_snapshot(replace(WORLDS["random"], households=300, campaigns=3, first_launch_block=2))
    registry = Registry(tmp_path)
    replay(short, contract, registry, progress=False)
    audit = registry.audit().query("method == 'weighting'").sort_values("launch")
    assert audit.iloc[0]["codes"] == ["DATA_INSUFFICIENT_HISTORY"]
    assert audit.iloc[0]["effect"] is None and not audit.iloc[0]["valid_placebo"]
    assert audit.iloc[1]["effect"] is not None


def test_a_readout_due_before_the_feed_starts_is_a_refusal_not_a_gap(snapshot, contract, tmp_path):
    unit = Unit(77, snapshot.first_day - pd.Timedelta(days=40), "Type B")
    refusal = refuse_without_feed(unit, contract, contract.method, snapshot.snapshot_id, unit.readout_day(contract))
    assert isinstance(refusal.result, Refused) and refusal.result.reasons[0].code == "DATA_NO_FEED"
    registry = Registry(tmp_path)
    read_out(snapshot, contract, registry, unit)
    assert [r.reasons[0].code for r in registry.readouts()] == ["DATA_NO_FEED"]
    assert len(registry.audit()) == len(contract.methods)


def test_an_audit_reads_a_campaign_out_before_it_was_launched(snapshot, contract, tmp_path):
    registry = Registry(tmp_path)
    summary = replay(snapshot, contract, registry, shift=1, progress=False)
    audit = registry.audit()
    assert set(audit["shift"]) == {1} and len(summary.read_out) == len(units(snapshot, contract))
    assert registry.readouts() == []  # audits are never published
    for _, row in audit.iterrows():
        assert pd.Timestamp(row["anchor"]) == pd.Timestamp(row["launch"]) - pd.Timedelta(days=28)
        assert pd.Timestamp(row["as_of"]) == pd.Timestamp(row["launch"])
    estimated = audit[audit["effect"].notna()]
    assert len(estimated) > 0 and (estimated["treated"] >= 50).all()


def test_with_enough_households_a_readout_stands_on_its_own_placebos(contract, tmp_path):
    """A randomised campaign in a panel large enough: its own placebos lie within the tolerance and it is published."""
    world = replace(WORLDS["random"], households=8000, campaigns=4)
    registry = Registry(tmp_path)
    replay(
        synthetic_snapshot(world), with_updates(contract, tolerances={"placebo_usd": 10.0}), registry, progress=False
    )
    audit = registry.audit().query("method == 'regression'")
    published = audit[audit["verdict"] == "published"]
    assert len(published) >= 3  # no record is needed, so the first campaigns can already publish
    for _, row in published.iterrows():
        states = {g["gate"]: g["measurements"].get("state") for g in row["gates"]}
        assert states["prehistory_placebo"] == states["assignment"] == "OWN_WITHIN"
    errors = np.array([row["estimate"] for row in published["effect"]]) - world.effect
    assert np.abs(errors).max() < 12.0


def test_diagnostics_say_how_much_one_household_matters(replayed):
    row = replayed.audit().query("valid_placebo").iloc[0]
    diagnostic = row["diagnostics"]
    assert set(diagnostic) == {
        "auc",
        "effective_controls",
        "largest_weight_share",
        "treated_extreme_share",
        "largest_shift_from_one_household",
    }
    assert diagnostic["largest_shift_from_one_household"] > 0 and 0 < diagnostic["largest_weight_share"] < 1
