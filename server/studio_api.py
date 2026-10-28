"""Voice Studio endpoints: record or upload, review edits, real-voice and AI-voice output."""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from server.studio import jobs, render

router = APIRouter(prefix="/studio")
log = logging.getLogger("unhurried.studio")
_tasks: set[asyncio.Task] = set()


def _job(job_id: str) -> dict:
    try:
        return jobs.load(job_id)
    except (FileNotFoundError, ValueError):
        raise HTTPException(404, "recording not found")


def _view(job: dict) -> dict:
    return {**job, "clean_text": jobs.clean_text(job),
            "output_map": render.output_map(job["duration"], job["edits"]),
            "clone_available": jobs.clone_available()}


@router.post("/process")
async def process(audio: UploadFile = File(...), source: str = Form("upload"),
                  keywords: str = Form("[]"), spark: bool = Form(True)):
    data = await audio.read()
    if len(data) > 40 * 1024 * 1024:
        raise HTTPException(413, "file too large")
    try:
        kw = [str(k) for k in json.loads(keywords)][:100]
        job = await jobs.create(data, "mic" if source == "mic" else "upload", kw, use_spark=spark)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        log.exception("studio processing failed")
        raise HTTPException(502, f"could not process: {type(exc).__name__}")
    return _view(job)


@router.get("/{job_id}")
async def get(job_id: str):
    return _view(_job(job_id))


@router.post("/{job_id}/reanalyze")
async def reanalyze(job_id: str):
    return _view(await jobs.reanalyze(_job(job_id)))


@router.post("/{job_id}/edits")
async def toggle(job_id: str, request: Request):
    body = await request.json()
    return _view(jobs.apply_toggles(_job(job_id), {str(k): bool(v) for k, v in body.get("on", {}).items()}))


@router.post("/{job_id}/render")
async def render_clean(job_id: str):
    job = _job(job_id)
    await asyncio.to_thread(jobs.render_clean, job)
    return {"url": f"/studio/{job_id}/audio/clean.wav", "clean_text": jobs.clean_text(job)}


@router.get("/{job_id}/audio/{name}")
async def audio(job_id: str, name: str):
    if name not in ("original.wav", "clean.wav", "clone.wav"):
        raise HTTPException(404, "not found")
    _job(job_id)
    p = jobs._dir(job_id) / name
    if not p.exists():
        raise HTTPException(404, "not rendered yet")
    label = {"original.wav": "original", "clean.wav": "real-voice-clean", "clone.wav": "AI-voice"}[name]
    return FileResponse(p, media_type="audio/wav", filename=f"unhurried-{label}.wav")


@router.get("/verify/sentence")
async def sentence():
    return {"sentence": jobs.verify_sentence()}


@router.post("/{job_id}/verify")
async def verify(job_id: str, audio: UploadFile = File(...), sentence: str = Form(...)):
    try:
        return await jobs.verify(_job(job_id), await audio.read(), sentence)
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.post("/{job_id}/clone")
async def clone(job_id: str):
    job = _job(job_id)
    if not job.get("verified"):
        raise HTTPException(403, "Read the sentence first to confirm the voice is yours.")
    if not jobs.clone_available():
        raise HTTPException(501, "Voice clone is not installed on this machine.")
    if (job.get("clone") or {}).get("status") == "running":
        return {"status": "running"}
    task = asyncio.create_task(jobs.clone(job))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return {"status": "running"}


@router.delete("/{job_id}")
async def delete(job_id: str):
    _job(job_id)
    jobs.delete(job_id)
    return {"deleted": True}
