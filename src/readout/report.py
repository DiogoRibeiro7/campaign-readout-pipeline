"""Tables and figures from the registry.

Everything quoted in the README or anywhere else is written here, into
``results/`` and ``figures/``, from what the pipeline recorded. Nothing is
estimated in this module except the comparison with the prototype and one
check on the pre-history placebo, both of which are point estimates on the
snapshot.

The tables show the estimates of refused readouts. That is the analyst's view
of the internal trail, there to explain the refusals. What a consumer would
receive is ``readouts.jsonl``, and it holds none of them.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from . import diagnostics, parity, planning, worlds  # noqa: E402
from .contract import Contract  # noqa: E402
from .features import ROLES  # noqa: E402
from .registry import Registry  # noqa: E402
from .result import RESULT  # noqa: E402
from .snapshot import Snapshot  # noqa: E402
from .sweep import smallest_tolerance, sweep  # noqa: E402

TOLERANCES = [5.0, 10.0, 20.0, 30.0, 40.0, 50.0, 75.0, 100.0]
INK, MUTED, BAND = "#1f2933", "#9aa5b1", "#e4e7eb"
COLOURS = {"effect": "#1f2933", "prehistory_placebo": "#c2410c", "shifted_placebo": "#0f766e"}
LABELS = {
    "effect": "Estimate, window from launch",
    "prehistory_placebo": "Pre-history placebo",
    "shifted_placebo": "Shifted placebo",
}
DRAWN = ("effect", "prehistory_placebo", "shifted_placebo")  # top to bottom within a row
OFFSETS = {"effect": 0.24, "prehistory_placebo": 0.0, "shifted_placebo": -0.24}
POOLED = diagnostics.POOLED


def _label(contract: Contract) -> str:
    return f"v{contract.version}"


# ---- tables --------------------------------------------------------------------------
def prototype_to_production(table: pd.DataFrame) -> pd.DataFrame:
    """Means over the prototype's campaigns, run the prototype's way and the pipeline's way."""
    rows = []
    for (window, estimator), group in table.groupby(["window", "estimator"], sort=False):
        rows.append(
            {
                "window": window,
                "estimator": estimator,
                "campaigns": len(group),
                "published_by_prototype": group["published"].mean(),
                "pipeline_as_prototype": group["prototype"].mean(),
                "data_as_of_readout": group["as_of"].mean(),
                "production_rules": group["production"].mean(),
                "largest_difference_from_published": float(np.abs(group["prototype"] - group["published"]).max()),
                "mean_change_from_data_as_of_readout": float(np.abs(group["as_of"] - group["prototype"]).mean()),
                "largest_change_from_data_as_of_readout": float(np.abs(group["as_of"] - group["prototype"]).max()),
                "mean_change_from_population_at_launch": float(np.abs(group["production"] - group["as_of"]).mean()),
                "largest_change_from_population_at_launch": float(np.abs(group["production"] - group["as_of"]).max()),
                "households_whole_year": int(group["households_prototype"].max()),
                "fewest_households_as_of_readout": int(group["households_as_of"].min()),
                "fewest_households_at_launch": int(group["households_production"].min()),
            }
        )
    return pd.DataFrame(rows)


def readouts_table(registry: Registry, contracts: list[Contract]) -> pd.DataFrame:
    """One row per readout of the real period, with what the pipeline measured and did not publish."""
    rows = []
    for contract in contracts:
        trail = registry.audit(contract)
        trail = trail[trail["shift"] == 0]
        k = contract.tolerances.min_record_campaigns
        for _, r in trail.iterrows():
            row = {
                "contract": _label(contract),
                "method": r["method"],
                "primary": bool(r["primary"]),
                "campaign": int(r["campaign"]),
                "campaign_type": r["campaign_type"],
                "launch": r["launch"],
                "as_of": r["as_of"],
                "targeted": int(r["treated"]),
                "comparison": int(r["controls"]),
                "verdict": r["verdict"],
                "reasons": " ".join(r["codes"]),
            }
            for role in ROLES:
                estimate = r[role] if isinstance(r[role], dict) else {}
                prefix = "internal_estimate" if role == "effect" else role
                for part in ("estimate", "low", "high", "se"):
                    row[prefix if part == "estimate" else f"{prefix}_{part}"] = estimate.get(part)
            diagnostic = r["diagnostics"] or {}
            for name in (
                "auc",
                "effective_controls",
                "largest_weight_share",
                "treated_extreme_share",
                "largest_shift_from_one_household",
            ):
                row[name] = diagnostic.get(name)
            row["smallest_tolerance_undocumented"] = smallest_tolerance(r, k, documented=False)
            row["smallest_tolerance_documented"] = smallest_tolerance(r, k, documented=True)
            rows.append(row)
    table = pd.DataFrame(rows)
    return table.sort_values(
        ["contract", "primary", "as_of", "campaign"], ascending=[True, False, True, True], ignore_index=True
    )


def pooled_table(registry: Registry, contracts: list[Contract]) -> pd.DataFrame:
    """Per contract, method and shift: the campaigns together, with the programme's last verdict."""
    parts = []
    for contract in contracts:
        shifts = tuple(sorted(int(s) for s in registry.audit(contract)["shift"].unique()))
        summary = diagnostics.pooled_by_shift(registry, contract, shifts)
        if summary.empty:
            continue
        programme = registry.programme(contract)
        verdicts, reasons = [], []
        for _, row in summary.iterrows():
            mine = (
                programme[(programme["method"] == row["method"]) & (programme["shift"] == row["shift"])]
                if not programme.empty
                else programme
            )
            last = mine.sort_values("as_of").iloc[-1] if len(mine) else None
            verdicts.append("" if last is None else "published" if last["kind"] == "programme_published" else "refused")
            reasons.append(
                ""
                if last is None or last["kind"] == "programme_published"
                else " ".join(x["code"] for x in last["reasons"])
            )
        summary.insert(0, "contract", _label(contract))
        summary.insert(1, "history_days", contract.windows.history_days)
        summary.insert(4, "primary", summary["method"] == contract.method.name)
        summary["programme_verdict"], summary["programme_reasons"] = verdicts, reasons
        parts.append(summary)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def _per_contract(function, contracts: list[Contract]) -> pd.DataFrame:
    parts = []
    for contract in contracts:
        part = function(contract)
        if not part.empty:
            part.insert(0, "contract", _label(contract))
            parts.append(part)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


# ---- figures -------------------------------------------------------------------------
def _style() -> None:
    plt.rcParams.update(
        {
            "font.size": 10,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.edgecolor": MUTED,
            "axes.labelcolor": INK,
            "xtick.color": INK,
            "ytick.color": INK,
            "text.color": INK,
            "figure.dpi": 150,
            "savefig.bbox": "tight",
            "legend.frameon": False,
        }
    )


def _clipped(ax, y: float, estimate: dict, colour: str, limit: float) -> None:
    """An interval with its point estimate; arrows where it runs off the axis."""
    low, high, mid = estimate["low"], estimate["high"], estimate["estimate"]
    ax.plot([max(low, -limit), min(high, limit)], [y, y], color=colour, lw=1.6, solid_capstyle="butt")
    if -limit <= mid <= limit:
        ax.plot([mid], [y], "o", color=colour, ms=4.5)
    if low < -limit:
        ax.plot([-limit], [y], marker="<", color=colour, ms=5, clip_on=False)
    if high > limit:
        ax.plot([limit], [y], marker=">", color=colour, ms=5, clip_on=False)


REASON_WORDS = {
    "DATA_NO_FEED": "no data yet",
    "DATA_INSUFFICIENT_HISTORY": "too little history",
    "DATA_TOO_FEW_TREATED": "too few targeted households",
    "DATA_TOO_FEW_CONTROLS": "too few comparison households",
    "DATA_OUTCOME_INCOMPLETE": "outcome window still open",
    "DATA_GAP": "gap in the feed",
    "OVERLAP_EXTREME_SCORES": "no comparable households",
    "OVERLAP_FEW_EFFECTIVE_CONTROLS": "too few comparable households",
    "OVERLAP_ONE_HOUSEHOLD_DOMINATES": "one comparison household dominates",
    "ESTIMATOR_FAILED": "estimator failed",
}


def _reason(codes: list[str]) -> str:
    if not codes:
        return "published"
    if codes[0] in REASON_WORDS:
        return "refused: " + REASON_WORDS[codes[0]]
    if codes[0].startswith("TIMING"):
        return "refused: timing"
    parts = []
    if any(code.startswith("PREHISTORY") for code in codes):
        parts.append("pre-history placebo")
    if any(code.startswith("ASSIGNMENT") for code in codes):
        parts.append("assignment")
    return "refused: " + " and ".join(parts)


def _legend(ax, tolerance: float, first: str | None = None) -> None:
    handles = [
        plt.Line2D([], [], color=COLOURS[role], marker="o", ms=4.5, lw=1.6, label=LABELS[role]) for role in DRAWN
    ]
    if first:
        handles[0].set_label(first)
    handles.append(plt.Rectangle((0, 0), 1, 1, color=BAND, label=f"Tolerance for placebos, ±${tolerance:g}"))
    ax.legend(handles=handles, loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=4, fontsize=8.5)


def figure_replay(path: Path, registry: Registry, contract: Contract, limit: float = 120.0) -> None:
    """The period as the pipeline lived it: every campaign in readout order, with the verdict it received."""
    trail = registry.audit(contract)
    trail = trail[(trail["shift"] == 0) & (trail["method"] == contract.method.name)].sort_values(["as_of", "campaign"])
    if trail.empty:
        return
    tolerance = contract.tolerances.placebo_usd
    fig, ax = plt.subplots(figsize=(9.5, 0.33 * len(trail) + 1.6))
    ax.axvspan(-tolerance, tolerance, color=BAND, zorder=0)
    ax.axvline(0, color=MUTED, lw=0.8, zorder=0)
    ticks = []
    for position, (_, row) in enumerate(trail.iterrows()):
        y = len(trail) - 1 - position
        ticks.append(f"{int(row['campaign'])} ({row['campaign_type'][-1]})  {row['as_of']}")
        for role in DRAWN:
            if isinstance(row[role], dict):
                _clipped(ax, y + OFFSETS[role], row[role], COLOURS[role], limit)
        ax.text(limit * 1.04, y, _reason(row["codes"]), va="center", fontsize=8.5, color=INK)
    ax.set_yticks(range(len(trail) - 1, -1, -1), ticks, fontsize=8.5)
    ax.set_xlim(-limit, limit)
    ax.set_ylim(-0.8, len(trail) - 0.2)
    ax.set_xlabel(f"US dollars per targeted household over {contract.windows.outcome_days} days")
    ax.set_ylabel("Campaign (type) and readout date")
    _legend(ax, tolerance, LABELS["effect"] + " (not published)")
    fig.savefig(path)
    plt.close(fig)


def figure_pooled(path: Path, pooled: pd.DataFrame, contracts: list[Contract]) -> None:
    """The campaigns together, by contract, method and window."""
    main = contracts[0]
    days = main.windows.outcome_days
    rows = pooled.sort_values(["contract", "primary", "shift"], ascending=[True, False, True])
    fig, ax = plt.subplots(figsize=(8.5, 0.5 * len(rows) + 1.6))
    ax.axvspan(-main.tolerances.placebo_usd, main.tolerances.placebo_usd, color=BAND, zorder=0)
    ax.axvline(0, color=MUTED, lw=0.8, zorder=0)
    ticks = []
    for position, (_, row) in enumerate(rows.iterrows()):
        y = len(rows) - 1 - position
        when = "at launch" if row["shift"] == 0 else f"anchored {int(row['shift']) * days} days before launch"
        ticks.append(f"{row['contract']}  {row['method']}  {when}")
        for role in DRAWN:
            name = POOLED[role]
            ax.plot(
                [row[name + "_low"], row[name + "_high"]],
                [y + OFFSETS[role]] * 2,
                color=COLOURS[role],
                lw=1.8,
                solid_capstyle="butt",
            )
            ax.plot([row[name]], [y + OFFSETS[role]], "o", color=COLOURS[role], ms=5)
    ax.set_yticks(range(len(rows) - 1, -1, -1), ticks, fontsize=8.5)
    ax.set_ylim(-0.7, len(rows) - 0.3)
    ax.set_xlabel(f"Mean across campaigns, US dollars per targeted household over {days} days")
    _legend(ax, main.tolerances.placebo_usd, "Estimate")
    fig.savefig(path)
    plt.close(fig)


WORLD_TITLES = {
    "random": "Households drawn at random",
    "observed": "Chosen on recent spending,\nwhich the adjustment set holds",
    "long_run": "Chosen on long-run spending,\nwhich it holds only in part",
    "foresight": "Chosen on what they are\nabout to spend",
}


def figure_worlds(path: Path, root: Path, stored: list, method: str, low: float = -15.0, high: float = 45.0) -> None:
    """Estimates against the known effect in each synthetic world, by what the gates decided.

    The axis is fixed; an interval or an estimate beyond it is drawn to the edge and marked with an arrow.
    """
    names = [name for name in WORLD_TITLES if any(world.name == name for world in stored)]
    if not names:
        return
    fig, axes = plt.subplots(2, len(names), figsize=(3.3 * len(names), 6.4), sharey="row", squeeze=False)
    for column, name in enumerate(names):
        mine = [world for world in stored if world.name == name]
        for line, rule in enumerate(worlds.RULES):
            ax = axes[line][column]
            ax.axhline(mine[0].effect, color=MUTED, lw=1.0, ls="--")
            position, published, total = 0, 0, 0
            for world in mine:
                trail = Registry(worlds.world_dir(root, world) / rule).audit()
                trail = trail[trail["method"] == method].sort_values("launch")
                for _, row in trail.iterrows():
                    position += 1
                    total += 1
                    if not isinstance(row["effect"], dict):
                        continue
                    passed = row["verdict"] == "published"
                    published += passed
                    colour = COLOURS["effect"] if passed else MUTED
                    effect = row["effect"]
                    ax.plot([position] * 2, [max(effect["low"], low), min(effect["high"], high)], color=colour, lw=1.2)
                    if low <= effect["estimate"] <= high:
                        ax.plot(
                            [position],
                            [effect["estimate"]],
                            "o",
                            color=colour,
                            ms=3.5,
                            mfc=colour if passed else "white",
                        )
                    if effect["low"] < low:
                        ax.plot([position], [low], marker="v", color=colour, ms=4, clip_on=False)
                    if effect["high"] > high:
                        ax.plot([position], [high], marker="^", color=colour, ms=4, clip_on=False)
                position += 1.5  # a gap between seeds
            count = f"{published} of {total} published"
            ax.set_title(f"{WORLD_TITLES[name]}\n\n{count}" if line == 0 else count, fontsize=9)
            ax.set_xticks([])
            ax.set_ylim(low, high)
            if column == 0:
                stated = "Assignment rule documented" if rule == "documented" else "Assignment rule not documented"
                ax.set_ylabel(f"{stated}\nUS dollars per targeted household", fontsize=9)
            if line == 1:
                ax.set_xlabel("Campaigns in readout order, seed by seed", fontsize=9)
    handles = [
        plt.Line2D([], [], color=COLOURS["effect"], marker="o", ms=4.5, lw=1.4, label="Published"),
        plt.Line2D(
            [], [], color=MUTED, marker="o", ms=4.5, mfc="white", lw=1.4, label="Refused (estimate kept internally)"
        ),
        plt.Line2D([], [], color=MUTED, ls="--", lw=1.0, label="True effect"),
    ]
    fig.legend(handles=handles, loc="lower center", bbox_to_anchor=(0.5, 0.98), ncol=3, fontsize=8.5)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def figure_planning(path: Path, plan: pd.DataFrame, contract: Contract) -> None:
    """How often the pooled placebos of an unbiased method would pass, by length of record."""
    rows = plan[(plan["method"] == contract.method.name) & (plan["true_mean_placebo"] == 0.0)]
    if rows.empty:
        return
    placebos = [p for p in ("prehistory_placebo", "shifted_placebo") if p in set(rows["placebo"])]
    fig, axes = plt.subplots(1, len(placebos), figsize=(4.2 * len(placebos), 3.5), sharey=True, squeeze=False)
    shades = [INK, COLOURS["shifted_placebo"], COLOURS["prehistory_placebo"]]
    for ax, placebo in zip(axes[0], placebos, strict=True):
        part = rows[rows["placebo"] == placebo]
        for colour, (correlation, line) in zip(shades, part.groupby("assumed_correlation"), strict=False):
            ax.plot(
                line["campaigns"],
                line["passes"],
                "o-",
                color=colour,
                ms=4,
                lw=1.5,
                label=f"Correlation between campaigns {correlation:g}",
            )
        ax.set_xscale("log")
        ticks = sorted(part["campaigns"].unique())
        ax.set_xticks(ticks, [str(k) for k in ticks])
        ax.minorticks_off()
        ax.set_title(LABELS[placebo], fontsize=9.5)
        ax.set_xlabel("Campaigns in the record")
        ax.set_ylim(-0.03, 1.03)
    axes[0][0].set_ylabel(
        f"Chance that the pooled placebo of an\nunbiased method lies within ±${contract.tolerances.placebo_usd:g}"
    )
    axes[0][-1].legend(fontsize=8, loc="upper left")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


# ---- the written summary -------------------------------------------------------------
def _md(frame: pd.DataFrame, digits: int = 2) -> str:
    """A Markdown table."""

    def cell(value) -> str:
        if value is None or value is pd.NA or (isinstance(value, float) and np.isnan(value)):
            return ""
        if isinstance(value, bool | np.bool_):
            return "yes" if value else "no"
        if isinstance(value, float | np.floating):
            return "none" if np.isinf(value) else f"{value:.{digits}f}"
        return str(value)

    header = "| " + " | ".join(str(c).replace("_", " ") for c in frame.columns) + " |"
    rule = "|" + "|".join(" --- " for _ in frame.columns) + "|"
    body = ["| " + " | ".join(cell(v) for v in row) + " |" for row in frame.itertuples(index=False)]
    return "\n".join([header, rule, *body])


def _ci(frame: pd.DataFrame, name: str, digits: int = 2) -> pd.Series:
    def text(r) -> str:
        if pd.isna(r[name]):
            return ""
        return f"{r[name]:.{digits}f} [{r[name + '_low']:.{digits}f}, {r[name + '_high']:.{digits}f}]"

    return frame.apply(text, axis=1)


def _window(shift: int, days: int) -> str:
    return "at launch" if shift == 0 else f"anchored {days * int(shift)} days before launch"


def results_markdown(
    tables: dict[str, pd.DataFrame], contracts: list[Contract], snapshot: Snapshot, world_notes: list[dict]
) -> str:
    main = contracts[0]
    tol, days = main.tolerances, main.windows.outcome_days
    out = ["# Results", "", "Written by `readout report` from the registry. Do not edit by hand.", ""]
    out += [
        "The tables show estimates of refused readouts. They come from the internal audit trail and are here to explain the refusals. "
        "What a consumer would receive is in `readouts.jsonl`.",
        "",
        "## Data and contracts",
        "",
        f"Snapshot `{snapshot.snapshot_id}`: {snapshot.manifest['households']:,} households, "
        f"{snapshot.manifest['rows']['daily']:,} household-days with a purchase, {snapshot.first_day.date()} to {snapshot.last_day.date()}, "
        f"{len(snapshot.tables['descriptions'])} campaigns.",
        "",
    ]
    for contract in contracts:
        t = contract.tolerances
        out.append(
            f"- `{contract.tag}`: history {contract.windows.history_days} days, outcome {contract.windows.outcome_days} days, "
            f"primary method {contract.method.name}, tolerance for placebos ${t.placebo_usd:g}, {contract.bootstrap.replications} bootstrap replications, "
            f"assignment rule {'documented' if contract.assignment.documented else 'not documented'}."
        )
    out.append("")

    p2p = tables["prototype_to_production"]
    if not p2p.empty:
        out += [
            "## From the prototype to production rules",
            "",
            f"Mean estimate over the prototype's {int(p2p['campaigns'].max())} campaigns, in US dollars per targeted household. "
            "`published by prototype` is the prototype's own output; `pipeline as prototype` is this code given the prototype's inputs and choices; "
            "`data as of readout` restricts the data to what existed on the readout date; "
            "`production rules` also restricts the households to those that had shopped before the day the covariates are dated.",
            "",
            _md(
                p2p[
                    [
                        "window",
                        "estimator",
                        "campaigns",
                        "published_by_prototype",
                        "pipeline_as_prototype",
                        "data_as_of_readout",
                        "production_rules",
                    ]
                ]
            ),
            "",
            f"Largest difference between the prototype's published numbers and the pipeline run the prototype's way: {p2p['largest_difference_from_published'].max():.2g}.",
            "",
            "How much each of the two changes moves one campaign's estimate, in absolute value:",
            "",
            _md(
                p2p[
                    [
                        "window",
                        "estimator",
                        "mean_change_from_data_as_of_readout",
                        "largest_change_from_data_as_of_readout",
                        "mean_change_from_population_at_launch",
                        "largest_change_from_population_at_launch",
                    ]
                ]
            ),
            "",
            f"Households an analysis runs on: {p2p['households_whole_year'].max():,} in the whole year, as few as {p2p['fewest_households_as_of_readout'].min():,} seen by a readout date "
            f"and {p2p['fewest_households_at_launch'].min():,} seen before the day the covariates are dated (the smallest is a shifted placebo's). "
            "The weighting rows include the Type A campaigns, for which weighting has almost no comparable households; the pipeline refuses those at the overlap gate.",
            "",
        ]

    readouts = tables["audit_readouts"]
    out += [] if readouts.empty else ["## The period, read out campaign by campaign", ""]
    for contract in [] if readouts.empty else contracts:
        mine = readouts[(readouts["contract"] == _label(contract)) & readouts["primary"]]
        if mine.empty:
            continue
        counts = mine["verdict"].value_counts()
        gates_failed = {
            "data": mine["reasons"].str.contains("DATA_").sum(),
            "timing": mine["reasons"].str.contains("TIMING_").sum(),
            "estimator": mine["reasons"].str.contains("ESTIMATOR_").sum(),
            "overlap": mine["reasons"].str.contains("OVERLAP_").sum(),
            "pre-history placebo": mine["reasons"].str.contains("PREHISTORY_").sum(),
            "assignment": mine["reasons"].str.contains("ASSIGNMENT_").sum(),
        }
        out += [
            f"### Contract {_label(contract)}, primary method ({contract.method.name})",
            "",
            f"{len(mine)} readouts fell due by the end of the snapshot: {int(counts.get('published', 0))} published, {int(counts.get('refused', 0))} refused. "
            "Readouts failing each gate (a readout that reaches the two placebo gates can fail both): "
            + ", ".join(f"{name} {int(count)}" for name, count in gates_failed.items())
            + ".",
            "",
            _md(mine[["campaign", "campaign_type", "launch", "as_of", "targeted", "comparison", "verdict", "reasons"]]),
            "",
        ]
        estimated = mine[mine["internal_estimate"].notna()].copy()
        if len(estimated):
            estimated["estimate (not published)"] = _ci(estimated, "internal_estimate", 1)
            estimated["pre-history placebo"] = _ci(estimated, "prehistory_placebo", 1)
            estimated["shifted placebo"] = _ci(estimated, "shifted_placebo", 1)
            keep = [
                "campaign",
                "estimate (not published)",
                "pre-history placebo",
                "shifted placebo",
                "treated_extreme_share",
                "effective_controls",
                "largest_weight_share",
                "largest_shift_from_one_household",
                "smallest_tolerance_undocumented",
            ]
            widths = (estimated["shifted_placebo_high"] - estimated["shifted_placebo_low"])[
                estimated["verdict"].notna() & ~estimated["reasons"].str.contains("OVERLAP_")
            ]
            out += [
                "What the pipeline measured for the campaigns that reached estimation, those refused at the overlap gate included. `largest shift from one household` is the most the estimate moves when a single household is left out; "
                "`smallest tolerance` is the smallest tolerance at which the readout would have been published with the rule unknown.",
                "",
                _md(estimated[keep]),
                "",
            ]
            if len(widths):
                out += [
                    f"Median width of one campaign's shifted-placebo interval, among the campaigns that passed the overlap gate: ${widths.median():.0f}.",
                    "",
                ]

    pooled = tables["pooled"]
    if not pooled.empty:
        view = pooled.copy()
        view["window"] = view["shift"].map(lambda s: _window(s, days))
        for name in POOLED.values():
            view[name.replace("mean_", "").replace("_", " ")] = _ci(view, name)
        view["pre-history minus shifted"] = _ci(view, "placebo_difference")
        keep = [
            "contract",
            "method",
            "window",
            "units",
            "units_with_estimates",
            "estimate",
            "prehistory placebo",
            "shifted placebo",
            "pre-history minus shifted",
            "programme_verdict",
            "smallest_tolerance_undocumented",
        ]
        out += [
            "## The campaigns together",
            "",
            "Mean across the campaigns whose data, timing and overlap gates passed, each counting once, with 95% intervals from the household bootstrap. "
            "`units` is the number of readouts that fell due, `units with estimates` the number averaged. "
            "The rows anchored before the launch are readouts of a campaign that had not been sent; the sets of campaigns differ from row to row. "
            "`smallest tolerance` is the smallest tolerance for placebos at which the programme readout would have been published.",
            "",
            _md(view[keep]),
            "",
        ]

    alike = tables["like_for_like"]
    if not alike.empty:
        view = alike.copy()
        for name in POOLED.values():
            view[name.replace("mean_", "").replace("_", " ")] = _ci(view, name)
            if f"change_in_{name}" in view:
                view["change in " + name.replace("mean_", "").replace("_", " ")] = _ci(view, f"change_in_{name}")
        changes = [c for c in view.columns if c.startswith("change in ")]
        out += [
            "## The contracts on the same campaigns",
            "",
            f"The campaigns that passed the data, timing and overlap gates under every contract: {alike['campaign_ids'].iloc[0]}. "
            "The changes are from the first contract, with intervals from the same bootstrap draws. "
            "The pre-history placebo of a longer history is measured on an earlier window, so its change mixes two things: more adjustment and an older window.",
            "",
            _md(
                view[
                    [
                        "contract",
                        "history_days",
                        "method",
                        "campaigns",
                        "estimate",
                        "prehistory placebo",
                        "shifted placebo",
                    ]
                ]
            ),
            "",
            _md(view.loc[view[changes[0]] != "", ["contract", "method", *changes]]) if changes else "",
            "",
        ]

    gap = tables["spending_gap"]
    if not gap.empty:
        by_window = gap.groupby("window").agg(
            campaigns=("campaign", "count"),
            targeted=("targeted", "mean"),
            comparison=("comparison", "mean"),
            gap=("gap", "mean"),
        )
        complete = gap.groupby("campaign")["window"].min()
        longest = gap[gap["campaign"].isin(complete[complete == complete.min()].index)]
        same = longest.groupby("window").agg(
            campaigns=("campaign", "count"),
            targeted=("targeted", "mean"),
            comparison=("comparison", "mean"),
            gap=("gap", "mean"),
        )
        out += [
            "## How long before the launch the two groups already differed",
            "",
            f"Contract {_label(main)}, the campaigns that passed the data, timing and overlap gates. Mean spending per household in each window of {days} days, "
            "counted from the launch: 0 is the outcome window, -1 the window before the launch. No adjustment.",
            "",
            "All campaigns; the early windows exist only for the campaigns launched late enough:",
            "",
            _md(by_window.reset_index()),
            "",
            f"The {int(same['campaigns'].max())} campaigns that have every window, so that the rows compare like with like:",
            "",
            _md(same.reset_index()),
            "",
        ]

    check = tables["prehistory_check"]
    check = check.dropna(subset=["prehistory_placebo_seen_before_window"]) if not check.empty else check
    if not check.empty:
        means = check.groupby("method", sort=False).mean(numeric_only=True).reset_index()
        out += [
            "## Is the pre-history placebo driven by households with no recorded spending in its window?",
            "",
            f"Contract {_label(main)}, point estimates, mean across campaigns. The placebo is recomputed on the households already seen in the feed when the pre-history window opened. "
            "The feed starts on a fixed day, so this is about recorded purchases, not about when a household became a customer.",
            "",
            _md(
                means[
                    [
                        "method",
                        "households",
                        "households_seen_before_window",
                        "targeted_without_spending_in_window",
                        "comparison_without_spending_in_window",
                        "prehistory_placebo",
                        "prehistory_placebo_seen_before_window",
                    ]
                ]
            ),
            "",
        ]

    swept = tables["tolerance_sweep"]
    if not swept.empty:
        mine = swept[
            (swept["contract"] == _label(main)) & (swept["shift"] == 0) & (swept["method"] == main.method.name)
        ]
        out += [
            "## What a looser tolerance would have published",
            "",
            f"Contract {_label(main)}, primary method, the real readouts re-read at other tolerances and with the assignment rule taken as documented. Nothing is recomputed.",
            "",
            _md(mine.drop(columns=["contract", "method", "shift"])),
            "",
        ]

    gate = tables["gate_audit"]
    if not gate.empty:
        mine = gate[
            (gate["contract"] == _label(main)) & (gate["method"] == main.method.name) & (gate["published"] > 0)
        ].copy()
        if len(mine):
            mine["mean estimate of what was published"] = _ci(mine, "mean_estimate")
            mine["window"] = mine["shift"].map(lambda s: _window(s, days))
            out += [
                "## Readouts anchored before the launch, at other tolerances",
                "",
                f"Contract {_label(main)}, primary method. The campaign had not been sent in these windows. Rows with nothing published are omitted: "
                "at tolerances below the first row shown for a window, every readout there is refused.",
                "",
                _md(
                    mine[
                        [
                            "window",
                            "assignment_documented",
                            "tolerance_usd",
                            "units_with_estimates",
                            "published",
                            "mean estimate of what was published",
                            "largest_estimate",
                        ]
                    ]
                ),
                "",
            ]

    world_table = tables["worlds"]
    if not world_table.empty:
        note = world_notes[0] if world_notes else {}
        big = world_table[world_table["world"] != "random_small"]
        sizes = ", ".join(f"{int(h):,}" for h in sorted(big["households"].unique(), reverse=True)) if len(big) else ""
        shown = [
            "world",
            "households",
            "campaign_reach",
            "assignment_rule",
            "rule_as_stated_holds",
            "readouts",
            "published",
            "published_on_own_placebos",
            "published_on_the_record",
            "published_mean_error",
            "published_largest_error",
            "published_intervals_holding_truth",
            "programmes_published",
            "programme_mean_error",
        ]
        inside = [
            "world",
            "true_effect",
            "mean_estimate",
            "mean_error",
            "mean_error_smallest",
            "mean_error_largest",
            "mean_prehistory_placebo",
            "mean_shifted_placebo",
            "mean_standard_error",
        ]
        out += [
            "## Synthetic retailers with a known effect",
            "",
            f"Every campaign adds ${world_table['true_effect'].iloc[0]:g} to the spending of each targeted household. "
            f"Each world is drawn with {int(world_table['seeds'].max())} seeds and {note.get('campaigns', '')} campaigns per seed, and the counts below add the seeds up. "
            f"Households per world: {sizes}; `random_small` has the size of the real panel. `campaign reach` is the share of households a campaign is sent to. "
            f"Bootstrap replications per readout: {note.get('replications', '')}. "
            "`rule as stated holds` says whether a contract that calls the assignment rule documented, reading spending only, is telling the truth in that world. "
            "`programmes published` counts the seeds whose last programme readout was published.",
            "",
        ]
        for primary, title in ((True, f"Primary method ({main.method.name})"), (False, "Shadow methods")):
            part = world_table[world_table["primary"] == primary]
            if part.empty:
                continue
            columns = shown if primary else ["method", *shown]
            out += [f"### {title}", "", _md(part[columns]), ""]
            out += [
                "What was estimated in each world, whatever the gates decided (identical under both rules). Means across seeds; the smallest and largest are over seeds:",
                "",
                _md(part[part["assignment_rule"] == "undocumented"][inside if primary else ["method", *inside]]),
                "",
            ]

    plan = tables["planning"]
    if not plan.empty:
        mine = plan[plan["true_mean_placebo"] == 0.0]
        wide = mine.pivot_table(
            index=["method", "placebo", "assumed_correlation"], columns="campaigns", values="passes", sort=False
        ).reset_index()
        wide.columns = [str(c) for c in wide.columns]
        edge = (
            plan[plan["true_mean_placebo"] > 0]
            .pivot_table(
                index=["method", "placebo", "assumed_correlation"], columns="campaigns", values="passes", sort=False
            )
            .reset_index()
        )
        edge.columns = [str(c) for c in edge.columns]
        noise = (
            plan.groupby(["method", "placebo", "assumed_correlation"], sort=False)[
                [
                    "campaigns_in_registry",
                    "standard_error_of_one_campaign",
                    "measured_correlation",
                    "campaigns_for_interval_to_fit",
                    "campaigns_for_80_percent",
                ]
            ]
            .first()
            .reset_index()
        )
        out += [
            "## How long a record the gates need",
            "",
            f"Chance that the pooled placebo of K campaigns lies within ±${tol.placebo_usd:g} when the method's true mean placebo effect is zero, at the noise of this panel (contract {_label(main)}). "
            "A normal approximation; no simulation. With the rule unknown both placebos have to pass.",
            "",
            _md(wide),
            "",
            f"The same when the true mean placebo effect is ${tol.placebo_usd:g}, the edge of the tolerance:",
            "",
            _md(edge, 3),
            "",
            "What the calculation is built on, and the fewest campaigns at which the pooled interval is narrow enough to fit inside the tolerance at all, and at which an unbiased method passes four times in five (blank: never):",
            "",
            _md(noise, 3),
            "",
        ]
    return "\n".join(out)


# ---- everything ----------------------------------------------------------------------
def write(
    contracts: list[Contract],
    snapshot: Snapshot,
    registry: Registry,
    results: Path,
    figures: Path,
    prototype: str | Path | None,
) -> dict[str, pd.DataFrame]:
    """Write every table and figure. ``prototype`` is the prototype's results file, if there is one to compare with."""
    main = contracts[0]
    if registry.audit(main).empty:
        raise ValueError(
            f"nothing is recorded under {main.tag} in {registry.root}; run `readout replay` with the same contract and --replications"
        )
    contracts = [c for c in contracts if not registry.audit(c).empty]
    results.mkdir(parents=True, exist_ok=True)
    figures.mkdir(parents=True, exist_ok=True)
    shifts = tuple(sorted(int(s) for s in registry.audit(main)["shift"].unique()))

    parity_path = results / "parity.csv"
    if parity_path.exists():
        parity_table = pd.read_csv(parity_path)
    elif prototype is not None:
        parity_table = parity.compare(snapshot, main, prototype)
    else:
        parity_table = None
    world_root = registry.root / "worlds"
    stored = worlds.stored_worlds(world_root)
    world_notes = [
        json.loads(path.read_text(encoding="utf-8")) for path in sorted(world_root.glob("*/seed*/world.json"))
    ]
    seeds = worlds.by_seed(world_root, main, stored) if stored else pd.DataFrame()
    has_estimates = not registry.valid_units(main, main.method, 0).empty

    tables = {
        "prototype_to_production": pd.DataFrame() if parity_table is None else prototype_to_production(parity_table),
        "audit_readouts": readouts_table(registry, contracts) if 0 in shifts else pd.DataFrame(),
        "pooled": pooled_table(registry, contracts),
        "like_for_like": diagnostics.like_for_like(registry, contracts),
        "spending_gap": diagnostics.spending_gap(snapshot, registry, main) if has_estimates else pd.DataFrame(),
        "prehistory_check": diagnostics.prehistory_check(snapshot, registry, main) if has_estimates else pd.DataFrame(),
        "tolerance_sweep": _per_contract(
            lambda c: sweep(registry.audit(c), TOLERANCES, c.tolerances.min_record_campaigns), contracts
        ),
        "gate_audit": _per_contract(lambda c: diagnostics.gate_audit(registry, c, shifts, TOLERANCES), contracts),
        "worlds_by_seed": seeds,
        "worlds": worlds.summarise(seeds),
        "planning": planning.plan(registry, main),
    }
    for name, table in tables.items():
        path = results / f"{name}.csv"
        if table.empty:
            path.unlink(missing_ok=True)  # a table that no longer applies must not linger from an earlier run
        else:
            table.to_csv(path, index=False, float_format="%.6g", lineterminator="\n")

    with (results / "readouts.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
        for result in registry.readouts(main):
            handle.write(json.dumps(RESULT.dump_python(result, mode="json"), sort_keys=True, allow_nan=False) + "\n")
    (results / "RESULTS.md").write_text(
        results_markdown(tables, contracts, snapshot, world_notes) + "\n", encoding="utf-8", newline="\n"
    )

    _style()
    for name in ("replay.png", "pooled.png", "worlds.png", "planning.png"):
        (figures / name).unlink(missing_ok=True)
    figure_replay(figures / "replay.png", registry, main)
    if not tables["pooled"].empty:
        figure_pooled(figures / "pooled.png", tables["pooled"], contracts)
    figure_worlds(figures / "worlds.png", world_root, stored, main.method.name)
    if not tables["planning"].empty:
        figure_planning(figures / "planning.png", tables["planning"], main)
    return tables
