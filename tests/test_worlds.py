"""The synthetic retailers: what they are built to contain, and the audit that runs on them."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from readout import worlds
from readout.simulate import BLOCK, WORLDS, World, synthetic_snapshot


def _spend(snapshot, block: int) -> pd.Series:
    daily = snapshot.tables["daily"]
    start = snapshot.first_day + pd.Timedelta(days=block * BLOCK)
    rows = daily[(daily["day"] >= start) & (daily["day"] < start + pd.Timedelta(days=BLOCK))]
    households = np.arange(1, snapshot.manifest["households"] + 1)
    return rows.groupby("household_id")["sales_value"].sum().reindex(households).fillna(0.0)


def _members(snapshot, campaign: int) -> np.ndarray:
    members = snapshot.tables["campaigns"]
    ids = members.loc[members["campaign_id"] == campaign, "household_id"]
    return np.isin(np.arange(1, snapshot.manifest["households"] + 1), ids)


def test_worlds_are_reproducible_and_differ_by_seed():
    world = replace(WORLDS["observed"], households=300, campaigns=3)
    assert synthetic_snapshot(world).snapshot_id == synthetic_snapshot(world).snapshot_id
    assert synthetic_snapshot(replace(world, seed=1)).snapshot_id != synthetic_snapshot(world).snapshot_id


def test_the_feed_is_as_long_as_the_campaigns_need():
    world = World(households=200, campaigns=4, first_launch_block=3)
    snapshot = synthetic_snapshot(world)
    assert world.blocks == 7
    assert (snapshot.last_day - snapshot.first_day).days + 1 == 7 * BLOCK
    last = snapshot.tables["descriptions"]["start_date"].max()
    assert last + pd.Timedelta(days=BLOCK) == snapshot.end  # the last outcome window closes with the feed


def test_the_share_of_targeted_households_is_the_one_asked_for():
    for name in WORLDS:
        snapshot = synthetic_snapshot(replace(WORLDS[name], households=4000, campaigns=2))
        assert _members(snapshot, 1).mean() == pytest.approx(0.25, abs=0.03), name


def test_the_effect_is_the_number_of_dollars_declared():
    """The same world with and without an effect differs by exactly that amount, for targeted households only."""
    world = World(name="random", households=800, campaigns=2)
    with_effect, without = synthetic_snapshot(world), synthetic_snapshot(replace(world, effect=0.0))
    members = _members(with_effect, 1)
    assert (members == _members(without, 1)).all()
    gain = _spend(with_effect, world.first_launch_block) - _spend(without, world.first_launch_block)
    np.testing.assert_allclose(gain[members], world.effect, atol=1e-9)
    np.testing.assert_allclose(gain[~members], 0.0, atol=1e-9)


def test_each_world_targets_on_what_it_says():
    size = {"households": 6000, "campaigns": 2}
    block = WORLDS["random"].first_launch_block

    def gaps(name):
        snapshot = synthetic_snapshot(replace(WORLDS[name], effect=0.0, **size))
        members = _members(snapshot, 1)
        return [
            float(_spend(snapshot, b)[members].mean() - _spend(snapshot, b)[~members].mean())
            for b in (block - 1, block)
        ]

    before, after = gaps("random")
    assert abs(before) < 12 and abs(after) < 12  # chance alone
    before, after = gaps("observed")
    assert before > 60 and after > 30  # chosen on what they had just spent
    before, after = gaps("long_run")
    assert before > 60 and after > 60  # chosen on what they always spend
    before, after = gaps("foresight")
    assert abs(before) < 12 and after > 10  # nothing to see before the launch, a gap after it with no effect


def test_a_world_needs_room_before_its_first_campaign():
    with pytest.raises(ValueError, match="at least one campaign"):
        synthetic_snapshot(World(households=100, campaigns=0))
    with pytest.raises(ValueError, match="two blocks"):
        synthetic_snapshot(World(households=100, campaigns=2, first_launch_block=1))


def test_the_audit_worlds_cover_the_declared_cases():
    chosen = worlds.audit_worlds(1234, 7, (0, 5))
    assert (
        {w.name for w in chosen}
        == {"random", "observed", "long_run", "foresight", "random_small"}
        == set(worlds.CLAIM_HOLDS)
    )
    assert {w.seed for w in chosen} == {0, 5} and len(chosen) == 10 and {w.campaigns for w in chosen} == {7}
    small = next(w for w in chosen if w.name == "random_small")
    assert small.households == worlds.REAL_PANEL and small.treated_share == worlds.REAL_SHARE
    assert next(w for w in chosen if w.name == "observed").households == 1234


@pytest.fixture(scope="module")
def audited(contract, tmp_path_factory):
    root = tmp_path_factory.mktemp("worlds")
    tiny = [
        replace(WORLDS[name], households=500, campaigns=6, seed=seed)
        for name in ("random", "observed")
        for seed in (0, 1)
    ]
    for world in tiny:
        worlds.run_world(world, contract, root, replications=40)
    return root, tiny


def test_the_audit_runs_and_keeps_a_note_of_what_was_run(audited, contract):
    root, tiny = audited
    assert worlds.stored_worlds(root) == tiny
    with pytest.raises(ValueError, match="other settings"):
        worlds.run_world(tiny[0], contract, root, replications=41)
    worlds.run_world(tiny[0], contract, root, replications=40)  # the same settings: nothing to do, no complaint


def test_the_audit_table_has_every_column_whatever_was_published(audited, contract):
    root, tiny = audited
    seeds = worlds.by_seed(root, contract, tiny)
    assert len(seeds) == 2 * 2 * 2 * 2  # worlds, seeds, assignment rules, methods
    assert (seeds["published"] == seeds["published_on_own_placebos"] + seeds["published_on_the_record"]).all()
    assert (seeds["published"] == 0).all()  # five hundred households cannot show anything to within $5
    for column in (
        "published_error_sum",
        "published_largest_error",
        "published_intervals_holding_truth",
        "programme_published",
        "programme_error",
        "programme_reasons",
    ):
        assert column in seeds
    by_rule = seeds.set_index(["world", "seed", "method", "assignment_rule"])
    for method in ("weighting", "regression"):
        # The estimates are shared; only what the gates require differs.
        same = (
            by_rule.loc[("observed", 0, method, "documented"), "mean_estimate"]
            == by_rule.loc[("observed", 0, method, "undocumented"), "mean_estimate"]
        )
        assert same
        assert by_rule.loc[("observed", 0, method, "undocumented"), "failing_assignment"] >= 3
        assert by_rule.loc[("observed", 0, method, "documented"), "failing_assignment"] == 0
    assert seeds.loc[seeds["assignment_rule"] == "documented", "rule_as_stated_holds"].all()

    table = worlds.summarise(seeds)
    assert len(table) == 2 * 2 * 2 and (table["seeds"] == 2).all()
    assert (table["readouts"] == 12).all() and table["published_mean_error"].isna().all()
    first = table.iloc[0]
    mine = seeds[
        (seeds["world"] == first["world"])
        & (seeds["assignment_rule"] == first["assignment_rule"])
        & (seeds["method"] == first["method"])
    ]
    assert first["mean_error"] == pytest.approx(mine["mean_error"].mean())
    assert first["mean_error_smallest"] <= first["mean_error"] <= first["mean_error_largest"]
    assert worlds.summarise(seeds.iloc[0:0]).empty
