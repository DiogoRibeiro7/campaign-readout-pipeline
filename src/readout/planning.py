"""How long a record does a method need before its pooled placebo can pass?

The gates ask for evidence that a placebo effect is small, and evidence costs
data. The pooled placebo of K campaigns passes when its whole interval lies
inside the tolerance. Whether it can depends on three things read from the
registry: how noisy one campaign's placebo is, how much the placebos of two
campaigns move together, and K.

The calculation is a normal approximation with no simulation in it. The mean
of K placebo estimates with standard errors s_i and a common correlation r has
standard error sqrt(mean(s_i^2) (1 + (K - 1) r) / K). It passes when its
estimate lies within the tolerance minus z standard errors of zero.

The correlation matters more than its size suggests. Campaigns share their
comparison households, so their estimates are not independent, and a common
component does not average out: with correlation r the standard error of the
mean never falls below s sqrt(r), however many campaigns there are. A
correlation of 0.01 cannot be told from zero with a dozen campaigns, so the
table is given for several values.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

from .contract import Contract, Method
from .pipeline import PLACEBOS
from .registry import Registry


def noise_profile(registry: Registry, contract: Contract, method: Method, placebo: str, shift: int = 0) -> dict:
    """Noise of the method's placebo estimates and how they move together, from the registry.

    The standard error of a campaign is taken from the width of its interval,
    which is what the gates compare with the tolerance. The standard deviation
    of weighting's bootstrap draws has long tails and would overstate it.
    """
    units = registry.valid_units(contract, method, shift)
    if units.empty:
        return {"campaigns": 0, "standard_errors": np.array([]), "mean_correlation": float("nan")}
    level = contract.tolerances.interval_level
    z = stats.norm.ppf(0.5 + level / 2)
    draws = np.column_stack([registry.draws(key)[placebo] for key in units["key"]])
    tail = 100.0 * (1.0 - level) / 2.0
    low, high = np.percentile(draws, [tail, 100.0 - tail], axis=0)
    k = draws.shape[1]
    correlation = np.corrcoef(draws, rowvar=False) if k > 1 else np.ones((1, 1))
    mean_correlation = float((correlation.sum() - k) / (k * (k - 1))) if k > 1 else 0.0
    return {"campaigns": k, "standard_errors": (high - low) / (2 * z), "mean_correlation": mean_correlation}


def pooled_standard_error(standard_error: float, correlation: float, campaigns: int) -> float:
    """Standard error of the mean of ``campaigns`` estimates with a common correlation."""
    return float(standard_error * np.sqrt((1.0 + (campaigns - 1) * correlation) / campaigns))


def pass_probability(standard_error: float, true_mean: float, tolerance: float, level: float) -> float:
    """Chance that an interval around a normal estimate lies wholly within the tolerance."""
    room = tolerance - stats.norm.ppf(0.5 + level / 2) * standard_error
    if room <= 0:
        return 0.0
    return float(
        stats.norm.cdf((room - true_mean) / standard_error) - stats.norm.cdf((-room - true_mean) / standard_error)
    )


def campaigns_needed(
    standard_error: float, correlation: float, tolerance: float, level: float, power: float | None, limit: int = 100_000
) -> int | None:
    """Fewest campaigns at which the pooled placebo of an unbiased method passes with chance ``power``.

    With ``power = None``: fewest campaigns at which the interval is narrow
    enough to fit inside the tolerance at all. None if no number up to
    ``limit`` is enough.
    """

    def enough(k: int) -> bool:
        se = pooled_standard_error(standard_error, correlation, k)
        if power is None:
            return stats.norm.ppf(0.5 + level / 2) * se < tolerance
        return pass_probability(se, 0.0, tolerance, level) >= power

    if not enough(limit):
        return None
    low, high = 1, limit
    while low < high:  # the chance rises with the number of campaigns
        middle = (low + high) // 2
        low, high = (low, middle) if enough(middle) else (middle + 1, high)
    return low


def plan(
    registry: Registry,
    contract: Contract,
    campaigns: tuple[int, ...] = (13, 25, 50, 100, 200, 400),
    correlations: tuple[float, ...] = (0.0, 0.01, 0.03),
) -> pd.DataFrame:
    """Chance that the pooled placebo passes, by method, placebo, correlation, length of record and true mean."""
    tol = contract.tolerances
    rows = []
    for method in contract.methods:
        for placebo in PLACEBOS:
            profile = noise_profile(registry, contract, method, placebo)
            if profile["campaigns"] < 2:
                continue
            rms = float(np.sqrt(np.mean(profile["standard_errors"] ** 2)))
            for correlation in correlations:
                fit = campaigns_needed(rms, correlation, tol.placebo_usd, tol.interval_level, None)
                eighty = campaigns_needed(rms, correlation, tol.placebo_usd, tol.interval_level, 0.8)
                for k in campaigns:
                    se = pooled_standard_error(rms, correlation, k)
                    for true_mean in (0.0, tol.placebo_usd):
                        rows.append(
                            {
                                "method": method.name,
                                "placebo": placebo,
                                "campaigns_in_registry": profile["campaigns"],
                                "standard_error_of_one_campaign": rms,
                                "measured_correlation": profile["mean_correlation"],
                                "assumed_correlation": correlation,
                                "campaigns": k,
                                "true_mean_placebo": true_mean,
                                "pooled_standard_error": se,
                                "passes": pass_probability(se, true_mean, tol.placebo_usd, tol.interval_level),
                                "campaigns_for_interval_to_fit": fit,
                                "campaigns_for_80_percent": eighty,
                            }
                        )
    table = pd.DataFrame(rows)
    for column in ("campaigns_for_interval_to_fit", "campaigns_for_80_percent"):
        if column in table:
            table[column] = table[column].astype("Int64")
    return table
