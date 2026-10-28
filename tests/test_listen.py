import json

import numpy as np

from server.studio import align, listen
from server.studio.align import Word
from tests.fakes import run

RATE = align.RATE


def voice(seconds, gaps=()):
    """Loud tone audio with silent gaps [(start, end)]."""
    t = np.arange(int(seconds * RATE)) / RATE
    x = (0.3 * np.sin(2 * np.pi * 180 * t)).astype(np.float32)
    for a, b in gaps:
        x[int(a * RATE):int(b * RATE)] = 0
    return x


def test_parse_verbatim_strict_and_fallback():
    assert listen.parse_verbatim('{"verbatim": "B- B- Binula"}') == "B- B- Binula"
    assert listen.parse_verbatim('Sure! {"verbatim": "my my name"} ok') == "my my name"
    assert listen.parse_verbatim("no json here") is None
    assert listen.parse_verbatim('{"verbatim": ""}') is None


def test_stammer_marks_and_agreement():
    assert listen.stammer_marks("My My My name is B- B- Binula") == 5   # 2 repeats, 2 fragments, B- B-
    assert listen.agreement(["Hi", "my", "name", "Binula"], ["hi", "my", "name", "Tilaga"]) == 0.5


def test_chunks_split_in_quiet_places():
    x = voice(30, gaps=[(11.0, 11.4), (22.0, 22.3)])
    spans = listen.chunks(x)
    assert spans[0][0] == 0 and abs(spans[-1][1] - 30) < 1e-6
    assert all(listen.CHUNK_MIN_S - 0.01 <= b - a <= listen.CHUNK_MAX_S + 0.01 for a, b in spans[:-1])
    assert 11.0 <= spans[0][1] <= 11.4


def test_gates():
    x = voice(4, gaps=[(1.0, 2.0)])
    w = [Word("B-", 0.2, 0.3, 0.05), Word("Binula", 0.5, 0.9, 0.9), Word("is", 1.2, 1.3, 0.9),
         Word("is", 2.2, 2.4, 0.9), Word("here", 2.5, 2.9, 0.9)]
    ac = [{"text": "B", "start": 0.2, "end": 0.3}]
    sound = {"kind": "sound", "start": 0.2, "end": 0.5, "words": [0, 0], "text": "B-"}
    assert listen.check(sound, w, ac, x, 0.01) == (True, None)          # weak align is fine for a fragment
    silent = {"kind": "repeat", "start": 1.1, "end": 1.9, "words": [2, 2], "text": "is"}
    assert listen.check(silent, w, ac, x, 0.01)[1] == "no voice there"
    long = {**sound, "end": 3.0}
    assert "longer than" in listen.check(long, w, ac, x, 0.01)[1]
    unheard = {"kind": "sound", "start": 2.2, "end": 2.5, "words": [3, 3], "text": "is"}
    assert listen.check(unheard, w, ac, x, 0.01) == (False, None)       # passes, but not confirmed


def test_limit_share_turns_off_unconfirmed_first():
    found = [{"start": 0, "end": 2, "on": True, "confirmed": True},
             {"start": 3, "end": 5, "on": True, "confirmed": False},
             {"start": 6, "end": 7, "on": True, "confirmed": True}]
    listen.limit_share(found, 10)          # 5 s of 10 s > 35%
    assert [e["on"] for e in found] == [True, False, True] and found[1]["limited"]


def test_scan_model_cuts_need_evidence_and_drift_falls_back(monkeypatch):
    x = voice(20, gaps=[(9.9, 10.4)])
    listens = {"n": 0}

    async def chat(messages, **kw):
        listens["n"] += 1
        return {"content": json.dumps({"verbatim": "B- B- Binula is here" if listens["n"] <= 2 else "totally different words"})}

    def fake_align(seg, text):
        toks = text.split()
        return [Word(t, 0.2 + 0.3 * i, 0.4 + 0.3 * i, 0.9) for i, t in enumerate(toks)]

    monkeypatch.setattr(listen.align, "align", fake_align)
    vt = [Word("Binula", 0.8, 1.0, 0.9), Word("is", 1.1, 1.2, 0.9), Word("here", 1.4, 1.6, 0.9),
          Word("we", 12.0, 12.2, 0.9), Word("then", 12.3, 12.6, 0.9), Word("went", 12.7, 13.0, 0.9)]
    ac = [{"text": "B", "start": 0.2, "end": 0.35}]
    res = run(listen.scan(x, vt, ac, chat=chat))
    used = [p["used"] for p in res["pieces"]]
    assert used[0] == "model" and used[-1] == "rules"           # second piece drifted
    sounds = [e for e in res["edits"] if e["kind"] == "sound"]
    assert sounds and sounds[0]["by"] == "spark" and sounds[0]["on"]
    assert sounds[0]["agreed"]                                  # both listens of piece 1 agreed


def test_noise_floor_is_the_room_not_the_voice():
    x = voice(4, gaps=[(1.0, 2.0)])
    x[int(1.0 * RATE):int(2.0 * RATE)] = 0.001
    assert listen.noise_floor(x) < 0.01
    assert listen.noise_floor(voice(4)) == 0.02          # no pauses: capped below speech level
