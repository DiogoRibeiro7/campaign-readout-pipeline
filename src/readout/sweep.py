"""Re-read stored readouts under other rules, without recomputing anything.

Every gate compares a stored measurement with a threshold, so the verdict a
readout would have received at another tolerance, or with a documented
assignment rule, follows from the audit trail. Two questions are answered this
way: how the verdicts change as the tolerance is relaxed, and what the
smallest tolerance is at which a readout could have been published. The second
is a property of the data and the method: the tightest bound the evidence puts
on the size of the placebo effect.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .certificate import band_state, record_state

PRECONDITIONS = ("data", "timing", "estimator", "overlap")
_RECORD_CODE = {"too_few": "RECORD_TOO_FEW", "bias": "RECORD_BIAS", "not_certified": "RECORD_NOT_CERTIFIED"}


def _precondition_failed(row: pd.Series | dict) -> bool:
    return any(gate in PRECONDITIONS for gate in row["failed_gates"])


def evidence_at(own: dict, record: dict, tolerance: float, min_record_campaigns: int) -> tuple[bool, str]:
    """Whether one placebo shows a negligible effect at the given tolerance, and the state it is in."""
    state = band_state(own["low"], own["high"], tolerance)
    if state == "outside":
        return False, "OWN_OUTSIDE"
    if state == "within":
        return True, "OWN_WITHIN"
    mean = record["mean"] or {}
    verdict = record_state(
        len(record["campaigns"]),
        mean.get("low"),
        mean.get("high"),
        record["prediction_low"],
        record["prediction_high"],
        tolerance,
        min_record_campaigns,
    )
    if verdict == "certified":
        return True, "RECORD_CERTIFIED"
    return False, _RECORD_CODE[verdict]


def verdict_at(
    row: pd.Series | dict, tolerance: float, min_record_campaigns: int, documented: bool | None = None
) -> tuple[str, tuple[str, ...]]:
    """Verdict and reason codes of one audit row at the given tolerance.

    ``documented`` overrides what the contract said about the assignment rule.
    """
    if _precondition_failed(row):
        return "refused", tuple(row["codes"][:1])
    documented = bool(row["documented"]) if documented is None else documented
    codes = []
    passed, state = evidence_at(
        row["prehistory_placebo"], row["prehistory_placebo_record"], tolerance, min_record_campaigns
    )
    if not passed:
        codes.append(f"PREHISTORY_{state}")
    if not documented:
        passed, state = evidence_at(
            row["shifted_placebo"], row["shifted_placebo_record"], tolerance, min_record_campaigns
        )
        if not passed:
            codes.append(f"ASSIGNMENT_UNDOCUMENTED_{state}")
    return ("refused" if codes else "published"), tuple(codes)


def evidence_tolerance(own: dict, record: dict, min_record_campaigns: int) -> float:
    """Smallest tolerance at which one placebo shows a negligible effect.

    The readout's own interval does it once the band contains it. The method's
    record does it once the band contains the range it gives for a campaign of
    the programme, provided the own interval does not lie beyond the band.
    """
    own_inside = max(abs(own["low"]), abs(own["high"]))
    if record["prediction_low"] is None or len(record["campaigns"]) < max(min_record_campaigns, 3):
        return float(own_inside)
    record_inside = max(abs(record["prediction_low"]), abs(record["prediction_high"]))
    own_not_beyond = max(own["low"], -own["high"], 0.0)
    return float(min(own_inside, max(record_inside, own_not_beyond)))


def smallest_tolerance(row: pd.Series | dict, min_record_campaigns: int, documented: bool | None = None) -> float:
    """Smallest tolerance at which the readout would have been published; infinite if none."""
    if _precondition_failed(row):
        return float("inf")
    documented = bool(row["documented"]) if documented is None else documented
    needed = [evidence_tolerance(row["prehistory_placebo"], row["prehistory_placebo_record"], min_record_campaigns)]
    if not documented:
        needed.append(evidence_tolerance(row["shifted_placebo"], row["shifted_placebo_record"], min_record_campaigns))
    return float(max(needed))


def sweep(audit: pd.DataFrame, tolerances: list[float], min_record_campaigns: int) -> pd.DataFrame:
    """Number of readouts published and refused, by method, shift, assignment rule and tolerance."""
    rows = []
    for (method, shift), group in audit.groupby(["method", "shift"], sort=False):
        for documented in (False, True):
            for tolerance in tolerances:
                verdicts = [verdict_at(row, tolerance, min_record_campaigns, documented) for _, row in group.iterrows()]
                codes = [code for _, reasons in verdicts for code in reasons]

                def count(prefix: str, codes=codes) -> int:
                    return int(sum(code.startswith(prefix) for code in codes))

                rows.append(
                    {
                        "method": method,
                        "shift": shift,
                        "assignment_documented": documented,
                        "tolerance_usd": tolerance,
                        "readouts": len(group),
                        "published": int(np.sum([v == "published" for v, _ in verdicts])),
                        "refused_before_estimation": count("DATA") + count("TIMING") + count("ESTIMATOR"),
                        "refused_for_overlap": count("OVERLAP"),
                        "failing_prehistory_placebo": count("PREHISTORY"),
                        "failing_assignment": count("ASSIGNMENT"),
                    }
                )
    return pd.DataFrame(rows)
