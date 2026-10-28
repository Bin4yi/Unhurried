"""Stores encrypted Voice Passport blobs exactly as the browser sends them.

The server never has the passphrase or key, so it cannot read a profile.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path("runs/passports")
MAX_BYTES = 256 * 1024
_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
FIELDS = {"v", "kdf", "rounds", "salt", "iv", "ct"}


class PassportError(ValueError):
    pass


def _path(pid: str, root: Path) -> Path:
    if not _ID.match(pid or ""):
        raise PassportError("bad profile id")
    return root / f"{pid}.json"


def validate(blob: dict) -> dict:
    if not isinstance(blob, dict) or set(blob) != FIELDS:
        raise PassportError("blob must have exactly: " + ", ".join(sorted(FIELDS)))
    for k in ("salt", "iv", "ct", "kdf"):
        if not isinstance(blob[k], str):
            raise PassportError(f"{k} must be a string")
    if len(json.dumps(blob)) > MAX_BYTES:
        raise PassportError("blob too large")
    return blob


def save(pid: str, blob: dict, root: Path = ROOT) -> None:
    p = _path(pid, root)
    root.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(validate(blob)), encoding="utf-8")


def load(pid: str, root: Path = ROOT) -> dict | None:
    p = _path(pid, root)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def delete(pid: str, root: Path = ROOT) -> bool:
    p = _path(pid, root)
    if p.exists():
        p.unlink()
        return True
    return False
