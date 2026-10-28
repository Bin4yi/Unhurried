import asyncio
import json
from pathlib import Path

from server.session import Session
from tests.fakes import FakeStream, run


def test_session_forwards_partials_and_logs():
    sent = []

    async def send(ev):
        sent.append(ev)

    async def go():
        fake = FakeStream()
        s = Session(send, {"type": "start", "mode": "baseline", "session_id": "t1",
                           "keywords": ["Binula"]}, stream_factory=lambda kw: fake)
        await s.start()
        await s.audio(b"\x00\x00" * 1920)
        fake.queue.put_nowait({"type": "transcript", "transcript": "Book a", "final": False})
        await asyncio.sleep(0.05)
        await s.stop()
        return fake

    fake = run(go())
    assert fake.opened and fake.closed
    assert sent[0]["type"] == "ready"
    assert {"type": "partial", "text": "Book a", "t": 0.08} in sent
    lines = Path("runs/t1/events.jsonl").read_text().splitlines()
    assert any(json.loads(x).get("text") == "Book a" for x in lines)
