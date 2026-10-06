"""Re-reading stored readouts agrees with running the gates, and the diagnostics say what they claim."""

from __future__ import annotations

import math

import numpy as np
import pytest

from conftest import with_updates
from readout import diagnostics, planning
from readout.registry import Registry
from readout.replay import replay
from readout.sweep import evidence_tolerance, smallest_tolerance, sweep, verdict_at


@pytest.fixture(scope="module")
def two_shifts(snapshot, contract, tmp_path_factory) -> Registry:
    registry = Registry(tmp_path_factory.mktemp("two_shifts"))
    for shift in (0, 1):
        replay(snapshot, contract, registry, shift=shift, progress=False)
    return registry


def test_the_sweep_reproduces_the_recorded_verdicts(replayed, replayed_lenient, contract, lenient):
    for registry, used in ((replayed, contract), (replayed_lenient, lenient)):
        tol = used.tolerances
        for _, row in registry.audit().iterrows():
            verdict, codes = verdict_at(row, tol.placebo_usd, tol.min_record_campaigns)
            assert verdict == row["verdict"]
            if not any(gate in ("data", "timing", "estimator", "overlap") for gate in row["failed_gates"]):
                assert list(codes) == row["codes"]


def test_the_smallest_tolerance_is_where_the_verdict_turns(replayed, contract):
    k = contract.tolerances.min_record_campaigns
    turned = 0
    for _, row in replayed.audit().iterrows():
        for documented in (False, True):
            smallest = smallest_tolerance(row, k, documented)
            if math.isinf(smallest):
                assert row["failed_gates"] and row["failed_gates"][0] in ("data", "timing", "estimator", "overlap")
                continue
            assert verdict_at(row, smallest * (1 + 1e-9), k, documented)[0] == "published"
            assert verdict_at(row, smallest * (1 - 1e-6), k, documented)[0] == "refused"
            turned += 1
        assert smallest_tolerance(row, k, True) <= smallest_tolerance(row, k, False)
    assert turned > 0


def test_evidence_tolerance_by_hand():
    own = {"low": -4.0, "high": 9.0}
    short = {"campaigns": [1, 2], "prediction_low": None, "prediction_high": None}
    tight = {"campaigns": list(range(8)), "prediction_low": -2.0, "prediction_high": 3.0}
    assert evidence_tolerance(own, short, 5) == 9.0  # only the own interval can do it
    assert evidence_tolerance(own, tight, 5) == 3.0  # the record does it sooner
    beyond = {"low": 6.0, "high": 20.0}
    assert evidence_tolerance(beyond, tight, 5) == 6.0  # not while the own interval lies beyond the band


def test_sweep_counts_add_up(replayed, contract):
    table = sweep(replayed.audit(), [5.0, 50.0, 1e6], contract.tolerances.min_record_campaigns)
    assert set(table["assignment_documented"]) == {False, True}
    assert (table["published"] <= table["readouts"]).all()
    for _, group in table.groupby(["method", "shift", "assignment_documented"]):
        published = group.sort_values("tolerance_usd")["published"].tolist()
        assert published == sorted(published)  # relaxing the tolerance never refuses more
        blocked = group["refused_before_estimation"].iloc[0] + group["refused_for_overlap"].iloc[0]
        assert published[-1] == group["readouts"].iloc[0] - blocked
    documented = table[table["assignment_documented"]].set_index(["method", "tolerance_usd"])["published"]
    unknown = table[~table["assignment_documented"]].set_index(["method", "tolerance_usd"])["published"]
    assert (documented >= unknown).all()


def test_pooled_by_shift(two_shifts, contract):
    table = diagnostics.pooled_by_shift(two_shifts, contract, (0, 1))
    assert len(table) == 4 and set(table["shift"]) == {0, 1}
    assert (table["smallest_tolerance_documented"] <= table["smallest_tolerance_undocumented"]).all()
    row = table[(table["method"] == "regression") & (table["shift"] == 0)].iloc[0]
    units = two_shifts.valid_units(contract, contract.shadow_methods[0], 0)
    assert row["units_with_estimates"] == len(units)
    assert row["mean_estimate"] == pytest.approx(np.mean([e["estimate"] for e in units["effect"]]))
    # The difference between the two placebos is the difference of their means, with an interval of its own.
    assert row["placebo_difference"] == pytest.approx(row["mean_prehistory_placebo"] - row["mean_shifted_placebo"])
    assert row["placebo_difference_low"] < row["placebo_difference"] < row["placebo_difference_high"]
    # In this world the shifted placebo is what the retailer targeted on, and the difference shows it.
    assert row["placebo_difference_high"] < 0


def test_gate_audit_reads_only_the_earlier_windows(two_shifts, contract):
    gate = diagnostics.gate_audit(two_shifts, contract, (0, 1), [5.0, 1e6])
    assert set(gate["shift"]) == {1}
    everything = gate[gate["tolerance_usd"] == 1e6]
    assert (everything["published"] == everything["units_with_estimates"]).all()
    nothing = gate[(gate["tolerance_usd"] == 5.0) & ~gate["assignment_documented"]]
    assert (nothing["published"] == 0).all() and "mean_estimate" in gate


def test_spending_gap_is_the_raw_difference(replayed, snapshot, contract):
    gap = diagnostics.spending_gap(snapshot, replayed, contract, windows_back=3)
    assert set(gap["window"]) <= {-3, -2, -1, 0} and gap["window"].max() == 0
    assert np.allclose(gap["gap"], gap["targeted"] - gap["comparison"])
    assert (gap.loc[gap["window"] == -1, "gap"] > 0).all()  # chosen on recent spending


def test_prehistory_check_restricts_to_households_already_seen(replayed, snapshot, contract):
    check = diagnostics.prehistory_check(snapshot, replayed, contract)
    assert set(check["method"]) == {"weighting", "regression"}
    assert (check["households_seen_before_window"] <= check["households"]).all()
    late = check[check["households_seen_before_window"] < 100]
    assert late["prehistory_placebo_seen_before_window"].isna().all()  # too few to estimate on: no number, no warning


def test_like_for_like_pairs_the_contracts_on_shared_campaigns(snapshot, contract, tmp_path):
    longer = with_updates(contract, windows={"history_days": 84}).model_copy(update={"version": 2})
    registry = Registry(tmp_path)
    for used in (contract, longer):
        replay(snapshot, used, registry, progress=False)
    table = diagnostics.like_for_like(registry, [contract, longer])
    assert set(table["contract"]) == {"v1", "v2"} and table["campaigns"].nunique() == 1
    first = table[table["contract"] == "v1"]
    second = table[table["contract"] == "v2"].set_index("method")
    assert first["change_in_mean_estimate"].isna().all()
    for method, row in second.iterrows():
        base = first.set_index("method").loc[method]
        assert row["change_in_mean_estimate"] == pytest.approx(row["mean_estimate"] - base["mean_estimate"])
        assert (
            row["change_in_mean_estimate_low"] <= row["change_in_mean_estimate"] <= row["change_in_mean_estimate_high"]
        )
    assert diagnostics.like_for_like(registry, [contract]).empty


# ---- planning ------------------------------------------------------------------------
def test_pass_probability_by_hand():
    # A standard error of 1 and a tolerance of 5: the estimate has to fall within 5 - 1.96 of zero.
    assert planning.pass_probability(1.0, 0.0, 5.0, 0.95) == pytest.approx(0.99764, abs=1e-4)
    # At the edge of the tolerance the chance is at most 2.5%, whatever the precision.
    for se in (0.1, 1.0, 2.0, 2.5):
        assert planning.pass_probability(se, 5.0, 5.0, 0.95) <= 0.025 + 1e-9
    assert planning.pass_probability(0.01, 5.0, 5.0, 0.95) == pytest.approx(0.025, abs=1e-6)
    # An interval wider than the band cannot fit, whatever the estimate.
    assert planning.pass_probability(3.0, 0.0, 5.0, 0.95) == 0.0


def test_correlated_estimates_do_not_average_out():
    assert planning.pooled_standard_error(10.0, 0.0, 100) == pytest.approx(1.0)
    assert planning.pooled_standard_error(10.0, 0.04, 100) == pytest.approx(10.0 * math.sqrt(4.96 / 100))
    assert planning.pooled_standard_error(10.0, 0.04, 10**6) == pytest.approx(2.0, abs=1e-3)  # the floor: s sqrt(r)


def test_campaigns_needed():
    # Standard error 10, tolerance 5: the interval fits once 1.96 * 10 / sqrt(K) < 5, that is from K = 16.
    assert planning.campaigns_needed(10.0, 0.0, 5.0, 0.95, None) == 16
    eighty = planning.campaigns_needed(10.0, 0.0, 5.0, 0.95, 0.8)
    assert eighty > 16
    assert planning.pass_probability(planning.pooled_standard_error(10.0, 0.0, eighty), 0.0, 5.0, 0.95) >= 0.8
    assert planning.pass_probability(planning.pooled_standard_error(10.0, 0.0, eighty - 1), 0.0, 5.0, 0.95) < 0.8
    assert planning.campaigns_needed(10.0, 0.1, 5.0, 0.95, None) is None  # the floor is above the tolerance


def test_plan_reads_its_noise_from_the_registry(replayed, contract):
    profile = planning.noise_profile(replayed, contract, contract.method, "prehistory_placebo")
    units = replayed.valid_units(contract, contract.method, 0)
    assert profile["campaigns"] == len(units) > 1
    widths = np.array([e["high"] - e["low"] for e in units["prehistory_placebo"]])
    assert np.allclose(profile["standard_errors"], widths / (2 * 1.959964), rtol=1e-6)
    table = planning.plan(replayed, contract, campaigns=(10, 1000), correlations=(0.0, 0.05))
    assert set(table["placebo"]) == {"prehistory_placebo", "shifted_placebo"}
    zero = table[(table["true_mean_placebo"] == 0) & (table["assumed_correlation"] == 0.0)]
    for _, group in zero.groupby(["method", "placebo"]):
        assert group.sort_values("campaigns")["passes"].is_monotonic_increasing
    edge = table[table["true_mean_placebo"] > 0]
    assert (edge["passes"] <= 0.025 + 1e-9).all()
