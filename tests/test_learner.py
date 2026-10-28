import json

from server.learner import check_proposal, propose, summarize_session
from tests.fakes import run


def write(d, name, rows):
    (d / f"{name}.jsonl").write_text("\n".join(json.dumps(r) for r in rows))


def make_session(tmp_path):
    d = tmp_path / "s1"
    d.mkdir()
    write(d, "decisions", [
        {"decision": "hold", "pause_ms": 3400, "reason": "linking_word"},
        {"decision": "send", "pause_ms": 4200, "reason": "max_wait"}])
    write(d, "turns", [{"clean": "Book a table for Binula", "guard_fails": []}])
    write(d, "confirms", [{"text": "Book a table for 2?", "answer": "change"}])
    return d


def test_summary_has_no_audio_and_counts(tmp_path):
    s = summarize_session(make_session(tmp_path), 3000)
    assert s["holds"] == 1 and s["longest_hold_pause_ms"] == 3400
    assert s["turns_sent_by_max_wait"] == 1 and s["change_taps"] == ["Book a table for 2?"]


def test_hard_limits():
    p = check_proposal("adjust_max_wait", {"new_ms": 9000, "reason": "r"}, 3000)
    assert p["args"]["new_ms"] == 4000            # at most 1 s per step
    assert check_proposal("adjust_max_wait", {"new_ms": 500}, 2000) is None  # floor: no change
    assert check_proposal("adjust_max_wait", {"new_ms": 5800}, 6000)["args"]["new_ms"] == 5800
    assert check_proposal("set_pref", {"name": "fluency", "value": 1}, 3000) is None
    assert check_proposal("set_pref", {"name": "show_cue", "value": False}, 3000)["args"]["value"] is False
    assert check_proposal("add_listen_word", {"word": "x " * 30}, 3000) is None
    assert check_proposal("unknown", {}, 3000) is None


def test_propose_uses_tools_and_filters(tmp_path):
    make_session(tmp_path)

    async def chat(messages, **kw):
        assert "audio" not in messages[1]["content"]
        calls = [
            {"function": {"name": "adjust_max_wait", "arguments": json.dumps(
                {"new_ms": 3800, "reason": "You paused up to 3.4 s inside sentences today."})}},
            {"function": {"name": "set_pref", "arguments": json.dumps({"name": "x", "value": 1})}},
            {"function": {"name": "add_listen_word", "arguments": json.dumps(
                {"word": "Binula", "reason": "A name you used."})}},
        ]
        return {"content": "", "tool_calls": calls, "ms": 5}

    out = run(propose("s1", 3000, chat=chat, root=tmp_path))
    assert [p["tool"] for p in out] == ["adjust_max_wait", "add_listen_word"]
    assert out[0]["text"].startswith("Wait up to 3.8 s instead of 3.0 s.")


def test_propose_rejects_path_tricks(tmp_path):
    assert run(propose("../etc", 3000, root=tmp_path)) == []
