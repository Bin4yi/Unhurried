import io
import json
import wave
from pathlib import Path

from fastapi.testclient import TestClient

from server.bench_api import build_clip, next_clip_id
from server.main import app


def wav(seconds=1.0, rate=24000):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(rate * seconds))
    return buf.getvalue()


META = {"kind": "stammer", "features": ["silent_block", "bogus"], "speech_end_s": 0.8,
        "expected": {"tool": "book_table", "args": {"people": 2, "time": "19:00", "day": "Fri"}},
        "consent": "self", "public_audio": True, "script": "Book a table"}


def test_next_clip_id(tmp_path):
    p = tmp_path / "clips.jsonl"
    assert next_clip_id(p) == "clip_01"
    p.write_text('{"id": "clip_07"}\n{"id": "syn_99"}\n')
    assert next_clip_id(p) == "clip_08"


def test_volunteer_audio_is_never_public():
    clip = build_clip({**META, "consent": "volunteer", "public_audio": True}, "clip_01", 1.0)
    assert clip["public_audio"] is False and clip["file"] == "bench/audio_private/clip_01.wav"


def test_save_clip_appends_line_and_saves_wav():
    c = TestClient(app)
    r = c.post("/bench/clip", files={"audio": ("c.wav", wav(), "audio/wav")},
               data={"meta": json.dumps(META)})
    assert r.status_code == 200, r.text
    clip = r.json()
    assert clip["id"] == "clip_01" and clip["features"] == ["silent_block"]
    assert Path("bench/audio/clip_01.wav").exists()
    line = json.loads(Path("bench/clips.jsonl").read_text().splitlines()[0])
    assert line == clip
    assert set(line) >= {"id", "file", "kind", "features", "speech_end_s", "expected",
                         "consent", "public_audio"}
    assert c.get("/bench/audio/clip_01.wav").status_code == 200


def test_rejects_bad_input():
    c = TestClient(app)
    bad_end = c.post("/bench/clip", files={"audio": ("c.wav", wav(), "audio/wav")},
                     data={"meta": json.dumps({**META, "speech_end_s": 5})})
    assert bad_end.status_code == 400
    stereo = io.BytesIO()
    with wave.open(stereo, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(b"\x00" * 400)
    r = c.post("/bench/clip", files={"audio": ("c.wav", stereo.getvalue(), "audio/wav")},
               data={"meta": json.dumps(META)})
    assert r.status_code == 400
    assert c.get("/bench/audio/..%2F..%2Fsecret.wav").status_code == 404
