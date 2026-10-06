"""A bootstrap keyed on households, so that readouts made on different days agree.

Each household gets its own stream of Poisson(1) multiplicities, derived from
the contract's seed and the household's identifier. Replication r therefore
resamples a household the same number of times in every analysis it appears
in, whichever campaign is being read out, on whatever day, and whoever else is
in the panel by then. Three properties follow that a multinomial resample of
row positions does not have:

* analyses of different campaigns can be combined replication by replication,
  which gives the pooled intervals their correct dependence;
* a readout computed in April does not have to be recomputed in October for
  its draws to line up with October's;
* adding households to the panel leaves the draws of the others unchanged.
"""

from __future__ import annotations

import numpy as np

from .estimators import EstimatorError, Regression, Weighting


class HouseholdBootstrap:
    def __init__(self, replications: int, seed: int) -> None:
        self.replications = replications
        self.seed = seed
        self._streams: dict[int, np.ndarray] = {}

    def multiplicities(self, households: np.ndarray) -> np.ndarray:
        """Array of shape (replications, households): how often each household is drawn."""
        out = np.empty((self.replications, len(households)), dtype=np.int16)
        for j, household in enumerate(households.tolist()):
            stream = self._streams.get(household)
            if stream is None:
                rng = np.random.default_rng([self.seed, int(household)])
                stream = rng.poisson(1.0, self.replications).astype(np.int16)
                self._streams[household] = stream
            out[:, j] = stream
        return out

    def draws(
        self, estimator: Regression | Weighting, y: np.ndarray, d: np.ndarray, x: np.ndarray, households: np.ndarray
    ) -> np.ndarray:
        """The estimator on each resample of the households."""
        counts = self.multiplicities(households)
        resample = estimator.resampler(y, d, x)
        out = np.empty(self.replications)
        for r in range(self.replications):
            treated = int(counts[r] @ d)
            if treated == 0 or treated == int(counts[r].sum()):
                raise EstimatorError("a bootstrap resample has no treated or no untreated households")
            out[r] = resample(counts[r])
        return out


def interval(draws: np.ndarray, level: float = 0.95) -> tuple[float, float]:
    """Percentile interval."""
    tail = 100.0 * (1.0 - level) / 2.0
    return float(np.percentile(draws, tail)), float(np.percentile(draws, 100.0 - tail))
