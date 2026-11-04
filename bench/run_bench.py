"""Benchmark runner: replay labeled clips through the live server at 1x speed.

Each clip goes through every config (baseline = default end-of-speech, and
Unhurried variants), over the same /listen WebSocket the browser uses.
Confirms are auto-approved and counted.

Usage (server running: python -m uvicorn server.main:app --port 8000):
  python bench/run_bench.py --set real_self --configs baseline,sound_spark
  python bench/run_bench.py --set synthetic --only syn_01
  python bench/run_bench.py --set all          (one results file per set; sets never mixed)
A failed run is retried up to 2 times; runs that still fail are listed separately.
Writes bench/results/{date}_{time}_{set}.json and prints counts like "cut-offs: 3/30".
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bench.metrics import added_delay, score_run, summarize  # noqa: E402

CONFIGS = {
    "baseline": {"mode": "baseline"},
    "words": {"mode": "unhurried", "engine": {"spark_check": False}},
    "unhurried": {"mode": "unhurried", "engine": {"spark_check": True}},
    "sound": {"mode": "unhurried", "engine": {"spark_check": False, "sound": True}},
    "sound_spark": {"mode": "unhurried", "engine": {"spark_check": True, "sound": True}},
}
SETS = ("real_self", "synthetic")
CLIP_FILES = ("bench/clips.jsonl", "bench/clips_synthetic.jsonl")
TRIES = 3
TAIL_S = 10.0         # silence after the clip (longer than 6 s max wait + speech lag)
SETTLE_S = 25.0       # max wait for the bot to finish after the audio


def load_clips(clip_set: str, only: list[str] | None) -> list[dict]:
    clips = []
    for f in CLIP_FILES:
        p = ROOT / f
        if p.exists():
            clips += [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
    clips = [c for c in clips if c.get("set") == clip_set]
    if only:
        clips = [c for c in clips if c["id"] in only]
    return [c for c in clips if (ROOT / c["file"]).exists()]


def read_pcm(path: Path) -> tuple[bytes, int]:
    with wave.open(str(path)) as w:
        return w.readframes(w.getnframes()), w.getframerate()


async def run_clip(url: str, clip: dict, name: str, cfg: dict, tag: str) -> list[dict]:
    import websockets
    pcm, rate = read_pcm(ROOT / clip["file"])
    pcm += b"\x00\x00" * int(TAIL_S * rate)
    events: list[dict] = []
    async with websockets.connect(url, max_size=None) as ws:
        sid = f"bench_{tag}_{name}_{clip['id']}"
        start_msg = {"type": "start", "bench": True, "auto_confirm": True, "session_id": sid, **cfg}
        if clip.get("bot"):
            start_msg["bot"] = clip["bot"]           # free talk goes to the general assistant
        await ws.send(json.dumps(start_msg))
        ready, turns_open = asyncio.Event(), {"turns": 0, "bots": 0, "last": time.monotonic()}

        async def rx():
            async for raw in ws:
                ev = json.loads(raw)
                events.append(ev)
                if ev["type"] == "ready":
                    ready.set()
                elif ev["type"] == "sending":
                    turns_open["turns"] += 1
                elif ev["type"] == "bot":
                    turns_open["bots"] += 1
                turns_open["last"] = time.monotonic()
                if ev["type"] == "stopped":
                    return

        reader = asyncio.create_task(rx())
        await asyncio.wait_for(ready.wait(), 20)
        step = int(rate * 0.08) * 2
        start = time.monotonic()
        for k, i in enumerate(range(0, len(pcm), step)):
            await ws.send(pcm[i:i + step])
            wait = start + (k + 1) * 0.08 - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
        # Keep streaming silence while the bot finishes (the speech service closes
        # the stream if audio stops arriving).
        deadline = time.monotonic() + SETTLE_S
        silence = bytes(2 * int(rate * 0.08))
        while turns_open["bots"] < turns_open["turns"] and time.monotonic() < deadline:
            await ws.send(silence)
            await asyncio.sleep(0.08)
        await ws.send(json.dumps({"type": "stop"}))
        try:
            await asyncio.wait_for(reader, 40)
        except asyncio.TimeoutError:
            reader.cancel()
    return events


def spent_usd(since: int) -> float:
    p = ROOT / "runs/llm_calls.jsonl"
    if not p.exists():
        return 0.0
    with p.open("rb") as f:
        f.seek(since)
        return sum(json.loads(x).get("usd", 0) for x in f.read().decode().splitlines() if x.strip())


async def main_async(args) -> int:
    sets = SETS if args.set == "all" else (args.set,)
    for clip_set in sets:
        clips = load_clips(clip_set, args.only.split(",") if args.only else None)
        if not clips:
            print(f"No clips in set {clip_set} (check bench/clips*.jsonl and the audio files).")
            continue
        await run_set(args, clip_set, clips)
    return 0


async def run_set(args, clip_set: str, clips: list[dict]) -> None:
    names = [n.strip() for n in args.configs.split(",")]
    tag = f"{time.strftime('%Y%m%d_%H%M%S')}_{clip_set}"
    log_path = ROOT / "runs/llm_calls.jsonl"
    cost_start = log_path.stat().st_size if log_path.exists() else 0
    sem = asyncio.Semaphore(args.parallel)
    rows: dict[str, list[dict]] = {n: [] for n in names}
    stop = {"flag": False}

    async def one(clip, name):
        async with sem:
            if stop["flag"]:
                return
            row = None
            for attempt in range(1, TRIES + 1):
                try:
                    events = await run_clip(args.url, clip, name, CONFIGS[name], f"{tag}_{attempt}")
                    row = {**score_run(clip, events), "attempts": attempt}
                    break
                except Exception as exc:
                    row = {"clip": clip["id"], "kind": clip["kind"], "error": repr(exc), "attempts": attempt}
                    await asyncio.sleep(2)
            rows[name].append(row)
            usd = spent_usd(cost_start)
            flag = f"CUT x{row.get('cut_ins')}" if row.get("cut_off") else "      "
            ok = "OK " if row.get("understood") else "-- "
            print(f"[{name:>9}] {clip['id']:<8} {flag} {ok} turns={row.get('turns')} "
                  f"delay={row.get('delay_s')} ${usd:.3f}", flush=True)
            if args.max_usd and usd > args.max_usd:
                stop["flag"] = True
                print(f"Stopping: spent ${usd:.2f} > --max-usd {args.max_usd}")

    await asyncio.gather(*[one(c, n) for c in clips for n in names])

    good = {n: [r for r in rs if "error" not in r] for n, rs in rows.items()}
    failed = [{"config": n, **r} for n, rs in rows.items() for r in rs if "error" in r]
    summary = {n: summarize(rs) for n, rs in good.items()}
    if "baseline" in good:
        for n in names:
            if n != "baseline":
                summary[n]["added_delay_vs_baseline"] = added_delay(good["baseline"], good[n])
    result = {"run": tag, "set": clip_set, "date": time.strftime("%Y-%m-%d %H:%M"), "failed": failed,
              "configs": {n: CONFIGS[n] for n in names}, "summary": summary, "rows": rows,
              "usd": round(spent_usd(cost_start), 4)}
    out = ROOT / "bench/results" / f"{tag}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")

    print(f"\nResults, set {clip_set} ({len(clips)} clips, small set) -> {out.relative_to(ROOT)}")
    for n, s in summary.items():
        line = (f"{n:>11}: cut-offs {s['cut_offs']}/{s['stammer_clips']} clips ({s['cut_ins']} replies "
                f"while still talking)  early end-of-speech {s['early_eos_stammer']}  "
                f"understood {s['understood']}/{s['understanding_clips']}  "
                f"fluent delay median {s['fluent_delay_median_s']} s  "
                f"invented {s['invented_turns']}/{s['turns']} turns  "
                f"slow runs {s['slow_runs']}")
        if "added_delay_vs_baseline" in s:
            line += f"  added delay median {s['added_delay_vs_baseline']['median_s']} s"
        print(line)
    if failed:
        print(f"{len(failed)} runs failed after {TRIES} tries: " +
              ", ".join(f"{f['config']}/{f['clip']}" for f in failed))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--set", default="real_self", choices=[*SETS, "all"])
    p.add_argument("--only", help="comma-separated clip ids")
    p.add_argument("--configs", "--mode", dest="configs", default="baseline,unhurried",
                   help="comma-separated: " + ", ".join(CONFIGS))
    p.add_argument("--url", default="ws://127.0.0.1:8000/listen")
    p.add_argument("--parallel", type=int, default=2,
                   help="clips at once; more than 3 made speech results slow and noisy")
    p.add_argument("--max-usd", type=float, default=0.0)
    return asyncio.run(main_async(p.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
