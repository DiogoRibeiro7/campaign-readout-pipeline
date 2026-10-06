"""The pipeline computes what the prototype computed, when asked the prototype's way."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from conftest import ROOT, as_prototype_data
from readout import parity
from readout.estimators import ESTIMATORS, overlap
from readout.features import build_problem

WINDOW, HISTORY = 28, 56
RULES = {False: "through_outcome_window", True: "at_launch"}


@pytest.mark.parametrize("running_only", [False, True])
@pytest.mark.parametrize(("lag", "role"), [(0, "effect"), (1, "shifted_placebo")])
def test_problems_equal_the_prototypes(prototype, snapshot, running_only, lag, role):
    """Outcome, treatment and covariates, element by element, on a synthetic retailer."""
    view = snapshot.full()
    data = as_prototype_data(view)
    for campaign in (3, 4, 5):
        launch = view.descriptions.loc[campaign, "start_date"]
        y, d, x, _ = prototype.problem(data, campaign, lag, WINDOW, HISTORY, running_only)
        ours = build_problem(
            view, campaign, launch, role, WINDOW, HISTORY, RULES[running_only], population="whole_view"
        )
        np.testing.assert_array_equal(ours.y, y)
        np.testing.assert_array_equal(ours.d, d)
        np.testing.assert_array_equal(ours.x, x)


def test_estimates_equal_the_prototypes(prototype, snapshot):
    view = snapshot.full()
    data = as_prototype_data(view)
    for campaign in (3, 4, 5):
        y, d, x, _ = prototype.problem(data, campaign, 0, WINDOW, HISTORY)
        theirs = prototype.three_estimates(y, d, x)
        assert ESTIMATORS["regression"](y, d, x) == pytest.approx(theirs["Regression"], abs=1e-9)
        assert ESTIMATORS["weighting"](y, d, x) == pytest.approx(theirs["Weighting"], abs=1e-9)
        scores = overlap(d, x, 0.9)
        assert scores.auc == pytest.approx(theirs["auc"], abs=1e-12)
        assert scores.effective_controls == pytest.approx(theirs["weighting_effective_controls"], rel=1e-9)
        assert scores.treated_extreme_share == pytest.approx(theirs["treated_score_above_0.9"], abs=1e-12)


def test_the_pipeline_drops_the_prototypes_estimator_without_an_interval():
    assert set(ESTIMATORS) == {"regression", "weighting"}


@pytest.mark.data
def test_published_numbers_are_reproduced_on_the_real_data(real_snapshot, real_contract):
    table = parity.compare(real_snapshot, real_contract, ROOT / "prototype" / "placebo_results.json")
    assert len(table) == 16 * 2 * 2  # campaigns, windows, estimators
    assert parity.largest_difference(table) < 1e-6
    # The two deliberate changes shrink the comparison group, and move the estimates a little.
    main = table[table["window"] == "main"]
    assert (main["households_production"] <= main["households_as_of"]).all()
    assert (main["households_as_of"] <= main["households_prototype"]).all()
    assert (main["households_production"] < main["households_prototype"]).all()
    regression = main[main["estimator"] == "regression"]
    assert 0 < np.abs(regression["production"] - regression["prototype"]).max() < 2.0


@pytest.mark.data
def test_real_campaign_dates_match_the_published_ones(real_snapshot):
    import json

    published = json.loads((ROOT / "prototype" / "placebo_results.json").read_text())["primary"]["campaigns"]
    descriptions = real_snapshot.tables["descriptions"].set_index("campaign_id")
    for item in published:
        assert pd.Timestamp(item["start"]) == descriptions.loc[int(item["campaign"]), "start_date"]
