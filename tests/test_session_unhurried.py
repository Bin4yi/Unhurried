import asyncio

from server.session import Session
from tests.fakes import FakeStream, run


class FakeBot:
    def __init__(self):
        self.got = []

    async def respond(self, text):
        self.got.append(text)
        return {"reply": "ok", "tool_calls": []}


async def yes_checker(text, provider="spark"):
    return "yes", 5.0


def start_session(sent, fake, bot, **cfg):
    async def send(ev):
        sent.append(ev)
    start = {"type": "start", "mode": "unhurried", "session_id": "u_t", "bench": True, **cfg}
    return Session(send, start, stream_factory=lambda kw: fake, bot_factory=lambda: bot,
                   checker=yes_checker)


def test_unhurried_joins_turns_and_sends_clean_text():
    sent, bot = [], FakeBot()

    async def go():
        fake = FakeStream()
        s = start_session(sent, fake, bot, engine={"spark_check": False, "sound": False})
        await s.start()
        q = fake.queue.put_nowait
        q({"type": "speechStart", "turnId": 0, "audioProcessedMs": 0})
        q({"type": "speechEnd", "turnId": 0, "audioProcessedMs": 1000})
        q({"type": "speechComplete", "turnId": 0, "transcript": "I-I want to b-b-book a table for"})
        await asyncio.sleep(0.02)
        q({"type": "speechStart", "turnId": 1, "audioProcessedMs": 3000})
        q({"type": "speechEnd", "turnId": 1, "audioProcessedMs": 4000})
        q({"type": "speechComplete", "turnId": 1, "transcript": "two"})
        await asyncio.sleep(0.02)
        for _ in range(10):  # 0.8 s of audio drives the clock past the 300 ms send delay
            await s.audio(b"\x00\x00" * 1920)
        await asyncio.sleep(0.05)
        await s.stop()

    run(go())
    kinds = [e["type"] for e in sent]
    assert "hold" in kinds and kinds.count("turn") == 1
    decisions = [e for e in sent if e["type"] == "decision"]
    assert [d["decision"] for d in decisions] == ["hold", "send_soon", "send"]
    assert decisions[0]["reason"] == "linking_word"
    turn = next(e for e in sent if e["type"] == "turn")
    assert turn["raw"] == "I-I want to b-b-book a table for two"
    assert turn["clean"] == "I want to book a table for two"
    assert bot.got == ["I want to book a table for two"]


def test_typed_text_in_baseline_goes_straight_to_bot():
    sent, bot = [], FakeBot()

    async def go():
        fake = FakeStream()
        s = start_session(sent, fake, bot, mode="baseline")
        await s.start()
        await s.command({"type": "text", "text": "What time do you close?"})
        await asyncio.sleep(0.02)
        await s.stop()

    run(go())
    assert bot.got == ["What time do you close?"]
