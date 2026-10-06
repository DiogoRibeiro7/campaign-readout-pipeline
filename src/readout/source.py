"""Fetch the pinned source files and refuse anything that does not match its hash."""

from __future__ import annotations

import hashlib
import urllib.request
from pathlib import Path

from .contract import Source


class SourceIntegrityError(RuntimeError):
    """A source file is missing or is not the file the contract pins."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify(source: Source, raw_dir: str | Path) -> None:
    """Raise unless every pinned file is present with the pinned hash."""
    raw = Path(raw_dir)
    for name, expected in source.files.items():
        path = raw / name
        if not path.exists():
            raise SourceIntegrityError(f"{name} is missing from {raw}")
        actual = sha256(path)
        if actual != expected:
            raise SourceIntegrityError(f"{name}: SHA-256 is {actual}, the contract pins {expected}")


def fetch(source: Source, raw_dir: str | Path, timeout: float = 120.0) -> Path:
    """Download the pinned files that are not present yet, then verify all of them."""
    raw = Path(raw_dir)
    raw.mkdir(parents=True, exist_ok=True)
    for name in source.files:
        path = raw / name
        if path.exists():
            continue
        partial = path.with_suffix(path.suffix + ".part")
        with urllib.request.urlopen(source.url(name), timeout=timeout) as response:
            partial.write_bytes(response.read())
        partial.replace(path)
    verify(source, raw)
    return raw
