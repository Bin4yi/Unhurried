"""Per-session JSON-lines logs in runs/{session}/."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

RUNS = Path("runs")


def new_session_id(prefix: str = "s") -> str:
    return f"{prefix}_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"


class RunLog:
    def __init__(self, session_id: str, root: Path = RUNS):
        self.dir = root / session_id
        self.dir.mkdir(parents=True, exist_ok=True)

    def write(self, name: str, row: dict) -> None:
        with (self.dir / f"{name}.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
