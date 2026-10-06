"""The report writes its tables, its summary and its figures from a registry, whatever the registry holds."""

from __future__ import annotations

from dataclasses import replace

import pytest

from conftest import with_updates
from readout import report, worlds
from readout.registry import Registry
from readout.replay import read_out, replay, units
from readout.result import RESULT
from readout.simulate import WORLDS


@pytest.fixture(scope="module")
def longer(contract):
    return with_updates(contract, windows={"history_days": 84}).model_copy(update={"version": 2})


def test_report_from_a_full_registry(snapshot, contract, longer, tmp_path):
    registry = Registry(tmp_path / "registry")
    for used in (contract, longer):
        for shift in (0, 1):
            replay(snapshot, used, registry, shift=shift, progress=False)
    for name in ("random", "observed"):
        worlds.run_world(
            replace(WORLDS[name], households=500, campaigns=6), contract, registry.root / "worlds", replications=40
        )
    results, figures = tmp_path / "results", tmp_path / "figures"
    (results).mkdir()
    (results / "worlds_by_seed.csv").write_text("stale")  # rewritten, not kept
    (results / "prototype_to_production.csv").write_text("stale")  # no prototype here: removed
    tables = report.write([contract, longer], snapshot, registry, results, figures, prototype=None)

    present = (
        "audit_readouts",
        "pooled",
        "like_for_like",
        "spending_gap",
        "prehistory_check",
        "tolerance_sweep",
        "gate_audit",
        "worlds_by_seed",
        "worlds",
        "planning",
    )
    for name in present:
        assert not tables[name].empty, name
        assert (results / f"{name}.csv").read_text() != "stale", name
    assert not (results / "prototype_to_production.csv").exists()
    assert set(tables["audit_readouts"]["contract"]) == {"v1", "v2"}
    assert set(tables["pooled"]["shift"]) == {0, 1} and set(tables["pooled"]["history_days"]) == {56, 84}
    assert set(tables["like_for_like"]["contract"]) == {"v1", "v2"}

    # What consumers may read: the primary method of the contract in force, and nothing internal.
    public = [RESULT.validate_json(line) for line in (results / "readouts.jsonl").read_text().splitlines()]
    assert len(public) == len(registry.readouts(contract)) > 0
    assert {r.method for r in public} == {contract.method.name}
    assert {r.provenance.contract_sha256 for r in public} == {contract.sha256}

    text = (results / "RESULTS.md").read_text()
    headings = (
        "# Results",
        "## The period, read out campaign by campaign",
        "## The campaigns together",
        "## The contracts on the same campaigns",
        "## Synthetic retailers with a known effect",
        "## How long a record the gates need",
    )
    for heading in headings:
        assert heading in text, heading
    assert "From the prototype" not in text  # nothing to compare with here
    assert " nan " not in text.lower() and "| nan" not in text.lower()
    for name in ("replay.png", "pooled.png", "worlds.png", "planning.png"):
        assert (figures / name).stat().st_size > 5000, name


def _write(registry, contracts, snapshot, tmp_path):
    return report.write(contracts, snapshot, registry, tmp_path / "results", tmp_path / "figures", prototype=None)


def test_report_refuses_an_empty_registry_with_a_reason(snapshot, contract, tmp_path):
    with pytest.raises(ValueError, match="nothing is recorded"):
        _write(Registry(tmp_path / "registry"), [contract], snapshot, tmp_path)


def test_report_from_one_contract_at_launch_only(replayed, snapshot, contract, longer, tmp_path):
    tables = _write(replayed, [contract, longer], snapshot, tmp_path)  # nothing was replayed under the second contract
    assert set(tables["audit_readouts"]["contract"]) == {"v1"}
    assert tables["like_for_like"].empty and tables["gate_audit"].empty and tables["worlds"].empty
    assert not (tmp_path / "results" / "like_for_like.csv").exists()
    assert not (tmp_path / "figures" / "worlds.png").exists()
    assert "## The contracts on the same campaigns" not in (tmp_path / "results" / "RESULTS.md").read_text()


def test_report_from_earlier_windows_only(snapshot, contract, tmp_path):
    registry = Registry(tmp_path / "registry")
    replay(snapshot, contract, registry, shift=1, progress=False)
    tables = _write(registry, [contract], snapshot, tmp_path)
    assert tables["audit_readouts"].empty and tables["spending_gap"].empty and tables["planning"].empty
    assert set(tables["pooled"]["shift"]) == {1}
    assert (tmp_path / "results" / "readouts.jsonl").read_text() == ""  # nothing a consumer may read


def test_report_from_single_readouts_without_a_programme(snapshot, contract, tmp_path):
    """`readout run` records campaigns and no programme readout. The report copes."""
    registry = Registry(tmp_path / "registry")
    for unit in units(snapshot, contract)[:3]:
        read_out(snapshot, contract, registry, unit)
    assert registry.programme().empty
    tables = _write(registry, [contract], snapshot, tmp_path)
    assert set(tables["pooled"]["programme_verdict"]) == {""}
    assert len(tables["audit_readouts"]) == 3 * len(contract.methods)
