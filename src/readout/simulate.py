"""A synthetic retailer whose campaigns have a known effect.

The real data cannot show that the pipeline publishes when it should, or what
it lets through: no one knows what the campaigns did. This module builds a
feed in the same five tables as the real one, in which every campaign adds a
known number of dollars to the spending of the households it is sent to, and
in which the way the retailer chooses those households is set by the caller.

Every household has a typical level of spending and an appetite that moves
around it from one 28-day block to the next, partly carried over from the
block before. The retailer scores households and sends the campaign to those
with high scores. Three things can enter the score:

``observed``   what the household spent in the two blocks before the launch.
               The adjustment set holds it.
``long_run``   the household's typical level of spending, which the retailer
               knows from years of records. The adjustment set sees it only
               through eight weeks of spending, so part of it is hidden. It
               was there before the history and is there after the launch.
``foresight``  the change in appetite that arrives with the launch block: the
               retailer knows something about the weeks ahead. No table holds
               it and it has left no trace in anything recorded before the
               launch.

With all three at zero the campaign goes to households drawn at random.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd
from scipy.optimize import brentq

from .snapshot import Snapshot

BLOCK = 28
SLOPE = 1.2  # how sharply the chance of being targeted rises with the score


@dataclass(frozen=True)
class World:
    name: str = "observed"
    households: int = 4000
    campaigns: int = 12
    first_launch_block: int = 3  # blocks of 28 days before the first launch
    treated_share: float = 0.25
    effect: float = 10.0  # dollars added to a targeted household's spending in the 28 days from launch
    observed: float = 0.0
    long_run: float = 0.0
    foresight: float = 0.0
    persistence: float = 0.7  # of the appetite from one block to the next
    start: str = "2021-01-04"
    seed: int = 0

    @property
    def blocks(self) -> int:
        """Blocks of 28 days in the feed: one campaign a block, and the outcome window of the last."""
        return self.first_launch_block + self.campaigns


# The weights were set by hand, large enough for each mechanism to be visible.
WORLDS = {
    "random": World(name="random"),
    "observed": World(name="observed", observed=1.0),
    "long_run": World(name="long_run", long_run=1.0),
    "foresight": World(name="foresight", foresight=0.4),
}


def _standardise(values: np.ndarray) -> np.ndarray:
    return (values - values.mean()) / values.std()


def _targeted(score: np.ndarray, share: float, rng: np.random.Generator) -> np.ndarray:
    """Send the campaign with a chance that rises with the score and averages ``share``."""

    def excess(intercept: float) -> float:
        return float((1.0 / (1.0 + np.exp(-(SLOPE * score + intercept)))).mean() - share)

    intercept = brentq(excess, -50.0, 50.0)
    return rng.random(len(score)) < 1.0 / (1.0 + np.exp(-(SLOPE * score + intercept)))


def synthetic_snapshot(world: World) -> Snapshot:
    rng = np.random.default_rng([world.seed, 77])
    n, days = world.households, world.blocks * BLOCK
    if world.campaigns < 1:
        raise ValueError("a world needs at least one campaign")
    if world.first_launch_block < 2:
        raise ValueError("the retailer needs two blocks of spending before the first launch")

    level = np.exp(rng.normal(np.log(120.0), 0.7, n))  # typical spending per block
    appetite_sd = 0.35
    change_sd = appetite_sd * np.sqrt(1 - world.persistence**2)
    change = rng.normal(0.0, change_sd, (n, world.blocks))
    appetite = np.empty((n, world.blocks))
    appetite[:, 0] = rng.normal(0.0, appetite_sd, n)
    for b in range(1, world.blocks):
        appetite[:, b] = world.persistence * appetite[:, b - 1] + change[:, b]
    block_mean = level[:, None] * np.exp(appetite - appetite_sd**2 / 2)

    visit_rate = 0.08 + 0.4 * rng.beta(2.0, 4.0, n)
    visits = rng.random((n, days)) < visit_rate[:, None]
    basket = np.repeat(block_mean, BLOCK, axis=1) / (BLOCK * visit_rate[:, None])
    spend = np.where(visits, basket * np.exp(rng.normal(-0.18, 0.6, (n, days))), 0.0)

    start = pd.Timestamp(world.start)
    memberships, descriptions = [], []
    for c in range(world.campaigns):
        b = world.first_launch_block + c
        launch = b * BLOCK
        last = np.log1p(spend[:, launch - BLOCK : launch].sum(axis=1))
        before = np.log1p(spend[:, launch - 2 * BLOCK : launch - BLOCK].sum(axis=1))
        score = (
            world.observed * (0.9 * _standardise(last) + 0.5 * _standardise(before))
            + world.long_run * _standardise(np.log(level))
            + world.foresight * change[:, b] / change_sd
        )
        treated = _targeted(score, world.treated_share, rng)
        # The effect: a known number of dollars, on one day of the outcome window.
        day = launch + rng.integers(0, BLOCK, n)
        rows = np.flatnonzero(treated)
        spend[rows, day[rows]] += world.effect
        visits[rows, day[rows]] = True
        memberships.append(pd.DataFrame({"campaign_id": c + 1, "household_id": rows + 1}))
        descriptions.append(
            {
                "campaign_id": c + 1,
                "campaign_type": "Type B",
                "start_date": start + pd.Timedelta(days=launch),
                "end_date": start + pd.Timedelta(days=launch + BLOCK + 6),
            }
        )

    household, day = np.nonzero(visits)
    value = spend[household, day]
    home = rng.integers(1, 6, n)
    elsewhere = rng.random(len(value)) < 0.15
    store = np.where(elsewhere, rng.integers(1, 6, len(value)), home[household])
    private_share = rng.beta(2.0, 6.0, n)[household]
    discount_share = rng.uniform(0.0, 0.2, n)[household]
    calendar = (start + pd.to_timedelta(np.arange(days), unit="D")).to_numpy("datetime64[ns]")
    daily = pd.DataFrame(
        {
            "household_id": household + 1,
            "day": calendar[day],
            "sales_value": value,
            "private": value * private_share,
            "retail": value * discount_share,
            "coupon": np.where(rng.random(len(value)) < 0.05, 1.0, 0.0),
            "trips": 1,
        }
    )
    tables = {
        "daily": daily,
        "stores": pd.DataFrame({"household_id": household + 1, "day": calendar[day], "store_id": store}),
        "campaigns": pd.concat(memberships, ignore_index=True),
        "descriptions": pd.DataFrame(descriptions).astype(
            {"start_date": "datetime64[ns]", "end_date": "datetime64[ns]"}
        ),
        "redemptions": pd.DataFrame(
            {"household_id": pd.Series(dtype="int64"), "day": pd.Series(dtype="datetime64[ns]")}
        ),
    }
    return Snapshot.from_tables(tables, {"synthetic": asdict(world)})
