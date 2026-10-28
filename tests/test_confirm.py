import asyncio

from server.confirm import ConfirmGate, say_time, spoken_answer, summary
from tests.fakes import run


def test_summary_and_time():
    assert summary("book_table", {"people": 2, "time": "19:00", "day": "Friday"}) == \
        "Book a table for 2 at 7 PM on Friday?"
    assert summary("book_table", {"people": 4, "time": "12:30", "day": "tomorrow"}) == \
        "Book a table for 4 at 12:30 PM tomorrow?"
    assert summary("cancel_booking", {"id": "b1"}) == "Cancel booking b1?"
    assert say_time("00:15") == "12:15 AM" and say_time("7pm") == "7pm"


def test_spoken_answers():
    assert spoken_answer("Yes.") == "yes" and spoken_answer("yeah") == "yes"
    assert spoken_answer("No") == "change" and spoken_answer("change it") == "change"
    assert spoken_answer("yes but at eight") is None


def make_gate(**kw):
    events, rows = [], []

    async def emit(ev):
        events.append(ev)

    return ConfirmGate(emit, rows.append, **kw), events, rows


def test_button_answer_resolves():
    async def go():
        g, events, rows = make_gate()
        task = asyncio.create_task(g.gate_tool("book_table", {"people": 2, "time": "19:00", "day": "Friday"}))
        await asyncio.sleep(0)
        assert events[0]["type"] == "confirm" and events[0]["action_id"] == "act_1"
        assert g.answer("act_1", "yes")
        return await task, events, rows
    answer, events, rows = run(go())
    assert answer == "yes"
    assert rows[0]["answer"] == "yes" and rows[0]["by"] == "button"
    assert events[-1] == {"type": "confirm_done", "action_id": "act_1", "answer": "yes"}


def test_voice_answer_without_id_and_change():
    async def go():
        g, _, rows = make_gate()
        task = asyncio.create_task(g.ask("Did you mean: x?", "rebuild"))
        await asyncio.sleep(0)
        g.answer(None, "change", by="voice")
        return await task, rows
    answer, rows = run(go())
    assert answer == "change" and rows[0]["by"] == "voice"


def test_auto_yes_counts_without_asking():
    g, events, rows = make_gate(auto_yes=True)
    assert run(g.ask("Book?", "action")) == "yes"
    assert g.count == 1 and events == [] and rows[0]["by"] == "auto"


def test_timeout_means_change():
    g, _, rows = make_gate(timeout_s=0.01)
    assert run(g.ask("Book?", "action")) == "change"
    assert rows[0]["by"] == "timeout"
