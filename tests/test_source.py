"""The source files are the pinned ones or the pipeline does not start."""

from __future__ import annotations

import hashlib

import pytest

from readout import source
from readout.contract import Source


def _pinned(tmp_path, content: bytes = b"transactions") -> Source:
    (tmp_path / "a.rds").write_bytes(content)
    return Source(repository="owner/repo", commit="0" * 40, files={"a.rds": hashlib.sha256(content).hexdigest()})


def test_verify_accepts_the_pinned_file(tmp_path):
    source.verify(_pinned(tmp_path), tmp_path)


def test_verify_refuses_a_changed_file(tmp_path):
    pinned = _pinned(tmp_path)
    (tmp_path / "a.rds").write_bytes(b"transactions, edited")
    with pytest.raises(source.SourceIntegrityError, match="SHA-256"):
        source.verify(pinned, tmp_path)


def test_verify_refuses_a_missing_file(tmp_path):
    pinned = _pinned(tmp_path)
    (tmp_path / "a.rds").unlink()
    with pytest.raises(source.SourceIntegrityError, match="missing"):
        source.verify(pinned, tmp_path)


def test_fetch_does_not_download_what_is_present(tmp_path, monkeypatch):
    pinned = _pinned(tmp_path)

    def no_network(*args, **kwargs):
        raise AssertionError("fetch went to the network for a file that is present")

    monkeypatch.setattr(source.urllib.request, "urlopen", no_network)
    assert source.fetch(pinned, tmp_path) == tmp_path


def test_url_is_pinned_to_the_commit():
    pinned = Source(repository="owner/repo", commit="a" * 40, files={})
    assert pinned.url("x.rds") == f"https://raw.githubusercontent.com/owner/repo/{'a' * 40}/data/x.rds"
