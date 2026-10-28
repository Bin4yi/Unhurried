"""Compare two Meta models on the same turns: Muse Spark vs Muse Glimmer.

Uses the decision points of a benchmark run (text at each pause) with labels
taken from the clips themselves: a pause the person spoke after was NOT the
end ("no"); the final text was the end ("yes"). For each model it measures:
  completeness check correct (vs these labels), median / p95 time per call,
  rebuild changes that pass the no-new-content guard.

Glimmer runs on any OpenAI-compatible host: set GLIMMER_BASE_URL,
GLIMMER_API_KEY, GLIMMER_MODEL (e.g. Fireworks, Together, OpenRouter, Ollama).

Usage: python bench/compare_models.py [bench/results/<run>.json] [--models spark,glimmer]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bench.metrics import pct  # noqa: E402
from server.completeness import check_complete  # noqa: E402
from server.rebuild import rebuild  # noqa: E402

REBUILD_CASES = [  # self-corrections: the guard decides if the result is safe
    "A table for two, no, three people at seven on Sunday",
    "Book for Friday, I mean Saturday, at eight",
    "Book a table for four, actually make it five, on Sunday",
    "Can I, sorry, can we book a table for two at nine tonight",
    "Book a table at seven, no wait, at half past seven on Friday",
    "I want a table for six, sorry, for five at eight on Thursday",
]


def decision_points(run: dict) -> list[tuple[str, str]]:
    """(text so far, label) from the 'words' or 'unhurried' run's session logs."""
    points: list[tuple[str, str]] = []
    for name in ("words", "unhurried", "baseline"):
        for row in run["rows"].get(name, []):
            if "error" in row:
                continue
            d = ROOT / "runs" / f"bench_{run['run']}_{name}_{row['clip']}" / "events.jsonl"
            if not d.exists():
                continue
            texts = [json.loads(x)["text"] for x in d.read_text(encoding="utf-8").splitlines()
                     if '"model_turn"' in x and '"dir": "in"' in x]
            texts = [t for t in texts if t]
            for i in range(len(texts)):
                points.append((" ".join(texts[: i + 1]), "yes" if i == len(texts) - 1 else "no"))
        if points:
            break
    return sorted(set(points))


async def run_model(provider: str, points: list[tuple[str, str]]) -> dict:
    sem = asyncio.Semaphore(4)

    async def check(text):
        async with sem:
            return await check_complete(text, provider=provider)

    results = await asyncio.gather(*[check(t) for t, _ in points])
    correct = sum(a == label for (a, _), (_, label) in zip(results, points))
    ms = [m for a, m in results if a not in ("error",)]
    errors = sum(a == "error" for a, _ in results)

    async def rb(text):
        async with sem:
            return await rebuild(text, provider=provider)

    rebuilt = await asyncio.gather(*[rb(t) for t in REBUILD_CASES])
    passed = sum(1 for r in rebuilt if not r["guard_fails"] and not (r.get("spark") or {}).get("error"))
    rb_ms = [r["spark"]["ms"] for r in rebuilt if r.get("spark") and "ms" in r["spark"]]
    return {
        "check_correct": correct, "check_total": len(points), "check_errors": errors,
        "check_ms_median": round(statistics.median(ms)) if ms else None, "check_ms_p95": pct(ms, 95),
        "rebuild_passed_guard": passed, "rebuild_total": len(REBUILD_CASES),
        "rebuild_ms_median": round(statistics.median(rb_ms)) if rb_ms else None,
        "rebuild_examples": [{"raw": r["raw"], "clean": r["clean"], "guard_fails": r["guard_fails"]}
                             for r in rebuilt],
    }


async def main_async(args) -> int:
    files = sorted((ROOT / "bench/results").glob("2*.json"))
    path = Path(args.results) if args.results else (files[-1] if files else None)
    if not path:
        print("No benchmark results yet.")
        return 1
    run = json.loads(path.read_text(encoding="utf-8"))
    points = decision_points(run)
    print(f"{len(points)} decision points from {path.name}")
    out = {"source": path.name, "points": len(points), "models": {}}
    for m in args.models.split(","):
        if m == "glimmer" and not os.environ.get("GLIMMER_BASE_URL"):
            out["models"][m] = {"skipped": "GLIMMER_BASE_URL not set"}
            print("glimmer: skipped (set GLIMMER_BASE_URL, GLIMMER_API_KEY, GLIMMER_MODEL)")
            continue
        res = await run_model(m, points)
        out["models"][m] = res
        print(f"{m}: check correct {res['check_correct']}/{res['check_total']} "
              f"(median {res['check_ms_median']} ms, p95 {res['check_ms_p95']} ms), "
              f"rebuild passed guard {res['rebuild_passed_guard']}/{res['rebuild_total']}")
    dest = ROOT / "bench/results" / f"models_{path.stem}.json"
    dest.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"-> {dest.relative_to(ROOT)}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("results", nargs="?")
    p.add_argument("--models", default="spark,glimmer")
    return asyncio.run(main_async(p.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
