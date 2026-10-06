"""Each gate, failed on purpose."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from conftest import launch_of, with_extra_campaign, with_updates, without_early_purchases
from readout import gates
from readout.estimators import Overlap
from readout.features import ROLES, build_problem
from readout.result import Interval, Record
from readout.snapshot import Snapshot

WINDOW, HISTORY = 28, 56
THROUGH, AT_LAUNCH = "through_outcome_window", "at_launch"


# ---- data ----------------------------------------------------------------------------
def test_data_gate_passes_on_a_whole_feed(snapshot, contract):
    launch = launch_of(snapshot, 3)
    view = snapshot.as_of(launch + pd.Timedelta(days=WINDOW))
    outcome = gates.data_gate(view, launch, 120, 380, contract)
    assert outcome.passed and outcome.code is None
    assert outcome.measurements["days_without_sales"] == 0


def test_data_gate_needs_the_outcome_window_to_have_closed(snapshot, contract):
    launch = launch_of(snapshot, 3)
    view = snapshot.as_of(launch + pd.Timedelta(days=WINDOW - 1))
    assert gates.data_gate(view, launch, 120, 380, contract).code == "DATA_OUTCOME_INCOMPLETE"


def test_data_gate_needs_history_for_the_placebos(snapshot, contract):
    launch = snapshot.first_day + pd.Timedelta(days=HISTORY + WINDOW - 1)
    view = snapshot.as_of(launch + pd.Timedelta(days=WINDOW))
    assert gates.data_gate(view, launch, 120, 380, contract).code == "DATA_INSUFFICIENT_HISTORY"
    enough = launch + pd.Timedelta(days=1)
    assert gates.data_gate(snapshot.as_of(enough + pd.Timedelta(days=WINDOW)), enough, 120, 380, contract).passed


def test_data_gate_counts_households(snapshot, contract):
    launch = launch_of(snapshot, 3)
    view = snapshot.as_of(launch + pd.Timedelta(days=WINDOW))
    assert gates.data_gate(view, launch, 49, 380, contract).code == "DATA_TOO_FEW_TREATED"
    assert gates.data_gate(view, launch, 120, 49, contract).code == "DATA_TOO_FEW_CONTROLS"


def test_data_gate_sees_a_day_missing_from_the_feed(snapshot, contract):
    launch = launch_of(snapshot, 3)
    lost = launch - pd.Timedelta(days=10)
    tables = {name: frame.copy() for name, frame in snapshot.tables.items()}
    tables["daily"] = tables["daily"][tables["daily"]["day"] != lost]
    view = Snapshot.from_tables(tables, {"synthetic": "one day lost"}).as_of(launch + pd.Timedelta(days=WINDOW))
    outcome = gates.data_gate(view, launch, 120, 380, contract)
    assert outcome.code == "DATA_GAP" and str(lost.date()) in outcome.detail
    # A day the contract declares closed is not a gap.
    declared = with_updates(contract, data={"closed_days": (lost.strftime("%m-%d"),)})
    assert gates.data_gate(view, launch, 120, 380, declared).passed


# ---- timing --------------------------------------------------------------------------
def _problems(view, campaign, launch, rule=THROUGH, **kwargs):
    return [build_problem(view, campaign, launch, role, WINDOW, HISTORY, rule, **kwargs) for role in ROLES]


def test_timing_gate_passes_on_problems_built_as_declared(snapshot, contract):
    launch = launch_of(snapshot, 4)
    busier = with_extra_campaign(snapshot, launch + pd.Timedelta(days=5), range(1, 200))
    view = busier.as_of(launch + pd.Timedelta(days=WINDOW))
    outcome = gates.timing_gate(view, _problems(view, 4, launch), contract)
    assert outcome.passed
    assert all(value == 0 for value in outcome.measurements.values())
    at_launch = with_updates(contract, covariates={"concurrent_campaigns": AT_LAUNCH})
    assert gates.timing_gate(view, _problems(view, 4, launch, AT_LAUNCH), at_launch).passed


def test_timing_gate_refuses_a_calendar_rule_the_contract_does_not_declare(snapshot, contract):
    launch = launch_of(snapshot, 4)
    view = snapshot.as_of(launch + pd.Timedelta(days=WINDOW))
    at_launch = with_updates(contract, covariates={"concurrent_campaigns": AT_LAUNCH})
    outcome = gates.timing_gate(view, _problems(view, 4, launch, THROUGH), at_launch)
    assert not outcome.passed and outcome.code == "TIMING_LATE_COVARIATE"


def test_timing_gate_catches_a_leak_the_labels_hide(snapshot, contract):
    """Covariates that follow the calendar past their date, labelled as if they did not: the recomputation finds them."""
    launch = launch_of(snapshot, 4)
    busier = with_extra_campaign(snapshot, launch + pd.Timedelta(days=5), range(1, 200))
    view = busier.as_of(launch + pd.Timedelta(days=WINDOW))
    at_launch = with_updates(contract, covariates={"concurrent_campaigns": AT_LAUNCH})
    mislabelled = [replace(p, calendar_until=p.covariates_end) for p in _problems(view, 4, launch, THROUGH)]
    outcome = gates.timing_gate(view, mislabelled, at_launch)
    assert not outcome.passed and outcome.code == "TIMING_LEAK"
    assert outcome.measurements["largest_change_in_covariates_when_cut_at_their_date"] >= 1.0


def test_timing_gate_catches_a_population_selected_on_the_future(snapshot, contract):
    """Households first seen after the launch, compared as if they had been there: the prototype's population."""
    launch = launch_of(snapshot, 4)
    late = without_early_purchases(snapshot, [1, 2, 3], launch + pd.Timedelta(days=2))
    view = late.as_of(launch + pd.Timedelta(days=WINDOW))
    outcome = gates.timing_gate(view, _problems(view, 4, launch, population="whole_view"), contract)
    assert not outcome.passed and outcome.code == "TIMING_POPULATION"
    assert outcome.measurements["households_not_seen_before_covariate_date"] >= 3
    assert gates.timing_gate(view, _problems(view, 4, launch), contract).passed


def test_timing_gate_catches_an_outcome_from_another_window(snapshot, contract):
    launch = launch_of(snapshot, 4)
    view = snapshot.as_of(launch + pd.Timedelta(days=WINDOW))
    problems = _problems(view, 4, launch)
    swapped = [replace(problems[0], y=problems[2].y), *problems[1:]]  # the effect given the pre-history spending
    outcome = gates.timing_gate(view, swapped, contract)
    assert not outcome.passed and outcome.code == "TIMING_OUTCOME"
    early = snapshot.as_of(launch + pd.Timedelta(days=WINDOW - 3))  # the outcome window has not closed
    assert (
        gates.timing_gate(
            early,
            _problems(early, 4, launch, AT_LAUNCH),
            with_updates(contract, covariates={"concurrent_campaigns": AT_LAUNCH}),
        ).code
        == "TIMING_OUTCOME"
    )


# ---- overlap -------------------------------------------------------------------------
def _overlap(share=0.02, effective=400.0, largest=0.01):
    return Overlap(auc=0.7, effective_controls=effective, largest_weight_share=largest, treated_extreme_share=share)


def _scores(**shifted):
    return {"effect": _overlap(), "shifted_placebo": _overlap(**shifted)}


def test_overlap_gate(contract):
    weighting, regression = contract.method, contract.shadow_methods[0]
    assert (weighting.name, regression.name) == ("weighting", "regression")
    assert gates.overlap_gate(_scores(), contract, weighting).passed
    assert gates.overlap_gate({"effect": _overlap(share=0.3)}, contract, weighting).code == "OVERLAP_EXTREME_SCORES"
    assert gates.overlap_gate({"effect": _overlap(share=0.3)}, contract, regression).code == "OVERLAP_EXTREME_SCORES"
    assert (
        gates.overlap_gate({"effect": _overlap(effective=20.0)}, contract, weighting).code
        == "OVERLAP_FEW_EFFECTIVE_CONTROLS"
    )
    assert (
        gates.overlap_gate({"effect": _overlap(largest=0.2)}, contract, weighting).code
        == "OVERLAP_ONE_HOUSEHOLD_DOMINATES"
    )
    # The two conditions on weights are properties of the weights; regression does not use them.
    assert gates.overlap_gate({"effect": _overlap(effective=20.0, largest=0.2)}, contract, regression).passed


def test_overlap_gate_also_judges_the_shifted_placebo(contract):
    outcome = gates.overlap_gate(_scores(share=0.3), contract, contract.method)
    assert outcome.code == "OVERLAP_EXTREME_SCORES" and "shifted placebo" in outcome.detail
    assert outcome.measurements["effect_treated_extreme_share"] == 0.02
    assert outcome.measurements["shifted_placebo_treated_extreme_share"] == 0.3


# ---- the two placebo gates -----------------------------------------------------------
def _interval(low, high):
    return Interval(estimate=(low + high) / 2, low=low, high=high, se=(high - low) / 4)


def _record(state):
    return Record(
        state=state,
        campaigns=tuple(range(8)),
        mean=_interval(-1, 1),
        heterogeneity_sd=0.5,
        heterogeneity_upper=1.2,
        prediction_low=-3.0,
        prediction_high=3.0,
    )


@pytest.mark.parametrize(
    ("own", "record", "passed", "state", "source"),
    [
        ((-2, 3), "too_few", True, "OWN_WITHIN", "own_placebo"),
        ((6, 30), "certified", False, "OWN_OUTSIDE", None),  # the record cannot overrule the readout's own placebo
        ((-8, 12), "certified", True, "RECORD_CERTIFIED", "method_record"),
        ((-8, 12), "too_few", False, "RECORD_TOO_FEW", None),
        ((-8, 12), "bias", False, "RECORD_BIAS", None),
        ((-8, 12), "not_certified", False, "RECORD_NOT_CERTIFIED", None),
    ],
)
def test_what_counts_as_evidence(own, record, passed, state, source):
    assert gates._evidence(_interval(*own), _record(record), 5.0) == (passed, state, source)


def test_a_placebo_that_merely_contains_zero_shows_nothing(contract):
    """An interval from -8 to 12 does not reject zero. It does not pass either."""
    outcome, source = gates.prehistory_gate(_interval(-8, 12), _record("too_few"), contract)
    assert not outcome.passed and source is None


def test_prehistory_gate_reports_its_state(contract):
    outcome, source = gates.prehistory_gate(_interval(-8, 12), _record("bias"), contract)
    assert (outcome.gate, outcome.passed, outcome.code, source) == (
        "prehistory_placebo",
        False,
        "PREHISTORY_RECORD_BIAS",
        None,
    )
    assert outcome.thresholds["placebo_usd"] == contract.tolerances.placebo_usd
    outcome, source = gates.prehistory_gate(_interval(-2, 3), _record("bias"), contract)
    assert outcome.passed and outcome.code is None and source == "own_placebo"


def test_assignment_gate_needs_the_shifted_placebo_only_when_the_rule_is_unknown(contract, documented):
    failing = _interval(40, 90)
    outcome, source = gates.assignment_gate(failing, _record("bias"), contract)
    assert not outcome.passed and outcome.code == "ASSIGNMENT_UNDOCUMENTED_OWN_OUTSIDE" and source is None
    outcome, source = gates.assignment_gate(failing, _record("bias"), documented)
    assert outcome.passed and source == "documented_rule"
    assert outcome.measurements["placebo"] == 65.0  # still measured and reported
    outcome, source = gates.assignment_gate(_interval(-8, 12), _record("certified"), contract)
    assert outcome.passed and source == "method_record"


def test_a_gate_that_cannot_be_evaluated_fails(contract):
    """No record and an inconclusive placebo: missing evidence is not evidence that things are fine."""
    empty = Record(
        state="too_few",
        campaigns=(1,),
        mean=_interval(-8, 12),
        heterogeneity_sd=None,
        heterogeneity_upper=None,
        prediction_low=None,
        prediction_high=None,
    )
    assert not gates.prehistory_gate(_interval(-8, 12), empty, contract)[0].passed
    assert not gates.assignment_gate(_interval(-8, 12), empty, contract)[0].passed
    assert np.isfinite(contract.tolerances.placebo_usd)
