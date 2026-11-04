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


def test_real_scripts_parse_expected():
    from server.bench_api import parse_real_scripts
    rows = parse_real_scripts("# c\nread | Book a table for two | 2 19:00 friday\n"
                              "read | What are my bookings | list_bookings\nthink | When do you close? | none\n"
                              "think | Book a family dinner | ask\n")
    assert rows[0]["expected"] == {"tool": "book_table", "args": {"people": 2, "time": "19:00", "day": "friday"}}
    assert rows[1]["expected"]["tool"] == "list_bookings" and rows[2]["expected"] == {}
    assert rows[3]["expected"] == {"tool": "book_table", "args": {}}
    assert [r["kind"] for r in rows] == ["fluent", "fluent", "stammer", "stammer"]
    assert rows[3]["mode"] == "think"


def test_real_self_clips_go_to_their_folder_and_can_be_undone():
    c = TestClient(app)
    meta = {**META, "set": "real_self"}
    r = c.post("/bench/clip", files={"audio": ("c.wav", wav(), "audio/wav")}, data={"meta": json.dumps(meta)})
    clip = r.json()
    assert clip["id"] == "real_01" and clip["set"] == "real_self"
    assert clip["file"] == "bench/audio/real_self/real_01.wav" and Path(clip["file"]).exists()
    assert c.get("/bench/audio/real_01.wav").status_code == 200
    assert c.delete("/bench/clip/real_01").json() == {"deleted": "real_01"}
    assert not Path(clip["file"]).exists() and Path("bench/clips.jsonl").read_text() == ""
    assert c.delete("/bench/clip/clip_01").status_code == 400      # only real-session clips


def test_real_self_must_be_own_voice():
    clip = build_clip({**META, "set": "real_self", "consent": "self"}, "real_01", 1.0)
    assert clip["set"] == "real_self"
    import pytest
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        build_clip({**META, "set": "real_self", "consent": "volunteer"}, "real_02", 1.0)
