"""The programme readout: the mean effect over the campaigns read out so far.

A single campaign is usually too small for its own placebos to show anything.
The campaigns together are larger. The programme readout takes the campaigns
whose data, timing and overlap gates passed, each counting once whatever its
size, and averages them. It is published under the same two conditions as a
campaign readout, applied to the pooled placebos: the pooled pre-history
placebo must lie within the tolerance, and either the assignment rule is
documented or the pooled shifted placebo lies within the tolerance too.

It is a statement about the campaigns that could be estimated. Campaigns
refused for data or overlap are not in it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import __version__
from .certificate import band_state, pooled_mean
from .contract import Contract, Method
from .pipeline import PLACEBOS
from .registry import Registry
from .result import GateOutcome, Interval, ProgrammePublished, ProgrammeRefused, Provenance

_STATE_CODE = {"outside": "POOLED_OUTSIDE", "inconclusive": "POOLED_INCONCLUSIVE"}
_STATE_WORDS = {
    "within": "the mean placebo across campaigns lies within the tolerance",
    "outside": "the mean placebo across campaigns lies beyond the tolerance",
    "inconclusive": "the mean placebo across campaigns is not shown to lie within the tolerance",
}


def _measurements(pooled: Interval, state: str, campaigns: int) -> dict:
    return {
        "campaigns": campaigns,
        "placebo": pooled.estimate,
        "placebo_low": pooled.low,
        "placebo_high": pooled.high,
        "state": state,
    }


def programme_readout(
    registry: Registry, contract: Contract, method: Method, as_of: pd.Timestamp, snapshot_id: str, shift: int = 0
) -> ProgrammePublished | ProgrammeRefused:
    tol = contract.tolerances
    rows = registry.valid_units(contract, method, shift)
    rows = rows[rows["as_of"] <= str(as_of.date())] if not rows.empty else rows
    campaigns = tuple(int(c) for c in rows["campaign"]) if not rows.empty else ()
    thresholds = {"placebo_usd": tol.placebo_usd, "min_record_campaigns": tol.min_record_campaigns}
    provenance = Provenance(
        contract=contract.tag,
        contract_sha256=contract.sha256,
        snapshot_id=snapshot_id,
        view_id=f"{snapshot_id}@{as_of.date()}",
        code_version=__version__,
    )

    def refuse(reasons: list[GateOutcome]) -> ProgrammeRefused:
        return ProgrammeRefused(
            as_of=as_of.date(), method=method.name, campaigns=campaigns, reasons=tuple(reasons), provenance=provenance
        )

    if len(campaigns) < tol.min_record_campaigns:
        return refuse(
            [
                GateOutcome(
                    gate="data",
                    passed=False,
                    code="PROGRAMME_TOO_FEW",
                    detail=f"{len(campaigns)} campaigns with valid placebos, fewer than {tol.min_record_campaigns}",
                    measurements={"campaigns": len(campaigns)},
                    thresholds=thresholds,
                )
            ]
        )

    stored = [registry.draws(key) for key in rows["key"]]
    pooled = {
        role: pooled_mean(
            np.column_stack([s[role] for s in stored]),
            np.array([row["estimate"] for row in rows[role]]),
            tol.interval_level,
        )
        for role in ("effect", *PLACEBOS)
    }
    states = {placebo: band_state(pooled[placebo].low, pooled[placebo].high, tol.placebo_usd) for placebo in PLACEBOS}

    pre_state = states["prehistory_placebo"]
    outcomes = [
        GateOutcome(
            gate="prehistory_placebo",
            passed=pre_state == "within",
            code=None if pre_state == "within" else f"PREHISTORY_{_STATE_CODE[pre_state]}",
            detail=_STATE_WORDS[pre_state],
            measurements=_measurements(pooled["prehistory_placebo"], pre_state, len(campaigns)),
            thresholds=thresholds,
        )
    ]
    shifted_state = states["shifted_placebo"]
    documented = contract.assignment.documented
    measurements = {**_measurements(pooled["shifted_placebo"], shifted_state, len(campaigns)), "documented": documented}
    if documented:
        outcomes.append(
            GateOutcome(
                gate="assignment",
                passed=True,
                detail="the rule that chose the households is documented and reads only the adjustment set",
                measurements=measurements,
                thresholds=thresholds,
            )
        )
    else:
        outcomes.append(
            GateOutcome(
                gate="assignment",
                passed=shifted_state == "within",
                code=None if shifted_state == "within" else f"ASSIGNMENT_UNDOCUMENTED_{_STATE_CODE[shifted_state]}",
                detail=(
                    "the rule is not documented, but " if shifted_state == "within" else "the rule is not documented; "
                )
                + _STATE_WORDS[shifted_state],
                measurements=measurements,
                thresholds=thresholds,
            )
        )
    failed = [o for o in outcomes if not o.passed]
    if failed:
        return refuse(failed)
    return ProgrammePublished(
        as_of=as_of.date(),
        method=method.name,
        effect_unit=f"US dollars per targeted household over {contract.windows.outcome_days} days, mean across campaigns",
        campaigns=campaigns,
        effect=pooled["effect"],
        prehistory_placebo=pooled["prehistory_placebo"],
        shifted_placebo=pooled["shifted_placebo"],
        assignment_evidence="documented_rule" if documented else "pooled_placebo",
        provenance=provenance,
    )
