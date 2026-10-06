"""The gates. Each one measures something, compares it with the contract, and can fail.

A readout is published only if every gate passes. A gate that cannot be
evaluated fails: missing evidence is not evidence that things are fine.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .certificate import band_state
from .contract import Contract, Method
from .estimators import Overlap
from .features import Problem, covariates, design_columns, exposure, outcome, seen_before
from .result import GateOutcome, Interval, Record
from .snapshot import View


def data_gate(view: View, anchor: pd.Timestamp, treated: int, controls: int, contract: Contract) -> GateOutcome:
    """Is there enough data, and is the feed whole over the days the readout needs?"""
    w, tol = contract.windows, contract.tolerances
    window_end = anchor + pd.Timedelta(days=w.outcome_days)
    history_start = anchor - pd.Timedelta(days=w.history_days + w.outcome_days)
    span = pd.date_range(
        max(history_start, view.first_day), min(window_end, view.as_of) - pd.Timedelta(days=1), freq="D"
    )
    seen = set(view.daily["day"].unique())
    closed = set(contract.data.closed_days)
    missing = [str(day.date()) for day in span if day not in seen and day.strftime("%m-%d") not in closed]
    measurements = {
        "treated": treated,
        "controls": controls,
        "history_start": str(history_start.date()),
        "first_day_in_feed": str(view.first_day.date()),
        "outcome_window_end": str(window_end.date()),
        "as_of": str(view.as_of.date()),
        "days_without_sales": len(missing),
    }
    thresholds = {"min_treated": tol.min_treated, "min_controls": tol.min_controls}
    failures = []
    if window_end > view.as_of:
        failures.append(("DATA_OUTCOME_INCOMPLETE", "the outcome window has not closed on the readout date"))
    if history_start < view.first_day:
        failures.append(
            ("DATA_INSUFFICIENT_HISTORY", "the feed does not reach back far enough for the history and the placebos")
        )
    if treated < tol.min_treated:
        failures.append(("DATA_TOO_FEW_TREATED", f"{treated} targeted households, fewer than {tol.min_treated}"))
    if controls < tol.min_controls:
        failures.append(("DATA_TOO_FEW_CONTROLS", f"{controls} comparison households, fewer than {tol.min_controls}"))
    if missing:
        failures.append(("DATA_GAP", f"no sales recorded on {', '.join(missing[:5])}"))
    if failures:
        return GateOutcome(
            gate="data",
            passed=False,
            code=failures[0][0],
            detail="; ".join(text for _, text in failures),
            measurements=measurements,
            thresholds=thresholds,
        )
    return GateOutcome(
        gate="data",
        passed=True,
        detail="enough households and an unbroken feed",
        measurements=measurements,
        thresholds=thresholds,
    )


def _design(view: View, p: Problem, contract: Contract) -> np.ndarray:
    """The adjustment set of a problem, computed again from ``view``."""
    w = contract.windows
    frame = covariates(
        view,
        p.campaign,
        p.covariates_end,
        w.outcome_days,
        w.history_days,
        contract.covariates.concurrent_campaigns,
        p.households,
    )
    if p.role == "prehistory_placebo":
        frame = frame.join(exposure(view, p.campaign, p.outcome_start, w.outcome_days, p.households))
    return np.column_stack(list(design_columns(frame, p.drop).values()))


def _largest_gap(a: np.ndarray, b: np.ndarray) -> float:
    if a.shape != b.shape:
        return float("inf")
    return float(np.max(np.abs(a - b))) if a.size else 0.0


def timing_gate(view: View, problems: list[Problem], contract: Contract) -> GateOutcome:
    """Is everything a problem holds dated the way the contract says?

    The gate does not trust the code that built the problems. It computes
    their contents again from views cut at the dates they claim, and requires
    the same numbers.

    Population: every household has a purchase before the covariate date.
    Covariates: what the household did, and the campaigns sent before the
    covariate date, come out the same from the view cut at that date. The
    columns that follow the campaign calendar through the outcome window are
    allowed only if the contract declares that rule, and come out the same
    from the view cut where the outcome window closes. Outcome: it is the
    spending of the declared window, which has closed, and for the effect it
    starts no earlier than the covariate date.

    In a correct build none of this can fail. It is here for the day someone
    edits the covariates.
    """
    w = contract.windows
    days = pd.Timedelta(days=w.outcome_days)
    declared = contract.covariates.concurrent_campaigns == "through_outcome_window"
    strangers = undeclared = misplaced = 0
    gap_covariates = gap_calendar = gap_outcome = 0.0
    for p in problems:
        strangers += int((~np.isin(p.households, seen_before(view, p.covariates_end))).sum())
        late = p.late
        gap_covariates = max(
            gap_covariates, _largest_gap(_design(view.cut(p.covariates_end), p, contract)[:, ~late], p.x[:, ~late])
        )
        if late.any():
            if not declared or p.calendar_until > view.as_of:
                undeclared += 1
            else:
                gap_calendar = max(
                    gap_calendar, _largest_gap(_design(view.cut(p.calendar_until), p, contract)[:, late], p.x[:, late])
                )
        gap_outcome = max(gap_outcome, _largest_gap(outcome(view, p.households, p.outcome_start, w.outcome_days), p.y))
        if p.outcome_start + days > view.as_of or (p.role == "effect" and p.outcome_start < p.covariates_end):
            misplaced += 1

    def finite(gap: float) -> float | None:
        return gap if np.isfinite(gap) else None  # None: the recomputed table has another shape

    measurements = {
        "households_not_seen_before_covariate_date": strangers,
        "largest_change_in_covariates_when_cut_at_their_date": finite(gap_covariates),
        "problems_following_the_calendar_without_declaring_it": undeclared,
        "largest_change_in_calendar_columns_when_cut_at_window_end": finite(gap_calendar),
        "largest_change_in_outcome_when_recomputed": finite(gap_outcome),
        "problems_with_a_misplaced_outcome_window": misplaced,
    }

    def refuse(code: str, detail: str) -> GateOutcome:
        return GateOutcome(gate="timing", passed=False, code=code, detail=detail, measurements=measurements)

    if strangers:
        return refuse("TIMING_POPULATION", "the population holds households first seen after the covariate date")
    if undeclared:
        return refuse(
            "TIMING_LATE_COVARIATE",
            "a covariate follows the campaign calendar past its date and the contract does not declare it",
        )
    if gap_covariates > 1e-9 or gap_calendar > 1e-9:
        return refuse("TIMING_LEAK", "covariates change when later data are removed")
    if misplaced or gap_outcome > 1e-9:
        return refuse("TIMING_OUTCOME", "an outcome is not the spending of its declared window")
    return GateOutcome(
        gate="timing",
        passed=True,
        detail="population, covariates and outcomes are dated as declared",
        measurements=measurements,
    )


def overlap_gate(scores: dict[str, Overlap], contract: Contract, method: Method) -> GateOutcome:
    """Are there comparison households that resemble the targeted ones?

    Checked on the effect and on the shifted placebo, whose covariates differ.
    The pre-history placebo shares the households and covariates of the effect.
    The two conditions on weights apply to weighting only: regression does not
    use them.
    """
    tol = contract.tolerances
    weighting = method.estimator == "weighting"
    measurements: dict = {}
    for role, o in scores.items():
        measurements |= {
            f"{role}_treated_extreme_share": o.treated_extreme_share,
            f"{role}_effective_controls": o.effective_controls,
            f"{role}_largest_weight_share": o.largest_weight_share,
            f"{role}_auc": o.auc,
        }
    thresholds = {
        "extreme_score": tol.extreme_score,
        "max_treated_extreme_share": tol.max_treated_extreme_share,
        "min_effective_controls": tol.min_effective_controls if weighting else None,
        "max_control_weight_share": tol.max_control_weight_share if weighting else None,
    }

    def refuse(code: str, detail: str) -> GateOutcome:
        return GateOutcome(
            gate="overlap", passed=False, code=code, detail=detail, measurements=measurements, thresholds=thresholds
        )

    for role, o in scores.items():
        where = "" if role == "effect" else f" (in the {role.replace('_', ' ')})"
        if o.treated_extreme_share > tol.max_treated_extreme_share:
            share = f"{100 * o.treated_extreme_share:.0f}% of targeted households have a propensity score above {tol.extreme_score}"
            return refuse("OVERLAP_EXTREME_SCORES", share + where)
        if weighting and o.effective_controls < tol.min_effective_controls:
            return refuse(
                "OVERLAP_FEW_EFFECTIVE_CONTROLS",
                f"the weighted comparison group is worth {o.effective_controls:.0f} households" + where,
            )
        if weighting and o.largest_weight_share > tol.max_control_weight_share:
            return refuse(
                "OVERLAP_ONE_HOUSEHOLD_DOMINATES",
                f"one comparison household carries {100 * o.largest_weight_share:.0f}% of the weight" + where,
            )
    return GateOutcome(
        gate="overlap",
        passed=True,
        detail="targeted and comparison households overlap",
        measurements=measurements,
        thresholds=thresholds,
    )


def _evidence(own: Interval, record: Record, tolerance: float) -> tuple[bool, str, str | None]:
    """Does a placebo show that its effect is negligible? Returns (passed, state, source).

    The readout's own placebo can show it, if its whole interval lies inside
    the band. It can show the opposite, if its whole interval lies beyond the
    band. Usually it shows neither, and then the method's record of the same
    placebo on the campaigns read out so far has to vouch for it.
    """
    own_state = band_state(own.low, own.high, tolerance)
    if own_state == "outside":
        return False, "OWN_OUTSIDE", None
    if own_state == "within":
        return True, "OWN_WITHIN", "own_placebo"
    if record.state == "certified":
        return True, "RECORD_CERTIFIED", "method_record"
    return (
        False,
        {"too_few": "RECORD_TOO_FEW", "bias": "RECORD_BIAS", "not_certified": "RECORD_NOT_CERTIFIED"}[record.state],
        None,
    )


_WORDS = {
    "OWN_OUTSIDE": "the readout's own placebo lies beyond the tolerance",
    "OWN_WITHIN": "the readout's own placebo lies within the tolerance",
    "RECORD_CERTIFIED": "the method's record keeps the placebo of a campaign of this programme within the tolerance",
    "RECORD_TOO_FEW": "the own placebo is inconclusive and the method's record is too short",
    "RECORD_BIAS": "the method's mean placebo over the campaigns so far lies beyond the tolerance",
    "RECORD_NOT_CERTIFIED": "the own placebo is inconclusive and the method's record does not bound it",
}


def _measurements(own: Interval, record: Record) -> dict:
    return {
        "placebo": own.estimate,
        "placebo_low": own.low,
        "placebo_high": own.high,
        "record": record.state,
        "record_campaigns": len(record.campaigns),
        "record_mean": record.mean.estimate if record.mean else None,
        "record_mean_low": record.mean.low if record.mean else None,
        "record_mean_high": record.mean.high if record.mean else None,
        "record_prediction_low": record.prediction_low,
        "record_prediction_high": record.prediction_high,
    }


def _thresholds(contract: Contract) -> dict:
    tol = contract.tolerances
    return {"placebo_usd": tol.placebo_usd, "min_record_campaigns": tol.min_record_campaigns}


def prehistory_gate(own: Interval, record: Record, contract: Contract) -> tuple[GateOutcome, str | None]:
    """Did the choice of households use something the adjustment set lacks?

    Households with the same values of the adjustment set are compared on what
    they spent before the history begins. If they were chosen on nothing but
    what the adjustment set holds, the targeted and the untargeted do not
    differ there. A difference means the choice used something else that is
    related to that spending.

    The test says nothing about the size of the readout's error. It cannot see
    a reason for the choice that left no trace in that window, and a choice
    made on that window's own spending shows up larger than the error it
    causes later.
    """
    passed, state, source = _evidence(own, record, contract.tolerances.placebo_usd)
    outcome = GateOutcome(
        gate="prehistory_placebo",
        passed=passed,
        code=None if passed else f"PREHISTORY_{state}",
        detail=_WORDS[state],
        measurements={**_measurements(own, record), "state": state},
        thresholds=_thresholds(contract),
    )
    return outcome, source


def assignment_gate(own: Interval, record: Record, contract: Contract) -> tuple[GateOutcome, str | None]:
    """Is there positive support for the assumption that the choice of households is accounted for?

    Two things can supply it. The first is knowledge: the rule that chose the
    households is documented and reads only what the adjustment set holds. The
    second is the shifted placebo, the whole analysis moved one window back,
    when it shows no effect: the method then predicted what the targeted
    households spent just before the launch.

    The shifted placebo is not a necessary condition. If the retailer chooses
    households on their latest spending, it fails although the readout, which
    adjusts for that spending, is sound. That is why a documented rule passes
    this gate without it.
    """
    passed, state, source = _evidence(own, record, contract.tolerances.placebo_usd)
    documented = contract.assignment.documented
    measurements = {**_measurements(own, record), "state": state, "documented": documented}
    if documented:
        detail = "the rule that chose the households is documented and reads only the adjustment set"
        return GateOutcome(
            gate="assignment", passed=True, detail=detail, measurements=measurements, thresholds=_thresholds(contract)
        ), "documented_rule"
    outcome = GateOutcome(
        gate="assignment",
        passed=passed,
        code=None if passed else f"ASSIGNMENT_UNDOCUMENTED_{state}",
        detail=("the rule is not documented, but " if passed else "the rule is not documented; ") + _WORDS[state],
        measurements=measurements,
        thresholds=_thresholds(contract),
    )
    return outcome, source
