import pytest

from server.turn_controller import TurnController, classify

# (text, expected unfinished, reason key that must be true or None)
CASES = [
    ("Book a table for", True, "linking_word"),
    ("I want to", True, "linking_word"),
    ("Book a table at the", True, "linking_word"),
    ("Can I book a table with", True, "linking_word"),
    ("I would like to b-", True, "cut_word"),
    ("Book a table for two on Fr-", True, "cut_word"),
    ("I want a bo", True, "cut_word"),
    ("I I I", True, "repeat"),
    ("Book a table for two two", True, "repeat"),
    ("Book a table uh", True, "filler"),
    ("um", True, None),
    ("uh um", True, None),
    ("", True, None),
    ("Book a table for two", False, None),
    ("Book a table for two at seven on Friday.", False, None),
    ("What time do you close?", False, None),
    ("Cancel my booking", False, None),
    ("Yes", False, None),
    ("Book a table for 2 at 7 pm", False, None),
    ("I-I-I want to b-b-book a table for four", False, None),
]


@pytest.mark.parametrize("text,unfinished,key", CASES)
def test_classify(text, unfinished, key):
    sig = classify(text)
    assert sig["unfinished"] is unfinished
    if key:
        assert sig[key]


def test_linking_word_holds_then_joins_into_one_turn():
    c = TurnController()
    c.on_speech_start(0.1)
    c.on_pause(1.5, 2.2)
    acts = c.on_model_turn("Book a table for", 2.2)
    assert acts[0]["do"] == "hold" and acts[0]["reason"] == "linking_word"
    assert c.tick(4.0) == []                      # 3 s pause: still holding
    assert c.on_speech_start(4.6, start_t=4.5) == [{"do": "resume"}]
    assert c.inner_pauses_ms == [3000]
    c.on_pause(6.0, 6.7)
    assert c.on_model_turn("two at seven on Friday", 6.7) == []   # send soon
    assert c.tick(6.9) == []
    acts = c.tick(7.0)
    assert acts == [{"do": "send", "text": "Book a table for two at seven on Friday",
                     "reason": "rules"}]
    assert c.text == ""


def test_fluent_sentence_sends_after_300ms():
    c = TurnController()
    c.on_pause(2.0, 2.7)
    c.on_model_turn("What time do you close?", 2.7)
    assert c.tick(2.99) == []
    assert c.tick(3.0)[0]["reason"] == "rules"


def test_max_wait_sends_held_turn():
    c = TurnController(max_wait_ms=6000)
    c.on_pause(1.0, 1.7)
    c.on_model_turn("Book a table for", 1.7)
    assert c.tick(6.9) == []
    assert c.tick(7.0)[0] == {"do": "send", "text": "Book a table for", "reason": "max_wait"}


def test_filler_only_turn_never_ends_before_max_wait_from_open():
    c = TurnController(max_wait_ms=6000)
    c.on_speech_start(0.5)
    c.on_pause(1.0, 1.7)
    assert c.on_model_turn("uh", 1.7)[0]["reason"] == "no_words"
    assert c.tick(6.0) == []          # 5 s after the pause, 5.5 s after open
    assert c.tick(6.5)[0]["reason"] == "max_wait_empty"


def test_four_second_silence_after_linking_word_keeps_holding():
    c = TurnController(max_wait_ms=6000)
    c.on_pause(1.0, 1.7)
    c.on_model_turn("I want to", 1.7)
    assert c.tick(5.0) == []
    assert c.holding


def test_speech_resume_cancels_pending_send():
    c = TurnController()
    c.on_pause(1.0, 1.7)
    c.on_model_turn("Book a table for two", 1.7)
    c.on_speech_start(1.8, 1.75)
    assert c.tick(2.5) == []


def test_typed_text_joins_open_turn():
    c = TurnController()
    c.on_pause(1.0, 1.7)
    c.on_model_turn("Book a table for", 1.7)
    acts = c.on_typed("four people", 3.0)
    assert acts == [{"do": "send", "text": "Book a table for four people", "reason": "typed"}]


def test_decision_log_format():
    c = TurnController()
    c.on_pause(1.0, 1.8)
    c.on_model_turn("Book a table for", 1.8)
    row = c.decisions[-1]
    assert row["pause_ms"] == 800 and row["decision"] == "hold"
    assert row["last_words"] == ["table", "for"]
    assert row["signals"]["linking_word"] is True
    assert set(row) >= {"t", "pause_ms", "last_words", "signals", "spark_check",
                        "decision", "max_wait_ms"}


def test_typed_text_with_no_open_turn_sends_alone():
    c = TurnController()
    assert c.on_typed("What time do you close?", 1.0) == [
        {"do": "send", "text": "What time do you close?", "reason": "typed"}]


def test_typed_text_merges_with_live_partial():
    c = TurnController()
    c.on_partial("Book a table", 1.0)
    assert c.on_typed("for Matara branch", 2.0)[0]["text"] == "Book a table for Matara branch"


def test_own_voice_check_blocks_send_while_model_has_not_caught_up():
    c = TurnController()
    c.on_pause(1.0, 1.7)
    c.on_model_turn("Book a table for two", 1.7)      # send due at 2.0
    assert c.tick(2.1, last_voice_t=2.0) == []          # voice heard again at 2.0
    assert c.tick(2.6, last_voice_t=2.0)[0]["reason"] == "rules"  # quiet again: no new speech came


def test_max_wait_counts_from_last_voice():
    c = TurnController(max_wait_ms=3000)
    c.on_pause(1.0, 1.7)
    c.on_model_turn("I want to", 1.7)
    assert c.tick(4.5, last_voice_t=2.5) == []          # 2.0 s since voice
    assert c.tick(5.5, last_voice_t=2.5)[0]["reason"] == "max_wait"


@pytest.mark.parametrize("sound", [None,
                                   {"pitch_falling": None, "fade": 0.3, "voiced_in_pause": False, "score": 0.5},
                                   {"pitch_falling": False, "fade": 0.0, "voiced_in_pause": False, "score": 0.1}])
def test_no_decision_waits_more_than_700_ms_for_spark(sound):
    c = TurnController(use_checker=True, use_sound=True, check_timeout_ms=700)
    c.on_pause(1.0, 2.0)
    acts = c.on_model_turn("Book a table for two", 2.0, sound=sound)
    assert acts == [{"do": "check", "text": "Book a table for two"}]
    assert c.tick(2.69) == []                       # still inside the 700 ms budget
    late = c.tick(2.70)                             # Spark not back: decide now with words + voice
    assert late and late[0]["do"] in ("send", "hold")
    assert late[0]["reason"] in ("spark_late", "spark_late_sound")
    assert c.decisions[-1]["spark_check"] == {"answer": "late"}
    assert c.awaiting is None                       # nothing is left waiting on Spark


def test_words_and_voice_agree_skip_spark():
    c = TurnController(use_checker=True, use_sound=True)
    c.on_pause(1.0, 2.0)
    finished = {"pitch_falling": True, "fade": 0.8, "voiced_in_pause": False, "score": 0.9}
    assert c.on_model_turn("Book a table for two", 2.0, sound=finished)[0]["reason"] == "words_sound"
