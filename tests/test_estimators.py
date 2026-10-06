"""The estimators against independent computations, and resampling by weights against repeated rows."""

from __future__ import annotations

import numpy as np
import pytest

from readout import estimators as est


@pytest.fixture(scope="module")
def sample():
    rng = np.random.default_rng(11)
    n = 1500
    x = rng.normal(size=(n, 5))
    x[:, 4] = np.exp(x[:, 4])
    logit = 0.9 * x[:, 0] - 0.5 * x[:, 1] - 1.0
    d = (rng.random(n) < 1 / (1 + np.exp(-logit))).astype(int)
    y = 50 + 20 * x[:, 0] + 8 * x[:, 1] + 12.0 * d + rng.normal(0, 10, n)
    return y, d, x


def test_regression_is_least_squares(sample):
    y, d, x = sample
    z = np.column_stack([np.ones(len(y)), d, x])
    direct = np.linalg.lstsq(z, y, rcond=None)[0][1]
    assert est.ols_coefficient(y, d, x) == pytest.approx(direct, abs=1e-9)
    assert est.ESTIMATORS["regression"](y, d, x) == pytest.approx(direct, abs=1e-9)


def test_both_estimators_recover_a_known_effect(sample):
    y, d, x = sample
    assert est.ESTIMATORS["regression"](y, d, x) == pytest.approx(12.0, abs=1.5)
    assert est.ESTIMATORS["weighting"](y, d, x) == pytest.approx(12.0, abs=2.5)


def test_logit_solves_its_score_equations(sample):
    _, d, x = sample
    p, beta = est._logit(x, d, 1e-3, None, None)
    z = np.column_stack([np.ones(len(d)), est._standardise(x)])
    penalty = 1e-3 * np.eye(z.shape[1])
    penalty[0, 0] = 0.0
    np.testing.assert_allclose(z.T @ (d - p) - penalty @ beta, 0.0, atol=1e-6)


def test_a_warm_start_does_not_move_the_fit(sample):
    _, d, x = sample
    cold, beta = est._logit(x, d, 1e-3, None, None)
    for start in (beta, beta + 3.0, -5.0 * beta):
        warm, _ = est._logit(x, d, 1e-3, None, start)
        np.testing.assert_allclose(warm, cold, atol=1e-9)


def test_logit_survives_a_separable_sample():
    x = np.linspace(-1, 1, 40)[:, None]
    d = (x[:, 0] > 0).astype(int)
    p = est.fit_logit(x, d)
    assert np.isfinite(p).all() and p[d == 1].min() > p[d == 0].max()


def test_weights_are_repeated_rows(sample):
    y, d, x = sample
    rng = np.random.default_rng(3)
    counts = rng.poisson(1.0, len(y))
    rows = np.repeat(np.arange(len(y)), counts)
    for name, estimator in est.ESTIMATORS.items():
        by_weights = estimator.resampler(y, d, x)(counts)
        by_rows = estimator(y[rows], d[rows], x[rows])
        assert by_weights == pytest.approx(by_rows, abs=1e-8), name


def test_weighting_att_by_hand():
    y = np.array([10.0, 20.0, 1.0, 2.0, 3.0])
    d = np.array([1, 1, 0, 0, 0])
    p = np.array([0.5, 0.5, 0.5, 0.2, 0.2])
    odds = np.array([1.0, 0.25, 0.25])
    expected = 15.0 - (odds * np.array([1.0, 2.0, 3.0])).sum() / odds.sum()
    assert est.weighting_att(y, d, p) == pytest.approx(expected)


def test_auc_against_all_pairs():
    rng = np.random.default_rng(0)
    score = np.round(rng.random(60), 1)  # ties on purpose
    d = (rng.random(60) < 0.4).astype(int)
    pairs = [(a > b) + 0.5 * (a == b) for a in score[d == 1] for b in score[d == 0]]
    assert est.auc(score, d) == pytest.approx(np.mean(pairs))


def test_effective_size():
    assert est.effective_size(np.ones(10)) == pytest.approx(10.0)
    assert est.effective_size(np.array([1.0, 0.0, 0.0])) == pytest.approx(1.0)


def test_overlap_flags_extreme_scores_and_concentrated_weight():
    rng = np.random.default_rng(5)
    n = 2000
    x = rng.normal(size=(n, 1))
    d = (rng.random(n) < 1 / (1 + np.exp(-6 * x[:, 0]))).astype(int)  # treatment almost determined by x
    hard = est.overlap(d, x, 0.9)
    easy = est.overlap((rng.random(n) < 0.3).astype(int), x, 0.9)
    assert hard.treated_extreme_share > 0.5 > easy.treated_extreme_share
    assert hard.effective_controls < easy.effective_controls
    assert hard.largest_weight_share > 10 * easy.largest_weight_share
    assert easy.largest_weight_share < 2.0 / (n * 0.7)  # nearly equal weights
    assert hard.auc > 0.9 and abs(easy.auc - 0.5) < 0.05


def test_a_constant_column_is_left_out_whatever_its_rounding():
    x = np.column_stack([np.full(50, 0.1), np.arange(50.0)])
    z = est._standardise(x)
    np.testing.assert_array_equal(z[:, 0], 0.0)
    assert z[:, 1].std() == pytest.approx(1.0)
    weighted = est._standardise(x, np.linspace(1.0, 3.0, 50))
    np.testing.assert_array_equal(weighted[:, 0], 0.0)


def test_largest_shift_is_the_largest_leave_one_out_change(sample):
    y, d, x = sample
    y, d, x = y[:250].copy(), d[:250], x[:250]
    y[7] += 400.0  # one household with an unusual month
    rows = np.arange(len(y))
    regression, weighting = est.ESTIMATORS["regression"], est.ESTIMATORS["weighting"]
    full = regression(y, d, x)
    brute = max(abs(regression(y[rows != i], d[rows != i], x[rows != i]) - full) for i in rows)
    assert regression.largest_shift(y, d, x) == pytest.approx(brute, rel=1e-8)
    # For weighting the scores are held as fitted, so the formula is exact for that and close to a refit.
    p = est.fit_logit(x, d)
    full = est.weighting_att(y, d, p)
    held = max(abs(est.weighting_att(y[rows != i], d[rows != i], p[rows != i]) - full) for i in rows)
    assert weighting.largest_shift(y, d, x) == pytest.approx(held, rel=1e-8)
    refit = max(abs(weighting(y[rows != i], d[rows != i], x[rows != i]) - weighting(y, d, x)) for i in rows)
    assert weighting.largest_shift(y, d, x) == pytest.approx(refit, rel=0.25)
