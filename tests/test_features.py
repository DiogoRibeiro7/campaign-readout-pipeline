"""Covariates and outcomes: the three problems of a readout, and what they may not see."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from conftest import launch_of, with_extra_campaign, without_early_purchases
from readout.features import LATE_COLUMNS, ROLES, build_problem, covariates, design, design_columns, seen_before
from readout.snapshot import Snapshot

WINDOW, HISTORY = 28, 56
THROUGH, AT_LAUNCH = "through_outcome_window", "at_launch"


def _problems(view, campaign, launch, rule=THROUGH):
    return {role: build_problem(view, campaign, launch, role, WINDOW, HISTORY, rule) for role in ROLES}


def test_the_three_problems_use_the_right_days(snapshot):
    launch = launch_of(snapshot, 3)
    view = snapshot.as_of(launch + pd.Timedelta(days=WINDOW))
    p = _problems(view, 3, launch)
    daily = view.daily

    def spend(start, households):
        rows = daily[(daily["day"] >= start) & (daily["day"] < start + pd.Timedelta(days=WINDOW))]
        return rows.groupby("household_id")["sales_value"].sum().reindex(households).fillna(0.0).to_numpy()

    np.testing.assert_allclose(p["effect"].y, spend(launch, p["effect"].households))
    np.testing.assert_allclose(
        p["shifted_placebo"].y, spend(launch - pd.Timedelta(days=WINDOW), p["shifted_placebo"].households)
    )
    earlier = launch - pd.Timedelta(days=HISTORY + WINDOW)
    np.testing.assert_allclose(p["prehistory_placebo"].y, spend(earlier, p["prehistory_placebo"].households))
    assert p["shifted_placebo"].covariates_end == launch - pd.Timedelta(days=WINDOW)
    assert p["effect"].covariates_end == p["prehistory_placebo"].covariates_end == launch


def test_the_prehistory_placebo_adjusts_for_what_the_effect_adjusts_for(snapshot):
    launch = launch_of(snapshot, 3)
    p = _problems(snapshot.as_of(launch + pd.Timedelta(days=WINDOW)), 3, launch)
    effect, placebo = p["effect"], p["prehistory_placebo"]
    np.testing.assert_array_equal(placebo.households, effect.households)
    np.testing.assert_array_equal(placebo.d, effect.d)
    # The same columns, and two more for the other campaigns that were live in the placebo's own window.
    assert placebo.names == (*effect.names, "window_large", "window_small")
    np.testing.assert_array_equal(placebo.x[:, : effect.x.shape[1]], effect.x)


def test_each_placebo_outcome_lies_outside_its_own_history(snapshot):
    launch = launch_of(snapshot, 3)
    for role, p in _problems(snapshot.as_of(launch + pd.Timedelta(days=WINDOW)), 3, launch).items():
        history_start = p.covariates_end - pd.Timedelta(days=HISTORY)
        outcome_end = p.outcome_start + pd.Timedelta(days=WINDOW)
        assert outcome_end <= history_start or p.outcome_start >= p.covariates_end, role


def test_the_population_is_who_had_shopped_before_the_covariate_date(snapshot):
    """A household first seen later has no history and, in the outcome window, spending by construction."""
    launch = launch_of(snapshot, 3)
    late = without_early_purchases(snapshot, [1, 2, 3], launch + pd.Timedelta(days=2))
    view = late.as_of(launch + pd.Timedelta(days=WINDOW))
    assert {1, 2, 3} <= set(view.households)  # seen by the readout day
    p = _problems(view, 3, launch)
    for role in ROLES:
        assert not {1, 2, 3} & set(p[role].households), role
        np.testing.assert_array_equal(p[role].households, seen_before(view, p[role].covariates_end))
    whole = build_problem(view, 3, launch, "effect", WINDOW, HISTORY, THROUGH, population="whole_view")
    assert {1, 2, 3} <= set(whole.households)
    with pytest.raises(ValueError, match="unknown population"):
        build_problem(view, 3, launch, "effect", WINDOW, HISTORY, THROUGH, population="everyone")


def test_unknown_role_and_rule_are_rejected(snapshot):
    launch = launch_of(snapshot, 3)
    view = snapshot.as_of(launch + pd.Timedelta(days=WINDOW))
    with pytest.raises(ValueError, match="unknown role"):
        build_problem(view, 3, launch, "placebo", WINDOW, HISTORY, THROUGH)
    with pytest.raises(ValueError, match="unknown rule"):
        covariates(view, 3, launch, WINDOW, HISTORY, "whenever")


def _tampered_after(snapshot: Snapshot, day: pd.Timestamp) -> Snapshot:
    """The snapshot with every purchase dated on or after ``day`` changed."""
    tables = {name: frame.copy() for name, frame in snapshot.tables.items()}
    later = tables["daily"]["day"] >= day
    tables["daily"].loc[later, ["sales_value", "private", "retail"]] *= 7.0
    tables["daily"].loc[later, "trips"] += 3
    tables["stores"].loc[tables["stores"]["day"] >= day, "store_id"] += 100
    return Snapshot.from_tables(tables, {"synthetic": "tampered"})


def test_what_a_household_did_is_read_before_the_launch_only(snapshot):
    """Change every purchase from the launch on: no covariate moves, and no placebo outcome."""
    launch = launch_of(snapshot, 4)
    readout_day = launch + pd.Timedelta(days=WINDOW)
    original = _problems(snapshot.as_of(readout_day), 4, launch)
    changed = _problems(_tampered_after(snapshot, launch).as_of(readout_day), 4, launch)
    for role in ROLES:
        np.testing.assert_array_equal(changed[role].x, original[role].x)
    np.testing.assert_array_equal(changed["shifted_placebo"].y, original["shifted_placebo"].y)
    np.testing.assert_array_equal(changed["prehistory_placebo"].y, original["prehistory_placebo"].y)
    assert not np.array_equal(changed["effect"].y, original["effect"].y)


def test_the_campaign_calendar_is_followed_as_far_as_the_rule_says(snapshot):
    """A campaign that starts during the outcome window counts under one rule and not under the other."""
    launch = launch_of(snapshot, 4)
    readout_day = launch + pd.Timedelta(days=WINDOW)
    busier = with_extra_campaign(snapshot, launch + pd.Timedelta(days=5), range(1, 200))
    for rule, moves in ((THROUGH, True), (AT_LAUNCH, False)):
        original = build_problem(snapshot.as_of(readout_day), 4, launch, "effect", WINDOW, HISTORY, rule)
        changed = build_problem(busier.as_of(readout_day), 4, launch, "effect", WINDOW, HISTORY, rule)
        late = original.late
        assert late.any() == moves
        assert [n for n, flag in zip(original.names, late, strict=True) if flag] == (
            list(LATE_COLUMNS) if moves else []
        )
        np.testing.assert_array_equal(changed.x[:, ~late], original.x[:, ~late])
        assert (not np.array_equal(changed.x, original.x)) == moves
        assert original.calendar_until == (readout_day if moves else launch)


def test_members_can_be_given_for_a_campaign_not_launched_yet(snapshot):
    """An audit reads a campaign out before its launch, when the view does not know its members."""
    launch = launch_of(snapshot, 4)
    anchor = launch - pd.Timedelta(days=WINDOW)
    view = snapshot.as_of(anchor + pd.Timedelta(days=WINDOW))  # the launch day: campaign 4 is not visible
    assert 4 not in view.descriptions.index
    table = snapshot.tables["campaigns"]
    ids = table.loc[table["campaign_id"] == 4, "household_id"].to_numpy()
    p = build_problem(view, 4, anchor, "effect", WINDOW, HISTORY, THROUGH, member_ids=ids)
    assert p.treated == np.isin(p.households, ids).sum() > 0
    assert (
        build_problem(view, 4, anchor, "effect", WINDOW, HISTORY, THROUGH).treated == 0
    )  # the view alone knows nobody


def test_design_groups(snapshot):
    launch = launch_of(snapshot, 3)
    frame = covariates(snapshot.as_of(launch), 3, launch, WINDOW, HISTORY, THROUGH)
    assert design(frame).shape[1] == 2 * (HISTORY // WINDOW) + 7 + 3
    assert design(frame, ("spend",)).shape[1] == 7 + 3
    assert design(frame, ("spend", "behaviour")).shape[1] == 3
    assert list(design_columns(frame, ("spend", "behaviour"))) == ["earlier", "live_large", "live_small"]
    with pytest.raises(ValueError, match="unknown covariate groups"):
        design(frame, ("weather",))
