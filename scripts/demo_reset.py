"""Reset the app before a demo take. Run in PowerShell:  python scripts/demo_reset.py

Clears live session logs, bookings and server-side timing profiles, and loads a clean
demo booking list. Keeps your Voice Studio recordings (studio_data/), the benchmark
results and the call cost log. No real user data is created.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "runs"
KEEP = {"llm_calls.jsonl", "old_results"}
DEMO_BOOKINGS = [
    {"id": "b1", "people": 2, "time": "19:00", "day": "friday"},
    {"id": "b2", "people": 4, "time": "12:30", "day": "sunday"},
]
PAGES = [
    ("Live Studio", "http://127.0.0.1:8000/web/studio.html?demo=1"),
    ("Voice Studio", "http://127.0.0.1:8000/web/voice-studio.html?demo=1"),
    ("Voice-over (editing on/off)", "http://127.0.0.1:8000/web/voice-over.html?demo=1"),
    ("Clip demo", "http://127.0.0.1:8000/web/demo.html?demo=1"),
    ("Results", "http://127.0.0.1:8000/bench/results.html?demo=1"),
]


def main() -> int:
    removed = 0
    if RUNS.exists():
        for p in RUNS.iterdir():
            if p.name in KEEP:
                continue
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            else:
                p.unlink(missing_ok=True)
            removed += 1
    RUNS.mkdir(exist_ok=True)
    (RUNS / "bookings.json").write_text(json.dumps(DEMO_BOOKINGS, indent=2), encoding="utf-8")
    print(f"Cleared {removed} session items. Loaded {len(DEMO_BOOKINGS)} demo bookings.")
    print("Kept: Voice Studio recordings, benchmark results, cost log.\n")
    print("Restart the server if it is running, then open (Chrome, 1920x1080, 100% zoom):")
    for name, url in PAGES:
        print(f"  {name:<28} {url}")
    print("\nHeadphones on. The mic sends silence while the assistant speaks, but speakers can still leak.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
