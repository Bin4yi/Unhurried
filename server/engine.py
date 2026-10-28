"""Unhurried turn engine: feeds events to the turn controller and runs the
completeness checks in the background (started early, on live text).
"""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

from server.completeness import check_complete
from server.turn_controller import TurnController, check_key, classify

OnActions = Callable[[list[dict]], Awaitable[None]]
MAX_IN_FLIGHT = 3


class Engine:
    def __init__(self, controller: TurnController, now: Callable[[], float],
                 on_actions: OnActions, provider: str = "spark", checker=check_complete,
                 last_voice: Callable[[], float | None] = lambda: None):
        self.c = controller
        self.last_voice = last_voice
        self.now = now
        self.on_actions = on_actions
        self.provider = provider
        self.checker = checker
        self._asked: set[str] = set()
        self._tasks: set[asyncio.Task] = set()

    async def handle(self, ev: dict) -> list[dict]:
        c, now, kind = self.c, self.now(), ev["type"]
        if kind == "partial":
            acts = c.on_partial(ev["text"], now)
            self.speculate(c.text)
        elif kind == "speech_start":
            acts = c.on_speech_start(now, ev.get("start_t"))
        elif kind == "speech_end":
            acts = c.on_pause(ev["end_t"], now)
        elif kind == "model_turn":
            acts = c.on_model_turn(ev["text"], now)
        else:
            return []
        return self._launch(acts)

    def tick(self) -> list[dict]:
        return self._launch(self.c.tick(self.now(), self.last_voice()))

    def typed(self, text: str) -> list[dict]:
        return self._launch(self.c.on_typed(text, self.now()))

    def speculate(self, text: str) -> None:
        """Start a completeness check early if the rules think the text may be finished."""
        if not self.c.use_checker or not text or classify(text)["unfinished"]:
            return
        self._ask(text)

    def _launch(self, acts: list[dict]) -> list[dict]:
        """Turn 'check' actions into background tasks; return the rest."""
        rest = []
        for a in acts:
            if a["do"] == "check":
                self._ask(a["text"], force=True)
            else:
                rest.append(a)
        return rest

    def _ask(self, text: str, force: bool = False) -> None:
        key = check_key(text)
        if key in self._asked or key in self.c.check_cache:
            return
        if not force and len(self._tasks) >= MAX_IN_FLIGHT:
            return
        self._asked.add(key)
        task = asyncio.create_task(self._run_check(text))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run_check(self, text: str) -> None:
        answer, ms = await self.checker(text, provider=self.provider)
        acts = self.c.on_check(text, answer, ms, self.now())
        if acts:
            await self.on_actions(acts)

    def close(self) -> None:
        for t in list(self._tasks):
            t.cancel()
