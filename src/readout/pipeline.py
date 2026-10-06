"""One readout: from a view and a contract to a published estimate or a refusal."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import __version__, gates
from .bootstrap import HouseholdBootstrap, interval
from .certificate import method_record
from .contract import Contract, Method
from .estimators import ESTIMATORS, EstimatorError, Overlap, overlap
from .features import ROLES, Problem, build_problem, members, seen_before
from .result import GateOutcome, Interval, Provenance, Published, Record, Refused
from .snapshot import View

PLACEBOS = ("prehistory_placebo", "shifted_placebo")
OVERLAP_ROLES = ("effect", "shifted_placebo")  # the pre-history placebo shares the effect's households and covariates


@dataclass(frozen=True)
class Unit:
    """What is read out: a campaign, at its launch or, in an audit, some windows before it."""

    campaign: int
    launch: pd.Timestamp
    campaign_type: str
    shift: int = 0  # windows before the launch; 0 is the real readout

    def anchor(self, window: int) -> pd.Timestamp:
        return self.launch - pd.Timedelta(days=self.shift * window)

    def readout_day(self, contract: Contract) -> pd.Timestamp:
        w = contract.windows
        return self.anchor(w.outcome_days) + pd.Timedelta(days=w.outcome_days + w.readout_latency_days)


@dataclass(frozen=True)
class RecordEntry:
    """An earlier unit's placebo for one method, with its aligned bootstrap draws."""

    campaign: int
    estimate: float
    draws: np.ndarray


History = dict[str, list[RecordEntry]]  # placebo -> the entries of the units read out before


@dataclass
class Assessment:
    """Everything one readout established, including what it is not allowed to publish."""

    unit: Unit
    method: Method
    as_of: pd.Timestamp
    result: Published | Refused
    gates: list[GateOutcome]
    treated: int
    controls: int
    estimates: dict[str, Interval] = field(default_factory=dict)  # internal: by role, whenever computed
    draws: dict[str, np.ndarray] = field(default_factory=dict)
    records: dict[str, Record] = field(default_factory=dict)  # by placebo
    diagnostics: dict = field(default_factory=dict)
    valid_placebo: bool = False  # data, timing and overlap passed: the placebos may enter the method's record

    @property
    def published(self) -> bool:
        return isinstance(self.result, Published)


class Workbench:
    """Problems, estimates and bootstrap draws for one unit, computed once and shared between methods.

    A bench needs its view only to build problems. A replay that keeps benches
    for later sets ``view`` to None in between, so that a year of benches does
    not hold a year of views in memory.
    """

    def __init__(
        self,
        view: View,
        unit: Unit,
        contract: Contract,
        boot: HouseholdBootstrap,
        member_ids: np.ndarray | None = None,
    ) -> None:
        self.view: View | None = view
        self.unit, self.contract, self.boot = unit, contract, boot
        if member_ids is None:
            member_ids = view.campaigns.loc[view.campaigns["campaign_id"] == unit.campaign, "household_id"].to_numpy()
        self.member_ids = np.asarray(member_ids)
        population = seen_before(view, unit.anchor(contract.windows.outcome_days))
        self.treated = int(members(view, unit.campaign, population, self.member_ids).sum())
        self.controls = int(len(population) - self.treated)
        self._problems: dict[str, Problem] = {}
        self._estimates: dict[tuple[str, str], tuple[float, np.ndarray]] = {}
        self._overlaps: dict[str, Overlap] = {}
        self._shifts: dict[str, float] = {}

    @staticmethod
    def key(view: View, unit: Unit, contract: Contract) -> tuple:
        """Everything the numbers on a bench depend on. Contracts that agree on it can share one."""
        c = contract
        return (view.view_id, unit, c.windows, c.covariates, c.tolerances.extreme_score, c.bootstrap)

    def problem(self, role: str) -> Problem:
        if role not in self._problems:
            if self.view is None:
                raise RuntimeError("the bench has been detached from its view and cannot build new problems")
            w, c = self.contract.windows, self.contract.covariates
            self._problems[role] = build_problem(
                self.view,
                self.unit.campaign,
                self.unit.anchor(w.outcome_days),
                role,
                w.outcome_days,
                w.history_days,
                c.concurrent_campaigns,
                member_ids=self.member_ids,
                drop=c.dropped,
            )
        return self._problems[role]

    def estimate(self, estimator: str, role: str) -> tuple[float, np.ndarray]:
        key = (estimator, role)
        if key not in self._estimates:
            p = self.problem(role)
            function = ESTIMATORS[estimator]
            self._estimates[key] = (function(p.y, p.d, p.x), self.boot.draws(function, p.y, p.d, p.x, p.households))
        return self._estimates[key]

    def overlap(self, role: str) -> Overlap:
        if role not in self._overlaps:
            p = self.problem(role)
            self._overlaps[role] = overlap(p.d, p.x, self.contract.tolerances.extreme_score)
        return self._overlaps[role]

    def largest_shift(self, estimator: str) -> float:
        """How far leaving one household out can move the estimate of the effect."""
        if estimator not in self._shifts:
            p = self.problem("effect")
            self._shifts[estimator] = ESTIMATORS[estimator].largest_shift(p.y, p.d, p.x)
        return self._shifts[estimator]


def _interval(estimate: float, draws: np.ndarray, level: float) -> Interval:
    low, high = interval(draws, level)
    return Interval(estimate=float(estimate), low=low, high=high, se=float(draws.std(ddof=1)))


def _provenance(contract: Contract, snapshot_id: str, view_id: str) -> Provenance:
    return Provenance(
        contract=contract.tag,
        contract_sha256=contract.sha256,
        snapshot_id=snapshot_id,
        view_id=view_id,
        code_version=__version__,
    )


def assess(
    view: View,
    unit: Unit,
    contract: Contract,
    method: Method,
    boot: HouseholdBootstrap,
    history: History,
    member_ids: np.ndarray | None = None,
    bench: Workbench | None = None,
) -> Assessment:
    """Run the gates in order. A readout is published only if all of them pass.

    The data, timing and overlap gates are preconditions for computing
    anything worth judging, so the first of them to fail ends the readout. The
    two placebo gates are both evaluated, so that a refusal names every reason.

    ``history`` holds, for each placebo, the valid estimates of the units read
    out before this one under the same contract and method.
    """
    bench = bench or Workbench(view, unit, contract, boot, member_ids)
    w, tol = contract.windows, contract.tolerances
    treated, controls = bench.treated, bench.controls
    provenance = _provenance(contract, view.snapshot_id, view.view_id)
    outcomes: list[GateOutcome] = []

    def refuse(**extra) -> Assessment:
        result = Refused(
            campaign_id=unit.campaign,
            launch=unit.launch.date(),
            as_of=view.as_of.date(),
            method=method.name,
            reasons=tuple(o for o in outcomes if not o.passed),
            gates=tuple(outcomes),
            provenance=provenance,
        )
        return Assessment(unit, method, view.as_of, result, outcomes, treated, controls, **extra)

    outcomes.append(gates.data_gate(view, unit.anchor(w.outcome_days), treated, controls, contract))
    if not outcomes[-1].passed:
        return refuse()

    outcomes.append(gates.timing_gate(view, [bench.problem(role) for role in ROLES], contract))
    if not outcomes[-1].passed:
        return refuse()

    try:
        parts = {role: bench.estimate(method.estimator, role) for role in ROLES}
        scores = {role: bench.overlap(role) for role in OVERLAP_ROLES}
        largest_shift = bench.largest_shift(method.estimator)
    except EstimatorError as error:
        outcomes.append(GateOutcome(gate="estimator", passed=False, code="ESTIMATOR_FAILED", detail=str(error)))
        return refuse()
    estimates = {role: _interval(*parts[role], tol.interval_level) for role in ROLES}
    draws = {role: parts[role][1] for role in ROLES}
    diagnostics = {
        "auc": scores["effect"].auc,
        "effective_controls": scores["effect"].effective_controls,
        "largest_weight_share": scores["effect"].largest_weight_share,
        "treated_extreme_share": scores["effect"].treated_extreme_share,
        "largest_shift_from_one_household": largest_shift,
    }
    computed = {"estimates": estimates, "draws": draws, "diagnostics": diagnostics}

    outcomes.append(gates.overlap_gate(scores, contract, method))
    if not outcomes[-1].passed:
        return refuse(**computed)

    records = {}
    for placebo in PLACEBOS:
        entries = [*history.get(placebo, []), RecordEntry(unit.campaign, estimates[placebo].estimate, draws[placebo])]
        records[placebo] = method_record(
            [e.campaign for e in entries],
            np.array([e.estimate for e in entries]),
            np.column_stack([e.draws for e in entries]),
            tol.placebo_usd,
            tol.min_record_campaigns,
            tol.interval_level,
            tol.heterogeneity_level,
        )
    prehistory, prehistory_evidence = gates.prehistory_gate(
        estimates["prehistory_placebo"], records["prehistory_placebo"], contract
    )
    assignment, assignment_evidence = gates.assignment_gate(
        estimates["shifted_placebo"], records["shifted_placebo"], contract
    )
    outcomes += [prehistory, assignment]
    if not (prehistory.passed and assignment.passed):
        return refuse(**computed, records=records, valid_placebo=True)

    result = Published(
        campaign_id=unit.campaign,
        launch=unit.launch.date(),
        as_of=view.as_of.date(),
        method=method.name,
        effect_unit=f"US dollars per targeted household over {w.outcome_days} days",
        households_treated=treated,
        households_compared=controls,
        effect=estimates["effect"],
        prehistory_placebo=estimates["prehistory_placebo"],
        shifted_placebo=estimates["shifted_placebo"],
        prehistory_evidence=prehistory_evidence,
        assignment_evidence=assignment_evidence,
        prehistory_record=records["prehistory_placebo"],
        shifted_record=records["shifted_placebo"],
        diagnostics=diagnostics,
        gates=tuple(outcomes),
        provenance=provenance,
    )
    return Assessment(
        unit, method, view.as_of, result, outcomes, treated, controls, records=records, valid_placebo=True, **computed
    )


def refuse_without_feed(
    unit: Unit, contract: Contract, method: Method, snapshot_id: str, day: pd.Timestamp
) -> Assessment:
    """The refusal for a readout that falls due before the feed holds any data."""
    outcome = GateOutcome(
        gate="data",
        passed=False,
        code="DATA_NO_FEED",
        detail="the feed holds no data on the readout date",
        measurements={"as_of": str(day.date())},
    )
    result = Refused(
        campaign_id=unit.campaign,
        launch=unit.launch.date(),
        as_of=day.date(),
        method=method.name,
        reasons=(outcome,),
        gates=(outcome,),
        provenance=_provenance(contract, snapshot_id, f"{snapshot_id}@{day.date()}"),
    )
    return Assessment(unit, method, day, result, [outcome], 0, 0)
