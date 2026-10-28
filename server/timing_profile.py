"""Personal timing: learn how long this person's pauses inside a sentence last.

Stores only pause lengths (no audio, no words).
max_wait_ms = 90th percentile of inner pauses + 1000 ms, kept in [2000, 6000].
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

MIN_WAIT_MS, MAX_WAIT_MS, DEFAULT_WAIT_MS = 2000, 6000, 6000
MARGIN_MS = 1000
KEEP = 200  # most recent pauses kept
PROFILES = Path("runs/profiles")


def percentile(values: list[int], p: float) -> float:
    """Linear-interpolated percentile, p in [0, 100]."""
    if not values:
        raise ValueError("no values")
    xs = sorted(values)
    k = (len(xs) - 1) * p / 100
    lo = int(k)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def compute_max_wait(inner_pauses_ms: list[int]) -> int:
    if not inner_pauses_ms:
        return DEFAULT_WAIT_MS
    wait = percentile(inner_pauses_ms, 90) + MARGIN_MS
    return int(max(MIN_WAIT_MS, min(MAX_WAIT_MS, round(wait))))


def _safe_id(user_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", user_id)[:64] or "u1"


@dataclass
class TimingProfile:
    user_id: str = "u1"
    inner_pauses_ms: list[int] = field(default_factory=list)
    max_wait_ms: int = DEFAULT_WAIT_MS
    updated: str = ""

    def add(self, pauses_ms: list[int]) -> None:
        self.inner_pauses_ms = (self.inner_pauses_ms + [int(p) for p in pauses_ms if p > 0])[-KEEP:]
        self.max_wait_ms = compute_max_wait(self.inner_pauses_ms)
        self.updated = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def to_json(self) -> dict:
        return {"user_id": self.user_id, "inner_pauses_ms": self.inner_pauses_ms,
                "max_wait_ms": self.max_wait_ms, "updated": self.updated}

    @classmethod
    def load(cls, user_id: str, root: Path = PROFILES) -> "TimingProfile":
        p = root / f"{_safe_id(user_id)}.json"
        if not p.exists():
            return cls(user_id=user_id)
        d = json.loads(p.read_text(encoding="utf-8"))
        return cls(user_id=d.get("user_id", user_id), inner_pauses_ms=d.get("inner_pauses_ms", []),
                   max_wait_ms=d.get("max_wait_ms", DEFAULT_WAIT_MS), updated=d.get("updated", ""))

    def save(self, root: Path = PROFILES) -> None:
        root.mkdir(parents=True, exist_ok=True)
        (root / f"{_safe_id(self.user_id)}.json").write_text(
            json.dumps(self.to_json(), indent=2), encoding="utf-8")
