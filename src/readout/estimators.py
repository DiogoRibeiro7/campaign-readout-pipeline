"""The estimators of the prototype, unchanged in what they compute.

Regression adjustment and normalised propensity weighting for the effect on
the treated, with the diagnostics the gates read. Matching is left out: the
prototype could not attach a valid bootstrap interval to it, and a readout
without an interval is not publishable.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np


class EstimatorError(RuntimeError):
    """An estimator could not produce a number it can stand behind."""


def _standardise(x: np.ndarray, w: np.ndarray | None = None) -> np.ndarray:
    """Columns centred and scaled to unit standard deviation, constant columns left at zero."""
    if w is None:
        mean, scale = x.mean(axis=0), x.std(axis=0)
    else:
        total = w.sum()
        mean = (w @ x) / total
        scale = np.sqrt((w @ (x - mean) ** 2) / total)
    constant = scale <= 1e-12 * np.maximum(1.0, np.abs(mean))  # a constant column can have a rounding-size spread
    centred = np.where(constant, 0.0, x - mean)
    return centred / np.where(constant, 1.0, scale)


def fit_logit(
    x: np.ndarray, d: np.ndarray, ridge: float = 1e-3, w: np.ndarray | None = None, start: np.ndarray | None = None
) -> np.ndarray:
    """Fitted probabilities from a logistic regression on standardised columns.

    A small ridge penalty on the slopes keeps the fit finite when a bootstrap
    sample is separable. ``w`` holds how often each row counts; the fit is the
    one that repeating the rows would give. ``start`` is a first guess for the
    coefficients and does not change the result.
    """
    return _logit(x, d, ridge, w, start)[0]


def _logit(x, d, ridge, w, start) -> tuple[np.ndarray, np.ndarray]:
    """Newton's method with step halving on the penalised log-likelihood."""
    z = np.column_stack([np.ones(len(x)), _standardise(x, w)])
    weight = np.ones(len(x)) if w is None else w
    penalty = ridge * np.eye(z.shape[1])
    penalty[0, 0] = 0.0

    def objective(beta: np.ndarray) -> float:
        eta = z @ beta
        return float(weight @ (d * eta - np.logaddexp(0.0, eta)) - 0.5 * beta @ penalty @ beta)

    beta = np.zeros(z.shape[1]) if start is None else np.array(start, dtype=float)
    value = objective(beta)
    for _ in range(200):
        p = 1.0 / (1.0 + np.exp(-np.clip(z @ beta, -35, 35)))
        hessian = z.T @ (z * (weight * p * (1 - p))[:, None]) + penalty + 1e-10 * np.eye(z.shape[1])
        step = np.linalg.solve(hessian, z.T @ (weight * (d - p)) - penalty @ beta)
        for _ in range(40):  # a full Newton step can overshoot; shorten it until the fit improves
            candidate = objective(beta + step)
            if candidate >= value - 1e-12 * abs(value):
                break
            step = step / 2.0
        else:
            raise EstimatorError("logistic regression could not improve its fit")
        beta, value = beta + step, candidate
        if np.max(np.abs(step)) < 1e-8:
            break
    else:
        raise EstimatorError("logistic regression did not converge")
    p = 1.0 / (1.0 + np.exp(-np.clip(z @ beta, -35, 35)))
    return np.clip(p, 1e-9, 1 - 1e-9), beta


def auc(score: np.ndarray, d: np.ndarray) -> float:
    """Area under the ROC curve from average ranks (ties handled)."""
    _, inverse, counts = np.unique(score, return_inverse=True, return_counts=True)
    upper = np.cumsum(counts)
    rank = (upper - (counts - 1) / 2.0)[inverse]
    n1 = d.sum()
    n0 = len(d) - n1
    return float((rank[d == 1].sum() - n1 * (n1 + 1) / 2.0) / (n1 * n0))


def ols_coefficient(y: np.ndarray, d: np.ndarray, x: np.ndarray, w: np.ndarray | None = None) -> float:
    """Coefficient on d in a least-squares regression of y on (1, d, x)."""
    z = np.column_stack([np.ones(len(y)), d, _standardise(x, w)])
    zw = z if w is None else z * w[:, None]
    beta, *_ = np.linalg.lstsq(zw.T @ z, zw.T @ y, rcond=None)  # normal equations on standardised columns
    return float(beta[1])


def effective_size(w: np.ndarray) -> float:
    """Kish effective sample size of a set of weights."""
    return float(w.sum() ** 2 / (w**2).sum())


def weighting_att(y: np.ndarray, d: np.ndarray, p: np.ndarray, w: np.ndarray | None = None) -> float:
    """Normalised inverse-probability weighting for the effect on the treated."""
    odds = p[d == 0] / (1 - p[d == 0])
    if w is None:
        return float(y[d == 1].mean() - (odds * y[d == 0]).sum() / odds.sum())
    odds = odds * w[d == 0]
    return float((w[d == 1] * y[d == 1]).sum() / w[d == 1].sum() - (odds * y[d == 0]).sum() / odds.sum())


Resampler = Callable[[np.ndarray], float]


class Regression:
    """Regression adjustment: the coefficient on the treatment."""

    name = "regression"

    def __call__(self, y: np.ndarray, d: np.ndarray, x: np.ndarray) -> float:
        return ols_coefficient(y, d, x)

    def resampler(self, y: np.ndarray, d: np.ndarray, x: np.ndarray) -> Resampler:
        """The estimate as a function of how often each row is drawn."""

        def estimate(counts: np.ndarray) -> float:
            keep = counts > 0
            return ols_coefficient(y[keep], d[keep], x[keep], counts[keep].astype(float))

        return estimate

    def largest_shift(self, y: np.ndarray, d: np.ndarray, x: np.ndarray) -> float:
        """The largest change in the estimate from leaving one household out."""
        z = np.column_stack([np.ones(len(y)), d, _standardise(x)])
        inverse = np.linalg.pinv(z.T @ z)
        residual = y - z @ (inverse @ (z.T @ y))
        leverage = np.einsum("ij,jk,ik->i", z, inverse, z)
        shift = -(z @ inverse[:, 1]) * residual / np.clip(1.0 - leverage, 1e-12, None)
        return float(np.abs(shift).max())


class Weighting:
    """Normalised propensity weighting for the effect on the treated."""

    name = "weighting"

    def __call__(self, y: np.ndarray, d: np.ndarray, x: np.ndarray) -> float:
        return weighting_att(y, d, fit_logit(x, d))

    def resampler(self, y: np.ndarray, d: np.ndarray, x: np.ndarray) -> Resampler:
        """The estimate as a function of how often each row is drawn.

        Each refit starts from the coefficients of the full sample, which
        saves iterations and leaves the answer where it is.
        """
        _, start = _logit(x, d, 1e-3, None, None)

        def estimate(counts: np.ndarray) -> float:
            keep = counts > 0
            w = counts[keep].astype(float)
            p, _ = _logit(x[keep], d[keep], 1e-3, w, start)
            return weighting_att(y[keep], d[keep], p, w)

        return estimate

    def largest_shift(self, y: np.ndarray, d: np.ndarray, x: np.ndarray) -> float:
        """The largest change in the estimate from leaving one household out, the scores held as fitted."""
        p = fit_logit(x, d)
        targeted, others = y[d == 1], y[d == 0]
        share = p[d == 0] / (1 - p[d == 0])
        share = share / share.sum()
        from_targeted = (targeted - targeted.mean()) / max(len(targeted) - 1, 1)
        from_others = share * (others - share @ others) / np.clip(1.0 - share, 1e-12, None)
        return float(max(np.abs(from_targeted).max(), np.abs(from_others).max()))


ESTIMATORS: dict[str, Regression | Weighting] = {"regression": Regression(), "weighting": Weighting()}


@dataclass(frozen=True)
class Overlap:
    """How far the targeted households are from the households they are compared with."""

    auc: float
    effective_controls: float  # Kish size of the weighted comparison group
    largest_weight_share: float  # share of the weight carried by one comparison household
    treated_extreme_share: float  # share of targeted households with a score above the threshold


def overlap(d: np.ndarray, x: np.ndarray, extreme_score: float) -> Overlap:
    p = fit_logit(x, d)
    w = p[d == 0] / (1 - p[d == 0])
    return Overlap(
        auc=auc(p, d),
        effective_controls=effective_size(w),
        largest_weight_share=float(w.max() / w.sum()),
        treated_extreme_share=float((p[d == 1] > extreme_score).mean()),
    )
