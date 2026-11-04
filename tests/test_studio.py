import json

import numpy as np
import pytest
from fastapi.testclient import TestClient

from server.studio import align, edits, jobs, render
from server.studio.align import Word
from tests.fakes import run


def words(spec):
    """spec: [(text, start, end)]"""
    return [Word(t, s, e, 0.9) for t, s, e in spec]


def test_spoken_tokens_and_split():
    assert align.spoken_tokens("b-b-book") == "B B BOOK"
    assert align.spoken_tokens("2") == "TWO" and align.spoken_tokens("19") == "NINETEEN"
    assert align.split_words("I want to b-b-book it.") == ["I", "want", "to", "b-", "b-", "book", "it."]
    assert align.split_words("well-known") == ["well-known"]


def test_viterbi_finds_token_order():
    # 3 tokens over 8 frames, blank = 0; token k is likely in frames 2k+1
    em = np.full((8, 4), np.log(0.01))
    em[:, 0] = np.log(0.5)
    for k, t in enumerate([1, 3, 5]):
        em[t, k + 1] = np.log(0.97)
    states = align.viterbi(em, [1, 2, 3], blank=0)
    firsts = [int(np.argmax(states == 2 * k + 1)) for k in range(3)]
    assert firsts == [1, 3, 5]


def test_repeats_keep_last_copy_and_phrases():
    w = words([("I", 0.0, 0.1), ("I", 0.3, 0.4), ("I", 0.6, 0.7), ("want", 0.8, 1.0),
               ("in", 1.1, 1.2), ("depth", 1.2, 1.5), ("in", 1.6, 1.7), ("depth", 1.7, 2.0)])
    found = edits.find_repeats(w)
    assert [(e["words"], e["text"]) for e in found] == [([0, 1], "I I"), ([4, 5], "in depth")]
    assert found[0]["start"] == 0.0 and found[0]["end"] == 0.6   # cut up to the kept copy


def test_fillers_blocks_and_transcript_sound_repeats():
    w = words([("b-", 0.0, 0.1), ("book", 0.4, 0.7), ("uh", 0.9, 1.1), ("a", 2.5, 2.6), ("table", 2.6, 3.0)])
    kinds = sorted(e["kind"] for e in edits.find_sounds(w, []) + edits.find_fillers(w) + edits.find_blocks(w))
    assert kinds == ["block", "filler", "sound"]
    block = edits.find_blocks(w)[0]
    assert block["start"] == pytest.approx(1.25) and block["end"] == pytest.approx(2.35)


def test_acoustic_sound_repeat_inside_word():
    w = words([("book", 0.0, 1.0)])
    acoustic = [{"text": "B", "start": 0.0, "end": 0.1}, {"text": "B", "start": 0.3, "end": 0.4},
                {"text": "BOOK", "start": 0.6, "end": 1.0}]
    e = edits.find_sounds(w, acoustic)[0]
    assert e["kind"] == "sound" and e["end"] == 0.6 and e["partial"]


def test_corrections_only_delete_and_are_bounded():
    w = words([(t, i * 0.3, i * 0.3 + 0.2) for i, t in enumerate("a table for two no three people".split())])

    async def chat(messages, **kw):
        return {"content": json.dumps({"remove": [[3, 4], [99, 100], "bad"]})}

    found = run(edits.find_corrections(w, chat=chat))
    assert [e["words"] for e in found] == [[3, 4]]
    assert edits.clean_text(w, found) == "a table for three people"

    async def greedy(messages, **kw):
        return {"content": json.dumps({"remove": [[0, 6]]})}
    assert run(edits.find_corrections(w, chat=greedy)) == []   # guard: not most of the recording


def test_render_only_cuts():
    rate = 1000
    x = np.arange(3000, dtype=np.float32) / 3000
    assert render.keep_ranges(3.0, [(0.5, 1.0), (0.9, 1.5)]) == [(0.0, 0.5), (1.5, 3.0)]
    y = render.render(x, rate, [{"start": 0.5, "end": 1.5, "on": True}, {"start": 2, "end": 2.5, "on": False}])
    assert len(y) == 2000 - int(render.FADE_S * rate)
    assert y.max() <= x.max() + 1e-6                      # nothing louder or new
    assert render.output_map(3.0, [{"start": 0.5, "end": 1.5, "on": True}])[1] == {"src": [1.5, 3.0], "dst": 0.5}


def test_words_match_for_live_check():
    assert jobs.words_match("the river was calm and green this morning", jobs.VERIFY_SENTENCES[0]) == 1.0
    assert jobs.words_match("hello", jobs.VERIFY_SENTENCES[0]) < 0.7


def test_studio_api_flow(monkeypatch, tmp_path):
    from server.main import app

    async def fake_transcribe(wav, **kw):
        return {"transcript": "I I want a table", "turns": [{"transcript": "I I want a table"}]}

    def fake_align(audio16, transcript):
        return words([("I", 0.0, 0.1), ("I", 0.2, 0.3), ("want", 0.4, 0.6), ("a", 0.7, 0.8),
                      ("table", 0.8, 1.0)]), []

    monkeypatch.setattr(jobs.llm, "transcribe_file", fake_transcribe)
    monkeypatch.setattr(jobs.align, "align_all", fake_align)
    wav = render.wav_bytes(np.zeros(24000, dtype=np.float32), 24000)
    c = TestClient(app)
    r = c.post("/studio/process", files={"audio": ("a.wav", wav, "audio/wav")},
               data={"source": "upload", "spark": "false"})
    assert r.status_code == 200, r.text
    job = r.json()
    assert job["clean_text"] == "I want a table" and job["edits"][0]["kind"] == "repeat"
    jid = job["id"]
    assert c.post(f"/studio/{jid}/edits", json={"on": {"e1": False}}).json()["clean_text"] == "I I want a table"
    assert c.post(f"/studio/{jid}/render").status_code == 200
    assert c.get(f"/studio/{jid}/audio/clean.wav").status_code == 200
    assert c.get(f"/studio/{jid}/audio/../job.json").status_code == 404
    # uploaded audio can never be cloned
    assert c.post(f"/studio/{jid}/verify", files={"audio": ("v.wav", wav, "audio/wav")},
                  data={"sentence": jobs.VERIFY_SENTENCES[0]}).status_code == 403
    assert c.post(f"/studio/{jid}/clone").status_code == 403
    assert c.delete(f"/studio/{jid}").json() == {"deleted": True}
    assert c.get(f"/studio/{jid}").status_code == 404


def test_correction_wins_over_overlapping_repeat():
    w = words([(t, i * 0.3, i * 0.3 + 0.2) for i, t in enumerate("a table for four four no five people".split())])

    async def chat(messages, **kw):
        return {"content": json.dumps({"remove": [[3, 5]]})}

    found = run(edits.find_edits(w, [], chat=chat))
    assert [e["kind"] for e in found] == ["correction"]
    assert edits.clean_text(w, found) == "a table for five people"


def test_viterbi_handles_long_recordings():
    # 400 tokens = 801 CTC states: past the int8 range that used to overflow
    n, T = 400, 1200
    rng = np.random.default_rng(1)
    em = np.log(rng.dirichlet(np.ones(30), size=T))
    tokens = list(rng.integers(1, 30, size=n))
    states = align.viterbi(em, tokens, blank=0)
    assert len(states) == T and states[-1] >= 2 * n - 1
    assert all(b >= a for a, b in zip(states, states[1:]))   # path only moves forward


def test_transcript_sound_token_before_word():
    w = words([("is", 5.6, 5.8), ("BBV", 5.96, 6.48), ("Binula", 6.96, 7.4)])
    found = edits.find_sounds(w, [])
    assert [(e["text"], e["end"]) for e in found] == [("BBV", 6.96)]
    assert edits.clean_text(w, found) == "is Binula"
    # real words with repeated letters are not sound repeats
    for real, nxt in [("test", "this"), ("app", "and"), ("that", "the"), ("will", "work")]:
        assert not edits.is_sound_token(real, nxt)
    assert edits.is_sound_token("Pp", "person") and edits.is_sound_token("b-", "book")


def test_acoustic_chain_with_voiced_twin_and_look_back():
    # "period" heard as "B B B DIAN"; the repeats sit inside the previous word's span
    w = words([("undergraduate", 24.9, 26.3), ("period", 26.7, 27.3)])
    acoustic = [{"text": "UNDREDUA", "start": 24.9, "end": 25.4},
                {"text": "BE", "start": 25.58, "end": 25.7}, {"text": "BE", "start": 26.1, "end": 26.2},
                {"text": "BE", "start": 26.72, "end": 26.8}, {"text": "DIET", "start": 26.9, "end": 27.3}]
    e = edits.find_sounds(w, acoustic)[0]
    assert (e["start"], e["end"], e["text"]) == (25.58, 26.72, "be- be-")


def test_acoustic_chain_ignores_other_words():
    # "going to test": "TO" before "TES" is a word, not a repeated sound
    w = words([("to", 4.0, 4.12), ("test", 4.12, 4.38)])
    acoustic = [{"text": "TO", "start": 4.0, "end": 4.1}, {"text": "TES", "start": 4.14, "end": 4.38}]
    assert edits.find_sounds(w, acoustic) == []
    # a whole repeated word is left to the repeat finder
    w2 = words([("my", 2.0, 2.2), ("name", 2.5, 2.8)])
    ac2 = [{"text": "MY", "start": 2.0, "end": 2.2}, {"text": "MY", "start": 2.25, "end": 2.4},
           {"text": "NAME", "start": 2.5, "end": 2.8}]
    assert edits.find_sounds(w2, ac2) == []


def test_short_attempt_before_word():
    assert edits.is_sound_token("ma", "mouse") and edits.is_sound_token("ca", "currently")
    for word, nxt in [("my", "mouse"), ("to", "test"), ("in", "india"), ("a", "apple"), ("me", "meta")]:
        assert not edits.is_sound_token(word, nxt)


def test_voiceover_time_mapping_and_ab_clip(monkeypatch, tmp_path):
    from server.studio import voiceover
    omap = render.output_map(10.0, [{"start": 2.0, "end": 4.0, "on": True}, {"start": 6.0, "end": 7.0, "on": True}])
    assert voiceover.to_clean_time(1.0, omap) == 1.0
    assert voiceover.to_clean_time(3.0, omap) == 2.0          # inside a cut: next kept part
    assert voiceover.to_clean_time(5.0, omap) == 3.0
    assert voiceover.to_clean_time(8.0, omap) == 5.0
    assert voiceover.to_original_time(3.0, omap) == 5.0
    assert voiceover.to_original_time(4.5, omap) == 7.5
    for t in [0.5, 1.9, 4.2, 5.5, 7.1, 9.9]:                 # round trip on kept audio
        assert abs(voiceover.to_original_time(voiceover.to_clean_time(t, omap), omap) - t) < 1e-9

    monkeypatch.setattr(jobs, "DATA", tmp_path)
    rate = 24000
    x = np.ones(rate * 10, dtype=np.float32) * 0.1
    job = {"id": "a" * 16, "created": 1.0, "duration": 10.0, "transcript": "hi", "source": "mic",
           "edits": [{"start": 2.0, "end": 4.0, "on": True}]}
    d = tmp_path / job["id"]
    d.mkdir()
    (d / "original.wav").write_bytes(render.wav_bytes(x, rate))
    (d / "job.json").write_text(json.dumps(job))
    y, r = render.read_wav_bytes(voiceover.ab_clip(job, 1.0, 5.0))
    # before: 5 s; gap 0.7 s; after: original 1-6 s minus the 2 s cut = 3 s
    assert abs(len(y) / r - (5.0 + voiceover.GAP_S + 3.0)) < 0.05
    assert voiceover.recent()[0]["id"] == job["id"]


def test_latin_only_drops_other_scripts():
    hindi = chr(0x92e) + chr(0x93e) + chr(0x908)
    assert jobs.latin_only(hindi + " inside my browser") == "inside my browser"
    assert jobs.latin_only("caf" + chr(0xe9) + " ok") == "caf" + chr(0xe9) + " ok"


def test_whole_word_with_dash_stays_in_clean_text():
    w = words([("before", 0.0, 0.3), ("it", 0.4, 0.5), ("books-", 0.6, 0.9), ("b-", 1.0, 1.1), ("anything", 1.2, 1.6)])
    assert edits.clean_text(w, []) == "before it books anything"


def test_person_choices_survive_reanalysis():
    old = [{"kind": "repeat", "start": 1.0, "end": 1.5, "on": False, "user_set": True},
           {"kind": "sound", "start": 3.0, "end": 3.2, "on": True}]
    new = [{"kind": "repeat", "start": 1.1, "end": 1.6, "on": True},
           {"kind": "sound", "start": 3.0, "end": 3.2, "on": False}]
    jobs.keep_person_choices(old, new)
    assert new[0]["on"] is False and new[0]["user_set"]
    assert new[1]["on"] is False          # not chosen by hand: the new analysis decides


def test_manual_cut_and_it_survives_reanalysis(monkeypatch, tmp_path):
    monkeypatch.setattr(jobs, "DATA", tmp_path)
    job = {"id": "b" * 16, "edits": [], "words": [
        {"text": "way", "start": 1.0, "end": 1.2, "score": 0.9},
        {"text": "way", "start": 1.3, "end": 1.5, "score": 0.9},
        {"text": "to", "start": 1.6, "end": 1.7, "score": 0.9}]}
    (tmp_path / job["id"]).mkdir()
    jobs.add_manual_cut(job, 0)
    e = job["edits"][0]
    assert (e["kind"], e["start"], e["end"], e["on"]) == ("manual", 1.0, 1.3, True)
    import pytest
    with pytest.raises(ValueError):
        jobs.add_manual_cut(job, 2)           # no word after it
    new = []
    jobs.keep_person_choices(job["edits"], new)
    assert new and new[0]["kind"] == "manual"
