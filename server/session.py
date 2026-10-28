"""One live session: browser socket <-> audio router <-> (later) turn logic and bot."""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

from server import llm
from server.audio_router import AudioRouter
from server.runlog import RunLog, new_session_id

Send = Callable[[dict], Awaitable[None]]


def default_stream_factory(keywords: list[str]):
    return llm.TranscribeStream(mode="ENDPOINTING", keywords=keywords)


class Session:
    def __init__(self, send: Send, start: dict, stream_factory=default_stream_factory):
        self.send_browser = send
        self.config = start
        self.mode = start.get("mode", "baseline")
        self.id = start.get("session_id") or new_session_id(self.mode[0])
        self.log = RunLog(self.id)
        self.stream = stream_factory(list(start.get("keywords") or []))
        self.router = AudioRouter(self.stream, self.on_event)
        self._pump: asyncio.Task | None = None
        self._stopped = False

    async def start(self) -> None:
        await self.stream.open()
        self._pump = asyncio.create_task(self.router.pump())
        await self.emit({"type": "ready", "session_id": self.id, "mode": self.mode})

    async def emit(self, ev: dict) -> None:
        self.log.write("events", {"dir": "out", **ev})
        try:
            await self.send_browser(ev)
        except Exception:
            pass

    async def audio(self, pcm: bytes) -> None:
        if not self._stopped:
            await self.router.feed(pcm)

    async def on_event(self, ev: dict) -> None:
        self.log.write("events", {"dir": "in", **ev})
        if ev["type"] in ("partial", "speech_end", "speech_start", "error"):
            await self.emit(ev)

    async def command(self, cmd: dict) -> None:
        self.log.write("events", {"dir": "cmd", **cmd})

    async def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        await self.stream.close()
        if self._pump:
            try:
                await asyncio.wait_for(self._pump, 2)
            except (asyncio.TimeoutError, Exception):
                self._pump.cancel()
