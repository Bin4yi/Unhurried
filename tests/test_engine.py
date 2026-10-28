import asyncio

from server.completeness import check_complete, parse_answer
from server.engine import Engine
from server.turn_controller import TurnController
from tests.fakes import run


class Clock:
    t = 0.0


def make(answer="yes", delay=0.0):
    calls, out = [], []

    async def checker(text, provider="spark"):
        calls.append(text)
        await asyncio.sleep(delay)
        return answer, delay * 1000

    async def on_actions(acts):
        out.extend(acts)

    c = TurnController(use_checker=True)
    clock = Clock()
    return Engine(c, lambda: clock.t, on_actions, checker=checker), c, clock, calls, out


def test_parse_answer():
    assert parse_answer(" Yes.") == "yes" and parse_answer("no") == "no"
    assert parse_answer("maybe") == "unknown"


def test_check_complete_handles_errors():
    async def broken(*a, **k):
        raise RuntimeError("down")
    assert run(check_complete("hi", chat=broken))[0] == "error"


def test_speculative_answer_is_used_at_pause():
    async def go():
        e, c, clock, calls, out = make("yes")
        await e.handle({"type": "partial", "text": "What time do you close"})
        await e.handle({"type": "partial", "text": "Book a table for"})   # unfinished: no call
        await asyncio.sleep(0.01)
        clock.t = 2.0
        await e.handle({"type": "speech_end", "end_t": 1.5})
        acts = await e.handle({"type": "model_turn", "text": "What time do you close?"})
        return calls, acts
    calls, acts = run(go())
    assert calls == ["What time do you close"]
    assert acts == [{"do": "send", "text": "What time do you close?", "reason": "check_yes"}]


def test_slow_check_times_out_and_sends():
    async def go():
        e, c, clock, calls, out = make("yes", delay=0.2)
        clock.t = 2.0
        await e.handle({"type": "speech_end", "end_t": 1.5})
        acts = await e.handle({"type": "model_turn", "text": "Cancel my booking"})
        await asyncio.sleep(0)
        assert acts == [] and calls == ["Cancel my booking"]
        clock.t = 2.69
        assert e.tick() == []
        clock.t = 2.7
        sent = e.tick()
        await asyncio.sleep(0.3)   # late answer must not send twice
        return sent, out
    sent, out = run(go())
    assert sent[0]["reason"] == "check_timeout"
    assert out == []


def test_no_answer_holds():
    async def go():
        e, c, clock, calls, out = make("no", delay=0.01)
        clock.t = 2.0
        await e.handle({"type": "speech_end", "end_t": 1.5})
        await e.handle({"type": "model_turn", "text": "Book a table for two"})
        await asyncio.sleep(0.05)
        return out, c
    out, c = run(go())
    assert out[0]["do"] == "hold" and out[0]["reason"] == "check_no"
    assert c.decisions[-1]["spark_check"]["answer"] == "no"
