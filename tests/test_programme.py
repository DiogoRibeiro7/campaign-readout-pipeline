"""The programme readout: the campaigns together, under the same two conditions."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from readout.programme import programme_readout
from readout.result import ProgrammePublished, ProgrammeRefused


def _last(registry, method="weighting"):
    rows = registry.programme()
    return rows[rows["method"] == method].sort_values("as_of").iloc[-1]


def test_one_programme_readout_per_readout_day_and_method(replayed, contract):
    rows = replayed.programme()
    assert not rows.duplicated(["method", "as_of"]).any()
    assert set(rows["method"]) == {method.name for method in contract.methods}


def test_too_few_campaigns_is_a_refusal(replayed):
    first = replayed.programme().sort_values("as_of").iloc[0]
    assert first["kind"] == "programme_refused" and "effect" not in first.dropna()
    assert first["reasons"][0]["code"] == "PROGRAMME_TOO_FEW"


def test_the_pooled_shifted_placebo_refuses_when_the_rule_is_unknown(replayed):
    last = _last(replayed, "regression")
    assert last["kind"] == "programme_refused"
    assert "ASSIGNMENT_UNDOCUMENTED_POOLED_OUTSIDE" in [reason["code"] for reason in last["reasons"]]


def test_published_programme_is_the_mean_of_its_campaigns(replayed_lenient, lenient):
    last = _last(replayed_lenient)
    assert last["kind"] == "programme_published" and last["assignment_evidence"] == "pooled_placebo"
    units = replayed_lenient.valid_units(lenient, lenient.method, 0)
    assert list(last["campaigns"]) == list(units["campaign"])
    assert last["effect"]["estimate"] == pytest.approx(np.mean([row["estimate"] for row in units["effect"]]))
    draws = np.column_stack([replayed_lenient.draws(key)["effect"] for key in units["key"]]).mean(axis=1)
    assert last["effect"]["low"] == pytest.approx(np.percentile(draws, 2.5))


def test_programme_readout_looks_no_further_than_its_date(replayed_lenient, plain_snapshot, lenient):
    rows = replayed_lenient.programme().query("method == 'weighting'").sort_values("as_of")
    middle = rows.iloc[len(rows) // 2]
    result = programme_readout(
        replayed_lenient, lenient, lenient.method, pd.Timestamp(middle["as_of"]), plain_snapshot.snapshot_id
    )
    assert isinstance(result, ProgrammePublished | ProgrammeRefused)
    assert list(result.campaigns) == list(middle["campaigns"])
    assert len(result.campaigns) < len(rows.iloc[-1]["campaigns"])
