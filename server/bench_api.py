"""Benchmark clip recording endpoints (used by bench/record.html).

Public clips (own voice, public_audio=true) go to bench/audio/.
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


def next_clip_id(clips_path: Path) -> str:
    n = 0
    if clips_path.exists():
        for line in clips_path.read_text(encoding="utf-8").splitlines():
            m = re.match(r"clip_(\d+)$", json.loads(line).get("id", "")) if line.strip() else None
            if m:
                n = max(n, int(m.group(1)))
    return f"clip_{n + 1:02d}"


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
    folder = "audio" if public else "audio_private"
    return {
        "id": clip_id, "file": f"bench/{folder}/{clip_id}.wav", "kind": kind,
        "features": [f for f in meta.get("features", []) if f in FEATURES],
        "speech_end_s": round(end, 2), "expected": meta.get("expected") or {},
        "script": str(meta.get("script", ""))[:300], "consent": consent, "public_audio": public,
    }


@router.get("/bench/record.html")
async def record_page():
    return FileResponse(BENCH / "record.html")


@router.get("/bench/scripts")
async def scripts():
    p = BENCH / "scripts.txt"
    lines = p.read_text(encoding="utf-8").splitlines() if p.exists() else []
    return [ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")]


@router.post("/bench/clip")
async def save_clip(audio: UploadFile = File(...), meta: str = Form(...)):
    data = await audio.read()
    duration = check_wav(data)
    clips = BENCH / "clips.jsonl"
    clip = build_clip(json.loads(meta), next_clip_id(clips), duration)
    path = Path(clip["file"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    with clips.open("a", encoding="utf-8") as f:
        f.write(json.dumps(clip) + "\n")
    return clip


@router.get("/bench/clips")
async def list_clips():
    p = BENCH / "clips.jsonl"
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


@router.get("/bench/audio/{name}")
async def public_audio(name: str):
    """Only public clips are served (used by the demo page)."""
    if not re.fullmatch(r"[\w-]+\.wav", name) or not (BENCH / "audio" / name).exists():
        raise HTTPException(404, "not found")
    return FileResponse(BENCH / "audio" / name, media_type="audio/wav")
