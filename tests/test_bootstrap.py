"""The bootstrap is keyed on households, so analyses made at different times line up."""

from __future__ import annotations

import numpy as np
import pytest

from readout.bootstrap import HouseholdBootstrap, interval
from readout.estimators import ESTIMATORS, EstimatorError


def test_a_household_is_drawn_the_same_way_in_every_analysis():
    boot = HouseholdBootstrap(200, seed=7)
    first = boot.multiplicities(np.array([3, 10, 42]))
    second = HouseholdBootstrap(200, seed=7).multiplicities(np.array([42, 99, 3, 7]))
    np.testing.assert_array_equal(first[:, 2], second[:, 0])
    np.testing.assert_array_equal(first[:, 0], second[:, 2])


def test_seeds_and_households_give_different_streams():
    a = HouseholdBootstrap(500, seed=1).multiplicities(np.array([1, 2]))
    b = HouseholdBootstrap(500, seed=2).multiplicities(np.array([1, 2]))
    assert not np.array_equal(a, b)
    assert not np.array_equal(a[:, 0], a[:, 1])
    assert abs(a.mean() - 1.0) < 0.1  # Poisson with mean one


def test_draws_equal_the_estimator_on_the_resampled_rows():
    rng = np.random.default_rng(2)
    n = 400
    x = rng.normal(size=(n, 3))
    d = (rng.random(n) < 0.3).astype(int)
    y = x[:, 0] + 2.0 * d + rng.normal(size=n)
    households = np.arange(1000, 1000 + n)
    boot = HouseholdBootstrap(5, seed=9)
    counts = boot.multiplicities(households)
    for estimator in ESTIMATORS.values():
        draws = boot.draws(estimator, y, d, x, households)
        for r in range(5):
            rows = np.repeat(np.arange(n), counts[r])
            assert draws[r] == pytest.approx(estimator(y[rows], d[rows], x[rows]), abs=1e-8)


def test_draws_of_two_campaigns_share_their_households():
    """Estimates on the same households move together across replications."""
    rng = np.random.default_rng(4)
    n = 600
    x = rng.normal(size=(n, 2))
    d = (rng.random(n) < 0.4).astype(int)
    noise = rng.normal(size=n)
    y1, y2 = d + noise, d + noise + 0.1 * rng.normal(size=n)
    households = np.arange(n)
    regression = ESTIMATORS["regression"]
    same = HouseholdBootstrap(300, seed=1)
    a, b = same.draws(regression, y1, d, x, households), same.draws(regression, y2, d, x, households)
    other = HouseholdBootstrap(300, seed=2).draws(regression, y2, d, x, households)
    assert np.corrcoef(a, b)[0, 1] > 0.9
    assert abs(np.corrcoef(a, other)[0, 1]) < 0.3


def test_a_resample_without_treated_households_is_an_error():
    boot = HouseholdBootstrap(200, seed=0)
    y, x = np.arange(6.0), np.arange(6.0)[:, None]
    d = np.array([1, 0, 0, 0, 0, 0])
    with pytest.raises(EstimatorError, match="no treated"):
        boot.draws(ESTIMATORS["regression"], y, d, x, np.arange(6))


def test_interval_is_the_percentile_interval():
    draws = np.arange(1001.0)
    assert interval(draws, 0.95) == pytest.approx((25.0, 975.0))
    assert interval(draws, 0.90) == pytest.approx((50.0, 950.0))
