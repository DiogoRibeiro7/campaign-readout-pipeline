"""The registry only grows, and the first answer for a readout stands."""

from __future__ import annotations

import json

import numpy as np
import pytest

from readout.bootstrap import HouseholdBootstrap
from readout.features import ROLES
from readout.pipeline import PLACEBOS, assess
from readout.registry import Registry, RegistryConflict, _same, readout_key
from readout.replay import read_out, replay, units


def _assessment(snapshot, contract, position=2):
    unit = units(snapshot, contract)[position]
    view = snapshot.as_of(unit.readout_day(contract))
    boot = HouseholdBootstrap(contract.bootstrap.replications, contract.bootstrap.seed)
    return assess(view, unit, contract, contract.method, boot, {})


def test_only_the_primary_method_is_published(replayed, contract):
    audit = replayed.audit()
    assert set(audit["method"]) == {"weighting", "regression"}
    public = replayed.readouts()
    assert {result.method for result in public} == {contract.method.name}
    assert len(public) == int(audit["primary"].sum())


def test_one_record_per_readout(replayed, snapshot, contract):
    keys = [json.loads(line)["key"] for line in replayed.audit_path.read_text().splitlines()]
    expected = {
        readout_key(contract, m.name, u.campaign, 0) for u in units(snapshot, contract) for m in contract.methods
    }
    assert set(keys) == expected and len(keys) == len(expected)


def test_recording_again_changes_nothing(snapshot, contract, tmp_path):
    registry = Registry(tmp_path)
    assessment = _assessment(snapshot, contract)
    registry.record(assessment, contract, publish=True)
    before = registry.audit_path.read_text(), registry.readouts_path.read_text()
    registry.record(assessment, contract, publish=True)
    registry.record(_assessment(snapshot, contract), contract, publish=True)  # computed afresh
    assert (registry.audit_path.read_text(), registry.readouts_path.read_text()) == before


def test_a_different_answer_for_the_same_readout_is_a_conflict(snapshot, contract, tmp_path):
    registry = Registry(tmp_path)
    assessment = _assessment(snapshot, contract)
    registry.record(assessment, contract, publish=True)
    assessment.treated += 1  # the same readout, now claiming something else
    with pytest.raises(RegistryConflict):
        registry.record(assessment, contract, publish=True)
    assert len(registry.audit()) == 1


def test_the_last_digits_of_a_number_are_not_a_different_answer():
    a = {
        "effect": {"estimate": 12.345678901234567, "low": -1.0},
        "codes": ["X"],
        "treated": 81,
        "provenance": {"view_id": "a"},
    }
    b = {
        "effect": {"estimate": 12.345678901234569, "low": -1.0},
        "codes": ["X"],
        "treated": 81,
        "provenance": {"view_id": "b"},
    }
    assert _same(a, b)  # rounding, and where the run happened
    assert not _same(a, {**b, "effect": {"estimate": 12.3457, "low": -1.0}})
    assert not _same(a, {**b, "treated": 82})
    assert not _same(a, {**b, "codes": ["Y"]})
    assert not _same(a, {k: v for k, v in b.items() if k != "treated"})
    assert not _same({"x": 1.0}, {"x": True}) and not _same({"x": None}, {"x": 0.0})


def test_a_line_cut_short_by_a_crash_is_dropped_and_the_registry_goes_on(snapshot, contract, tmp_path):
    registry = Registry(tmp_path)
    registry.record(_assessment(snapshot, contract, 2), contract, publish=True)
    with registry.audit_path.open("a") as handle:
        handle.write('{"key": "half a li')  # no newline: the process died here
    assert len(registry.audit()) == 1
    registry.record(_assessment(snapshot, contract, 3), contract, publish=True)
    lines = registry.audit_path.read_text().splitlines()
    assert len(lines) == 2 and all(json.loads(line)["key"] for line in lines)


def test_draws_are_stored_for_every_role(replayed):
    row = replayed.audit().query("valid_placebo").iloc[0]
    stored = replayed.draws(row["key"])
    assert set(stored) == set(ROLES)
    for role in ROLES:
        assert stored[role].shape == (60,)
        assert np.percentile(stored[role], 2.5) == pytest.approx(row[role]["low"])


def test_the_record_of_a_unit_holds_only_what_was_anchored_before_it(replayed, snapshot, contract):
    ordered = units(snapshot, contract)
    valid = set(replayed.audit().query("valid_placebo and method == 'weighting'")["campaign"])
    for position, unit in enumerate(ordered):
        history = replayed.record_history(contract, contract.method, unit)
        earlier = [u.campaign for u in ordered[:position] if u.campaign in valid]
        for placebo in PLACEBOS:
            assert [entry.campaign for entry in history[placebo]] == earlier


def test_records_of_other_contracts_are_not_mixed_in(replayed, snapshot, contract, lenient):
    unit = units(snapshot, contract)[-1]
    assert replayed.record_history(lenient, lenient.method, unit) == {placebo: [] for placebo in PLACEBOS}
    assert replayed.audit(lenient).empty and replayed.readouts(lenient) == [] and replayed.programme(lenient).empty
    assert len(replayed.audit(contract)) == len(replayed.audit())


def test_a_replay_can_be_run_again_and_computes_nothing_twice(snapshot, contract, tmp_path, monkeypatch):
    registry = Registry(tmp_path)
    replay(snapshot, contract, registry, progress=False)
    before = {
        path.name: path.read_text() for path in (registry.audit_path, registry.readouts_path, registry.programme_path)
    }

    def no_estimates(*args, **kwargs):
        raise AssertionError("a recorded readout was estimated again")

    monkeypatch.setattr(HouseholdBootstrap, "draws", no_estimates)
    replay(snapshot, contract, registry, progress=False)
    read_out(snapshot, contract, registry, units(snapshot, contract)[1])
    assert {
        path.name: path.read_text() for path in (registry.audit_path, registry.readouts_path, registry.programme_path)
    } == before


def test_running_campaigns_out_of_order_keeps_the_first_answers(snapshot, contract, tmp_path):
    """A campaign read out before an earlier one keeps the record it had at the time."""
    registry = Registry(tmp_path)
    ordered = units(snapshot, contract)
    read_out(snapshot, contract, registry, ordered[4])
    first = registry.audit_path.read_text()
    read_out(snapshot, contract, registry, ordered[3])
    read_out(snapshot, contract, registry, ordered[4])  # again, now that an earlier campaign is on record
    assert registry.audit_path.read_text().startswith(first)
    assert registry.audit()["campaign"].value_counts().max() == len(contract.methods)


def test_every_line_is_json_with_a_unique_key(replayed):
    for path in (replayed.audit_path, replayed.readouts_path, replayed.programme_path):
        keys = [json.loads(line)["key"] for line in path.read_text().splitlines()]
        assert len(keys) == len(set(keys)) > 0
