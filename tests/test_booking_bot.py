import json

from server.bot.booking_bot import BookingBot, BookingStore
from tests.fakes import run


def tool_call(name, args, id="c1"):
    return {"id": id, "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)}}


class FakeChat:
    def __init__(self, replies):
        self.replies = list(replies)
        self.seen = []

    async def __call__(self, messages, **kw):
        self.seen.append([dict(m) for m in messages])
        return self.replies.pop(0)


def test_store_book_cancel_list(tmp_path):
    s = BookingStore(tmp_path / "b.json")
    b = s.book(2, "19:00", "Friday")
    assert b["id"] == "b1"
    assert BookingStore(tmp_path / "b.json").items[0]["people"] == 2
    assert s.run("list_bookings", {})["bookings"] == [b]
    assert s.cancel("b1") and not s.items


def test_plain_reply():
    chat = FakeChat([{"content": "How many people?", "tool_calls": []}])
    bot = BookingBot(chat=chat)
    out = run(bot.respond("Book a table for"))
    assert out == {"reply": "How many people?", "tool_calls": []}


def test_tool_call_runs_then_replies():
    chat = FakeChat([
        {"content": "", "tool_calls": [tool_call("book_table", {"people": 2, "time": "19:00", "day": "Friday"})]},
        {"content": "Booked for 2 at 7 pm Friday.", "tool_calls": []},
    ])
    bot = BookingBot(chat=chat)
    out = run(bot.respond("Book a table for two at seven on Friday"))
    assert out["reply"].startswith("Booked")
    assert out["tool_calls"][0]["confirmed"] is True
    assert bot.store.items[0]["time"] == "19:00"
    last = chat.seen[1][-1]
    assert last["role"] == "tool" and last["tool_call_id"] == "c1"


def test_gate_change_does_not_book():
    async def gate(name, args):
        return "change"

    chat = FakeChat([
        {"content": "", "tool_calls": [tool_call("book_table", {"people": 2, "time": "19:00", "day": "Friday"})]},
        {"content": "What would you like to change?", "tool_calls": []},
    ])
    bot = BookingBot(chat=chat, gate=gate)
    out = run(bot.respond("Book it"))
    assert bot.store.items == []
    assert out["tool_calls"][0]["confirmed"] is False


def test_list_bookings_skips_gate():
    called = []

    async def gate(name, args):
        called.append(name)
        return "change"

    chat = FakeChat([
        {"content": "", "tool_calls": [tool_call("list_bookings", {})]},
        {"content": "You have no bookings.", "tool_calls": []},
    ])
    run(BookingBot(chat=chat, gate=gate).respond("What are my bookings?"))
    assert called == []


def test_system_prompt_has_calm_pace_rules():
    from server.bot.booking_bot import SYSTEM
    assert "never finish their sentence" in SYSTEM
    assert "Do not repeat a question" in SYSTEM
    assert "twice in a row" in SYSTEM
