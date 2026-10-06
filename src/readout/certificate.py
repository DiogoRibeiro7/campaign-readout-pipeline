"""What a method's record of placebos is allowed to conclude.

A placebo estimates an effect that is known to be zero, so what it estimates
is the method's error on that problem. One campaign's placebo is usually too
noisy to show that this error is small. Many campaigns' placebos, combined,
can be. Two questions are asked of them.

For the programme as a whole: what is the mean placebo effect? This is a
confidence interval for the mean.

For a single readout: in what range is the placebo effect of a campaign of
this programme expected to fall? That range widens with the uncertainty of the
mean and with how much the campaigns differ from each other. How much they
differ is itself poorly known from a few campaigns, so the range is built on
an upper confidence bound for it, not on its point estimate: a record in which
the campaigns happen to agree must not be read as proof that they always will.

The placebo estimates of different campaigns are computed on overlapping
households, so they are correlated. The bootstrap draws are aligned by
replication, so the covariance between campaigns is estimated from them and
used throughout.
"""

from __future__ import annotations

import numpy as np
from scipy import optimize, stats

from .bootstrap import interval
from .result import Interval, Record


def band_state(low: float, high: float, tolerance: float) -> str:
    """Where an interval lies relative to the band of placebo effects treated as none.

    ``within``: the whole interval is inside the band, so the effect is shown
    to be negligible. ``outside``: the whole interval is beyond it, so the
    effect is shown not to be. ``inconclusive``: neither.
    """
    if -tolerance <= low and high <= tolerance:
        return "within"
    if low > tolerance or high < -tolerance:
        return "outside"
    return "inconclusive"


def pooled_mean(draws: np.ndarray, estimates: np.ndarray, level: float) -> Interval:
    """Mean across campaigns, with its interval from the aligned draws."""
    means = draws.mean(axis=1)
    low, high = interval(means, level)
    return Interval(estimate=float(estimates.mean()), low=low, high=high, se=float(means.std(ddof=1)))


def heterogeneity_sd(estimates: np.ndarray, draws: np.ndarray) -> float:
    """Standard deviation of the true values between campaigns, by the method of moments.

    The spread of the estimates is the spread of the true values plus sampling
    noise. With sampling covariance S between the k estimates, noise alone
    gives an expected sample variance of (trace(S) - sum(S) / k) / (k - 1).
    The trace is the sum of the variances of the draws, and the sum of S is
    the variance of their row totals, so S itself is never formed.
    """
    k = estimates.size
    trace = float(draws.var(axis=0, ddof=1).sum())
    total = float(draws.sum(axis=1).var(ddof=1))
    noise = (trace - total / k) / (k - 1)
    return float(np.sqrt(max(0.0, estimates.var(ddof=1) - noise)))


def heterogeneity_upper(estimates: np.ndarray, draws: np.ndarray, level: float) -> float:
    """Upper confidence bound for the standard deviation of the true values between campaigns.

    If the true values have mean m and variance t2, the estimates are
    distributed around m with covariance S + t2 I. The generalised least
    squares statistic Q(t2) = (y - m)' (S + t2 I)^-1 (y - m), with m estimated,
    then follows a chi-square distribution with k - 1 degrees of freedom. Q
    falls as t2 rises, and the bound is the t2 at which it reaches the lower
    tail of that distribution: any larger spread would make estimates this
    close together improbable. This is the Q-profile method, with the
    covariance between campaigns taken from the bootstrap.
    """
    k = estimates.size
    if draws.shape[0] <= k:
        raise ValueError("more bootstrap replications than campaigns are needed to estimate their covariance")
    values, vectors = np.linalg.eigh(np.atleast_2d(np.cov(draws, rowvar=False)))
    values = np.clip(values, 1e-10 * values.max(), None)
    y, one = vectors.T @ estimates, vectors.T @ np.ones(k)

    def q(t2: float) -> float:
        w = 1.0 / (values + t2)
        centre = (one * w) @ y / ((one * w) @ one)
        return float(w @ (y - centre * one) ** 2)

    target = float(stats.chi2.ppf(1.0 - level, k - 1))
    if q(0.0) <= target:
        return 0.0
    high = max(float(estimates.var(ddof=1)), float(values.max()))
    while q(high) > target:
        high *= 4.0
    return float(np.sqrt(optimize.brentq(lambda t2: q(t2) - target, 0.0, high)))


def record_state(
    campaigns: int,
    mean_low: float | None,
    mean_high: float | None,
    prediction_low: float | None,
    prediction_high: float | None,
    tolerance: float,
    min_campaigns: int,
) -> str:
    """The verdict on a method's record at a given tolerance.

    ``certified``: the range expected to hold the placebo effect of a campaign
    of this programme is inside the band. ``bias``: the mean placebo effect is
    shown to be beyond it. ``too_few``: the record is too short to say.
    ``not_certified``: none of these.
    """
    if campaigns < max(min_campaigns, 3) or prediction_low is None or prediction_high is None:
        return "too_few"
    if band_state(prediction_low, prediction_high, tolerance) == "within":
        return "certified"
    if band_state(mean_low, mean_high, tolerance) == "outside":
        return "bias"
    return "not_certified"


def method_record(
    campaigns: list[int],
    estimates: np.ndarray,
    draws: np.ndarray,
    tolerance: float,
    min_campaigns: int,
    level: float,
    heterogeneity_level: float,
) -> Record:
    """Judge a method by its placebo estimates on ``campaigns``.

    ``draws`` has one row per bootstrap replication and one column per campaign.
    The range for a campaign is the mean plus or minus a Student-t quantile
    with k - 2 degrees of freedom times the square root of the upper bound for
    the between-campaign variance plus the squared standard error of the mean.
    It has the form of the prediction interval of a random-effects
    meta-analysis, with the bound in place of the point estimate.
    """
    k = len(campaigns)
    mean = pooled_mean(draws, estimates, level)
    between = upper = low = high = None
    if k >= 3:
        between = heterogeneity_sd(estimates, draws)
        upper = max(between, heterogeneity_upper(estimates, draws, heterogeneity_level))
        half = stats.t.ppf(0.5 + level / 2, k - 2) * np.sqrt(upper**2 + mean.se**2)
        low, high = float(mean.estimate - half), float(mean.estimate + half)
    return Record(
        state=record_state(k, mean.low, mean.high, low, high, tolerance, min_campaigns),
        campaigns=tuple(campaigns),
        mean=mean,
        heterogeneity_sd=between,
        heterogeneity_upper=upper,
        prediction_low=low,
        prediction_high=high,
    )
