"""The command line, and the exit status a scheduler acts on."""

from __future__ import annotations

import json

import pandas as pd
import pytest

from conftest import CONTRACT_PATH
from readout import cli
from readout.registry import Registry
from readout.snapshot import Snapshot


@pytest.fixture(scope="module")
def workspace(plain_snapshot, tmp_path_factory):
    root = tmp_path_factory.mktemp("workspace")
    plain_snapshot.save(root / "snapshot")
    lenient = root / "lenient.toml"
    lenient.write_text(CONTRACT_PATH.read_text().replace("placebo_usd = 5.0", "placebo_usd = 1000000.0"))
    assert "1000000.0" in lenient.read_text()
    return root


def _args(workspace, contract=CONTRACT_PATH, registry="registry", snapshot="snapshot"):
    return [
        "--contract", str(contract), "--snapshot", str(workspace / snapshot), "--registry", str(workspace / registry),
        "--results", str(workspace / "results"), "--figures", str(workspace / "figures"), "--replications", "40",
    ]  # fmt: skip


def test_a_refused_readout_exits_with_its_own_status(workspace, capsys):
    status = cli.main([*_args(workspace), "run", "--campaign", "4"])
    printed = json.loads(capsys.readouterr().out)
    assert status == cli.EXIT_REFUSED == 3
    assert printed["kind"] == "refused" and "effect" not in printed
    registry = Registry(workspace / "registry")
    assert [r.campaign_id for r in registry.readouts()] == [4]
    assert set(registry.audit()["method"]) == {"weighting", "regression"}  # the shadow method ran too


def test_a_published_readout_exits_with_zero(workspace, capsys):
    status = cli.main([*_args(workspace, workspace / "lenient.toml", "registry_lenient"), "run", "--campaign", "4"])
    printed = json.loads(capsys.readouterr().out)
    assert status == cli.EXIT_PUBLISHED == 0
    assert printed["kind"] == "published" and printed["effect"]["low"] <= printed["effect"]["high"]


def test_running_the_same_readout_again_prints_the_recorded_answer(workspace, capsys):
    arguments = [*_args(workspace, registry="registry_twice"), "run", "--campaign", "3"]
    first_status = cli.main(arguments)
    first = capsys.readouterr().out
    before = (workspace / "registry_twice" / "audit.jsonl").read_text()
    assert cli.main(arguments) == first_status
    assert capsys.readouterr().out == first
    assert (workspace / "registry_twice" / "audit.jsonl").read_text() == before


def test_a_readout_that_is_not_due_has_its_own_status_and_leaves_no_trace(workspace, plain_snapshot, capsys):
    tables = {
        n: (t[t["day"] < plain_snapshot.last_day - pd.Timedelta(days=5)] if "day" in t else t).copy()
        for n, t in plain_snapshot.tables.items()
    }
    Snapshot.from_tables(tables, {"cut": "short"}).save(workspace / "short")
    status = cli.main([*_args(workspace, registry="registry_short", snapshot="short"), "run", "--campaign", "6"])
    assert status == cli.EXIT_NOT_DUE == 4
    assert "falls due" in capsys.readouterr().err
    assert Registry(workspace / "registry_short").audit().empty


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (["run", "--campaign", "999"], "not in the snapshot"),
        (["--snapshot", "no/such/place", "run", "--campaign", "4"], "FileNotFoundError"),
        (["--contract", "no/such/contract.toml", "replay"], "FileNotFoundError"),
        (["worlds", "--only", "atlantis"], "unknown worlds"),
        (["--registry", "{empty}", "report"], "nothing is recorded"),
        (["check", "--reference", "no/such/reference"], "no reference tables"),
    ],
)
def test_errors_exit_with_two_and_a_message(workspace, capsys, arguments, message):
    arguments = [a.replace("{empty}", str(workspace / "registry_empty")) for a in arguments]
    base = _args(workspace)
    # Options given in the case replace the defaults of the workspace.
    given = {a for a in arguments if a.startswith("--")}
    kept = [x for i in range(0, len(base), 2) if base[i] not in given for x in base[i : i + 2]]
    command = next(i for i, a in enumerate(arguments) if a in cli.HANDLERS)
    status = cli.main([*kept, *arguments[:command], *arguments[command:]])
    assert status == cli.EXIT_ERROR == 2
    assert message in capsys.readouterr().err


def test_bad_arguments_are_refused_by_the_parser(capsys):
    for arguments in (
        ["--replications", "0", "replay"],
        ["--replications", "1", "replay"],
        ["replay", "--shift", "-1"],
        ["--jobs", "0", "worlds"],
    ):
        with pytest.raises(SystemExit) as stopped:
            cli.main(arguments)
        assert stopped.value.code == 2
    capsys.readouterr()


def test_replay_then_run_changes_nothing(workspace, capsys):
    registry = workspace / "registry_replay"
    assert cli.main([*_args(workspace, registry=registry), "replay", "--shift", "0"]) == 0
    before = (registry / "audit.jsonl").read_text()
    cli.main([*_args(workspace, registry=registry), "run", "--campaign", "6"])
    assert cli.main([*_args(workspace, registry=registry), "replay", "--shift", "0"]) == 0
    assert (registry / "audit.jsonl").read_text() == before
    capsys.readouterr()


def test_schema_is_printed_or_written_one_file_per_type(workspace, capsys):
    out = workspace / "schema"
    assert cli.main(["schema", "--out", str(out)]) == 0
    assert sorted(p.name for p in out.iterdir()) == ["programme.schema.json", "readout.schema.json"]
    readout = json.loads((out / "readout.schema.json").read_text())
    assert set(readout["discriminator"]["mapping"]) == {"published", "refused"} and "$defs" in readout
    assert cli.main(["schema"]) == 0
    assert set(json.loads(capsys.readouterr().out)) == {"readout", "programme"}


def test_check_compares_tables_within_a_tolerance(tmp_path, capsys):
    new, ref = tmp_path / "new", tmp_path / "ref"
    new.mkdir(), ref.mkdir()
    table = pd.DataFrame({"method": ["a", "b"], "value": [1.0, float("inf")], "count": [3, 4]})
    table.to_csv(ref / "t.csv", index=False)

    def check() -> int:
        return cli.main(["--results", str(new), "check", "--reference", str(ref)])

    table.assign(value=[1.0 + 1e-6, float("inf")]).to_csv(new / "t.csv", index=False)
    assert check() == 0
    table.assign(value=[1.1, float("inf")]).to_csv(new / "t.csv", index=False)
    assert check() == cli.EXIT_ERROR and "DIFFERS in value" in capsys.readouterr().out
    table.assign(method=["a", "c"]).to_csv(new / "t.csv", index=False)
    assert check() == cli.EXIT_ERROR
    table.assign(count=[3, 5]).to_csv(new / "t.csv", index=False)
    assert check() == cli.EXIT_ERROR
    table.to_csv(new / "t.csv", index=False)
    table.to_csv(new / "extra.csv", index=False)  # a table the reference does not have
    assert check() == cli.EXIT_ERROR and "only in" in capsys.readouterr().out
    (new / "extra.csv").unlink()
    (new / "t.csv").unlink()  # a table the new run did not write
    assert check() == cli.EXIT_ERROR
    capsys.readouterr()


def test_worlds_in_parallel_then_report(workspace, capsys):
    """Two tiny worlds in two processes, then the report with nothing published and no real replay of shift 1."""
    base = [
        *_args(workspace, registry="registry_worlds"),
        "--households",
        "400",
        "--campaigns",
        "5",
        "--seeds",
        "0",
        "--world-replications",
        "30",
        "--jobs",
        "2",
    ]
    assert cli.main([*base, "worlds", "--only", "random", "observed"]) == 0
    assert cli.main([*base, "replay", "--shift", "0"]) == 0
    assert cli.main([*base, "--prototype", "no/such/file.json", "report"]) == 0
    text = (workspace / "results" / "RESULTS.md").read_text()
    assert "## Synthetic retailers with a known effect" in text and "From the prototype" not in text
    assert (workspace / "figures" / "worlds.png").stat().st_size > 5000
    # Running the worlds again with other settings would mix two audits in one place.
    assert (
        cli.main([*base[:-2], "--jobs", "1", "--world-replications", "20", "worlds", "--only", "random"])
        == cli.EXIT_ERROR
    )
    assert "other settings" in capsys.readouterr().err
