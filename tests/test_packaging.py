"""The version is stated in three places, and they agree."""

from __future__ import annotations

import re
import tomllib

import readout
from conftest import ROOT


def test_one_version_everywhere():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    citation = re.search(r"^version: (.+)$", (ROOT / "CITATION.cff").read_text(), re.MULTILINE).group(1)
    assert readout.__version__ == project == citation


def test_the_shipped_contracts_are_the_default_of_the_command_line():
    from readout import cli

    assert [ROOT / path for path in cli.DEFAULT_CONTRACTS] == sorted((ROOT / "contracts").glob("*.toml"))
