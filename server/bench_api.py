"""Benchmark clip recording endpoints (used by bench/record.html).

Real-session clips (own voice, set "real_self") go to bench/audio/real_self/ (git-ignored).
Other public clips (own voice, public_audio=true) go to bench/audio/.
Everything else goes to bench/audio_private/ (git-ignored, never published).
"""

from __future__ import annotations

import io
import json
import re
import wave
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

BENCH = Path("bench")
FEATURES = {"silent_block", "repeat_sound", "repeat_word", "stretched_sound", "word_switch",
            "filler"}
router = APIRouter()


SETS = {"real_self", "volunteer", "other"}


def next_clip_id(clips_path: Path, prefix: str = "clip") -> str:
    n = 0
    if clips_path.exists():
        for line in clips_path.read_text(encoding="utf-8").splitlines():
            m = re.match(rf"{prefix}_(\d+)$", json.loads(line).get("id", "")) if line.strip() else None
            if m:
                n = max(n, int(m.group(1)))
    return f"{prefix}_{n + 1:02d}"


def parse_expected(text: str) -> dict:
    """'2 19:00 friday' -> book_table args; 'ask' -> book_table, details typed in after
    recording; 'list_bookings'; 'none' -> no action."""
    t = text.strip().lower()
    if t in ("", "none"):
        return {}
    if t == "list_bookings":
        return {"tool": "list_bookings", "args": {}}
    if t == "ask":
        return {"tool": "book_table", "args": {}}
    people, time, day = t.split()
    return {"tool": "book_table", "args": {"people": int(people), "time": time, "day": day}}


def parse_real_scripts(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        mode, say, expected = [part.strip() for part in line.split("|")]
        if mode not in ("think", "read"):
            raise ValueError(f"line must start with think or read: {line}")
        # thinking while speaking is where blocks happen; short reading is usually fluent
        out.append({"mode": mode, "kind": "stammer" if mode == "think" else "fluent",
                    "text": say, "expected": parse_expected(expected)})
    return out


def check_wav(data: bytes) -> float:
    """Validate mono 16-bit 16/24 kHz WAV; return duration in seconds."""
    try:
        with wave.open(io.BytesIO(data)) as w:
            if w.getnchannels() != 1 or w.getsampwidth() != 2 or w.getframerate() not in (16000, 24000):
                raise HTTPException(400, "need mono 16-bit 16/24 kHz WAV")
            return w.getnframes() / w.getframerate()
    except wave.Error as exc:
        raise HTTPException(400, f"bad wav: {exc}")


def build_clip(meta: dict, clip_id: str, duration: float) -> dict:
    kind = meta.get("kind")
    if kind not in ("stammer", "fluent"):
        raise HTTPException(400, "kind must be stammer or fluent")
    consent = meta.get("consent")
    if consent not in ("self", "volunteer"):
        raise HTTPException(400, "consent must be self or volunteer")
    end = float(meta.get("speech_end_s", 0))
    if not 0 < end <= duration:
        raise HTTPException(400, "speech_end_s must be inside the clip")
    public = bool(meta.get("public_audio")) and consent == "self"
    clip_set = meta.get("set") if meta.get("set") in SETS else "other"
    if clip_set == "real_self" and consent != "self":
        raise HTTPException(400, "real_self clips must be your own voice")
    if consent == "volunteer":
        clip_set = "volunteer"
    folder = ("audio/real_self" if clip_set == "real_self"
              else "audio" if public else "audio_private")
    return {
        "id": clip_id, "set": clip_set, "file": f"bench/{folder}/{clip_id}.wav", "kind": kind,
        "features": [f for f in meta.get("features", []) if f in FEATURES],
        "speech_end_s": round(end, 2), "expected": meta.get("expected") or {},
        "script": str(meta.get("script", ""))[:300], "consent": consent, "public_audio": public,
        "mode": meta.get("mode") if meta.get("mode") in ("think", "read") else None,
    }


@router.get("/bench/record.html")
async def record_page():
    return FileResponse(BENCH / "record.html")


@router.get("/bench/results.html")
async def results_page():
    p = BENCH / "results.html"
    if not p.exists():
        raise HTTPException(404, "run python bench/report.py first")
    return FileResponse(p)


@router.get("/bench/scripts")
async def scripts(set: str = ""):
    if set == "real_self":
        p = BENCH / "scripts_real.txt"
        return parse_real_scripts(p.read_text(encoding="utf-8")) if p.exists() else []
    p = BENCH / "scripts.txt"
    lines = p.read_text(encoding="utf-8").splitlines() if p.exists() else []
    return [ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")]


@router.post("/bench/clip")
async def save_clip(audio: UploadFile = File(...), meta: str = Form(...)):
    data = await audio.read()
    duration = check_wav(data)
    clips = BENCH / "clips.jsonl"
    m = json.loads(meta)
    prefix = "real" if m.get("set") == "real_self" else "clip"
    clip = build_clip(m, next_clip_id(clips, prefix), duration)
    path = Path(clip["file"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    with clips.open("a", encoding="utf-8") as f:
        f.write(json.dumps(clip) + "\n")
    return clip


@router.delete("/bench/clip/{clip_id}")
async def undo_clip(clip_id: str):
    """Remove a real-session clip (label line and audio), e.g. to record it again."""
    if not re.fullmatch(r"real_\d+", clip_id):
        raise HTTPException(400, "only real-session clips can be removed here")
    clips = BENCH / "clips.jsonl"
    text = clips.read_text(encoding="utf-8") if clips.exists() else ""
    rows = [json.loads(x) for x in text.splitlines() if x.strip()]
    keep = [r for r in rows if r.get("id") != clip_id]
    if len(keep) == len(rows):
        raise HTTPException(404, "not found")
    for r in rows:
        if r.get("id") == clip_id:
            Path(r["file"]).unlink(missing_ok=True)
    clips.write_text("".join(json.dumps(r) + "\n" for r in keep), encoding="utf-8")
    return {"deleted": clip_id}


@router.get("/bench/clips")
async def list_clips():
    out = []
    for name in ("clips.jsonl", "clips_synthetic.jsonl"):
        p = BENCH / name
        if p.exists():
            out += [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
    return out


@router.get("/bench/audio/{name}")
async def public_audio(name: str):
    """Only public clips are served (used by the demo page)."""
    if not re.fullmatch(r"[\w-]+\.wav", name):
        raise HTTPException(404, "not found")
    for folder in (BENCH / "audio", BENCH / "audio" / "real_self"):
        if (folder / name).exists():
            return FileResponse(folder / name, media_type="audio/wav")
    raise HTTPException(404, "not found")
