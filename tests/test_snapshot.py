"""Snapshots are identified by their content; views show nothing from their date on."""

from __future__ import annotations

import pandas as pd
import pytest

from readout.snapshot import Snapshot


def test_a_view_holds_nothing_from_its_date_on(snapshot):
    day = snapshot.first_day + pd.Timedelta(days=150)
    view = snapshot.as_of(day)
    assert view.daily["day"].max() < day
    assert view.stores["day"].max() < day
    assert (view.descriptions["start_date"] < day).all()
    assert set(view.campaigns["campaign_id"]) <= set(view.descriptions.index)
    assert view.last_day == day - pd.Timedelta(days=1)
    # Campaigns that launch later exist in the snapshot and are not visible yet.
    assert len(view.descriptions) < len(snapshot.tables["descriptions"])


def test_households_are_those_seen_so_far(snapshot):
    early = snapshot.as_of(snapshot.first_day + pd.Timedelta(days=3))
    late = snapshot.full()
    assert set(early.households) < set(late.households)
    assert list(early.households) == sorted(early.households)


def test_cutting_a_view_equals_viewing_at_the_earlier_date(snapshot):
    late = snapshot.as_of(snapshot.first_day + pd.Timedelta(days=200))
    day = snapshot.first_day + pd.Timedelta(days=120)
    cut, direct = late.cut(day), snapshot.as_of(day)
    assert cut.view_id == direct.view_id
    pd.testing.assert_frame_equal(cut.daily, direct.daily)
    pd.testing.assert_frame_equal(cut.descriptions, direct.descriptions)
    pd.testing.assert_frame_equal(cut.campaigns, direct.campaigns)
    assert (cut.households == direct.households).all()


def test_a_view_cannot_be_extended(snapshot):
    view = snapshot.as_of(snapshot.first_day + pd.Timedelta(days=100))
    with pytest.raises(ValueError, match="cannot be extended"):
        view.cut(snapshot.first_day + pd.Timedelta(days=101))


def test_no_view_before_the_feed_starts(snapshot):
    with pytest.raises(ValueError, match="no transactions"):
        snapshot.as_of(snapshot.first_day)


def test_snapshot_id_follows_the_content(snapshot):
    tables = {name: frame.copy() for name, frame in snapshot.tables.items()}
    same = Snapshot.from_tables(tables, snapshot.manifest["source"])
    assert same.snapshot_id == snapshot.snapshot_id
    tables["daily"].loc[tables["daily"].index[0], "sales_value"] += 0.01
    assert Snapshot.from_tables(tables, snapshot.manifest["source"]).snapshot_id != snapshot.snapshot_id


def test_save_and_load_round_trip(snapshot, tmp_path):
    snapshot.save(tmp_path)
    loaded = Snapshot.load(tmp_path)
    assert loaded.snapshot_id == snapshot.snapshot_id
    pd.testing.assert_frame_equal(loaded.tables["daily"], snapshot.tables["daily"])


def test_load_refuses_a_table_that_does_not_match_its_manifest(snapshot, tmp_path):
    snapshot.save(tmp_path)
    daily = pd.read_parquet(tmp_path / "daily.parquet")
    daily.loc[0, "sales_value"] += 1.0
    daily.to_parquet(tmp_path / "daily.parquet", index=False)
    with pytest.raises(RuntimeError, match="does not match its manifest"):
        Snapshot.load(tmp_path)


@pytest.mark.data
def test_real_snapshot_is_the_data_the_prototype_described(real_snapshot, prototype):
    import json

    from conftest import ROOT

    published = json.loads((ROOT / "prototype" / "placebo_results.json").read_text())["data"]
    assert real_snapshot.manifest["households"] == published["households"] == 2469
    assert str(real_snapshot.first_day.date()) == published["first_day"]
    assert str(real_snapshot.last_day.date()) == published["last_day"]
    assert len(real_snapshot.tables["descriptions"]) == published["campaigns"]
    assert len(real_snapshot.tables["campaigns"]) == published["household_campaign_pairs"]
