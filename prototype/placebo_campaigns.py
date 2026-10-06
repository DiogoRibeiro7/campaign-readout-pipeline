"""Reproduction script for "A Placebo Can Pass and Still Be as Large as the Estimate".

Sixteen targeted marketing campaigns of one grocery retailer are analysed the
way an analyst without an experiment would analyse them, and each analysis is
repeated on an outcome the campaign cannot have affected.

Data: the "Complete Journey" files of 84.51 / dunnhumby as distributed with the
R package completejourney (2,469 households, one year of transactions, 27
campaigns). The files are downloaded from the package's repository on first
use, and the job-training data of the comparison from the Mixtape repository.

Requires numpy, pandas, matplotlib and pyreadr. The full run takes about a
quarter of an hour on two cores:

    python placebo_campaigns.py --out output --data data

Protocol fixed before any estimate was looked at
------------------------------------------------
Unit of analysis: the campaign. For a campaign launched on day s,
    treatment  = the household received the campaign,
    outcome    = the household's spending in the 28 days from s,
    covariates = behaviour in the 56 days before s, plus campaign history.
The placebo is the same procedure moved back 28 days: outcome = spending in
the 28 days before s, covariates from the 56 days before that.
Eligible campaigns: at least 50 households, with 84 days of history before s
and 28 days after it inside the data.
A placebo fails if its 95% bootstrap percentile interval excludes zero; the
primary estimator is propensity weighting; "a large share" means more than
half of the campaigns.
For each covariate: partial R2 with treatment given the others, and partial
R2 with the outcome given the others among untreated households. Of the three
strongest treatment predictors, the share whose outcome strength is below the
median covariate is compared with one half.

Everything else in the script (pooled intervals, power, placebos further back,
longer histories) was added after the first results and is exploratory.
"""

from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path
from statistics import NormalDist

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import FuncFormatter

SEED = 20261003
WINDOW = 28
HISTORY = 56
MIN_TREATED = 50
REPS = 2000
PACKAGE_URL = "https://raw.githubusercontent.com/bradleyboehmke/completejourney/master/data/{name}"
PACKAGE_FILES = ("transactions.rds", "campaigns.rda", "campaign_descriptions.rda", "coupon_redemptions.rda", "products.rda")
MIXTAPE_URL = "https://raw.githubusercontent.com/scunning1975/mixtape/master/{name}.dta"

HISTORY_VARIABLES = ("Earlier campaigns", "Concurrent large campaigns", "Concurrent small campaigns")
BEHAVIOUR = (
    "Spend, last 4 weeks",
    "Spend, weeks 5 to 8",
    "Trips",
    "Stores",
    "Private-label share",
    "Discount share",
    "Coupon discount",
    "Coupon redemptions",
    "Days since last trip",
)
CONCEPTS = BEHAVIOUR + HISTORY_VARIABLES
ADJUSTMENT_SETS = {
    "Full set": (),
    "Without campaign history": ("history",),
    "Without past spending": ("spend",),
    "Campaign history only": ("spend", "behaviour"),
}


# --------------------------------------------------------------------------
# Estimators
# --------------------------------------------------------------------------
def fit_logit(x: np.ndarray, d: np.ndarray, ridge: float = 1e-3) -> np.ndarray:
    """Fitted probabilities from a logistic regression on standardised columns.

    A small ridge penalty on the slopes keeps the fit finite when a bootstrap
    sample is separable. On the full samples it leaves the weighting estimates
    essentially unchanged; nearest-neighbour matching is sensitive even to
    this (see matching_sensitivity).
    """
    scale = x.std(axis=0)
    scale[scale == 0] = 1.0
    z = np.column_stack([np.ones(len(x)), (x - x.mean(axis=0)) / scale])
    penalty = ridge * np.eye(z.shape[1])
    penalty[0, 0] = 0.0
    beta = np.zeros(z.shape[1])
    for _ in range(200):
        p = 1.0 / (1.0 + np.exp(-np.clip(z @ beta, -35, 35)))
        hessian = z.T @ (z * (p * (1 - p))[:, None]) + penalty + 1e-10 * np.eye(z.shape[1])
        step = np.linalg.solve(hessian, z.T @ (d - p) - penalty @ beta)
        beta += step
        if np.max(np.abs(step)) < 1e-8:
            break
    else:
        raise RuntimeError("logistic regression did not converge")
    p = 1.0 / (1.0 + np.exp(-np.clip(z @ beta, -35, 35)))
    return np.clip(p, 1e-9, 1 - 1e-9)


def auc(score: np.ndarray, d: np.ndarray) -> float:
    """Area under the ROC curve from average ranks (ties handled)."""
    _, inverse, counts = np.unique(score, return_inverse=True, return_counts=True)
    upper = np.cumsum(counts)
    rank = (upper - (counts - 1) / 2.0)[inverse]
    n1 = d.sum()
    n0 = len(d) - n1
    return float((rank[d == 1].sum() - n1 * (n1 + 1) / 2.0) / (n1 * n0))


def ols_coefficient(y: np.ndarray, d: np.ndarray, x: np.ndarray) -> float:
    """Coefficient on d in a least-squares regression of y on (1, d, x)."""
    scale = x.std(axis=0)
    scale[scale == 0] = 1.0
    z = np.column_stack([np.ones(len(y)), d, (x - x.mean(axis=0)) / scale])
    beta, *_ = np.linalg.lstsq(z.T @ z, z.T @ y, rcond=None)  # normal equations on standardised columns
    return float(beta[1])


def matching_weights(p: np.ndarray, d: np.ndarray) -> np.ndarray:
    """Weights on the controls from nearest-neighbour matching with replacement.

    Every treated unit is matched to the control(s) nearest in the logit of
    the propensity score; a match is shared equally among tied controls, so
    the result does not depend on the order of the rows.
    """
    score = np.log(p / (1 - p))
    treated_scores = score[d == 1]
    values, inverse, counts = np.unique(np.round(score[d == 0], 10), return_inverse=True, return_counts=True)
    pos = np.searchsorted(values, treated_scores)
    left = np.clip(pos - 1, 0, len(values) - 1)
    right = np.clip(pos, 0, len(values) - 1)
    gap_left = np.abs(values[left] - treated_scores)
    gap_right = np.abs(values[right] - treated_scores)
    tie = np.isclose(gap_left, gap_right, rtol=0.0, atol=1e-9) & (left != right)
    to_right = (gap_right < gap_left) & ~tie
    to_left = ~to_right & ~tie
    group = np.zeros(len(values))
    np.add.at(group, left[to_left], 1.0)
    np.add.at(group, right[to_right], 1.0)
    both = counts[left[tie]] + counts[right[tie]]
    np.add.at(group, left[tie], counts[left[tie]] / both)
    np.add.at(group, right[tie], counts[right[tie]] / both)
    return (group / counts)[inverse]


def effective_size(w: np.ndarray) -> float:
    """Kish effective sample size of a set of weights."""
    return float(w.sum() ** 2 / (w**2).sum())


def weighting_att(y: np.ndarray, d: np.ndarray, p: np.ndarray) -> float:
    """Normalised inverse-probability weighting for the effect on the treated."""
    w = p[d == 0] / (1 - p[d == 0])
    return float(y[d == 1].mean() - (w * y[d == 0]).sum() / w.sum())


def three_estimates(y: np.ndarray, d: np.ndarray, x: np.ndarray, ridge: float = 1e-3) -> dict[str, float]:
    """Regression, propensity matching and propensity weighting."""
    p = fit_logit(x, d, ridge)
    m = matching_weights(p, d)
    w = p[d == 0] / (1 - p[d == 0])
    return {
        "Regression": ols_coefficient(y, d, x),
        "Matching": float(y[d == 1].mean() - (m * y[d == 0]).sum() / m.sum()),
        "Weighting": weighting_att(y, d, p),
        "matching_effective_controls": effective_size(m),
        "weighting_effective_controls": effective_size(w),
        "treated_score_above_0.9": float((p[d == 1] > 0.9).mean()),
        "auc": auc(p, d),
    }


def bootstrap(y: np.ndarray, d: np.ndarray, x: np.ndarray, rng: np.random.Generator, reps: int) -> dict:
    """Standard error and 95% percentile interval for regression and weighting.

    Treated and untreated households are resampled separately. Matching is
    left out: the bootstrap is not valid for it (Abadie and Imbens, 2008).
    """
    treated, controls = np.flatnonzero(d == 1), np.flatnonzero(d == 0)
    draws: dict[str, list[float]] = {"Regression": [], "Weighting": []}
    for _ in range(reps):
        idx = np.concatenate([rng.choice(treated, len(treated)), rng.choice(controls, len(controls))])
        yb, db, xb = y[idx], d[idx], x[idx]
        draws["Regression"].append(ols_coefficient(yb, db, xb))
        draws["Weighting"].append(weighting_att(yb, db, fit_logit(xb, db)))
    return {
        name: {
            "se": float(np.std(v, ddof=1)),
            "low": float(np.percentile(v, 2.5)),
            "high": float(np.percentile(v, 97.5)),
        }
        for name, v in draws.items()
    }


# --------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------
def fetch(url: str, path: Path) -> Path:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(url, path)
    return path


def as_int(values: pd.Series) -> np.ndarray:
    """Identifiers are stored as text in the package, a few in scientific notation."""
    return pd.to_numeric(values).round().astype("int64").to_numpy()


def load(cache: Path) -> dict:
    import pyreadr

    frames = {}
    for name in PACKAGE_FILES:
        result = pyreadr.read_r(str(fetch(PACKAGE_URL.format(name=name), cache / name)))
        frames[name.split(".")[0]] = next(iter(result.values()))
    tx = frames["transactions"]
    products = frames["products"]
    private = set(as_int(products.loc[products["brand"].astype(str) == "Private", "product_id"]))
    # The package builds its timestamps in New York time and stores them in UTC.
    local = pd.to_datetime(tx["transaction_timestamp"]).dt.tz_localize("UTC").dt.tz_convert("America/New_York")
    tx = pd.DataFrame(
        {
            "household_id": as_int(tx["household_id"]),
            "basket_id": as_int(tx["basket_id"]),
            "store_id": as_int(tx["store_id"]),
            "day": local.dt.tz_localize(None).dt.normalize().to_numpy(),
            "sales_value": tx["sales_value"].to_numpy(float),
            "retail": tx["retail_disc"].abs().to_numpy(float),
            "coupon": (tx["coupon_disc"].abs() + tx["coupon_match_disc"].abs()).to_numpy(float),
        }
    )
    tx["private"] = np.where(np.isin(as_int(frames["transactions"]["product_id"]), list(private)), tx["sales_value"], 0.0)
    daily = tx.groupby(["household_id", "day"], as_index=False).agg(
        sales_value=("sales_value", "sum"),
        private=("private", "sum"),
        retail=("retail", "sum"),
        coupon=("coupon", "sum"),
        trips=("basket_id", "nunique"),
    )
    stores = tx[["household_id", "day", "store_id"]].drop_duplicates()
    campaigns = pd.DataFrame(
        {"campaign_id": as_int(frames["campaigns"]["campaign_id"]), "household_id": as_int(frames["campaigns"]["household_id"])}
    )
    desc = frames["campaign_descriptions"]
    desc = pd.DataFrame(
        {
            "campaign_type": desc["campaign_type"].astype(str).to_numpy(),
            "start_date": pd.to_datetime(desc["start_date"]).to_numpy(),
            "end_date": pd.to_datetime(desc["end_date"]).to_numpy(),
        },
        index=pd.Index(as_int(desc["campaign_id"]), name="campaign_id"),
    )
    desc["households"] = campaigns.groupby("campaign_id")["household_id"].nunique()
    red = frames["coupon_redemptions"]
    redemptions = pd.DataFrame(
        {"household_id": as_int(red["household_id"]), "day": pd.to_datetime(red["redemption_date"]).to_numpy()}
    )
    return {
        "daily": daily,
        "stores": stores,
        "households": np.sort(tx["household_id"].unique()),
        "campaigns": campaigns,
        "descriptions": desc,
        "redemptions": redemptions,
        "first_day": tx["day"].min(),
        "last_day": tx["day"].max(),
        "transactions": int(len(tx)),
    }


def members(data: dict, campaign: int) -> np.ndarray:
    ids = data["campaigns"].loc[data["campaigns"]["campaign_id"] == campaign, "household_id"]
    return np.isin(data["households"], ids).astype(int)


def outcome(data: dict, start: pd.Timestamp, window: int) -> np.ndarray:
    daily = data["daily"]
    end = start + pd.Timedelta(days=window)
    spend = daily[(daily["day"] >= start) & (daily["day"] < end)].groupby("household_id")["sales_value"].sum()
    return spend.reindex(data["households"]).fillna(0.0).to_numpy(float)


def features(data: dict, campaign: int, end: pd.Timestamp, window: int, history: int, running_only: bool) -> pd.DataFrame:
    """Covariates measured in the `history` days before `end`, one row per household.

    Spending enters once per block of `window` days. "Concurrent" campaigns
    are the other campaigns a household received that are live at some point
    in the outcome window; with `running_only` they must also have started
    before it, so that the count was known on the day the window opens.
    """
    daily, stores = data["daily"], data["stores"]
    start = end - pd.Timedelta(days=history)
    pre = daily[(daily["day"] >= start) & (daily["day"] < end)]
    out = pd.DataFrame(index=pd.Index(data["households"], name="household_id"))
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
    red = data["redemptions"]
    out["redemptions"] = red[(red["day"] >= start) & (red["day"] < end)].groupby("household_id").size()
    out["recency"] = (end - g["day"].max()).dt.days
    out["recency"] = out["recency"].fillna(history + 1)

    others = data["campaigns"][data["campaigns"]["campaign_id"] != campaign].merge(
        data["descriptions"], left_on="campaign_id", right_index=True
    )
    out["earlier"] = others[others["start_date"] < end].groupby("household_id").size()
    horizon = end if running_only else end + pd.Timedelta(days=window)
    live = others[(others["start_date"] < horizon) & (others["end_date"] >= end)]
    out["live_large"] = live[live["campaign_type"] == "Type A"].groupby("household_id").size()
    out["live_small"] = live[live["campaign_type"] != "Type A"].groupby("household_id").size()
    return out.fillna(0.0)


def design(f: pd.DataFrame, drop: tuple[str, ...] = ()) -> np.ndarray:
    """Adjustment set. `drop` may contain "history", "spend" and "behaviour"."""
    spend = [c for c in f.columns if c.startswith("spend_")]
    columns: list[np.ndarray] = []
    if "spend" not in drop:
        columns += [np.log1p(f[c]) for c in spend] + [f[c] for c in spend]
    if "behaviour" not in drop:
        columns += [
            np.log1p(f["trips"]),
            f["stores"],
            f["private_share"],
            f["discount_share"],
            np.log1p(f["coupon"]),
            f["redemptions"],
            f["recency"],
        ]
    if "history" not in drop:
        columns += [f["earlier"], f["live_large"], f["live_small"]]
    return np.column_stack(columns).astype(float)


def concept_matrix(f: pd.DataFrame) -> np.ndarray:
    """One column per covariate, in the order of CONCEPTS (two spending blocks)."""
    return np.column_stack(
        [
            np.log1p(f["spend_1"]),
            np.log1p(f["spend_2"]),
            np.log1p(f["trips"]),
            f["stores"],
            f["private_share"],
            f["discount_share"],
            np.log1p(f["coupon"]),
            f["redemptions"],
            f["recency"],
            f["earlier"],
            f["live_large"],
            f["live_small"],
        ]
    ).astype(float)


def eligible(data: dict, window: int, history: int, lags: int = 1) -> pd.DataFrame:
    """Campaigns with enough households and enough data on both sides of the launch."""
    desc = data["descriptions"]
    ok = (
        (desc["households"] >= MIN_TREATED)
        & (desc["start_date"] - pd.Timedelta(days=history + lags * window) >= data["first_day"])
        & (desc["start_date"] + pd.Timedelta(days=window) <= data["last_day"] + pd.Timedelta(days=1))
    )
    return desc[ok].reset_index().sort_values(["start_date", "campaign_id"]).set_index("campaign_id")


def problem(data: dict, campaign: int, lag: int, window: int, history: int, running_only: bool = False, drop=()):
    """Outcome, treatment and covariates for one campaign, `lag` windows before launch."""
    start = data["descriptions"].loc[campaign, "start_date"] - pd.Timedelta(days=lag * window)
    f = features(data, campaign, start, window, history, running_only)
    return outcome(data, start, window), members(data, campaign), design(f, drop), f


# --------------------------------------------------------------------------
# The fixed protocol
# --------------------------------------------------------------------------
def partial_r2(target: np.ndarray, x: np.ndarray) -> np.ndarray:
    """Partial R2 of each column of x with the target, given the other columns."""
    z = np.column_stack([np.ones(len(target)), x])
    beta, *_ = np.linalg.lstsq(z, target, rcond=None)
    resid = target - z @ beta
    dof = len(target) - np.linalg.matrix_rank(z)
    cov = (resid @ resid / dof) * np.linalg.pinv(z.T @ z)
    with np.errstate(divide="ignore", invalid="ignore"):
        t = beta / np.sqrt(np.diag(cov))
    t = np.nan_to_num(t[1:])
    return t**2 / (t**2 + dof)


def instrument_likeness(d: np.ndarray, y: np.ndarray, x: np.ndarray, names: tuple[str, ...], top: int = 3) -> dict:
    """Treatment strength against outcome strength, covariate by covariate."""
    with_treatment = partial_r2(d.astype(float), x)
    with_outcome = partial_r2(y[d == 0], x[d == 0])
    order = np.argsort(-with_treatment)
    below = with_outcome < np.median(with_outcome)
    rank = lambda v: np.argsort(np.argsort(v)).astype(float)
    return {
        "treatment_partial_r2": dict(zip(names, map(float, with_treatment))),
        "outcome_partial_r2": dict(zip(names, map(float, with_outcome))),
        "top": [names[i] for i in order[:top]],
        "top_share_below_median_outcome": float(below[order[:top]].mean()),
        "strongest_below_median_outcome": bool(below[order[0]]),
        "rank_correlation": float(np.corrcoef(rank(with_treatment), rank(with_outcome))[0, 1]),
    }


def analyse(data: dict, campaign: int, lag: int, window: int, history: int, running_only: bool, reps: int, seed: int) -> dict:
    y, d, x, f = problem(data, campaign, lag, window, history, running_only)
    est = three_estimates(y, d, x)
    out = {
        "treated_mean": float(y[d == 1].mean()),
        "untreated_mean": float(y[d == 0].mean()),
        "raw_difference": float(y[d == 1].mean() - y[d == 0].mean()),
        "untargeted_households": int((d == 0).sum()),
        "estimates": {k: est[k] for k in ("Regression", "Matching", "Weighting")},
        "auc": est["auc"],
        "weighting_effective_controls": est["weighting_effective_controls"],
        "matching_effective_controls": est["matching_effective_controls"],
        "treated_score_above_0.9": est["treated_score_above_0.9"],
        "bootstrap": bootstrap(y, d, x, np.random.default_rng([seed, campaign, lag]), reps),
    }
    if lag == 0 and history == 2 * window:
        out["likeness"] = instrument_likeness(d, y, concept_matrix(f), CONCEPTS)
        with_levels = ("Spend, last 4 weeks", "Spend, weeks 5 to 8", "Spend, last 4 weeks (level)", "Spend, weeks 5 to 8 (level)")
        out["likeness_with_levels"] = instrument_likeness(d, y, x, with_levels + CONCEPTS[2:])
    if lag == 1:
        out["by_adjustment_set"] = {
            name: {
                k: v
                for k, v in three_estimates(*problem(data, campaign, lag, window, history, running_only, drop)[:3]).items()
                if k in ("Regression", "Matching", "Weighting")
            }
            for name, drop in ADJUSTMENT_SETS.items()
        }
    return out


def excludes_zero(interval: dict) -> bool:
    return bool(interval["low"] > 0 or interval["high"] < 0)


def run_protocol(data: dict, window: int, history: int, running_only: bool, reps: int, seed: int) -> dict:
    rows = []
    for campaign, info in eligible(data, window, history).iterrows():
        rows.append(
            {
                "campaign": int(campaign),
                "type": info["campaign_type"],
                "start": str(info["start_date"].date()),
                "households": int(info["households"]),
                "main": analyse(data, campaign, 0, window, history, running_only, reps, seed),
                "placebo": analyse(data, campaign, 1, window, history, running_only, reps, seed),
            }
        )
    return {"window_days": window, "history_days": history, "campaigns": rows, "summary": summarise(rows)}


def summarise(rows: list[dict]) -> dict:
    out: dict = {"campaigns": len(rows)}
    small = [r for r in rows if r["type"] != "Type A"]
    for estimator in ("Weighting", "Regression", "Matching"):
        main = np.array([r["main"]["estimates"][estimator] for r in rows])
        placebo = np.array([r["placebo"]["estimates"][estimator] for r in rows])
        out[estimator] = {
            "placebo_positive": int((placebo > 0).sum()),
            "mean_main": float(main.mean()),
            "mean_placebo": float(placebo.mean()),
            "median_main": float(np.median(main)),
            "median_placebo": float(np.median(placebo)),
            "placebo_at_least_as_large_as_main": int((np.abs(placebo) >= np.abs(main)).sum()),
            "mean_main_small_campaigns": float(np.mean([r["main"]["estimates"][estimator] for r in small])),
            "mean_placebo_small_campaigns": float(np.mean([r["placebo"]["estimates"][estimator] for r in small])),
        }
        if estimator != "Matching":
            se = [r["placebo"]["bootstrap"][estimator]["se"] for r in rows]
            weight = 1.0 / np.square(se)
            centre = float((weight * placebo).sum() / weight.sum())
            out[estimator].update(
                {
                    "placebo_homogeneity_q": float((weight * (placebo - centre) ** 2).sum()),
                    "placebo_homogeneity_df": len(rows) - 1,
                    "placebo_precision_weighted_mean": centre,
                    "narrowest_placebo_interval": float(
                        min(r["placebo"]["bootstrap"][estimator]["high"] - r["placebo"]["bootstrap"][estimator]["low"] for r in rows)
                    ),
                    "placebo_fails": [r["campaign"] for r in rows if excludes_zero(r["placebo"]["bootstrap"][estimator])],
                    "main_excludes_zero": [r["campaign"] for r in rows if excludes_zero(r["main"]["bootstrap"][estimator])],
                    "placebo_se_range": [float(min(se)), float(max(se))],
                }
            )
    out["raw_difference"] = {
        "mean_main": float(np.mean([r["main"]["raw_difference"] for r in rows])),
        "mean_placebo": float(np.mean([r["placebo"]["raw_difference"] for r in rows])),
        "mean_treated_spend": float(np.mean([r["main"]["treated_mean"] for r in rows])),
        "mean_untreated_spend": float(np.mean([r["main"]["untreated_mean"] for r in rows])),
    }
    out["auc_range"] = [float(min(r["main"]["auc"] for r in rows)), float(max(r["main"]["auc"] for r in rows))]
    out["large_campaigns"] = {
        str(r["campaign"]): {
            "households": r["households"],
            "untargeted_households": int(round(r["main"]["untargeted_households"])),
            "treated_score_above_0.9": r["main"]["treated_score_above_0.9"],
            "weighting_effective_controls": r["main"]["weighting_effective_controls"],
            "matching_effective_controls": r["main"]["matching_effective_controls"],
        }
        for r in rows
        if r["type"] == "Type A"
    }
    like = [r["main"]["likeness"] for r in rows if "likeness" in r["main"]]
    if like:
        tops = [name for item in like for name in item["top"]]
        strongest = [x["top"][0] for x in like]
        out["covariates"] = {
            "mean_top3_share_below_median_outcome": float(np.mean([x["top_share_below_median_outcome"] for x in like])),
            "campaigns_with_majority_below": int(sum(x["top_share_below_median_outcome"] > 0.5 for x in like)),
            "median_rank_correlation": float(np.median([x["rank_correlation"] for x in like])),
            "top3_counts": {name: tops.count(name) for name in CONCEPTS if tops.count(name)},
            "strongest_counts": {name: strongest.count(name) for name in CONCEPTS if strongest.count(name)},
            "strongest_is_campaign_history": int(sum(name in HISTORY_VARIABLES for name in strongest)),
            "strongest_below_median_outcome": int(sum(x["strongest_below_median_outcome"] for x in like)),
            "median_treatment_partial_r2": {
                name: float(np.median([x["treatment_partial_r2"][name] for x in like])) for name in CONCEPTS
            },
            "median_outcome_partial_r2": {
                name: float(np.median([x["outcome_partial_r2"][name] for x in like])) for name in CONCEPTS
            },
            "mean_top3_share_below_median_outcome_with_spend_levels": float(
                np.mean([r["main"]["likeness_with_levels"]["top_share_below_median_outcome"] for r in rows])
            ),
        }
    out["placebo_by_adjustment_set"] = {
        estimator: {
            name: {
                "median_abs": float(np.median([abs(r["placebo"]["by_adjustment_set"][name][estimator]) for r in rows])),
                "mean": float(np.mean([r["placebo"]["by_adjustment_set"][name][estimator] for r in rows])),
            }
            for name in ADJUSTMENT_SETS
        }
        for estimator in ("Regression", "Matching", "Weighting")
    }
    return out


# --------------------------------------------------------------------------
# Exploratory additions
# --------------------------------------------------------------------------
def regression_estimate(y: np.ndarray, d: np.ndarray, x: np.ndarray) -> float:
    return ols_coefficient(y, d, x)


def weighting_estimate(y: np.ndarray, d: np.ndarray, x: np.ndarray) -> float:
    return weighting_att(y, d, fit_logit(x, d))


def pooled_bootstrap(problems: dict[str, list[tuple]], households: int, reps: int, seed: int, estimate=regression_estimate) -> dict[str, np.ndarray]:
    """Estimates for many analyses under one resampling of households.

    The campaigns share households, so households are the unit resampled and
    every analysis in a replication uses the same draw. Returns, per key, an
    array of shape (reps + 1, analyses); row 0 holds the point estimates.
    """
    rng = np.random.default_rng(seed)
    out = {key: np.empty((reps + 1, len(items))) for key, items in problems.items()}
    for rep in range(reps + 1):
        idx = np.arange(households) if rep == 0 else rng.integers(0, households, households)
        for key, items in problems.items():
            for j, (y, d, x) in enumerate(items):
                out[key][rep, j] = estimate(y[idx], d[idx], x[idx])
    return out


def interval(draws: np.ndarray) -> dict[str, float]:
    """Point estimate (row 0) with a 95% percentile interval from the rest."""
    return {
        "estimate": float(draws[0]),
        "low": float(np.percentile(draws[1:], 2.5)),
        "high": float(np.percentile(draws[1:], 97.5)),
        "se": float(np.std(draws[1:], ddof=1)),
    }


def pooled_summary(data: dict, primary: dict, reps: int, seed: int) -> dict:
    rows = primary["campaigns"]
    ids = [r["campaign"] for r in rows]
    small = np.array([r["type"] != "Type A" for r in rows])
    problems = {
        "main": [problem(data, c, 0, WINDOW, HISTORY)[:3] for c in ids],
        "placebo": [problem(data, c, 1, WINDOW, HISTORY)[:3] for c in ids],
    }
    draws = pooled_bootstrap(problems, len(data["households"]), reps, seed)
    main, placebo = draws["main"], draws["placebo"]
    usable = {key: [item for item, keep in zip(items, small) if keep] for key, items in problems.items()}
    weighted = pooled_bootstrap(usable, len(data["households"]), reps, seed + 100, weighting_estimate)
    return {
        "weighting_small_campaigns": {
            "campaigns": int(small.sum()),
            "mean_main": interval(weighted["main"].mean(axis=1)),
            "mean_placebo": interval(weighted["placebo"].mean(axis=1)),
            "mean_difference": interval((weighted["main"] - weighted["placebo"]).mean(axis=1)),
        },
        "correlation_main_placebo": float(np.corrcoef(main[0], placebo[0])[0, 1]),
        "mean_absolute_gap_main_placebo": float(np.abs(main[0] - placebo[0]).mean()),
        "mean_main": interval(main.mean(axis=1)),
        "mean_placebo": interval(placebo.mean(axis=1)),
        "mean_difference": interval((main - placebo).mean(axis=1)),
        "mean_placebo_small_campaigns": interval(placebo[:, small].mean(axis=1)),
        "mean_placebo_large_campaigns": interval(placebo[:, ~small].mean(axis=1)),
        "mean_main_small_campaigns": interval(main[:, small].mean(axis=1)),
        "mean_main_large_campaigns": interval(main[:, ~small].mean(axis=1)),
    }


def matching_sensitivity(data: dict, primary: dict, ridge: float = 1e-6) -> dict:
    """Matching estimates when the propensity model is fitted with a lighter penalty."""
    main, placebo = [], []
    for r in primary["campaigns"]:
        for lag, store in ((0, main), (1, placebo)):
            y, d, x, _ = problem(data, r["campaign"], lag, WINDOW, HISTORY)
            store.append(three_estimates(y, d, x, ridge)["Matching"])
    base = [r["placebo"]["estimates"]["Matching"] for r in primary["campaigns"]]
    return {
        "ridge": ridge,
        "mean_main": float(np.mean(main)),
        "mean_placebo": float(np.mean(placebo)),
        "placebo_positive": int(sum(v > 0 for v in placebo)),
        "largest_change_in_a_placebo": float(max(abs(a - b) for a, b in zip(placebo, base))),
    }


def power_table(primary: dict, bias: float) -> list[dict]:
    """Power of each campaign's placebo test against a bias of the given size."""
    normal = NormalDist()
    rows = []
    for r in primary["campaigns"]:
        row = {"campaign": r["campaign"], "households": r["households"], "type": r["type"]}
        for estimator in ("Regression", "Weighting"):
            se = r["placebo"]["bootstrap"][estimator]["se"]
            row[estimator] = {
                "se": se,
                "power": normal.cdf(bias / se - 1.96) + normal.cdf(-bias / se - 1.96),
                "detectable_at_80_percent": 2.8016 * se,
            }
        rows.append(row)
    return rows


def ladder(data: dict, reps: int, seed: int, lags: int = 3) -> dict:
    """The same analysis 0, 1, 2 and 3 windows before launch, on a common set of campaigns."""
    ids = list(eligible(data, WINDOW, HISTORY, lags).index)
    problems = {str(lag): [problem(data, c, lag, WINDOW, HISTORY)[:3] for c in ids] for lag in range(lags + 1)}
    draws = pooled_bootstrap(problems, len(data["households"]), reps, seed)
    return {
        "campaigns": [int(c) for c in ids],
        "lags": {
            lag: {**interval(values.mean(axis=1)), "positive": int((values[0] > 0).sum())} for lag, values in draws.items()
        },
    }


def history_sweep(data: dict, reps: int, seed: int, lengths=(28, 56, 84, 112)) -> dict:
    """Main and placebo estimates as the covariate history grows."""
    ids = list(eligible(data, WINDOW, max(lengths), 1).index)
    problems = {}
    for length in lengths:
        problems[f"placebo_{length}"] = [problem(data, c, 1, WINDOW, length)[:3] for c in ids]
        problems[f"main_{length}"] = [problem(data, c, 0, WINDOW, length)[:3] for c in ids]
    draws = pooled_bootstrap(problems, len(data["households"]), reps, seed)
    return {
        "campaigns": [int(c) for c in ids],
        "lengths": {
            str(length): {
                "placebo": {
                    **interval(draws[f"placebo_{length}"].mean(axis=1)),
                    "positive": int((draws[f"placebo_{length}"][0] > 0).sum()),
                },
                "main": interval(draws[f"main_{length}"].mean(axis=1)),
                "difference": interval((draws[f"main_{length}"] - draws[f"placebo_{length}"]).mean(axis=1)),
            }
            for length in lengths
        },
    }


def event_time(data: dict, primary: dict, before: int = 12, after: int = 4) -> dict:
    """Average weekly spending around launch, by whether the household was targeted."""
    weeks = list(range(-before, after))
    treated, untreated = [], []
    for r in primary["campaigns"]:
        d = members(data, r["campaign"])
        start = pd.Timestamp(r["start"])
        spend = np.array([outcome(data, start + pd.Timedelta(days=7 * w), 7) for w in weeks])
        treated.append(spend[:, d == 1].mean(axis=1))
        untreated.append(spend[:, d == 0].mean(axis=1))
    t, u = np.mean(treated, axis=0), np.mean(untreated, axis=0)
    return {
        "weeks": weeks,
        "treated": [float(v) for v in t],
        "untreated": [float(v) for v in u],
        "treated_mean_before": float(t[:before].mean()),
        "treated_mean_after": float(t[before:].mean()),
        "untreated_mean_before": float(u[:before].mean()),
        "untreated_mean_after": float(u[before:].mean()),
    }


def job_training(cache: Path) -> dict:
    """The covariate statistic on the trainees plus the CPS comparison group."""
    frames = [
        pd.read_stata(fetch(MIXTAPE_URL.format(name=name), cache / f"{name}.dta")).drop(columns="data_id").astype(float)
        for name in ("nsw_mixtape", "cps_mixtape")
    ]
    df = pd.concat([frames[0][frames[0]["treat"] == 1], frames[1]], ignore_index=True)
    names = ("age", "educ", "black", "hisp", "marr", "nodegree", "re74", "re75")
    return instrument_likeness(df["treat"].to_numpy(int), df["re78"].to_numpy(float), df[list(names)].to_numpy(float), names)


# --------------------------------------------------------------------------
# Figures
# --------------------------------------------------------------------------
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
BLUE = "#2a78d6"
ORANGE = "#eb6834"
NEUTRAL = "#f0efec"
MINUS = "−"


def _style() -> None:
    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ["Inter", "Helvetica Neue", "Arial", "DejaVu Sans"],
            "font.size": 10,
            "figure.facecolor": SURFACE,
            "axes.facecolor": SURFACE,
            "savefig.facecolor": SURFACE,
            "axes.edgecolor": AXIS,
            "axes.labelcolor": INK_2,
            "axes.titlecolor": INK,
            "axes.titlesize": 10.5,
            "axes.titleweight": "semibold",
            "axes.titlelocation": "left",
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "axes.axisbelow": True,
            "grid.color": GRID,
            "grid.linewidth": 0.8,
            "xtick.color": MUTED,
            "ytick.color": MUTED,
            "xtick.labelcolor": INK_2,
            "ytick.labelcolor": INK_2,
            "xtick.major.size": 0,
            "ytick.major.size": 0,
            "legend.frameon": False,
            "lines.linewidth": 2.0,
            "lines.solid_capstyle": "round",
        }
    )


def _headline(fig: plt.Figure, text: str, sub: str = "", y: float = 0.955) -> None:
    fig.text(0.03, y, text, fontsize=12, fontweight="semibold", color=INK)
    if sub:
        fig.text(0.03, y - 0.055, sub, fontsize=9, color=INK_2)


DOLLARS = FuncFormatter(lambda v, _: f"{v:,.0f}".replace("-", MINUS))


def figure_spending(path: Path, events: dict) -> None:
    fig, ax = plt.subplots(figsize=(8.6, 4.3))
    weeks = np.array(events["weeks"]) + 0.5
    ax.axvspan(0, max(weeks) + 0.5, color=NEUTRAL, linewidth=0, zorder=0)
    ax.plot(weeks, events["treated"], color=BLUE, marker="o", markersize=5, markeredgecolor=SURFACE, label="Households that received the campaign")
    ax.plot(weeks, events["untreated"], color=ORANGE, marker="o", markersize=5, markeredgecolor=SURFACE, label="Households that did not")
    ax.axvline(0, color=INK, linewidth=1.2)
    top = max(events["treated"]) * 1.22
    ax.text(0.15, top * 0.965, "campaign live", fontsize=9, color=INK_2, va="top")
    ax.set_ylim(0, top)
    ax.set_xlim(min(weeks) - 0.5, max(weeks) + 0.5)
    ax.set_xticks(range(min(events["weeks"]), max(events["weeks"]) + 2, 2))
    ax.set_xlabel("Weeks from launch")
    ax.set_ylabel("Spending per household per week (US$)")
    ax.yaxis.set_major_formatter(DOLLARS)
    ax.grid(axis="x", visible=False)
    ax.legend(loc="lower left", bbox_to_anchor=(0.0, 0.02), fontsize=9)
    _headline(fig, "The targeted households were already spending more than twice as much",
              "Average over the 16 campaigns. Weekly spending in the twelve weeks before launch and the four weeks after.")
    fig.subplots_adjust(top=0.82, bottom=0.13, left=0.09, right=0.98)
    fig.savefig(path, dpi=200)
    plt.close(fig)


def figure_campaigns(path: Path, primary: dict) -> None:
    rows = primary["campaigns"]
    fig, ax = plt.subplots(figsize=(8.6, 6.4))
    positions = np.arange(len(rows))[::-1]
    for pos, r in zip(positions, rows):
        for offset, key, colour in ((0.17, "main", BLUE), (-0.17, "placebo", ORANGE)):
            b = r[key]["bootstrap"]["Regression"]
            ax.plot([b["low"], b["high"]], [pos + offset] * 2, color=colour, linewidth=1.6, alpha=0.55, zorder=2)
            ax.scatter(r[key]["estimates"]["Regression"], pos + offset, s=38, color=colour, edgecolors=SURFACE, linewidths=1.0, zorder=3)
    ax.axvline(0, color=INK, linewidth=1.2, zorder=1)
    ax.set_yticks(positions)
    ax.set_yticklabels([f"{r['campaign']}  ·  {r['households']:,}" for r in rows], color=INK)
    ax.set_ylim(-0.7, len(rows) - 0.3)
    ax.set_xlabel("US$ per household over four weeks, regression adjustment, with 95% bootstrap intervals")
    ax.xaxis.set_major_formatter(DOLLARS)
    ax.grid(axis="y", visible=False)
    ax.spines["left"].set_visible(False)
    handles = [
        plt.Line2D([], [], color=BLUE, marker="o", markersize=6, markeredgecolor=SURFACE, linewidth=1.6, label="Estimated effect: four weeks after launch"),
        plt.Line2D([], [], color=ORANGE, marker="o", markersize=6, markeredgecolor=SURFACE, linewidth=1.6, label="Placebo: four weeks before launch"),
    ]
    ax.legend(handles=handles, loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=2, fontsize=9, columnspacing=2.2)
    _headline(fig, "On average, the same analysis run before launch gives estimates of the same size", y=0.965)
    fig.text(0.03, 0.918, "Campaign number and households targeted, in order of launch.", fontsize=9, color=INK_2)
    fig.subplots_adjust(top=0.85, bottom=0.09, left=0.14, right=0.975)
    fig.savefig(path, dpi=200)
    plt.close(fig)


def _strip(ax: plt.Axes, items: list[dict], colours: list[str], offset: float = 0.0, label_side: float = 0.13) -> None:
    """Dots with intervals at integer positions, each labelled with its value."""
    for i, (item, colour) in enumerate(zip(items, colours)):
        ax.plot([i + offset] * 2, [item["low"], item["high"]], color=colour, linewidth=1.8, alpha=0.55, zorder=2)
        ax.scatter(i + offset, item["estimate"], s=46, color=colour, edgecolors=SURFACE, linewidths=1.0, zorder=3)
        ax.text(i + offset + label_side, item["estimate"], f"{item['estimate']:.0f}".replace("-", MINUS), fontsize=9,
                color=INK_2, va="center", ha="left" if label_side > 0 else "right")
    ax.axhline(0, color=INK, linewidth=1.0, zorder=1)
    ax.grid(axis="x", visible=False)
    ax.yaxis.set_major_formatter(DOLLARS)


def figure_power(path: Path, power: list[dict], pooled: dict, ladder_result: dict) -> None:
    fig, (left, right) = plt.subplots(1, 2, figsize=(9.6, 4.3), gridspec_kw={"width_ratios": [1.1, 1]})
    sizes = [p["households"] for p in power]
    values = [100 * p["Regression"]["power"] for p in power]
    left.scatter(sizes, values, s=44, color=BLUE, alpha=0.75, edgecolors=SURFACE, linewidths=1.0, zorder=3)
    left.axhline(80, color=INK, linewidth=1.0)
    left.text(min(sizes), 82, "80%, the usual target", fontsize=9, color=INK_2, va="bottom")
    left.set_xscale("log")
    left.set_xticks([65, 125, 250, 500, 1000])
    left.set_xticklabels(["65", "125", "250", "500", "1,000"])
    left.minorticks_off()
    left.set_ylim(0, 100)
    left.set_xlabel("Households targeted by the campaign")
    left.set_ylabel("Chance that the placebo test fails (%)")
    left.set_title(f"Power of each campaign's placebo against a ${pooled['mean_placebo']['estimate']:.0f} bias")

    lags = ladder_result["lags"]
    order = ("3", "2", "1", "0")
    _strip(right, [lags[k] for k in order], [ORANGE, ORANGE, ORANGE, BLUE])
    right.set_xticks(range(4))
    right.set_xticklabels(["12 to 9\nbefore", "8 to 5\nbefore", "4 to 1\nbefore", "1 to 4\nafter"])
    right.set_xlim(-0.5, 3.6)
    right.set_xlabel("Outcome window, in weeks from launch")
    handles = [
        plt.Line2D([], [], color=ORANGE, marker="o", markersize=6, markeredgecolor=SURFACE, linewidth=1.6, label="Placebo"),
        plt.Line2D([], [], color=BLUE, marker="o", markersize=6, markeredgecolor=SURFACE, linewidth=1.6, label="Estimated effect"),
    ]
    right.legend(handles=handles, loc="upper left", fontsize=9)
    right.set_ylabel("Mean estimate across campaigns (US$)")
    right.set_title("The same analysis, moved back in time")
    low = min(min(v["low"] for v in lags.values()), 0)
    right.set_ylim(low - 2, max(v["high"] for v in lags.values()) + 8)
    _headline(fig, "Most single campaigns cannot see the bias; the estimate is much the same before launch",
              f"Regression adjustment. Right: the {len(ladder_result['campaigns'])} campaigns with enough history, 95% intervals from resampling households.")
    fig.subplots_adjust(top=0.78, bottom=0.2, left=0.075, right=0.985, wspace=0.24)
    fig.savefig(path, dpi=200)
    plt.close(fig)


def figure_history(path: Path, sweep: dict) -> None:
    fig, ax = plt.subplots(figsize=(8.2, 4.3))
    lengths = sweep["lengths"]
    keys = list(lengths)
    _strip(ax, [lengths[k]["main"] for k in keys], [BLUE] * len(keys), offset=-0.1, label_side=-0.11)
    _strip(ax, [lengths[k]["placebo"] for k in keys], [ORANGE] * len(keys), offset=0.1, label_side=0.11)
    ax.set_xticks(range(len(keys)))
    ax.set_xticklabels([f"{int(k) // 7} weeks" for k in keys])
    ax.set_xlim(-0.6, len(keys) - 0.4)
    ax.set_xlabel("History of spending and behaviour in the adjustment set")
    ax.set_ylabel("Mean estimate across campaigns (US$)")
    handles = [
        plt.Line2D([], [], color=BLUE, marker="o", markersize=6, markeredgecolor=SURFACE, linewidth=1.6, label="Estimated effect: four weeks after launch"),
        plt.Line2D([], [], color=ORANGE, marker="o", markersize=6, markeredgecolor=SURFACE, linewidth=1.6, label="Placebo: four weeks before launch"),
    ]
    ax.legend(handles=handles, loc="upper right", fontsize=9)
    _headline(fig, "More history shrinks the placebo, and the estimated effect shrinks with it",
              f"Regression adjustment, {len(sweep['campaigns'])} campaigns, 95% intervals from resampling households.")
    fig.subplots_adjust(top=0.82, bottom=0.14, left=0.09, right=0.98)
    fig.savefig(path, dpi=200)
    plt.close(fig)


def figure_covariates(path: Path, summary: dict) -> None:
    cov = summary["covariates"]
    fig, (left, right) = plt.subplots(1, 2, figsize=(10.0, 4.5), gridspec_kw={"width_ratios": [1.25, 1]})
    floor = 2e-5
    for name in CONCEPTS:
        t = max(cov["median_treatment_partial_r2"][name], floor)
        o = max(cov["median_outcome_partial_r2"][name], floor)
        history = name in HISTORY_VARIABLES
        left.scatter(t, o, s=52, color=ORANGE if history else BLUE, edgecolors=SURFACE, linewidths=1.0, zorder=3)
    labels = {
        "Earlier campaigns": ("Earlier campaigns", 0.85, "right"),
        "Concurrent small campaigns": ("Concurrent (small)", 1.2, "left"),
        "Concurrent large campaigns": ("Concurrent (large)", 1.25, "left"),
        "Spend, last 4 weeks": ("Spend, last 4 weeks", 0.85, "right"),
        "Days since last trip": ("Days since last trip", 0.85, "right"),
        "Private-label share": ("Private-label share", 1.2, "left"),
    }
    for name, (text, dx, align) in labels.items():
        t = max(cov["median_treatment_partial_r2"][name], floor)
        o = max(cov["median_outcome_partial_r2"][name], floor)
        left.text(t * dx, o, text, fontsize=8.5, color=INK_2, va="center", ha=align)
    left.set_xlim(1.4e-5, 6e-2)
    left.set_xscale("log")
    left.set_yscale("log")
    left.set_xlabel("Strength as a predictor of being targeted (partial R²)")
    left.set_ylabel("Strength as a predictor of spending (partial R²)")
    left.set_title("What predicts targeting, and what predicts spending")
    handles = [
        plt.Line2D([], [], color=ORANGE, marker="o", markersize=7, markeredgecolor=SURFACE, linewidth=0, label="Campaign history"),
        plt.Line2D([], [], color=BLUE, marker="o", markersize=7, markeredgecolor=SURFACE, linewidth=0, label="Shopping behaviour"),
    ]
    left.legend(handles=handles, loc="center left", fontsize=9, handletextpad=0.3)

    sets = summary["placebo_by_adjustment_set"]["Regression"]
    names = list(ADJUSTMENT_SETS)
    values = [sets[name]["median_abs"] for name in names]
    positions = np.arange(len(names))[::-1]
    right.barh(positions, values, height=0.5, color=BLUE)
    for pos, value in zip(positions, values):
        right.text(value + 2, pos, f"${value:.0f}", fontsize=9, color=INK_2, va="center")
    right.set_yticks(positions)
    right.set_yticklabels(names, color=INK)
    right.set_xlim(0, max(values) * 1.18)
    right.xaxis.set_major_formatter(DOLLARS)
    right.set_xlabel("Median size of the placebo estimate (US$)")
    right.set_title("Placebo by adjustment set")
    right.grid(axis="y", visible=False)
    right.spines["left"].set_visible(False)
    _headline(fig, "Campaign history predicts targeting best; under regression, dropping it does not improve the placebo",
              "Left: median over the 16 campaigns, one dot per covariate. Right: regression adjustment; the true value is zero.")
    fig.subplots_adjust(top=0.8, bottom=0.14, left=0.08, right=0.975, wspace=0.62)
    fig.savefig(path, dpi=200)
    plt.close(fig)


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def draw(out_dir: Path, results: dict) -> None:
    _style()
    figure_spending(out_dir / "placebo_fig1_spending.png", results["event_time"])
    figure_campaigns(out_dir / "placebo_fig2_campaigns.png", results["primary"])
    figure_power(out_dir / "placebo_fig3_power.png", results["power"], results["pooled"], results["ladder"])
    figure_history(out_dir / "placebo_fig4_history.png", results["history"])
    figure_covariates(out_dir / "placebo_fig5_covariates.png", results["primary"]["summary"])


def main(out_dir: Path, cache: Path, reps: int = REPS) -> dict:
    data = load(cache)
    primary = run_protocol(data, WINDOW, HISTORY, False, reps, SEED)
    pooled = pooled_summary(data, primary, reps, SEED + 1)
    results = {
        "data": {
            "households": int(len(data["households"])),
            "transactions": data["transactions"],
            "first_day": str(data["first_day"].date()),
            "last_day": str(data["last_day"].date()),
            "campaigns": int(len(data["descriptions"])),
            "household_campaign_pairs": int(len(data["campaigns"])),
            "households_ever_targeted": int(data["campaigns"]["household_id"].nunique()),
        },
        "primary": primary,
        "pooled": pooled,
        "power": (power := power_table(primary, pooled["mean_placebo"]["estimate"])),
        "expected_placebo_failures": {
            "bias": pooled["mean_placebo"]["estimate"],
            "Regression": float(sum(p["Regression"]["power"] for p in power)),
            "Weighting": float(sum(p["Weighting"]["power"] for p in power)),
        },
        "matching_sensitivity": matching_sensitivity(data, primary),
        "ladder": ladder(data, reps, SEED + 2),
        "history": history_sweep(data, reps, SEED + 3),
        "event_time": event_time(data, primary),
        "job_training": job_training(cache),
        "robustness": {
            "concurrent_known_at_launch": run_protocol(data, WINDOW, HISTORY, True, reps // 2, SEED + 4)["summary"],
            "windows_of_14_days": run_protocol(data, 14, HISTORY, False, reps // 2, SEED + 5)["summary"],
        },
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "placebo_results.json").write_text(json.dumps(results, indent=2))
    draw(out_dir, results)
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=Path("output"))
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument("--reps", type=int, default=REPS)
    parser.add_argument("--figures-only", action="store_true", help="redraw the figures from an existing results file")
    args = parser.parse_args()
    if args.figures_only:
        draw(args.out, json.loads((args.out / "placebo_results.json").read_text()))
    else:
        main(args.out, args.data, args.reps)
