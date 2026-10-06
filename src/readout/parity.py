"""Does the pipeline compute what the prototype computed?

The first test of a pipeline that replaces a script is that, given the script's
inputs and the script's choices, it returns the script's numbers. Only then is
a different number evidence of a deliberate change and not of a porting error.

The prototype read the whole year at once and compared the targeted households
with every other household of the year. The pipeline reads the data as of the
readout day and compares them with the households that had already shopped
when the campaign was launched. This module runs the pipeline's code three
ways, so that the two changes can be seen separately:

``prototype``   whole-year data, every household of the year;
``as_of``       data as of the readout day, every household seen by then;
``production``  data as of the readout day, the households seen before the
                day the covariates are dated, the contract's covariate rule.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .contract import Contract
from .estimators import ESTIMATORS, overlap
from .features import build_problem
from .snapshot import Snapshot

PROTOTYPE_NAMES = {"regression": "Regression", "weighting": "Weighting"}


def compare(snapshot: Snapshot, contract: Contract, prototype_results: str | Path) -> pd.DataFrame:
    """One row per campaign of the prototype, analysis window and estimator."""
    published = json.loads(Path(prototype_results).read_text(encoding="utf-8"))["primary"]
    w = contract.windows
    if (published["window_days"], published["history_days"]) != (w.outcome_days, w.history_days):
        raise ValueError("the contract's windows are not the prototype's")
    full = snapshot.full()
    rows = []
    for item in published["campaigns"]:
        campaign = int(item["campaign"])
        launch = full.descriptions.loc[campaign, "start_date"]
        as_of = snapshot.as_of(launch + pd.Timedelta(days=w.outcome_days + w.readout_latency_days))
        rule = contract.covariates.concurrent_campaigns
        modes = {
            "prototype": (full, "through_outcome_window", "whole_view"),
            "as_of": (as_of, "through_outcome_window", "whole_view"),
            "production": (as_of, rule, "seen_before_covariates"),
        }
        for role, window in (("effect", "main"), ("shifted_placebo", "placebo")):
            problems = {
                mode: build_problem(
                    view, campaign, launch, role, w.outcome_days, w.history_days, concurrent, population=population
                )
                for mode, (view, concurrent, population) in modes.items()
            }
            diagnostics = overlap(problems["prototype"].d, problems["prototype"].x, 0.9)
            for estimator, function in ESTIMATORS.items():
                values = {mode: function(p.y, p.d, p.x) for mode, p in problems.items()}
                rows.append(
                    {
                        "campaign": campaign,
                        "window": window,
                        "estimator": estimator,
                        "published": item[window]["estimates"][PROTOTYPE_NAMES[estimator]],
                        **values,
                        "households_prototype": len(problems["prototype"].d),
                        "households_as_of": len(problems["as_of"].d),
                        "households_production": len(problems["production"].d),
                        "published_effective_controls": item[window]["weighting_effective_controls"],
                        "effective_controls": diagnostics.effective_controls,
                        "published_auc": item[window]["auc"],
                        "auc": diagnostics.auc,
                    }
                )
    return pd.DataFrame(rows)


def largest_difference(table: pd.DataFrame) -> float:
    """Largest gap between the published numbers and the pipeline run the prototype's way."""
    gaps = [
        np.abs(table["prototype"] - table["published"]).max(),
        np.abs(table["effective_controls"] - table["published_effective_controls"]).max(),
        np.abs(table["auc"] - table["published_auc"]).max(),
    ]
    return float(max(gaps))
