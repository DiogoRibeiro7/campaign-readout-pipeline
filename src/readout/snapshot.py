"""Turn the source files into an immutable snapshot, and cut it at a date.

A snapshot is the set of tables the pipeline computes from, stored once and
identified by a hash of its content. A view is that snapshot as it stood on a
given day: nothing dated on or after the day is visible. Every readout runs on
a view, so it cannot use data that did not exist when it would have been run.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .contract import Source

TRANSFORM_VERSION = 1
TABLES = ("daily", "stores", "campaigns", "descriptions", "redemptions")
_DATE_COLUMNS = {
    "daily": ("day",),
    "stores": ("day",),
    "descriptions": ("start_date", "end_date"),
    "redemptions": ("day",),
}


def _as_int(values: pd.Series) -> np.ndarray:
    """Identifiers are stored as text in the package, a few in scientific notation."""
    return pd.to_numeric(values).round().astype("int64").to_numpy()


def _days(values) -> pd.Series:
    return pd.Series(pd.to_datetime(values)).dt.normalize().astype("datetime64[ns]")


def read_source(raw_dir: str | Path) -> dict[str, pd.DataFrame]:
    """Parse the R files into the five tables of a snapshot."""
    import pyreadr

    raw = Path(raw_dir)

    def read(name: str) -> pd.DataFrame:
        return next(iter(pyreadr.read_r(str(raw / name)).values()))

    tx_raw, products = read("transactions.rds"), read("products.rda")
    private = set(_as_int(products.loc[products["brand"].astype(str) == "Private", "product_id"]))
    # The package's data-raw/prep-data.R builds the timestamps with tz = "America/New_York"; the files hold them in UTC.
    local = pd.to_datetime(tx_raw["transaction_timestamp"]).dt.tz_localize("UTC").dt.tz_convert("America/New_York")
    tx = pd.DataFrame(
        {
            "household_id": _as_int(tx_raw["household_id"]),
            "basket_id": _as_int(tx_raw["basket_id"]),
            "store_id": _as_int(tx_raw["store_id"]),
            "day": _days(local.dt.tz_localize(None)).to_numpy(),
            "sales_value": tx_raw["sales_value"].to_numpy(float),
            "retail": tx_raw["retail_disc"].abs().to_numpy(float),
            "coupon": (tx_raw["coupon_disc"].abs() + tx_raw["coupon_match_disc"].abs()).to_numpy(float),
        }
    )
    tx["private"] = np.where(np.isin(_as_int(tx_raw["product_id"]), list(private)), tx["sales_value"], 0.0)
    daily = tx.groupby(["household_id", "day"], as_index=False).agg(
        sales_value=("sales_value", "sum"),
        private=("private", "sum"),
        retail=("retail", "sum"),
        coupon=("coupon", "sum"),
        trips=("basket_id", "nunique"),
    )
    stores = tx[["household_id", "day", "store_id"]].drop_duplicates().reset_index(drop=True)
    members, desc, red = read("campaigns.rda"), read("campaign_descriptions.rda"), read("coupon_redemptions.rda")
    campaigns = pd.DataFrame(
        {"campaign_id": _as_int(members["campaign_id"]), "household_id": _as_int(members["household_id"])}
    )
    descriptions = pd.DataFrame(
        {
            "campaign_id": _as_int(desc["campaign_id"]),
            "campaign_type": desc["campaign_type"].astype(str).to_numpy(),
            "start_date": _days(desc["start_date"]).to_numpy(),
            "end_date": _days(desc["end_date"]).to_numpy(),
        }
    ).sort_values("campaign_id", ignore_index=True)
    redemptions = pd.DataFrame(
        {"household_id": _as_int(red["household_id"]), "day": _days(red["redemption_date"]).to_numpy()}
    )
    daily = daily.sort_values(["household_id", "day"], ignore_index=True)
    stores = stores.sort_values(["household_id", "day", "store_id"], ignore_index=True)
    campaigns = campaigns.sort_values(["campaign_id", "household_id"], ignore_index=True)
    redemptions = redemptions.sort_values(["household_id", "day"], ignore_index=True)
    return {
        "daily": daily,
        "stores": stores,
        "campaigns": campaigns,
        "descriptions": descriptions,
        "redemptions": redemptions,
    }


def table_hash(name: str, frame: pd.DataFrame) -> str:
    """Content hash of a table that does not depend on how dates or text are stored."""
    canonical = frame.copy()
    for column in _DATE_COLUMNS.get(name, ()):
        canonical[column] = (canonical[column].to_numpy("datetime64[D]") - np.datetime64("1970-01-01")).astype("int64")
    digest = hashlib.sha256()
    digest.update(",".join(canonical.columns).encode())
    for column in canonical.columns:
        values = canonical[column]
        if values.dtype.kind in "iu":
            digest.update(np.ascontiguousarray(values.to_numpy("int64")).tobytes())
        elif values.dtype.kind == "f":
            digest.update(np.ascontiguousarray(values.to_numpy("float64")).tobytes())
        else:
            digest.update("\x1f".join(values.astype(str)).encode("utf-8"))
    return digest.hexdigest()


def build(raw_dir: str | Path, out_dir: str | Path, source: Source) -> dict:
    """Write the snapshot tables and a manifest that identifies them."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    tables = read_source(raw_dir)
    hashes = {name: table_hash(name, tables[name]) for name in TABLES}
    identity = {
        "source": {
            "repository": source.repository,
            "commit": source.commit,
            "files": dict(sorted(source.files.items())),
        },
        "transform_version": TRANSFORM_VERSION,
        "tables": hashes,
    }
    snapshot_id = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:16]
    for name in TABLES:
        tables[name].to_parquet(out / f"{name}.parquet", index=False)
    manifest = {
        "snapshot_id": snapshot_id,
        **identity,
        "rows": {name: int(len(tables[name])) for name in TABLES},
        "first_day": str(tables["daily"]["day"].min().date()),
        "last_day": str(tables["daily"]["day"].max().date()),
        "households": int(tables["daily"]["household_id"].nunique()),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    return manifest


@dataclass(frozen=True)
class View:
    """The snapshot as it stood at the start of ``as_of``: nothing from that day or later."""

    snapshot_id: str
    as_of: pd.Timestamp
    daily: pd.DataFrame
    stores: pd.DataFrame
    campaigns: pd.DataFrame
    descriptions: pd.DataFrame  # indexed by campaign_id
    redemptions: pd.DataFrame
    households: np.ndarray  # sorted identifiers of the households seen so far
    first_day: pd.Timestamp
    last_day: pd.Timestamp

    @property
    def view_id(self) -> str:
        return f"{self.snapshot_id}@{self.as_of.date()}"

    def cut(self, day: str | pd.Timestamp) -> View:
        """The same view, cut earlier."""
        cut = pd.Timestamp(day).normalize()
        if cut > self.as_of:
            raise ValueError("a view cannot be extended, only cut earlier")
        daily = self.daily[self.daily["day"] < cut]
        if daily.empty:
            raise ValueError(f"the view holds no transactions before {cut.date()}")
        descriptions = self.descriptions[self.descriptions["start_date"] < cut]
        return View(
            snapshot_id=self.snapshot_id,
            as_of=cut,
            daily=daily,
            stores=self.stores[self.stores["day"] < cut],
            campaigns=self.campaigns[self.campaigns["campaign_id"].isin(descriptions.index)],
            descriptions=descriptions,
            redemptions=self.redemptions[self.redemptions["day"] < cut],
            households=np.sort(daily["household_id"].unique()),
            first_day=daily["day"].min(),
            last_day=daily["day"].max(),
        )


class Snapshot:
    def __init__(self, tables: dict[str, pd.DataFrame], manifest: dict) -> None:
        self.tables = tables
        self.manifest = manifest
        self.snapshot_id: str = manifest["snapshot_id"]
        self.first_day = pd.Timestamp(manifest["first_day"])
        self.last_day = pd.Timestamp(manifest["last_day"])

    @classmethod
    def from_tables(cls, tables: dict[str, pd.DataFrame], origin: dict) -> Snapshot:
        """A snapshot held in memory, identified by its content like one read from disk."""
        identity = {
            "source": origin,
            "transform_version": TRANSFORM_VERSION,
            "tables": {n: table_hash(n, tables[n]) for n in TABLES},
        }
        manifest = {
            "snapshot_id": hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:16],
            **identity,
            "rows": {name: int(len(tables[name])) for name in TABLES},
            "first_day": str(tables["daily"]["day"].min().date()),
            "last_day": str(tables["daily"]["day"].max().date()),
            "households": int(tables["daily"]["household_id"].nunique()),
        }
        return cls(tables, manifest)

    def save(self, snapshot_dir: str | Path) -> None:
        """Write the tables and the manifest where ``load`` reads them."""
        directory = Path(snapshot_dir)
        directory.mkdir(parents=True, exist_ok=True)
        for name in TABLES:
            self.tables[name].to_parquet(directory / f"{name}.parquet", index=False)
        (directory / "manifest.json").write_text(
            json.dumps(self.manifest, indent=2) + "\n", encoding="utf-8", newline="\n"
        )

    @classmethod
    def load(cls, snapshot_dir: str | Path, verify: bool = True) -> Snapshot:
        directory = Path(snapshot_dir)
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        tables = {name: pd.read_parquet(directory / f"{name}.parquet") for name in TABLES}
        for name, columns in _DATE_COLUMNS.items():
            for column in columns:
                tables[name][column] = tables[name][column].astype("datetime64[ns]")
        if verify:
            for name in TABLES:
                actual = table_hash(name, tables[name])
                if actual != manifest["tables"][name]:
                    raise RuntimeError(f"snapshot table {name} does not match its manifest: {actual}")
        return cls(tables, manifest)

    @property
    def end(self) -> pd.Timestamp:
        """The first day after the snapshot's last day."""
        return self.last_day + pd.Timedelta(days=1)

    def as_of(self, day: str | pd.Timestamp) -> View:
        """Everything dated before ``day``. Campaigns are visible once they have launched."""
        cut = pd.Timestamp(day).normalize()
        t = self.tables
        daily = t["daily"][t["daily"]["day"] < cut]
        if daily.empty:
            raise ValueError(f"the snapshot holds no transactions before {cut.date()}")
        descriptions = t["descriptions"][t["descriptions"]["start_date"] < cut].set_index("campaign_id")
        campaigns = t["campaigns"][t["campaigns"]["campaign_id"].isin(descriptions.index)]
        return View(
            snapshot_id=self.snapshot_id,
            as_of=cut,
            daily=daily,
            stores=t["stores"][t["stores"]["day"] < cut],
            campaigns=campaigns,
            descriptions=descriptions,
            redemptions=t["redemptions"][t["redemptions"]["day"] < cut],
            households=np.sort(daily["household_id"].unique()),
            first_day=daily["day"].min(),
            last_day=daily["day"].max(),
        )

    def full(self) -> View:
        """The whole snapshot, as the prototype read it."""
        return self.as_of(self.end)
