"""Voice-over helpers: recent recordings, time mapping between the original and the
clean version, and before/after (A/B) clips for the demo video.
"""

from __future__ import annotations

import json
import re

import numpy as np

from server.studio import jobs, render

GAP_S = 0.7          # silence between "before" and "after" in an A/B clip


def recent(limit: int = 20) -> list[dict]:
    """Recordings on this machine, newest first (no audio, just a short preview)."""
    out = []
    if not jobs.DATA.exists():
        return out
    for d in jobs.DATA.iterdir():
        if not re.fullmatch(r"[a-f0-9]{16}", d.name) or not (d / "job.json").exists():
            continue
        j = json.loads((d / "job.json").read_text(encoding="utf-8"))
        out.append({"id": j["id"], "created": j.get("created", 0), "duration": j.get("duration"),
                    "source": j.get("source"), "preview": (j.get("transcript") or "")[:90],
                    "cuts": sum(1 for e in j.get("edits", []) if e.get("on")),
                    "clean_ready": (d / "clean.wav").exists()})
    return sorted(out, key=lambda r: r["created"], reverse=True)[:limit]


def to_clean_time(t: float, omap: list[dict]) -> float:
    """Original time -> clean time. Inside a cut, jump to where the next kept part starts."""
    for seg in omap:
        a, b = seg["src"]
        if t < a:
            return seg["dst"]
        if t <= b:
            return seg["dst"] + (t - a)
    last = omap[-1] if omap else None
    return last["dst"] + (last["src"][1] - last["src"][0]) if last else 0.0


def to_original_time(t: float, omap: list[dict]) -> float:
    """Clean time -> original time."""
    for seg in omap:
        a, b = seg["src"]
        if t <= seg["dst"] + (b - a):
            return a + max(0.0, t - seg["dst"])
    return omap[-1]["src"][1] if omap else 0.0


def ab_clip(job: dict, start: float, seconds: float) -> bytes:
    """'Before' (original from start, for `seconds`), a short silence, then the same
    words 'after' (clean). Only the person's own audio."""
    d = jobs._dir(job["id"])
    x, rate = render.read_wav_bytes((d / "original.wav").read_bytes())
    seconds = max(3.0, min(30.0, seconds))
    start = max(0.0, min(start, len(x) / rate - 1.0))
    end = min(len(x) / rate, start + seconds)
    clean = render.render(x, rate, job["edits"])
    omap = render.output_map(len(x) / rate, job["edits"])
    c0, c1 = to_clean_time(start, omap), to_clean_time(end, omap)
    before = x[int(start * rate):int(end * rate)]
    after = clean[int(c0 * rate):int(c1 * rate)]
    gap = np.zeros(int(GAP_S * rate), dtype=np.float32)
    return render.wav_bytes(np.concatenate([before, gap, after]), rate)
