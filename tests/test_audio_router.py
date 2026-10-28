import numpy as np

from server.audio_router import AudioRouter
from tests.fakes import FakeStream, run


def make_router(script=None):
    out = []

    async def emit(ev):
        out.append(ev)

    return AudioRouter(FakeStream(script=script), emit), out


def test_feed_advances_audio_clock_and_forwards():
    r, _ = make_router()
    run(r.feed(b"\x00\x00" * 1920))  # 80 ms at 24 kHz
    assert abs(r.audio_t - 0.08) < 1e-9
    assert len(r.stream.sent) == 3840


def test_recent_audio_keeps_last_seconds():
    r, _ = make_router()
    chunk = (np.ones(2400, dtype="<i2") * 1000).tobytes()  # 0.1 s
    for _ in range(50):
        run(r.feed(chunk))
    assert len(r.recent_audio(0.5)) == 12000
    assert r._recent_samples <= 4 * 24000 + 2400
    assert abs(r.recent_audio(0.1)[0] - 1000 / 32768) < 1e-6


def test_normalize_events():
    r, _ = make_router()
    r.audio_t = 2.0
    assert r.normalize({"type": "transcript", "transcript": " Book a ", "final": False}) == \
        {"type": "partial", "text": "Book a", "t": 2.0}
    assert r.normalize({"type": "transcript", "transcript": "", "final": True}) is None
    end = r.normalize({"type": "speechEnd", "turnId": 0, "audioProcessedMs": 1500})
    assert end == {"type": "speech_end", "t": 2.0, "end_t": 1.5, "turn_id": 0}
    turn = r.normalize({"type": "speechComplete", "turnId": 0, "transcript": "Book a table for"})
    assert turn["type"] == "model_turn" and turn["text"] == "Book a table for"
    assert r.normalize({"type": "session", "sessionId": "x"}) is None


def test_pump_emits_until_closed():
    script = [{"type": "speechStart", "turnId": 0},
              {"type": "transcript", "transcript": "hi", "final": False}, None]
    r, out = make_router(script)
    run(r.pump())
    assert [e["type"] for e in out] == ["speech_start", "partial"]


def test_voice_check_tracks_loud_audio_only():
    r, _ = make_router()
    quiet = (np.random.default_rng(0).normal(0, 30, 1920)).astype("<i2").tobytes()
    loud = (np.sin(np.arange(1920) / 5) * 8000).astype("<i2").tobytes()
    for _ in range(20):
        run(r.feed(quiet))
    assert r.last_voice_t is None
    run(r.feed(loud))
    assert abs(r.last_voice_t - 21 * 0.08) < 1e-6
    run(r.feed(quiet))
    assert abs(r.last_voice_t - 21 * 0.08) < 1e-6
