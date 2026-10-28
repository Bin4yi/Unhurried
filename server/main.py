"""FastAPI app: serves the web page and the /listen WebSocket."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from server import passport_store
from server.session import Session

ROOT = Path(__file__).resolve().parent.parent
app = FastAPI(title="Unhurried")


@app.get("/")
async def index():
    return RedirectResponse("/web/index.html")


@app.post("/profile/{pid}")
async def save_profile(pid: str, request: Request):
    """Store an encrypted Voice Passport blob as-is."""
    try:
        passport_store.save(pid, await request.json())
    except (passport_store.PassportError, json.JSONDecodeError) as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True}


@app.get("/profile/{pid}")
async def get_profile(pid: str):
    try:
        blob = passport_store.load(pid)
    except passport_store.PassportError as exc:
        raise HTTPException(400, str(exc))
    if blob is None:
        raise HTTPException(404, "no profile")
    return blob


@app.delete("/profile/{pid}")
async def delete_profile(pid: str):
    try:
        return {"deleted": passport_store.delete(pid)}
    except passport_store.PassportError as exc:
        raise HTTPException(400, str(exc))


@app.websocket("/listen")
async def listen(ws: WebSocket):
    """First message: JSON {"type": "start", ...}. Then binary PCM chunks and JSON commands."""
    await ws.accept()
    try:
        start = json.loads(await ws.receive_text())
    except (WebSocketDisconnect, json.JSONDecodeError):
        return
    session = Session(ws.send_json, start)
    try:
        await session.start()
    except Exception as exc:  # e.g. bad key or no network
        await ws.send_json({"type": "error", "message": f"could not start: {exc}"})
        await ws.close()
        return
    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            if msg.get("bytes") is not None:
                await session.audio(msg["bytes"])
            elif msg.get("text") is not None:
                cmd = json.loads(msg["text"])
                if cmd.get("type") == "stop":
                    await session.stop()
                    await ws.close()
                    break
                await session.command(cmd)
    except WebSocketDisconnect:
        pass
    finally:
        await session.stop()
        await asyncio.sleep(0)


app.mount("/web", StaticFiles(directory=ROOT / "web"), name="web")
