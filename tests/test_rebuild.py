import json

import pytest

from server import guard
from server.rebuild import code_pass, rebuild
from tests.fakes import run

SWITCH = [{"said": "the day after Monday", "means": "Tuesday", "approved": True}]


@pytest.mark.parametrize("raw,clean", [
    ("I-I-I want to b-b-book a table for, uh, two", "I want to book a table for two"),
    ("b- b- book a table", "book a table"),
    ("I I I want a table", "I want a table"),
    ("Book a table um for two", "Book a table for two"),
    ("for two at s-s-seven", "for two at seven"),
    ("I want I want a table", "I want a table"),
    ("Sssunday please", "Sunday please"),
    ("uh um book it", "book it"),
    ("What time do you close?", "What time do you close?"),
    ("the the table for four", "the table for four"),
])
def test_code_pass(raw, clean):
    out, changes = code_pass(raw)
    assert out == clean
    assert all(c["from"] for c in changes)


def test_code_pass_records_changes():
    _, changes = code_pass("I-I-I want to b-b-book a table for, uh, two")
    kinds = sorted(c["kind"] for c in changes)
    assert kinds == ["filler", "repeat", "repeat"]
    assert {"from": "b-b-book", "to": "book", "kind": "repeat"} in changes


def test_guard_normalizes_numbers_times_days():
    assert guard.check("a table for two at seven pm on Fri", "A table for 2 at 19:00 on Friday") == []
    assert guard.times("seven pm") == {"19:00"} and guard.times("7:30 am") == {"07:30"}


def test_guard_catches_invented_number():
    fails = guard.check("a table for two", "a table for three")
    assert {"kind": "numbers", "item": 3} in fails


def test_guard_catches_invented_name_and_word():
    fails = guard.check("book for me", "book for Matara tonight")
    assert {"kind": "names", "item": "matara"} in fails
    assert any(f["kind"] == "word" and f["item"] == "tonight" for f in fails) or \
        {"kind": "days", "item": "today"} in fails


def test_guard_allows_approved_switch():
    assert guard.check("book for the day after Monday", "book for Tuesday", SWITCH) == []
    unapproved = [{**SWITCH[0], "approved": False}]
    assert guard.check("book for the day after Monday", "book for Tuesday", unapproved)


class FakeChat:
    def __init__(self, data):
        self.data = data
        self.calls = 0

    async def __call__(self, messages, **kw):
        self.calls += 1
        return {"content": json.dumps(self.data), "tool_calls": [], "ms": 10}


def test_spark_resolves_self_correction():
    chat = FakeChat({"clean": "A table for three people", "confidence": 0.95,
                     "changes": [{"from": "two, no, three", "to": "three"}]})
    out = run(rebuild("A table for two, no, three people", chat=chat))
    assert out["clean"] == "A table for three people"
    assert not out["needs_confirm"] and out["guard_fails"] == []


def test_no_spark_without_correction_pattern():
    chat = FakeChat({})
    out = run(rebuild("Book a table for two", chat=chat))
    assert chat.calls == 0 and out["clean"] == "Book a table for two" and out["confidence"] == 1.0


def test_guard_flags_model_inventing_a_number():
    chat = FakeChat({"clean": "A table for four people", "confidence": 0.99, "changes": []})
    out = run(rebuild("A table for two, no, three people", chat=chat))
    assert out["needs_confirm"] is True
    assert {"kind": "numbers", "item": 4} in out["guard_fails"]
    assert out["raw"] == "A table for two, no, three people"


def test_low_confidence_needs_confirm():
    chat = FakeChat({"clean": "A table for three people", "confidence": 0.5, "changes": []})
    assert run(rebuild("A table for two, sorry, three people", chat=chat))["needs_confirm"]


def test_approved_switch_goes_through_spark_and_guard():
    chat = FakeChat({"clean": "Book for Tuesday", "confidence": 0.9, "changes": []})
    out = run(rebuild("Book for the day after Monday", SWITCH, chat=chat))
    assert chat.calls == 1 and out["clean"] == "Book for Tuesday" and not out["needs_confirm"]


def test_spark_error_keeps_code_pass():
    async def broken(*a, **k):
        raise RuntimeError("down")
    out = run(rebuild("uh two, no, three", chat=broken))
    assert out["clean"] == "Two, no, three" or out["clean"].lower() == "two, no, three"
    assert out["spark"]["error"] == "RuntimeError"
