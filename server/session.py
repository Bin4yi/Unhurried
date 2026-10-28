"""One live session: browser socket <-> audio router <-> turn logic <-> bot.

Modes:
  baseline   - send each model turn to the bot as soon as Voice Transcribe
               says speech ended (like a normal voice bot)
  unhurried  - the turn controller decides when the person is done
"""

from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable

from server import llm
from server.audio_router import AudioRouter
from server.bot.booking_bot import BookingBot, BookingStore
from server.runlog import RUNS, RunLog, new_session_id

Send = Callable[[dict], Awaitable[None]]


def default_stream_factory(keywords: list[str]):
    return llm.TranscribeStream(mode="ENDPOINTING", keywords=keywords)


class Session:
    def __init__(self, send: Send, start: dict, stream_factory=default_stream_factory,
                 bot_factory=None):
        self.send_browser = send
        self.config = start
        self.mode = start.get("mode", "baseline")
        self.bench = bool(start.get("bench"))
        self.id = start.get("session_id") or new_session_id(self.mode[0])
        self.log = RunLog(self.id)
        self.stream = stream_factory(list(start.get("keywords") or []))
        self.router = AudioRouter(self.stream, self.on_event)
        store = BookingStore(None if self.bench else RUNS / "bookings.json")
        self.bot = (bot_factory or (lambda: BookingBot(store)))()
        self.turns: asyncio.Queue = asyncio.Queue()
        self.last_speech_end: float | None = None
        self._tasks: list[asyncio.Task] = []
        self._stopped = False
        self.turn_count = 0

    @property
    def now(self) -> float:
        return round(self.router.audio_t, 3)

    async def start(self) -> None:
        await self.stream.open()
        self._tasks.append(asyncio.create_task(self.router.pump()))
        self._tasks.append(asyncio.create_task(self._bot_worker()))
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
        kind = ev["type"]
        if kind == "speech_end":
            self.last_speech_end = ev["end_t"]
        if kind in ("partial", "speech_end", "speech_start", "error"):
            await self.emit(ev)
        if kind == "model_turn" and self.mode == "baseline" and ev["text"]:
            await self.dispatch_turn(ev["text"], ev["text"], reason="model_end")

    async def dispatch_turn(self, raw: str, clean: str, *, reason: str, **extra) -> None:
        """Send one finished user turn to the bot."""
        self.turn_count += 1
        turn = {"type": "turn", "n": self.turn_count, "raw": raw, "clean": clean,
                "reason": reason, "speech_end_t": self.last_speech_end, "sent_t": self.now,
                **extra}
        self.log.write("turns", turn)
        await self.emit(turn)
        await self.turns.put(clean)

    async def _bot_worker(self) -> None:
        while True:
            text = await self.turns.get()
            if text is None:
                return
            t0 = time.monotonic()
            try:
                out = await self.bot.respond(text)
            except Exception as exc:
                out = {"reply": "Sorry, I had a problem. Please try again.", "tool_calls": [],
                       "error": type(exc).__name__}
            ev = {"type": "bot", "text": out["reply"], "tool_calls": out["tool_calls"],
                  "ms": round((time.monotonic() - t0) * 1000), "t": self.now}
            self.log.write("bot", {"user": text, **ev})
            await self.emit(ev)

    async def command(self, cmd: dict) -> None:
        self.log.write("events", {"dir": "cmd", **cmd})

    async def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        await self.stream.close()
        await self.turns.put(None)
        for t in self._tasks:
            try:
                await asyncio.wait_for(t, 30 if self.bench else 2)
            except (asyncio.TimeoutError, Exception):
                t.cancel()
        await self.emit({"type": "stopped", "turns": self.turn_count})
