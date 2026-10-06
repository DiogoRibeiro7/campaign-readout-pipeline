"""What a readout hands to its consumers: a published estimate or a refusal.

The two are different types. A refusal has no field for an effect estimate, so
code that reads results cannot pick up a number from a readout that was not
allowed to publish one; it has to handle the refusal. What a refusal does
carry is the list of gates, with what each measured and what it required.
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

Scalar = float | int | str | bool | None


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Interval(Frozen):
    estimate: float
    low: float
    high: float
    se: float


class GateOutcome(Frozen):
    """One gate: what it measured, what it required, and whether that was met."""

    gate: str
    passed: bool
    code: str | None = None  # machine-readable reason when the gate fails
    detail: str
    measurements: dict[str, Scalar] = {}
    thresholds: dict[str, Scalar] = {}


class Record(Frozen):
    """What a method's placebos on the campaigns read out so far say about it."""

    state: Literal["certified", "too_few", "bias", "not_certified"]
    campaigns: tuple[int, ...]
    mean: Interval | None  # mean placebo estimate across the campaigns
    heterogeneity_sd: float | None  # estimated standard deviation of the placebo effect between campaigns
    heterogeneity_upper: float | None  # upper confidence bound for it
    prediction_low: float | None  # range expected to hold the placebo effect of a campaign of the programme
    prediction_high: float | None


class Provenance(Frozen):
    contract: str
    contract_sha256: str
    snapshot_id: str
    view_id: str
    code_version: str


Evidence = Literal["own_placebo", "method_record"]


class Published(Frozen):
    kind: Literal["published"] = "published"
    campaign_id: int
    launch: dt.date
    as_of: dt.date
    method: str
    effect_unit: str
    households_treated: int
    households_compared: int
    effect: Interval
    prehistory_placebo: Interval
    shifted_placebo: Interval
    prehistory_evidence: Evidence
    assignment_evidence: Evidence | Literal["documented_rule"]
    prehistory_record: Record
    shifted_record: Record
    diagnostics: dict[str, Scalar]
    gates: tuple[GateOutcome, ...]
    provenance: Provenance


class Refused(Frozen):
    kind: Literal["refused"] = "refused"
    campaign_id: int
    launch: dt.date
    as_of: dt.date
    method: str
    reasons: tuple[GateOutcome, ...]  # the gates that failed
    gates: tuple[GateOutcome, ...]  # every gate that was evaluated
    provenance: Provenance


Result = Annotated[Published | Refused, Field(discriminator="kind")]
RESULT = TypeAdapter(Result)


class ProgrammePublished(Frozen):
    kind: Literal["programme_published"] = "programme_published"
    as_of: dt.date
    method: str
    effect_unit: str
    campaigns: tuple[int, ...]
    effect: Interval  # mean effect across the campaigns
    prehistory_placebo: Interval  # mean placebos across the same campaigns
    shifted_placebo: Interval
    assignment_evidence: Literal["documented_rule", "pooled_placebo"]
    provenance: Provenance


class ProgrammeRefused(Frozen):
    kind: Literal["programme_refused"] = "programme_refused"
    as_of: dt.date
    method: str
    campaigns: tuple[int, ...]
    reasons: tuple[GateOutcome, ...]
    provenance: Provenance


ProgrammeResult = Annotated[ProgrammePublished | ProgrammeRefused, Field(discriminator="kind")]
PROGRAMME_RESULT = TypeAdapter(ProgrammeResult)


def json_schemas() -> dict[str, dict]:
    """JSON Schema of each thing the pipeline publishes, by name."""
    return {"readout": RESULT.json_schema(), "programme": PROGRAMME_RESULT.json_schema()}
