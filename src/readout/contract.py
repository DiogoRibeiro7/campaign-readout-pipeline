"""The contract: the choices a readout depends on, declared before it runs.

A contract fixes the question (who, what treatment, what outcome, over which
days), the method, the data it may read and the tolerances its gates enforce.
It is a file under version control. The hash of its parsed content is stored
with every result, next to the version of the code, so a number can always be
traced to the rules it was produced under, and a change of rules is a change
to a file with a history, not an edit to a notebook cell.
"""

from __future__ import annotations

import hashlib
import json
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Source(Frozen):
    """Where the data come from, pinned to one commit and one hash per file."""

    repository: str
    commit: str = Field(min_length=40, max_length=40)
    files: dict[str, str]  # file name -> SHA-256

    def url(self, name: str) -> str:
        return f"https://raw.githubusercontent.com/{self.repository}/{self.commit}/data/{name}"


class Estimand(Frozen):
    """The question, in words. Not used in computation; it is what the numbers must answer."""

    population: str
    treatment: str
    outcome: str
    contrast: str


class Windows(Frozen):
    outcome_days: int = Field(gt=0)
    history_days: int = Field(gt=0)
    readout_latency_days: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _history_in_whole_windows(self) -> Windows:
        if self.history_days % self.outcome_days:
            raise ValueError("history_days must be a multiple of outcome_days: spending enters once per window")
        return self


Group = Literal["spend", "behaviour", "history"]
GROUPS: tuple[Group, ...] = ("spend", "behaviour", "history")


class Covariates(Frozen):
    """What enters the adjustment set.

    ``groups`` names the covariate groups in the adjustment set: "spend" (what
    the household spent in each window of the history), "behaviour" (trips,
    stores, private-label and discount shares, coupons, recency) and "history"
    (the other campaigns the household was sent).

    Everything a household did is measured before the launch; no contract can
    change that. ``concurrent_campaigns`` is about what the retailer did. With
    ``through_outcome_window`` the other campaigns a household was sent that
    are live at some point in the outcome window are counted, including those
    that start during it. That treats the campaign calendar as the retailer's
    plan, not as a consequence of what the household did after this launch,
    and it keeps the effects of those campaigns out of this one's estimate.
    With ``at_launch`` only the campaigns already running on the launch day
    are counted, and the estimate includes whatever else the retailer went on
    to send the same households during the window.
    """

    groups: tuple[Group, ...] = GROUPS
    concurrent_campaigns: Literal["through_outcome_window", "at_launch"] = "through_outcome_window"

    @model_validator(mode="after")
    def _groups_are_distinct(self) -> Covariates:
        if not self.groups or len(set(self.groups)) != len(self.groups):
            raise ValueError("groups must name at least one covariate group, each once")
        return self

    @property
    def dropped(self) -> tuple[str, ...]:
        """The covariate groups the adjustment set leaves out."""
        return tuple(group for group in GROUPS if group not in self.groups)


class Method(Frozen):
    estimator: Literal["regression", "weighting"]

    @property
    def name(self) -> str:
        return self.estimator


class Assignment(Frozen):
    """What is known about how the households were chosen.

    If the rule that chose them is documented, and everything it reads is in
    the adjustment set, the method's central assumption holds by construction.
    If it is not documented, the assumption has to be supported by evidence,
    and the contract says so by setting ``documented = false``.
    ``inputs`` names the covariate groups the rule reads: "spend", "behaviour"
    or "history".
    """

    documented: bool
    inputs: tuple[Group, ...] = ()
    note: str = ""

    @model_validator(mode="after")
    def _documented_rules_name_their_inputs(self) -> Assignment:
        if self.documented and not self.inputs:
            raise ValueError("a documented assignment rule must name the covariate groups it reads")
        return self


class Tolerances(Frozen):
    """The thresholds the gates enforce. Stated in advance so that a gate can be failed.

    ``placebo_usd`` is the largest placebo effect that is treated as none. It
    is a statement about the placebos, on which the true effect is zero. It is
    not a bound on the bias of the readout, which no placebo measures.
    """

    placebo_usd: float = Field(gt=0)
    min_treated: int = Field(gt=0)
    min_controls: int = Field(gt=0)
    min_effective_controls: float = Field(gt=0)
    max_control_weight_share: float = Field(gt=0, le=1)
    extreme_score: float = Field(gt=0.5, lt=1)
    max_treated_extreme_share: float = Field(ge=0, le=1)
    min_record_campaigns: int = Field(ge=3)
    interval_level: float = Field(default=0.95, gt=0.5, lt=1)
    heterogeneity_level: float = Field(default=0.95, gt=0.5, lt=1)


class Bootstrap(Frozen):
    replications: int = Field(ge=2)
    seed: int


class DataRules(Frozen):
    """What a healthy feed looks like. ``closed_days`` are month-day strings with no sales."""

    closed_days: tuple[str, ...] = ()


class Contract(Frozen):
    name: str
    version: int
    estimand: Estimand
    source: Source
    windows: Windows
    covariates: Covariates
    assignment: Assignment
    method: Method
    shadow_methods: tuple[Method, ...] = ()
    tolerances: Tolerances
    bootstrap: Bootstrap
    data: DataRules = DataRules()

    @model_validator(mode="after")
    def _documented_rule_is_adjusted_for(self) -> Contract:
        missing = [group for group in self.assignment.inputs if group not in self.covariates.groups]
        if self.assignment.documented and missing:
            raise ValueError(
                f"the documented assignment rule reads {missing}, which the adjustment set does not hold: "
                "the estimate would be confounded by construction"
            )
        return self

    @property
    def methods(self) -> tuple[Method, ...]:
        """The primary method followed by the shadow methods, without repeats."""
        seen: dict[str, Method] = {}
        for method in (self.method, *self.shadow_methods):
            seen.setdefault(method.name, method)
        return tuple(seen.values())

    @property
    def sha256(self) -> str:
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @property
    def tag(self) -> str:
        return f"{self.name}@v{self.version}:{self.sha256[:12]}"


def load_contract(path: str | Path) -> Contract:
    return Contract.model_validate(tomllib.loads(Path(path).read_text(encoding="utf-8")))
