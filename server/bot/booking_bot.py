"""Demo voice bot: a restaurant booking assistant on Muse Spark with tools."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Awaitable, Callable

from server import llm

SYSTEM = (
    "You are the voice assistant of a small restaurant. You can book a table, "
    "cancel a booking, or list bookings. Opening hours: every day 12:00-22:00. "
    "Use the tools. Call book_table only when you know people, time and day; "
    "otherwise ask for what is missing. Time is 24h HH:MM (7 pm = 19:00). "
    "Day is a weekday name like Friday, or 'today' / 'tomorrow'. "
    "Your replies are spoken aloud: keep them to one or two short sentences, "
    "no lists, no emoji. "
    "Calm pace: the caller may pause or repeat sounds while speaking; that is normal. "
    "Never hurry them, never finish their sentence for them, and never comment on how "
    "they speak. Do not repeat a question you asked in your previous reply; if something "
    "is still missing, ask for it once in different, simple words. Never say "
    "'sorry, I didn't catch that' twice in a row."
)

TOOLS = [
    {"type": "function", "function": {
        "name": "book_table", "description": "Book a table.",
        "parameters": {"type": "object", "properties": {
            "people": {"type": "integer", "description": "number of people"},
            "time": {"type": "string", "description": "24h time HH:MM"},
            "day": {"type": "string", "description": "weekday name, today or tomorrow"}},
            "required": ["people", "time", "day"]}}},
    {"type": "function", "function": {
        "name": "cancel_booking", "description": "Cancel a booking by id.",
        "parameters": {"type": "object", "properties": {"id": {"type": "string"}},
                       "required": ["id"]}}},
    {"type": "function", "function": {
        "name": "list_bookings", "description": "List current bookings.",
        "parameters": {"type": "object", "properties": {}}}},
]

IMPORTANT_TOOLS = {"book_table", "cancel_booking"}

CALM = (
    "Calm pace: the person may pause or repeat sounds while speaking; that is normal. "
    "Never hurry them, never finish their sentence for them, and never comment on how "
    "they speak. Do not repeat a question you asked in your previous reply. Never say "
    "'sorry, I didn't catch that' twice in a row."
)

ASSISTANT_SYSTEM = (
    "You are a friendly, helpful voice assistant. Talk about whatever the person wants: "
    "answer questions, discuss ideas, help them think or practise explaining something. "
    "Engage with what they actually said and build on it. Your replies are spoken aloud: "
    "keep them to two to four short sentences, no lists, no markdown, no emoji. " + CALM
)

# gate(name, args) -> "yes" | "change"
Gate = Callable[[str, dict], Awaitable[str]]


async def always_yes(name: str, args: dict) -> str:
    return "yes"


class BookingStore:
    """Bookings in memory, saved to a JSON file when a path is given."""

    def __init__(self, path: Path | None = None):
        self.path = path
        self.items: list[dict] = []
        if path and path.exists():
            self.items = json.loads(path.read_text(encoding="utf-8"))

    def _save(self) -> None:
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.items, indent=2), encoding="utf-8")

    def book(self, people: int, time: str, day: str) -> dict:
        item = {"id": f"b{len(self.items) + 1}", "people": int(people), "time": time, "day": day}
        self.items.append(item)
        self._save()
        return item

    def cancel(self, id: str) -> bool:
        before = len(self.items)
        self.items = [b for b in self.items if b["id"] != id]
        self._save()
        return len(self.items) < before

    def run(self, name: str, args: dict) -> dict:
        if name == "book_table":
            return {"ok": True, "booking": self.book(args["people"], args["time"], args["day"])}
        if name == "cancel_booking":
            return {"ok": self.cancel(str(args.get("id", "")))}
        if name == "list_bookings":
            return {"bookings": self.items}
        return {"error": f"unknown tool {name}"}


class BookingBot:
    def __init__(self, store: BookingStore | None = None, gate: Gate = always_yes,
                 system: str = SYSTEM, chat=llm.chat, tools: list[dict] | None = None):
        self.store = store or BookingStore()
        self.tools = TOOLS if tools is None else tools
        self.gate = gate
        self.chat = chat
        self.history: list[dict] = [{"role": "system", "content": system}]

    async def respond(self, text: str) -> dict:
        """One user turn. Returns {"reply", "tool_calls": [{name, args, result, confirmed}]}."""
        self.history.append({"role": "user", "content": text})
        done: list[dict] = []
        for _ in range(4):  # at most a few tool rounds per turn
            out = await self.chat(self.history, purpose="bot", tools=self.tools or None,
                                  reasoning_effort="low", max_tokens=800)
            calls = out["tool_calls"]
            self.history.append({"role": "assistant", "content": out["content"] or None,
                                 **({"tool_calls": calls} if calls else {})})
            if not calls:
                return {"reply": out["content"].strip(), "tool_calls": done}
            for call in calls:
                name = call["function"]["name"]
                try:
                    args = json.loads(call["function"].get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                answer = await self.gate(name, args) if name in IMPORTANT_TOOLS else "yes"
                if answer == "yes":
                    result = self.store.run(name, args)
                else:
                    result = {"ok": False, "note": "The user did not confirm. Ask what to change."}
                done.append({"name": name, "args": args, "result": result,
                             "confirmed": answer == "yes"})
                self.history.append({"role": "tool", "tool_call_id": call["id"],
                                     "content": json.dumps(result)})
        return {"reply": "Sorry, something went wrong. Could you say that again?",
                "tool_calls": done}
