"""Outcome, treatment and covariates for one campaign, from a view.

The definitions are those of the prototype. What is added is bookkeeping about
time: who is in the population on the day the covariates are dated, and which
day each column stops reading at, so that a gate can check both.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .contract import GROUPS
from .snapshot import View

RULES = ("through_outcome_window", "at_launch")
LATE_COLUMNS = ("live_large", "live_small")  # read the campaign calendar after the covariate date, if the rule says so


def seen_before(view: View, day: pd.Timestamp) -> np.ndarray:
    """Sorted identifiers of the households with a purchase before ``day``."""
    daily = view.daily
    return np.sort(daily.loc[daily["day"] < day, "household_id"].unique())


def members(view: View, campaign: int, households: np.ndarray, member_ids: np.ndarray | None = None) -> np.ndarray:
    """1 for the households that were sent the campaign, in the order of ``households``.

    ``member_ids`` overrides the membership read from the view. The audits need
    it: they anchor a readout before the campaign was launched, when the view
    does not know yet who will be sent it.
    """
    if member_ids is None:
        member_ids = view.campaigns.loc[view.campaigns["campaign_id"] == campaign, "household_id"].to_numpy()
    return np.isin(households, member_ids).astype(int)


def outcome(view: View, households: np.ndarray, start: pd.Timestamp, window: int) -> np.ndarray:
    """Spending in the ``window`` days from ``start``, zero for households that bought nothing."""
    end = start + pd.Timedelta(days=window)
    daily = view.daily
    spend = daily[(daily["day"] >= start) & (daily["day"] < end)].groupby("household_id")["sales_value"].sum()
    return spend.reindex(households).fillna(0.0).to_numpy(float)


def _others(view: View, campaign: int) -> pd.DataFrame:
    """The other campaigns each household was sent, with their dates and types."""
    return view.campaigns[view.campaigns["campaign_id"] != campaign].merge(
        view.descriptions, left_on="campaign_id", right_index=True
    )


def covariates(
    view: View,
    campaign: int,
    end: pd.Timestamp,
    window: int,
    history: int,
    concurrent: str,
    households: np.ndarray | None = None,
) -> pd.DataFrame:
    """Covariates dated ``end``, one row per household.

    What the household did is measured in the ``history`` days before ``end``;
    spending enters once per block of ``window`` days. ``earlier`` counts the
    other campaigns the household was sent that started before ``end``. The
    two ``live`` columns count the other campaigns it was sent that are live
    during the ``window`` days from ``end``: with ``concurrent =
    "through_outcome_window"`` those that start before the window closes and
    have not ended when it opens, with ``"at_launch"`` only those that had
    already started when it opens.
    """
    if concurrent not in RULES:
        raise ValueError(f"unknown rule for concurrent campaigns: {concurrent}")
    households = view.households if households is None else households
    daily, stores = view.daily, view.stores
    start = end - pd.Timedelta(days=history)
    pre = daily[(daily["day"] >= start) & (daily["day"] < end)]
    out = pd.DataFrame(index=pd.Index(households, name="household_id"))
    for block in range(history // window):
        high = end - pd.Timedelta(days=block * window)
        low = high - pd.Timedelta(days=window)
        part = pre[(pre["day"] >= low) & (pre["day"] < high)]
        out[f"spend_{block + 1}"] = part.groupby("household_id")["sales_value"].sum()
    g = pre.groupby("household_id")
    total = g["sales_value"].sum()
    out["trips"] = g["trips"].sum()
    in_window = stores[(stores["day"] >= start) & (stores["day"] < end)]
    out["stores"] = in_window.groupby("household_id")["store_id"].nunique()
    out["private_share"] = g["private"].sum() / total.where(total > 0)
    out["discount_share"] = g["retail"].sum() / (total + g["retail"].sum()).where(total > 0)
    out["coupon"] = g["coupon"].sum()
    red = view.redemptions
    out["redemptions"] = red[(red["day"] >= start) & (red["day"] < end)].groupby("household_id").size()
    out["recency"] = (end - g["day"].max()).dt.days
    out["recency"] = out["recency"].fillna(history + 1)

    others = _others(view, campaign)
    out["earlier"] = others[others["start_date"] < end].groupby("household_id").size()
    horizon = end if concurrent == "at_launch" else end + pd.Timedelta(days=window)
    live = others[(others["start_date"] < horizon) & (others["end_date"] >= end)]
    out["live_large"] = live[live["campaign_type"] == "Type A"].groupby("household_id").size()
    out["live_small"] = live[live["campaign_type"] != "Type A"].groupby("household_id").size()
    return out.fillna(0.0)


def exposure(view: View, campaign: int, start: pd.Timestamp, window: int, households: np.ndarray) -> pd.DataFrame:
    """Other campaigns the household was sent that were live during the ``window`` days from ``start``."""
    others = _others(view, campaign)
    live = others[(others["start_date"] < start + pd.Timedelta(days=window)) & (others["end_date"] >= start)]
    out = pd.DataFrame(index=pd.Index(households, name="household_id"))
    out["window_large"] = live[live["campaign_type"] == "Type A"].groupby("household_id").size()
    out["window_small"] = live[live["campaign_type"] != "Type A"].groupby("household_id").size()
    return out.fillna(0.0)


def design_columns(f: pd.DataFrame, drop: tuple[str, ...] = ()) -> dict[str, np.ndarray]:
    """The adjustment set, column by column. ``drop`` may contain "history", "spend" and "behaviour"."""
    unknown = set(drop) - set(GROUPS)
    if unknown:
        raise ValueError(f"unknown covariate groups: {sorted(unknown)}")
    spend = [c for c in f.columns if c.startswith("spend_")]
    columns: dict[str, np.ndarray] = {}
    if "spend" not in drop:
        columns |= {f"log_{c}": np.log1p(f[c]) for c in spend} | {c: f[c] for c in spend}
    if "behaviour" not in drop:
        columns |= {
            "log_trips": np.log1p(f["trips"]),
            "stores": f["stores"],
            "private_share": f["private_share"],
            "discount_share": f["discount_share"],
            "log_coupon": np.log1p(f["coupon"]),
            "redemptions": f["redemptions"],
            "recency": f["recency"],
        }
    if "history" not in drop:
        columns |= {c: f[c] for c in ("earlier", "live_large", "live_small", "window_large", "window_small") if c in f}
    return {name: np.asarray(values, dtype=float) for name, values in columns.items()}


def design(f: pd.DataFrame, drop: tuple[str, ...] = ()) -> np.ndarray:
    """The adjustment set as a matrix, in the prototype's column order."""
    return np.column_stack(list(design_columns(f, drop).values()))


ROLES = ("effect", "shifted_placebo", "prehistory_placebo")


@dataclass(frozen=True)
class Problem:
    """One estimation problem: outcome, treatment and adjustment set for the same households.

    Three problems are built for every readout.

    ``effect``              spending in the window from the launch, adjusted for the
                            history before the launch.
    ``shifted_placebo``     the whole analysis moved one window back: spending in the
                            window before the launch, adjusted for the history before
                            that. This is the prototype's placebo.
    ``prehistory_placebo``  spending in the window just before the history begins,
                            adjusted for the covariates of the effect and for the other
                            campaigns that were live in that window.

    The households are those with a purchase before the day the covariates are
    dated. A household first seen later would have no history by construction
    and, in the outcome window, spending by construction.
    """

    role: str
    campaign: int
    anchor: pd.Timestamp  # the launch, or the pseudo-launch of an audit
    outcome_start: pd.Timestamp
    covariates_end: pd.Timestamp  # covariates describe the days before this one
    calendar_until: pd.Timestamp  # the first day that no column reads, the campaign calendar included
    households: np.ndarray
    y: np.ndarray
    d: np.ndarray
    x: np.ndarray
    names: tuple[str, ...]  # one per column of x
    drop: tuple[str, ...] = ()

    @property
    def treated(self) -> int:
        return int(self.d.sum())

    @property
    def controls(self) -> int:
        return int(len(self.d) - self.d.sum())

    @property
    def late(self) -> np.ndarray:
        """True for the columns that read the campaign calendar after the covariate date."""
        after = self.calendar_until > self.covariates_end
        return np.array([after and name in LATE_COLUMNS for name in self.names])


def problem_dates(role: str, anchor: pd.Timestamp, window: int, history: int) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Where a problem's outcome window starts and what day its covariates are dated."""
    if role == "effect":
        return anchor, anchor
    if role == "shifted_placebo":
        earlier = anchor - pd.Timedelta(days=window)
        return earlier, earlier
    if role == "prehistory_placebo":
        return anchor - pd.Timedelta(days=history + window), anchor
    raise ValueError(f"unknown role: {role}")


def build_problem(
    view: View,
    campaign: int,
    anchor: pd.Timestamp,
    role: str,
    window: int,
    history: int,
    concurrent: str,
    member_ids: np.ndarray | None = None,
    drop: tuple[str, ...] = (),
    population: str = "seen_before_covariates",
) -> Problem:
    """Build one of the three problems of a readout anchored at ``anchor``.

    ``population = "whole_view"`` keeps every household of the view, as the
    prototype did; it exists for the comparison with the prototype.
    """
    outcome_start, covariates_end = problem_dates(role, anchor, window, history)
    if population == "seen_before_covariates":
        households = seen_before(view, covariates_end)
    elif population == "whole_view":
        households = view.households
    else:
        raise ValueError(f"unknown population: {population}")
    frame = covariates(view, campaign, covariates_end, window, history, concurrent, households)
    if role == "prehistory_placebo":
        frame = frame.join(exposure(view, campaign, outcome_start, window, households))
    columns = design_columns(frame, drop)
    through = concurrent == "through_outcome_window"
    return Problem(
        role=role,
        campaign=campaign,
        anchor=anchor,
        outcome_start=outcome_start,
        covariates_end=covariates_end,
        calendar_until=covariates_end + pd.Timedelta(days=window) if through else covariates_end,
        households=households,
        y=outcome(view, households, outcome_start, window),
        d=members(view, campaign, households, member_ids),
        x=np.column_stack(list(columns.values())),
        names=tuple(columns),
        drop=tuple(drop),
    )
