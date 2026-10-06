"""Shared fixtures: a small synthetic retailer, the contract, and the prototype as a module."""

from __future__ import annotations

import importlib.util
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

from readout import source
from readout.contract import Assignment, Contract, load_contract
from readout.registry import Registry
from readout.replay import replay
from readout.simulate import WORLDS, synthetic_snapshot
from readout.snapshot import Snapshot, build

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "contracts" / "campaign_readout_v1.toml"


def with_updates(contract: Contract, **sections) -> Contract:
    """A copy of the contract with fields of some sections replaced."""
    update = {name: getattr(contract, name).model_copy(update=fields) for name, fields in sections.items()}
    return contract.model_copy(update=update)


@pytest.fixture(scope="session")
def real_contract() -> Contract:
    return load_contract(CONTRACT_PATH)


@pytest.fixture(scope="session")
def contract(real_contract) -> Contract:
    """The real contract with a short bootstrap and no closed days, for synthetic data."""
    return with_updates(real_contract, bootstrap={"replications": 60}, data={"closed_days": ()})


@pytest.fixture(scope="session")
def documented(contract) -> Contract:
    return contract.model_copy(update={"assignment": Assignment(documented=True, inputs=("spend",))})


@pytest.fixture(scope="session")
def lenient(contract) -> Contract:
    """A tolerance no placebo can exceed: whatever reaches the placebo gates is published."""
    return with_updates(contract, tolerances={"placebo_usd": 1e6})


@pytest.fixture(scope="session")
def world():
    return replace(WORLDS["observed"], households=500, campaigns=6)


@pytest.fixture(scope="session")
def snapshot(world) -> Snapshot:
    return synthetic_snapshot(world)


@pytest.fixture(scope="session")
def replayed(snapshot, contract, tmp_path_factory) -> Registry:
    """The small world read out campaign by campaign under the undocumented contract."""
    registry = Registry(tmp_path_factory.mktemp("registry"))
    replay(snapshot, contract, registry, progress=False)
    return registry


@pytest.fixture(scope="session")
def plain_snapshot() -> Snapshot:
    """A small retailer whose campaigns go to households drawn at random: overlap is never the problem."""
    return synthetic_snapshot(replace(WORLDS["random"], households=500, campaigns=6))


@pytest.fixture(scope="session")
def replayed_lenient(plain_snapshot, lenient, tmp_path_factory) -> Registry:
    registry = Registry(tmp_path_factory.mktemp("registry_lenient"))
    replay(plain_snapshot, lenient, registry, progress=False)
    return registry


@pytest.fixture(scope="session")
def prototype():
    """The prototype script, imported as a module without running it."""
    spec = importlib.util.spec_from_file_location("placebo_campaigns", ROOT / "prototype" / "placebo_campaigns.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def real_snapshot(real_contract, tmp_path_factory) -> Snapshot:
    """The snapshot of the real data, if the pinned source files have been fetched."""
    raw = ROOT / "data" / "raw"
    try:
        source.verify(real_contract.source, raw)
    except source.SourceIntegrityError:
        pytest.skip("the pinned source files are not in data/raw; run `readout fetch`")
    out = tmp_path_factory.mktemp("snapshot")
    build(raw, out, real_contract.source)
    return Snapshot.load(out)


def launch_of(snapshot: Snapshot, campaign: int) -> pd.Timestamp:
    rows = snapshot.tables["descriptions"]
    return pd.Timestamp(rows.loc[rows["campaign_id"] == campaign, "start_date"].iloc[0])


def as_prototype_data(view) -> dict:
    """A view in the form the prototype's functions read."""
    descriptions = view.descriptions.copy()
    descriptions["households"] = view.campaigns.groupby("campaign_id")["household_id"].nunique()
    return {
        "daily": view.daily,
        "stores": view.stores,
        "households": view.households,
        "campaigns": view.campaigns,
        "descriptions": descriptions,
        "redemptions": view.redemptions,
        "first_day": view.first_day,
        "last_day": view.last_day,
    }


def with_extra_campaign(snapshot: Snapshot, start: pd.Timestamp, households, campaign_id: int = 99) -> Snapshot:
    """The snapshot with one more campaign, sent to ``households`` from ``start``."""
    tables = {name: frame.copy() for name, frame in snapshot.tables.items()}
    tables["campaigns"] = pd.concat(
        [tables["campaigns"], pd.DataFrame({"campaign_id": campaign_id, "household_id": list(households)})],
        ignore_index=True,
    )
    extra = pd.DataFrame(
        {
            "campaign_id": [campaign_id],
            "campaign_type": ["Type B"],
            "start_date": [pd.Timestamp(start)],
            "end_date": [pd.Timestamp(start) + pd.Timedelta(days=20)],
        }
    ).astype({"start_date": "datetime64[ns]", "end_date": "datetime64[ns]"})
    tables["descriptions"] = pd.concat([tables["descriptions"], extra], ignore_index=True)
    return Snapshot.from_tables(tables, {"synthetic": "with an extra campaign"})


def without_early_purchases(snapshot: Snapshot, households, before: pd.Timestamp) -> Snapshot:
    """The snapshot in which ``households`` are first seen on ``before`` or later."""
    tables = {name: frame.copy() for name, frame in snapshot.tables.items()}
    for name in ("daily", "stores"):
        table = tables[name]
        tables[name] = table[~(table["household_id"].isin(list(households)) & (table["day"] < before))].reset_index(
            drop=True
        )
    return Snapshot.from_tables(tables, {"synthetic": "some households appear late"})
