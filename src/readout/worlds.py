"""Audit the gates on synthetic retailers, where the effect of every campaign is known.

The pipeline is run unchanged on each world of ``simulate.WORLDS``, twice:
under a contract that says the assignment rule is not documented, and under
one that says it is documented and reads the households' spending. In two of
the worlds that second statement is true, in the other two it is false. Each
world is drawn several times, with different seeds. The result is a table of
what each gate stops and what it lets through.

The synthetic retailer is larger than the real panel on purpose, and its
campaigns reach a quarter of the households. The question here is what the
gates do when there is enough evidence to pass them. One more world, with
households drawn at random, as many of them as the real panel has and
campaigns that reach as few of them as the real ones do, shows what the gates
do when there is not. Its campaigns are estimated more precisely than the real
ones, so it is the easier case of the two.
"""

from __future__ import annotations

import json
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
import pandas as pd

from .certificate import pooled_mean
from .contract import Assignment, Contract
from .registry import Registry
from .replay import replay
from .simulate import WORLDS, World, synthetic_snapshot

HOUSEHOLDS = 50_000
CAMPAIGNS = 12
REPLICATIONS = 200
SEEDS = (0, 1, 2)
REAL_PANEL = 2_469  # households in the real feed
REAL_SHARE = 0.07  # share of them that a typical real campaign is sent to
RULES = {"undocumented": False, "documented": True}
# Whether a contract that calls the rule documented, reading spending only, tells the truth in each world.
CLAIM_HOLDS = {"random": True, "observed": True, "long_run": False, "foresight": False, "random_small": True}
ROLES = {
    "effect": "mean_estimate",
    "prehistory_placebo": "mean_prehistory_placebo",
    "shifted_placebo": "mean_shifted_placebo",
}


def audit_worlds(
    households: int = HOUSEHOLDS, campaigns: int = CAMPAIGNS, seeds: tuple[int, ...] = SEEDS
) -> list[World]:
    """The worlds of the audit: the four of ``simulate.WORLDS`` and a small randomised one, once per seed."""
    kinds = [replace(world, households=households, campaigns=campaigns) for world in WORLDS.values()]
    kinds.append(
        replace(
            WORLDS["random"], name="random_small", households=REAL_PANEL, treated_share=REAL_SHARE, campaigns=campaigns
        )
    )
    return [replace(world, seed=seed) for world in kinds for seed in seeds]


def world_dir(root: str | Path, world: World) -> Path:
    return Path(root) / world.name / f"seed{world.seed}"


def world_contract(contract: Contract, documented: bool, replications: int) -> Contract:
    """The contract a world is read out under: the real one, with the assignment rule set."""
    rule = (
        Assignment(documented=True, inputs=("spend",), note="The retailer scores households on their recent spending.")
        if documented
        else Assignment(documented=False, note="The retailer has not said how it chose the households.")
    )
    return contract.model_copy(
        update={
            "assignment": rule,
            "bootstrap": contract.bootstrap.model_copy(update={"replications": replications}),
            "data": contract.data.model_copy(update={"closed_days": ()}),
        }
    )


def run_world(
    world: World, contract: Contract, root: str | Path, replications: int = REPLICATIONS, progress: bool = False
) -> Path:
    """Replay one world under both contracts. Estimates are computed once and shared.

    The directory keeps a note of the world and the settings it was run with,
    and refuses to mix two runs with different ones.
    """
    directory = world_dir(root, world)
    note = {**asdict(world), "replications": replications, "contract": contract.tag}
    path = directory / "world.json"
    if path.exists() and json.loads(path.read_text(encoding="utf-8")) != note:
        raise ValueError(f"{directory} holds a world run with other settings; remove it or use another registry")
    directory.mkdir(parents=True, exist_ok=True)
    snapshot = synthetic_snapshot(world)
    benches: dict = {}
    for rule, documented in RULES.items():
        replay(
            snapshot,
            world_contract(contract, documented, replications),
            Registry(directory / rule),
            progress=progress,
            benches=benches,
        )
    path.write_text(json.dumps(note, indent=2) + "\n", encoding="utf-8", newline="\n")
    return directory


def stored_worlds(root: str | Path) -> list[World]:
    """The worlds that have been run under ``root``, in the order of the audit."""
    order = [*WORLDS, "random_small"]
    found = []
    for path in Path(root).glob("*/seed*/world.json"):
        note = json.loads(path.read_text(encoding="utf-8"))
        found.append(World(**{key: value for key, value in note.items() if key not in ("replications", "contract")}))
    return sorted(found, key=lambda w: (order.index(w.name) if w.name in order else len(order), w.seed))


def _route(gates: list[dict]) -> str:
    """Whether a published readout rested on its own placebos alone or needed the method's record."""
    relied_on = [
        g["measurements"].get("state")
        for g in gates
        if g["gate"] in ("prehistory_placebo", "assignment") and not g["measurements"].get("documented")
    ]
    return "record" if "RECORD_CERTIFIED" in relied_on else "own"


def by_seed(root: str | Path, contract: Contract, worlds: list[World]) -> pd.DataFrame:
    """One row per world, seed, assignment rule and method: what was published, and how wrong it was.

    Every column is present in every row, whatever was published.
    """
    level = contract.tolerances.interval_level
    rows = []
    for world in worlds:
        for rule, documented in RULES.items():
            registry = Registry(world_dir(root, world) / rule)
            audit, programme = registry.audit(), registry.programme()
            if audit.empty:
                continue
            for method in contract.methods:
                group = audit[audit["method"] == method.name]
                valid = group[group["valid_placebo"]]
                published = group[group["verdict"] == "published"]
                codes = [code for reasons in group["codes"] for code in reasons]
                routes = [_route(gates) for gates in published["gates"]]
                row = {
                    "world": world.name,
                    "seed": world.seed,
                    "households": world.households,
                    "campaign_reach": world.treated_share,
                    "assignment_rule": rule,
                    "rule_as_stated_holds": CLAIM_HOLDS.get(world.name) if documented else None,
                    "method": method.name,
                    "primary": method.name == contract.method.name,
                    "true_effect": world.effect,
                    "readouts": len(group),
                    "published": len(published),
                    "published_on_own_placebos": routes.count("own"),
                    "published_on_the_record": routes.count("record"),
                    "failing_prehistory_placebo": int(sum(code.startswith("PREHISTORY") for code in codes)),
                    "own_prehistory_placebo_outside": int(sum(code == "PREHISTORY_OWN_OUTSIDE" for code in codes)),
                    "failing_assignment": int(sum(code.startswith("ASSIGNMENT") for code in codes)),
                    "failing_overlap": int(sum(code.startswith("OVERLAP") for code in codes)),
                }
                for label in ROLES.values():
                    row[label] = row[f"{label}_low"] = row[f"{label}_high"] = np.nan
                row["mean_standard_error"] = np.nan
                if len(valid):
                    stored = [registry.draws(key) for key in valid["key"]]
                    for role, label in ROLES.items():
                        pooled = pooled_mean(
                            np.column_stack([s[role] for s in stored]),
                            np.array([e["estimate"] for e in valid[role]]),
                            level,
                        )
                        row[label], row[f"{label}_low"], row[f"{label}_high"] = pooled.estimate, pooled.low, pooled.high
                    row["mean_standard_error"] = float(np.mean([e["se"] for e in valid["effect"]]))
                row["mean_error"] = row["mean_estimate"] - world.effect
                errors = np.array([e["estimate"] for e in published["effect"]]) - world.effect
                row["published_error_sum"] = float(errors.sum())
                row["published_largest_error"] = float(np.abs(errors).max()) if len(errors) else np.nan
                row["published_intervals_holding_truth"] = int(
                    np.sum([e["low"] <= world.effect <= e["high"] for e in published["effect"]])
                )
                mine = (
                    programme[programme["method"] == method.name].sort_values("as_of")
                    if not programme.empty
                    else programme
                )
                last = mine.iloc[-1] if len(mine) else None
                passed = last is not None and last["kind"] == "programme_published"
                row["programme_published"] = bool(passed)
                row["programme_error"] = last["effect"]["estimate"] - world.effect if passed else np.nan
                row["programme_reasons"] = (
                    "" if passed or last is None else " ".join(reason["code"] for reason in last["reasons"])
                )
                rows.append(row)
    return pd.DataFrame(rows)


def summarise(seeds: pd.DataFrame) -> pd.DataFrame:
    """The seeds of each world added up: one row per world, assignment rule and method."""
    if seeds.empty:
        return seeds
    keys = ["world", "households", "campaign_reach", "assignment_rule", "method", "primary", "true_effect"]
    rows = []
    for values, group in seeds.groupby(keys, sort=False):
        published = int(group["published"].sum())
        truth = group["rule_as_stated_holds"].iloc[0]
        rows.append(
            {
                **dict(zip(keys, values, strict=True)),
                "rule_as_stated_holds": truth,
                "seeds": len(group),
                "readouts": int(group["readouts"].sum()),
                "published": published,
                "published_on_own_placebos": int(group["published_on_own_placebos"].sum()),
                "published_on_the_record": int(group["published_on_the_record"].sum()),
                "failing_prehistory_placebo": int(group["failing_prehistory_placebo"].sum()),
                "own_prehistory_placebo_outside": int(group["own_prehistory_placebo_outside"].sum()),
                "failing_assignment": int(group["failing_assignment"].sum()),
                "failing_overlap": int(group["failing_overlap"].sum()),
                "mean_estimate": group["mean_estimate"].mean(),
                "mean_error": group["mean_error"].mean(),
                "mean_error_smallest": group["mean_error"].min(),
                "mean_error_largest": group["mean_error"].max(),
                "mean_prehistory_placebo": group["mean_prehistory_placebo"].mean(),
                "mean_shifted_placebo": group["mean_shifted_placebo"].mean(),
                "mean_standard_error": group["mean_standard_error"].mean(),
                "published_mean_error": group["published_error_sum"].sum() / published if published else np.nan,
                "published_largest_error": group["published_largest_error"].max(),
                "published_intervals_holding_truth": int(group["published_intervals_holding_truth"].sum())
                if published
                else pd.NA,
                "programmes_published": int(group["programme_published"].sum()),
                "programme_mean_error": group["programme_error"].mean(),
            }
        )
    table = pd.DataFrame(rows)
    table["published_intervals_holding_truth"] = table["published_intervals_holding_truth"].astype("Int64")
    return table
