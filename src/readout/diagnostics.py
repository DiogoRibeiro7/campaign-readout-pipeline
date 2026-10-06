"""What the registry shows about the pipeline itself.

None of this is published to a consumer. It is the analyst's view of the
internal trail: the estimates of refused readouts pooled across campaigns, the
readouts made on windows before the launch, and a few checks on what the
placebos are picking up.

Readouts on earlier windows. Every campaign is also read out as if it had been
launched one window, and then two windows, before it was, when it had not
been sent. The estimate there is not an effect of this campaign. It is not
guaranteed to be zero either: other campaigns ran in those weeks, and if the
retailer chose the households on what they spent shortly before the launch,
that spending is the shifted readout's outcome. One window back, the estimate
is the real readout's shifted placebo by another name. These readouts are a
second look at the placebos from other anchors, not an independent test set.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .bootstrap import interval
from .certificate import pooled_mean
from .contract import Contract
from .estimators import ESTIMATORS
from .features import build_problem, outcome, seen_before
from .pipeline import PLACEBOS
from .registry import Registry
from .result import Interval
from .snapshot import Snapshot
from .sweep import verdict_at

POOLED = {
    "effect": "mean_estimate",
    "prehistory_placebo": "mean_prehistory_placebo",
    "shifted_placebo": "mean_shifted_placebo",
}


def _draws(registry: Registry, units: pd.DataFrame) -> dict[str, np.ndarray]:
    """Bootstrap draws of each role, one column per unit."""
    stored = [registry.draws(key) for key in units["key"]]
    return {role: np.column_stack([s[role] for s in stored]) for role in POOLED}


def _estimates(units: pd.DataFrame, role: str) -> np.ndarray:
    return np.array([e["estimate"] for e in units[role]])


def _pooled(registry: Registry, units: pd.DataFrame, level: float) -> dict[str, Interval]:
    """Means across units, and the difference between the two pooled placebos."""
    draws = _draws(registry, units)
    out = {role: pooled_mean(draws[role], _estimates(units, role), level) for role in POOLED}
    gap = draws["prehistory_placebo"] - draws["shifted_placebo"]
    out["placebo_difference"] = pooled_mean(
        gap, _estimates(units, "prehistory_placebo") - _estimates(units, "shifted_placebo"), level
    )
    return out


def _spread(row: dict, name: str, value: Interval) -> None:
    row[name], row[f"{name}_low"], row[f"{name}_high"] = value.estimate, value.low, value.high


def pooled_by_shift(registry: Registry, contract: Contract, shifts: tuple[int, ...]) -> pd.DataFrame:
    """Per method and shift: the campaigns that passed the data, timing and overlap gates, taken together.

    ``smallest_tolerance`` is the smallest tolerance at which the programme
    readout would have been published: the pooled placebo intervals it has to
    contain.
    """
    tol = contract.tolerances
    audit = registry.audit(contract)
    rows = []
    for method in contract.methods:
        for shift in shifts:
            units = registry.valid_units(contract, method, shift)
            if units.empty:
                continue
            everything = audit[(audit["method"] == method.name) & (audit["shift"] == shift)]
            pooled = _pooled(registry, units, tol.interval_level)
            row = {
                "method": method.name,
                "shift": shift,
                "units": len(everything),
                "units_with_estimates": len(units),
                "published": int((everything["verdict"] == "published").sum()),
            }
            for role, name in POOLED.items():
                _spread(row, name, pooled[role])
            _spread(row, "placebo_difference", pooled["placebo_difference"])
            row["estimate_intervals_holding_zero"] = int(
                np.sum([e["low"] <= 0.0 <= e["high"] for e in units["effect"]])
            )
            bound = {p: max(abs(pooled[p].low), abs(pooled[p].high)) for p in PLACEBOS}
            row["smallest_tolerance_undocumented"] = float(max(bound.values()))
            row["smallest_tolerance_documented"] = float(bound["prehistory_placebo"])
            rows.append(row)
    return pd.DataFrame(rows)


def gate_audit(
    registry: Registry, contract: Contract, shifts: tuple[int, ...], tolerances: list[float]
) -> pd.DataFrame:
    """Readouts on earlier windows: what each tolerance would have published, and what those estimates were.

    The campaign had not been sent, so a gate that publishes a large estimate
    there has let something through.
    """
    tol = contract.tolerances
    rows = []
    for method in contract.methods:
        for shift in shifts:
            if shift == 0:
                continue
            units = registry.valid_units(contract, method, shift)
            if units.empty:
                continue
            for documented in (False, True):
                for tolerance in tolerances:
                    verdicts = [
                        verdict_at(row, tolerance, tol.min_record_campaigns, documented)[0]
                        for _, row in units.iterrows()
                    ]
                    published = units[np.array(verdicts) == "published"]
                    row = {
                        "method": method.name,
                        "shift": shift,
                        "assignment_documented": documented,
                        "tolerance_usd": tolerance,
                        "units_with_estimates": len(units),
                        "published": len(published),
                    }
                    if len(published):
                        _spread(row, "mean_estimate", _pooled(registry, published, tol.interval_level)["effect"])
                        row["largest_estimate"] = float(np.abs(_estimates(published, "effect")).max())
                    rows.append(row)
    return pd.DataFrame(rows)


def prehistory_check(snapshot: Snapshot, registry: Registry, contract: Contract) -> pd.DataFrame:
    """Is the pre-history placebo driven by households with no recorded spending in its window?

    A household whose first recorded purchase falls inside the history has no
    spending before it. The placebo is recomputed on the households that had
    already been seen when the pre-history window opened. Point estimates
    only. The feed starts on a fixed day, so "first seen" is the first
    purchase in the feed, not the day the household became a customer.
    """
    w, c, tol = contract.windows, contract.covariates, contract.tolerances
    rows = []
    for method in contract.methods:
        units = registry.valid_units(contract, method, 0)
        for _, unit in units.iterrows():
            launch = pd.Timestamp(unit["launch"])
            view = snapshot.as_of(pd.Timestamp(unit["as_of"]))
            p = build_problem(
                view,
                int(unit["campaign"]),
                launch,
                "prehistory_placebo",
                w.outcome_days,
                w.history_days,
                c.concurrent_campaigns,
                drop=c.dropped,
            )
            seen = np.isin(p.households, seen_before(view, p.outcome_start))
            enough = p.d[seen].sum() >= tol.min_treated and (1 - p.d[seen]).sum() >= tol.min_controls
            restricted = ESTIMATORS[method.estimator](p.y[seen], p.d[seen], p.x[seen]) if enough else float("nan")
            rows.append(
                {
                    "method": method.name,
                    "campaign": int(unit["campaign"]),
                    "households": len(seen),
                    "households_seen_before_window": int(seen.sum()),
                    "targeted_without_spending_in_window": float((p.y[p.d == 1] == 0).mean()),
                    "comparison_without_spending_in_window": float((p.y[p.d == 0] == 0).mean()),
                    "prehistory_placebo": float(unit["prehistory_placebo"]["estimate"]),
                    "prehistory_placebo_seen_before_window": restricted,
                }
            )
    return pd.DataFrame(rows)


def spending_gap(snapshot: Snapshot, registry: Registry, contract: Contract, windows_back: int = 8) -> pd.DataFrame:
    """Mean spending of targeted and comparison households, window by window up to the readout.

    No adjustment, no estimate: what the two groups of the readout spent in
    each window of ``outcome_days`` counted from the launch (0 is the outcome
    window, -1 the window before the launch). It shows how long before the
    launch the two groups already differed.
    """
    w = contract.windows
    units = registry.valid_units(contract, contract.method, 0)
    rows = []
    for _, unit in units.iterrows():
        launch = pd.Timestamp(unit["launch"])
        view = snapshot.as_of(pd.Timestamp(unit["as_of"]))
        households = seen_before(view, launch)
        ids = view.campaigns.loc[view.campaigns["campaign_id"] == int(unit["campaign"]), "household_id"]
        targeted = np.isin(households, ids)
        for back in range(-windows_back, 1):
            start = launch + pd.Timedelta(days=back * w.outcome_days)
            if start < view.first_day:
                continue
            spent = outcome(view, households, start, w.outcome_days)
            rows.append(
                {
                    "campaign": int(unit["campaign"]),
                    "window": back,
                    "targeted": float(spent[targeted].mean()),
                    "comparison": float(spent[~targeted].mean()),
                    "gap": float(spent[targeted].mean() - spent[~targeted].mean()),
                }
            )
    return pd.DataFrame(rows)


def like_for_like(registry: Registry, contracts: list[Contract]) -> pd.DataFrame:
    """The contracts compared on the campaigns that passed the data, timing and overlap gates under every one of them.

    The bootstrap is keyed on households, so the draws of two contracts line
    up replication by replication, and the change from the first contract to
    each later one gets an interval of its own.
    """
    rows = []
    for name in sorted({method.name for contract in contracts for method in contract.methods}):
        valid = {}
        for contract in contracts:
            method = next((m for m in contract.methods if m.name == name), None)
            if method is not None:
                valid[contract.version] = (contract, registry.valid_units(contract, method, 0))
        if len(valid) < 2 or any(units.empty for _, units in valid.values()):
            continue
        shared = sorted(set.intersection(*(set(units["campaign"]) for _, units in valid.values())))
        if not shared:
            continue
        base = None
        for version, (contract, units) in valid.items():
            mine = units.set_index("campaign").loc[shared].reset_index()
            level = contract.tolerances.interval_level
            draws, pooled = _draws(registry, mine), _pooled(registry, mine, level)
            row = {
                "contract": f"v{version}",
                "history_days": contract.windows.history_days,
                "method": name,
                "campaigns": len(mine),
                "campaign_ids": " ".join(str(int(c)) for c in shared),
            }
            for role, label in POOLED.items():
                _spread(row, label, pooled[role])
            if base is None:
                base = (draws, pooled)
            else:
                for role, label in POOLED.items():
                    change = draws[role].mean(axis=1) - base[0][role].mean(axis=1)
                    low, high = interval(change, level)
                    row[f"change_in_{label}"] = pooled[role].estimate - base[1][role].estimate
                    row[f"change_in_{label}_low"], row[f"change_in_{label}_high"] = low, high
            rows.append(row)
    return pd.DataFrame(rows)
