"""Voice Studio jobs: one recording, its words, its edits, and its outputs.

Files live in studio_data/{id}/ (git-ignored) until the person deletes them.
Clone rules (in code):
  1. Only your own voice: cloning needs a recording made live in the Studio, plus a
     live reading of a random sentence that must match (proves a person is speaking now).
  2. Only your own words: the clone reads the clean text, which only has words you said.
  3. Watermark always on (Chatterbox), and the file is labelled AI voice.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import re
import secrets
import shutil
import subprocess
import time
from pathlib import Path

import numpy as np

from server import llm
from server.studio import align, edits as edits_mod, listen, render

DATA = Path("studio_data")
ROOT = Path(__file__).resolve().parent.parent.parent
CLONE_PKGS = ROOT / ".clone-pkgs"
MAX_SECONDS = 180
VERIFY_SENTENCES = [
    "The river was calm and green this morning.",
    "Seven small boats waited near the old bridge.",
    "I would like a cup of tea with honey, please.",
    "The library opens at nine on most weekdays.",
    "A warm wind moved slowly across the hills.",
    "Please send the blue folder to my office.",
]


def _dir(job_id: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{16}", job_id or ""):
        raise ValueError("bad job id")
    return DATA / job_id


def load(job_id: str) -> dict:
    p = _dir(job_id) / "job.json"
    if not p.exists():
        raise FileNotFoundError(job_id)
    return json.loads(p.read_text(encoding="utf-8"))


def save(job: dict) -> None:
    (_dir(job["id"]) / "job.json").write_text(json.dumps(job, indent=1), encoding="utf-8")


def to_wav24(data: bytes, tmp: Path) -> bytes:
    """Any audio -> mono 16-bit 24 kHz WAV (ffmpeg), unless it already is one."""
    try:
        x, rate = render.read_wav_bytes(data)
        if rate == 24000:
            return data
    except Exception:
        pass
    src, dst = tmp / "upload.bin", tmp / "converted.wav"
    src.write_bytes(data)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-ac", "1", "-ar", "24000",
                    "-sample_fmt", "s16", "-map_metadata", "-1", "-fflags", "+bitexact", str(dst)], check=True, timeout=120)
    out = dst.read_bytes()
    src.unlink(missing_ok=True)
    dst.unlink(missing_ok=True)
    return out


def to16k(x: np.ndarray, rate: int) -> np.ndarray:
    from scipy.signal import resample_poly
    if rate == 16000:
        return x
    g = np.gcd(16000, rate)
    return resample_poly(x, 16000 // g, rate // g).astype(np.float32)


async def create(data: bytes, source: str, keywords: list[str], use_spark: bool = True) -> dict:
    job_id = secrets.token_hex(8)
    d = _dir(job_id)
    d.mkdir(parents=True)
    try:
        wav = await asyncio.to_thread(to_wav24, data, d)
        x, rate = render.read_wav_bytes(wav)
        if len(x) / rate > MAX_SECONDS:
            raise ValueError(f"recordings up to {MAX_SECONDS // 60} minutes")
        (d / "original.wav").write_bytes(wav)
        t0 = time.monotonic()
        tr = await llm.transcribe_file(wav, keywords=keywords, purpose="studio")
        transcript = " ".join(t["transcript"] for t in tr.get("turns", [])) or tr.get("transcript", "")
        words, found, harness = await analyze(to16k(x, rate), transcript, use_spark)
    except Exception:
        shutil.rmtree(d, ignore_errors=True)
        raise
    job = {"id": job_id, "source": source, "created": time.time(), "duration": round(len(x) / rate, 3),
           "transcript": transcript, "words": [w.__dict__ for w in words], "edits": found,
           "harness": harness,
           "ms": round((time.monotonic() - t0) * 1000), "verified": False, "clone": None}
    save(job)
    return job


async def reanalyze(job: dict, use_spark: bool = True) -> dict:
    """Find the cuts again from the saved recording (after the cut finder improves)."""
    d = _dir(job["id"])
    x, rate = render.read_wav_bytes((d / "original.wav").read_bytes())
    words, found, harness = await analyze(to16k(x, rate), job["transcript"], use_spark)
    job.update(words=[w.__dict__ for w in words], edits=found, harness=harness, check=None)
    save(job)
    return job


async def analyze(x16: np.ndarray, transcript: str, use_spark: bool) -> tuple[list, list, dict]:
    """Model-led scan (Spark listens, code verifies); code rules only as the fallback."""
    vt_words, acoustic = await asyncio.to_thread(align.align_all, x16, transcript)
    if not use_spark:
        return vt_words, await edits_mod.find_edits(vt_words, acoustic, use_spark=False), {"mode": "rules"}
    res = await listen.scan(x16, vt_words, acoustic)
    words, found = res["words"], res["edits"]
    taken = {k for e in found if e.get("words") for k in range(e["words"][0], e["words"][1] + 1)}
    for e in await edits_mod.find_corrections(words):
        if not taken & set(range(e["words"][0], e["words"][1] + 1)):
            e["by"] = "spark"
            found.append(e)
    found += edits_mod.find_blocks(words)
    found.sort(key=lambda e: e["start"])
    for n, e in enumerate(found, 1):
        e["id"] = f"e{n}"
    return words, found, {"mode": "model", "rejected": res["rejected"], "pieces": res["pieces"]}


def apply_toggles(job: dict, on: dict[str, bool]) -> dict:
    for e in job["edits"]:
        if e["id"] in on:
            e["on"] = bool(on[e["id"]])
    save(job)
    return job


def clean_text(job: dict) -> str:
    words = [align.Word(**w) for w in job["words"]]
    return edits_mod.clean_text(words, job["edits"])


def render_clean(job: dict) -> Path:
    d = _dir(job["id"])
    x, rate = render.read_wav_bytes((d / "original.wav").read_bytes())
    y = render.render(x, rate, job["edits"])
    (d / "clean.wav").write_bytes(render.wav_bytes(y, rate))
    job["check"] = listen.content_check(y, rate, clean_text(job))   # listen again
    save(job)
    return d / "clean.wav"


def verify_sentence() -> str:
    return random.choice(VERIFY_SENTENCES)


def words_match(said: str, target: str) -> float:
    a = re.findall(r"[a-z']+", said.lower())
    b = re.findall(r"[a-z']+", target.lower())
    return sum(1 for w in b if w in a) / max(1, len(b))


async def verify(job: dict, data: bytes, sentence: str) -> dict:
    if job["source"] != "mic":
        raise PermissionError("Cloning needs a recording made live in the Studio.")
    if sentence not in VERIFY_SENTENCES:
        raise ValueError("unknown sentence")
    wav = await asyncio.to_thread(to_wav24, data, _dir(job["id"]))
    tr = await llm.transcribe_file(wav, purpose="studio_verify")
    score = words_match(tr.get("transcript", ""), sentence)
    job["verified"] = score >= 0.7
    job["verify_score"] = round(score, 2)
    save(job)
    return {"verified": job["verified"], "heard": tr.get("transcript", ""), "score": round(score, 2)}


def clone_available() -> bool:
    return (CLONE_PKGS / "chatterbox").is_dir()


def clone_python() -> list[str]:
    exe = os.environ.get("CLONE_PYTHON")
    return [exe] if exe else ["py", "-V:Astral/CPython3.12.15"]


async def clone(job: dict) -> None:
    """Generate the AI-voice version in the background; status goes into job.json."""
    if not job.get("verified"):
        raise PermissionError("Read the sentence first to confirm the voice is yours.")
    if not clone_available():
        raise RuntimeError("Voice clone is not installed on this machine.")
    d = _dir(job["id"])
    ref = render_clean(job)                      # your voice without the pauses
    text = clean_text(job)
    job["clone"] = {"status": "running", "started": time.time()}
    save(job)
    env = {**os.environ, "PYTHONPATH": str(CLONE_PKGS)}
    proc = await asyncio.create_subprocess_exec(
        *clone_python(), str(ROOT / "scripts" / "clone_worker.py"), "--text", text,
        "--ref", str(ref.resolve()), "--out", str((d / "clone.wav").resolve()),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env)
    out, err = await proc.communicate()
    job = load(job["id"])
    ok = proc.returncode == 0 and (d / "clone.wav").exists()
    job["clone"] = {"status": "done" if ok else "failed", "seconds": round(time.time() - job["clone"]["started"]),
                    "error": None if ok else err.decode(errors="replace")[-400:]}
    save(job)


def delete(job_id: str) -> None:
    shutil.rmtree(_dir(job_id), ignore_errors=True)

