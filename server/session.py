"""One live session: browser socket <-> audio router <-> turn logic <-> bot.

Modes:
  baseline   - send each model turn to the bot as soon as Voice Transcribe
               says speech ended (like a normal voice bot)
  unhurried  - the turn engine decides when the person is done
"""

from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable

from server import llm
from server.audio_router import AudioRouter
from server.bot.booking_bot import BookingBot, BookingStore
from server.engine import Engine
from server.rebuild import rebuild
from server.runlog import RUNS, RunLog, new_session_id
from server.timing_profile import TimingProfile
from server.turn_controller import TurnController

Send = Callable[[dict], Awaitable[None]]

# Words the demo bot expects; sent to Voice Transcribe as keyword biasing.
BOT_KEYWORDS = ["table", "booking", "book", "cancel", "Monday", "Tuesday", "Wednesday",
                "Thursday", "Friday", "Saturday", "Sunday", "tonight", "tomorrow"]


def default_stream_factory(keywords: list[str]):
    return llm.TranscribeStream(mode="ENDPOINTING", keywords=keywords)


class Session:
    def __init__(self, send: Send, start: dict, stream_factory=default_stream_factory,
                 bot_factory=None, checker=None):
        self.send_browser = send
        self.config = start
        self.mode = start.get("mode", "baseline")
        self.bench = bool(start.get("bench"))
        self.id = start.get("session_id") or new_session_id(self.mode[0])
        self.log = RunLog(self.id)
        user_words = [str(w).strip() for w in (start.get("keywords") or []) if str(w).strip()]
        self.stream = stream_factory(BOT_KEYWORDS + user_words)
        self.router = AudioRouter(self.stream, self.on_event)
        store = BookingStore(None if self.bench else RUNS / "bookings.json")
        self.bot = (bot_factory or (lambda: BookingBot(store)))()
        self.turns: asyncio.Queue = asyncio.Queue()
        self.last_speech_end: float | None = None
        self._tasks: list[asyncio.Task] = []
        self._stopped = False
        self.turn_count = 0

        # Personal timing: a max wait sent by the browser (Voice Passport) wins,
        # otherwise the server-side pause profile for this user id.
        self.profile = TimingProfile.load(str(start.get("user_id") or "u1"))
        max_wait = int(start.get("max_wait_ms") or self.profile.max_wait_ms)
        engine_cfg = {"spark_check": True, "rebuild_spark": True, **(start.get("engine") or {})}
        self.engine_cfg = engine_cfg
        self.switches = [s for s in (start.get("switches") or []) if isinstance(s, dict)]
        self.controller = TurnController(
            max_wait_ms=max_wait, use_checker=bool(engine_cfg["spark_check"]),
            check_timeout_ms=int(engine_cfg.get("check_timeout_ms", 700)))
        kw = {"checker": checker} if checker else {}
        self.engine = Engine(self.controller, lambda: self.now, self.act,
                             provider=engine_cfg.get("provider", "spark"), **kw)
        self._logged_decisions = 0

    @property
    def now(self) -> float:
        return round(self.router.audio_t, 3)

    async def start(self) -> None:
        await self.stream.open()
        self._tasks.append(asyncio.create_task(self.router.pump()))
        self._tasks.append(asyncio.create_task(self._bot_worker()))
        await self.emit({"type": "ready", "session_id": self.id, "mode": self.mode,
                         "max_wait_ms": self.controller.max_wait_ms})

    async def emit(self, ev: dict) -> None:
        self.log.write("events", {"dir": "out", **ev})
        try:
            await self.send_browser(ev)
        except Exception:
            pass

    async def audio(self, pcm: bytes) -> None:
        if self._stopped:
            return
        await self.router.feed(pcm)
        if self.mode == "unhurried":
            await self.act(self.engine.tick())

    async def on_event(self, ev: dict) -> None:
        self.log.write("events", {"dir": "in", **ev})
        kind = ev["type"]
        if kind == "speech_end":
            self.last_speech_end = ev["end_t"]
        if kind in ("partial", "speech_end", "speech_start", "error"):
            await self.emit(ev)
        if self.mode == "baseline":
            if kind == "model_turn" and ev["text"]:
                await self.dispatch_turn(ev["text"], reason="model_end")
            return
        acts = await self.engine.handle(ev)
        if kind == "model_turn":
            await self.emit({"type": "model_text", "text": self.controller.text, "t": self.now})
        await self.act(acts)

    async def act(self, acts: list[dict]) -> None:
        """Carry out turn-controller actions and write new decision log rows."""
        for row in self.controller.decisions[self._logged_decisions:]:
            self.log.write("decisions", row)
        self._logged_decisions = len(self.controller.decisions)
        for a in acts:
            if a["do"] == "hold":
                await self.emit({"type": "hold", "reason": a["reason"],
                                 "max_wait_ms": a["max_wait_ms"], "t": self.now})
            elif a["do"] == "resume":
                await self.emit({"type": "resume", "t": self.now})
            elif a["do"] == "send":
                await self.dispatch_turn(a["text"], reason=a["reason"])

    async def dispatch_turn(self, raw: str, *, reason: str) -> None:
        """The person's turn is finished: queue it for rebuild and the bot."""
        self.turn_count += 1
        item = {"n": self.turn_count, "raw": raw, "reason": reason,
                "speech_end_t": self.last_speech_end, "sent_t": self.now}
        await self.emit({"type": "sending", "n": self.turn_count, "t": self.now})
        await self.turns.put(item)

    async def clean_turn(self, item: dict) -> dict:
        """Meaning rebuild in unhurried mode; baseline passes raw text through."""
        if self.mode != "unhurried":
            return {"type": "turn", **item, "clean": item["raw"], "changes": [],
                    "confidence": 1.0, "needs_confirm": False, "guard_fails": []}
        rb = await rebuild(item["raw"], self.switches,
                           use_spark=bool(self.engine_cfg.get("rebuild_spark", True)),
                           provider=self.engine_cfg.get("provider", "spark"))
        return {"type": "turn", **item, **{k: rb[k] for k in (
            "clean", "changes", "confidence", "needs_confirm", "guard_fails", "spark")}}

    async def _bot_worker(self) -> None:
        while True:
            item = await self.turns.get()
            if item is None:
                return
            turn = await self.clean_turn(item)
            self.log.write("turns", turn)
            await self.emit(turn)
            text = turn["clean"]
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
        if cmd.get("type") == "text" and cmd.get("text", "").strip():
            if self.mode == "unhurried":
                await self.act(self.engine.typed(cmd["text"]))
            else:
                await self.dispatch_turn(cmd["text"], reason="typed")

    async def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        self.engine.close()
        await self.stream.close()
        await self.turns.put(None)
        for t in self._tasks:
            try:
                await asyncio.wait_for(t, 30 if self.bench else 2)
            except (asyncio.TimeoutError, Exception):
                t.cancel()
        pauses = list(self.controller.inner_pauses_ms)
        if pauses and not self.bench and not self.config.get("max_wait_ms"):
            self.profile.add(pauses)
            self.profile.save()
        await self.emit({"type": "stopped", "turns": self.turn_count,
                         "inner_pauses_ms": pauses})
