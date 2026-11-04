"""Add Voice Studio recordings (your own voice, recorded live) to the real benchmark set.

Free talk is where stammering happens, so these are the real_self clips. Each one is
copied to bench/audio/real_self/talk_XX.wav. The real end of speech is measured from
the audio (last 20 ms frame clearly above the room level), not guessed by a model.

Usage (PowerShell):  python bench/import_studio.py
                     python bench/import_studio.py --ids e955797e817a8234,684bb117e8f542d8
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
CLIPS = ROOT / "bench/clips.jsonl"
OUT = ROOT / "bench/audio/real_self"
STUDIO = ROOT / "studio_data"


def speech_end(path: Path) -> float:
    with wave.open(str(path)) as w:
        rate = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float32) / 32768
    hop = int(0.02 * rate)
    rms = np.sqrt((x[: len(x) // hop * hop].reshape(-1, hop) ** 2).mean(axis=1))
    loud = np.nonzero(rms > max(0.01, 4 * np.percentile(rms, 10)))[0]
    return round(float((loud[-1] + 1) * 0.02), 2) if len(loud) else 0.0


def load_rows() -> list[dict]:
    return [json.loads(x) for x in CLIPS.read_text(encoding="utf-8").splitlines() if x.strip()] \
        if CLIPS.exists() else []


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ids", help="comma-separated Voice Studio recording ids (default: all live ones)")
    args = ap.parse_args()
    rows = load_rows()
    done = {r.get("source_job") for r in rows}
    n = max([int(r["id"].split("_")[1]) for r in rows if r["id"].startswith("talk_")] + [0])
    wanted = set(args.ids.split(",")) if args.ids else None
    OUT.mkdir(parents=True, exist_ok=True)
    added = []
    for d in sorted(STUDIO.glob("*/job.json"), key=lambda p: json.loads(p.read_text())["created"]):
        job = json.loads(d.read_text(encoding="utf-8"))
        if job["id"] in done or (wanted and job["id"] not in wanted):
            continue
        if job.get("source") != "mic":
            print(f"skip {job['id']}: uploaded, not recorded live in Voice Studio")
            continue
        n += 1
        cid = f"talk_{n:02d}"
        dst = OUT / f"{cid}.wav"
        shutil.copyfile(d.parent / "original.wav", dst)
        row = {"id": cid, "set": "real_self", "file": f"bench/audio/real_self/{cid}.wav", "kind": "talk",
               "features": [], "speech_end_s": speech_end(dst), "expected": {}, "bot": "assistant",
               "script": (job.get("transcript") or "")[:300], "consent": "self", "public_audio": True,
               "mode": "free_talk", "source_job": job["id"]}
        rows.append(row)
        added.append(row)
        print(f"added {cid}: {job['duration']:.1f} s, speech ends at {row['speech_end_s']} s")
    CLIPS.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    print(f"{len(added)} recordings added to the real_self set.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
