"""Confirm gate: the person approves important actions before the bot runs them.

Used for book_table / cancel_booking, and for rebuilt text that the guard
could not verify (or low rebuild confidence). The person taps Yes / Change
or says "yes" / "no". In benchmark runs every confirm is auto-approved and
counted.
"""

from __future__ import annotations

import asyncio
import itertools
import re
import time
from typing import Awaitable, Callable

YES = re.compile(r"^\W*(yes|yeah|yep|yup|correct|right|sure|ok|okay|that's right|"
                 r"yes please|sounds good|confirm)\W*$", re.I)
NO = re.compile(r"^\W*(no|nope|change|change it|wrong|not right|cancel that)\W*$", re.I)
DAY_FMT = {"today": "today", "tomorrow": "tomorrow"}


def say_time(t: str) -> str:
    """'19:00' -> '7 PM', '07:30' -> '7:30 AM'. Unknown formats pass through."""
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", str(t).strip())
    if not m:
        return str(t)
    h, mm = int(m.group(1)), int(m.group(2))
    suffix = "PM" if h >= 12 else "AM"
    h12 = h % 12 or 12
    return f"{h12} {suffix}" if mm == 0 else f"{h12}:{mm:02d} {suffix}"


def summary(name: str, args: dict) -> str:
    if name == "book_table":
        day = str(args.get("day", ""))
        day = DAY_FMT.get(day.lower(), f"on {day}") if day else ""
        return f"Book a table for {args.get('people', '?')} at {say_time(args.get('time', '?'))} {day}?".replace("  ", " ").replace(" ?", "?")
    if name == "cancel_booking":
        return f"Cancel booking {args.get('id', '?')}?"
    return f"Run {name}?"


def spoken_answer(text: str) -> str | None:
    if YES.match(text or ""):
        return "yes"
    if NO.match(text or ""):
        return "change"
    return None


class ConfirmGate:
    def __init__(self, emit: Callable[[dict], Awaitable[None]], log: Callable[[dict], None],
                 auto_yes: bool = False, timeout_s: float = 90.0):
        self.emit = emit
        self.log = log
        self.auto_yes = auto_yes
        self.timeout_s = timeout_s
        self.pending: dict[str, asyncio.Future] = {}
        self.count = 0
        self._ids = itertools.count(1)

    async def ask(self, text: str, kind: str, detail: dict | None = None) -> str:
        """Show a confirm line and wait for 'yes' or 'change'."""
        self.count += 1
        action_id = f"act_{next(self._ids)}"
        row = {"action_id": action_id, "kind": kind, "text": text, "detail": detail or {},
               "asked": time.time()}
        if self.auto_yes:
            self.log({**row, "answer": "yes", "by": "auto"})
            return "yes"
        fut = asyncio.get_running_loop().create_future()
        self.pending[action_id] = fut
        await self.emit({"type": "confirm", "text": text, "action_id": action_id, "kind": kind})
        try:
            answer, by = await asyncio.wait_for(fut, self.timeout_s)
        except asyncio.TimeoutError:
            answer, by = "change", "timeout"
        finally:
            self.pending.pop(action_id, None)
        self.log({**row, "answer": answer, "by": by})
        await self.emit({"type": "confirm_done", "action_id": action_id, "answer": answer})
        return answer

    async def gate_tool(self, name: str, args: dict) -> str:
        """BookingBot gate for important tools."""
        return await self.ask(summary(name, args), "action", {"tool": name, "args": args})

    def answer(self, action_id: str | None, answer: str, by: str = "button") -> bool:
        """Resolve a pending confirm. With no id, resolves the oldest pending one."""
        if answer not in ("yes", "change"):
            return False
        if action_id is None or action_id not in self.pending:
            if not self.pending:
                return False
            action_id = next(iter(self.pending))
        fut = self.pending[action_id]
        if fut.done():
            return False
        fut.set_result((answer, by))
        return True

    def cancel_all(self) -> None:
        for fut in self.pending.values():
            if not fut.done():
                fut.set_result(("change", "stopped"))
