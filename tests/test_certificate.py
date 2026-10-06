"""What a record of placebos is allowed to conclude."""

from __future__ import annotations

import numpy as np
import pytest

from readout.certificate import (
    band_state,
    heterogeneity_sd,
    heterogeneity_upper,
    method_record,
    pooled_mean,
    record_state,
)


@pytest.mark.parametrize(
    ("low", "high", "state"),
    [
        (-2, 3, "within"),
        (-5, 5, "within"),
        (6, 9, "outside"),
        (-9, -6, "outside"),
        (-1, 7, "inconclusive"),
        (4, 9, "inconclusive"),
    ],
)
def test_band_state(low, high, state):
    assert band_state(low, high, 5.0) == state


def _record(rng, campaigns, mean, between_sd, se, replications=300, rho=0.0):
    """Placebo estimates of ``campaigns`` campaigns with their aligned bootstrap draws."""
    bias = mean + between_sd * rng.normal(size=campaigns)
    shared = np.sqrt(rho) * rng.normal()
    estimates = bias + se * (shared + np.sqrt(1 - rho) * rng.normal(size=campaigns))
    common = np.sqrt(rho) * rng.normal(size=(replications, 1))
    draws = estimates + se * (common + np.sqrt(1 - rho) * rng.normal(size=(replications, campaigns)))
    return bias, estimates, draws


def _judge(estimates, draws, tolerance=5.0, min_campaigns=5):
    return method_record(list(range(len(estimates))), estimates, draws, tolerance, min_campaigns, 0.95, 0.95)


def test_pooled_mean_uses_the_dependence_between_campaigns():
    rng = np.random.default_rng(0)
    _, estimates, draws = _record(rng, 12, 0.0, 0.0, 4.0, replications=2000, rho=0.6)
    aligned = pooled_mean(draws, estimates, 0.95)
    shuffled = pooled_mean(np.column_stack([rng.permutation(column) for column in draws.T]), estimates, 0.95)
    assert aligned.estimate == pytest.approx(estimates.mean())
    assert aligned.se > 1.5 * shuffled.se  # ignoring the dependence would understate the uncertainty


def test_heterogeneity_is_recovered_and_is_zero_when_there_is_none():
    rng = np.random.default_rng(1)
    with_spread, without = [], []
    for _ in range(200):
        _, estimates, draws = _record(rng, 30, 2.0, 6.0, 3.0)
        with_spread.append(heterogeneity_sd(estimates, draws))
        _, estimates, draws = _record(rng, 30, 2.0, 0.0, 3.0)
        without.append(heterogeneity_sd(estimates, draws))
    assert np.mean(with_spread) == pytest.approx(6.0, abs=0.5)
    assert np.median(without) < 1.5


@pytest.mark.parametrize(("between_sd", "rho"), [(0.0, 0.0), (3.0, 0.0), (6.0, 0.3)])
def test_the_upper_bound_on_heterogeneity_covers_the_truth(between_sd, rho):
    """The bound is at or above the true spread about 95% of the time, whatever the spread."""
    rng = np.random.default_rng(2)
    covered, simulations = 0, 400
    for _ in range(simulations):
        _, estimates, draws = _record(rng, 10, 1.0, between_sd, 3.0, replications=400, rho=rho)
        covered += heterogeneity_upper(estimates, draws, 0.95) >= between_sd
    assert 0.92 <= covered / simulations <= (1.0 if between_sd == 0 else 0.98)


def test_the_upper_bound_is_never_below_the_point_estimate():
    rng = np.random.default_rng(3)
    for _ in range(50):
        _, estimates, draws = _record(rng, 8, 0.0, 4.0, 2.0)
        record = _judge(estimates, draws)
        assert record.heterogeneity_upper >= record.heterogeneity_sd >= 0.0


def test_the_bound_needs_more_replications_than_campaigns():
    rng = np.random.default_rng(4)
    _, estimates, draws = _record(rng, 12, 0.0, 0.0, 1.0, replications=10)
    with pytest.raises(ValueError, match="more bootstrap replications"):
        heterogeneity_upper(estimates, draws, 0.95)


def test_a_short_record_cannot_vouch():
    rng = np.random.default_rng(5)
    _, estimates, draws = _record(rng, 4, 0.0, 0.0, 0.1)
    assert _judge(estimates, draws).state == "too_few"
    two = _judge(estimates[:2], draws[:, :2], min_campaigns=3)
    assert two.state == "too_few" and two.prediction_low is None and two.heterogeneity_upper is None


def test_states_of_a_long_record():
    rng = np.random.default_rng(6)
    _, estimates, draws = _record(rng, 20, 0.0, 0.0, 1.0)
    assert _judge(estimates, draws).state == "certified"
    _, estimates, draws = _record(rng, 20, 15.0, 0.0, 1.0)
    assert _judge(estimates, draws).state == "bias"
    _, estimates, draws = _record(rng, 20, 0.0, 10.0, 1.0)  # no mean bias, but campaigns differ a lot
    assert _judge(estimates, draws).state == "not_certified"


def test_a_larger_tolerance_never_takes_certification_away():
    rng = np.random.default_rng(7)
    _, estimates, draws = _record(rng, 12, 2.0, 2.0, 2.0)
    record = _judge(estimates, draws)
    states = [
        record_state(12, record.mean.low, record.mean.high, record.prediction_low, record.prediction_high, t, 5)
        for t in (1.0, 3.0, 6.0, 10.0, 20.0, 50.0)
    ]
    certified = [state == "certified" for state in states]
    assert certified == sorted(certified) and certified[-1]


def _certified_share(rng, campaigns, mean, between_sd, se, simulations=400):
    hits = 0
    for _ in range(simulations):
        _, estimates, draws = _record(rng, campaigns, mean, between_sd, se, replications=200)
        hits += _judge(estimates, draws).state == "certified"
    return hits / simulations


def test_the_record_does_not_vouch_when_campaigns_differ_too_much():
    """No mean bias, but a third of the campaigns beyond the tolerance: agreement by luck must not certify."""
    rng = np.random.default_rng(8)
    assert _certified_share(rng, 16, 0.0, 5.0, 3.0) <= 0.05
    assert _certified_share(rng, 16, 0.0, 5.0, 12.0) <= 0.05  # nor when the noise hides the spread


def test_the_record_does_not_vouch_for_a_biased_method():
    rng = np.random.default_rng(9)
    assert _certified_share(rng, 16, 5.0, 0.0, 3.0) <= 0.05


def test_the_record_can_vouch_for_an_unbiased_method_once_it_is_long_and_precise():
    rng = np.random.default_rng(10)
    assert _certified_share(rng, 8, 0.0, 0.0, 1.0) < _certified_share(rng, 30, 0.0, 0.0, 1.0)
    assert _certified_share(rng, 30, 0.0, 0.0, 1.0) > 0.9
    assert _certified_share(rng, 30, 0.0, 0.0, 12.0) < 0.02  # hardly ever at the noise of a small panel
