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
