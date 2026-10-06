"""Where readouts are kept: an append-only record in which the first answer stands.

Four things are stored under one directory.

``readouts.jsonl``   what consumers may read: one published estimate or one
                     refusal per line, for the primary method of a contract.
``audit.jsonl``      the internal trail: every measurement of every readout,
                     including the estimates that were not published and the
                     methods that ran in shadow. It exists so that the
                     pipeline itself can be examined.
``programme.jsonl``  the programme readouts: the campaigns taken together.
``draws/``           bootstrap draws of the effect and of the two placebos,
                     one file per readout, aligned by replication. The gates
                     read them when a later readout consults the record.

A readout is identified by its contract, method, campaign and shift. It is
recorded once. Recording it again is accepted if it says the same thing, up to
the last digits of its numbers, and is an error if it does not: a later run
cannot quietly replace an earlier answer.
"""

from __future__ import annotations

import contextlib
import json
import math
import os
from pathlib import Path

import numpy as np
import pandas as pd

from .contract import Contract, Method
from .features import ROLES
from .pipeline import PLACEBOS, Assessment, History, RecordEntry, Unit
from .result import PROGRAMME_RESULT, RESULT, ProgrammePublished, ProgrammeRefused, Published, Refused

try:  # advisory locks exist on POSIX only
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None


class RegistryConflict(RuntimeError):
    """A readout was recorded again with a different content."""


def readout_key(contract: Contract, method: str, campaign: int, shift: int) -> str:
    return f"{contract.sha256[:12]}.{method}.c{campaign:02d}.s{shift}"


def _same(a, b) -> bool:
    """Equal, allowing numbers to differ in their last digits and ignoring where the run happened."""
    if isinstance(a, dict) and isinstance(b, dict):
        keys = (set(a) | set(b)) - {"provenance", "view_id"}
        return all(key in a and key in b and _same(a[key], b[key]) for key in keys)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b, strict=True))
    if isinstance(a, float) or isinstance(b, float):
        if (
            not isinstance(a, int | float)
            or not isinstance(b, int | float)
            or isinstance(a, bool)
            or isinstance(b, bool)
        ):
            return False
        return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)
    return a == b


class Registry:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.draws_dir = self.root / "draws"
        self.draws_dir.mkdir(parents=True, exist_ok=True)
        self.readouts_path = self.root / "readouts.jsonl"
        self.audit_path = self.root / "audit.jsonl"
        self.programme_path = self.root / "programme.jsonl"

    # ---- writing -----------------------------------------------------------------
    @contextlib.contextmanager
    def _locked(self):
        """One writer at a time, so that two readouts cannot both pass the check and both append."""
        with (self.root / ".lock").open("w") as handle:
            if fcntl is not None:
                fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(handle, fcntl.LOCK_UN)

    @staticmethod
    def _lines(path: Path) -> list[dict]:
        """The complete lines of a file. A last line cut short by a crash is not one."""
        if not path.exists():
            return []
        text = path.read_text(encoding="utf-8")
        complete = text[: text.rfind("\n") + 1]
        return [json.loads(line) for line in complete.splitlines()]

    def _append(self, path: Path, key: str, record: dict) -> bool:
        """Append unless the key is present; raise if it is present with other content."""
        line = json.dumps({"key": key, **record}, sort_keys=True, allow_nan=False)
        with self._locked():
            for existing in self._lines(path):
                if existing["key"] == key:
                    if not _same(existing, json.loads(line)):
                        raise RegistryConflict(f"{path.name}: {key} is already recorded with different content")
                    return False
            if path.exists():
                text = path.read_bytes()
                if text and not text.endswith(b"\n"):  # drop what a crash left of a line
                    path.write_bytes(text[: text.rfind(b"\n") + 1])
            with path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(line + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        return True

    def record(self, assessment: Assessment, contract: Contract, publish: bool) -> str:
        """Store an assessment. ``publish`` is False for shadow methods and for audits."""
        a = assessment
        key = readout_key(contract, a.method.name, a.unit.campaign, a.unit.shift)
        failed = [o for o in a.gates if not o.passed]
        audit = {
            "contract_sha256": contract.sha256,
            "method": a.method.name,
            "primary": a.method.name == contract.method.name,
            "campaign": a.unit.campaign,
            "campaign_type": a.unit.campaign_type,
            "shift": a.unit.shift,
            "launch": str(a.unit.launch.date()),
            "anchor": str(a.unit.anchor(contract.windows.outcome_days).date()),
            "as_of": str(a.as_of.date()),
            "view_id": a.result.provenance.view_id,
            "treated": a.treated,
            "controls": a.controls,
            "verdict": a.result.kind,
            "failed_gates": [o.gate for o in failed],
            "codes": [o.code for o in failed],
            "valid_placebo": a.valid_placebo,
            "documented": contract.assignment.documented,
            **{role: a.estimates[role].model_dump() if role in a.estimates else None for role in ROLES},
            **{
                f"{placebo}_record": a.records[placebo].model_dump() if placebo in a.records else None
                for placebo in PLACEBOS
            },
            "diagnostics": a.diagnostics,
            "gates": [o.model_dump() for o in a.gates],
        }
        if a.draws and not self.recorded(key):
            partial = self.draws_dir / f"{key}.part.npz"
            np.savez_compressed(partial, **a.draws)
            partial.replace(self.draws_dir / f"{key}.npz")
        self._append(self.audit_path, key, audit)
        if publish:
            self._append(self.readouts_path, key, RESULT.dump_python(a.result, mode="json"))
        return key

    @staticmethod
    def _programme_key(contract: Contract, method: str, shift: int, day) -> str:
        return f"{contract.sha256[:12]}.{method}.s{shift}.{pd.Timestamp(day).date()}"

    def record_programme(
        self, result: ProgrammePublished | ProgrammeRefused, contract: Contract, shift: int = 0
    ) -> None:
        key = self._programme_key(contract, result.method, shift, result.as_of)
        self._append(self.programme_path, key, {"shift": shift, **PROGRAMME_RESULT.dump_python(result, mode="json")})

    def programme_recorded(self, contract: Contract, method: str, shift: int, day) -> bool:
        key = self._programme_key(contract, method, shift, day)
        return any(line["key"] == key for line in self._lines(self.programme_path))

    # ---- reading -----------------------------------------------------------------
    def recorded(self, key: str) -> bool:
        return any(line["key"] == key for line in self._lines(self.audit_path))

    def stored(self, key: str) -> Published | Refused | None:
        """The public result recorded under ``key``, if there is one."""
        for line in self._lines(self.readouts_path):
            if line["key"] == key:
                return RESULT.validate_python({k: v for k, v in line.items() if k != "key"})
        return None

    def audit(self, contract: Contract | None = None) -> pd.DataFrame:
        """The internal trail, of one contract if given."""
        frame = pd.DataFrame(self._lines(self.audit_path))
        if contract is not None and not frame.empty:
            frame = frame[frame["contract_sha256"] == contract.sha256]
        return frame

    def readouts(self, contract: Contract | None = None) -> list[Published | Refused]:
        """What consumers may read, of one contract if given."""
        out = []
        for line in self._lines(self.readouts_path):
            result = RESULT.validate_python({k: v for k, v in line.items() if k != "key"})
            if contract is None or result.provenance.contract_sha256 == contract.sha256:
                out.append(result)
        return out

    def programme(self, contract: Contract | None = None) -> pd.DataFrame:
        """The programme readouts, of one contract if given."""
        frame = pd.DataFrame(self._lines(self.programme_path))
        if contract is not None and not frame.empty:
            frame = frame[frame["provenance"].map(lambda p: p["contract_sha256"] == contract.sha256)]
        return frame

    def draws(self, key: str) -> dict[str, np.ndarray]:
        with np.load(self.draws_dir / f"{key}.npz") as stored:
            return {role: stored[role] for role in ROLES}

    def valid_units(self, contract: Contract, method: Method, shift: int, until: Unit | None = None) -> pd.DataFrame:
        """Audit rows of the units whose placebos may enter the record, oldest anchor first.

        With ``until``, only the units anchored before it: on the same day,
        those with a lower campaign number.
        """
        audit = self.audit(contract)
        if audit.empty:
            return audit
        rows = audit[(audit["method"] == method.name) & (audit["shift"] == shift) & audit["valid_placebo"]]
        if until is not None:
            anchor = str(until.anchor(contract.windows.outcome_days).date())
            earlier = (rows["anchor"] < anchor) | ((rows["anchor"] == anchor) & (rows["campaign"] < until.campaign))
            rows = rows[earlier]
        return rows.sort_values(["anchor", "campaign"])

    def record_history(self, contract: Contract, method: Method, unit: Unit) -> History:
        """For each placebo, the valid estimates of the units anchored before ``unit``, oldest first."""
        rows = self.valid_units(contract, method, unit.shift, until=unit)
        history: History = {placebo: [] for placebo in PLACEBOS}
        for row in rows.itertuples():
            stored = self.draws(row.key)
            for placebo in PLACEBOS:
                entry = RecordEntry(int(row.campaign), float(getattr(row, placebo)["estimate"]), stored[placebo])
                history[placebo].append(entry)
        return history
