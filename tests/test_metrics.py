from bench.metrics import added_delay, args_match, norm_day, score_run, summarize, understood

CLIP = {"id": "c1", "kind": "stammer", "speech_end_s": 5.0,
        "expected": {"tool": "book_table", "args": {"people": 2, "time": "19:00", "day": "friday"}}}


def bot(name, args, confirmed=True):
    return {"type": "bot", "tool_calls": [{"name": name, "args": args, "confirmed": confirmed}]}


def test_normalizers():
    assert norm_day("Fri") == "friday" and norm_day("Friday") == "friday"
    assert norm_day("tonight") == "today" and norm_day("tomorrow") == "tomorrow"
    assert args_match({"time": "19:00", "people": 2}, {"time": "19:00", "people": "2"})
    assert not args_match({"time": "19:00"}, {"time": "7:00"})


def test_understood_needs_right_tool_args_and_confirm():
    calls = [{"name": "book_table", "args": {"people": 2, "time": "19:00", "day": "Fri"}, "confirmed": True}]
    assert understood(CLIP["expected"], calls)
    assert not understood(CLIP["expected"], [{**calls[0], "confirmed": False}])
    assert not understood(CLIP["expected"], [{**calls[0], "args": {"people": 3, "time": "19:00", "day": "Fri"}}])
    assert understood({"tool": "list_bookings", "args": {}}, [{"name": "list_bookings", "args": {}}])


def test_cut_off_detected_when_turn_sent_before_real_end():
    events = [
        {"type": "speech_end", "end_t": 1.5},
        {"type": "turn", "sent_t": 2.3, "reason": "model_end", "clean": "Book a table for"},
        {"type": "bot", "tool_calls": []},
        {"type": "turn", "sent_t": 5.8, "reason": "model_end", "clean": "two at seven on Friday"},
        bot("book_table", {"people": 2, "time": "19:00", "day": "Friday"}),
        {"type": "stopped", "confirms": 1},
    ]
    r = score_run(CLIP, events)
    assert r["cut_off"] and r["turns"] == 2 and r["understood"]
    assert r["delay_s"] == 0.8 and r["early_eos"] == 1 and r["confirms"] == 1


def test_one_turn_after_end_is_not_a_cut_off():
    events = [{"type": "turn", "sent_t": 5.6, "guard_fails": [{"kind": "numbers", "item": 4}]},
              bot("book_table", {"people": 2, "time": "19:00", "day": "friday"})]
    r = score_run(CLIP, events)
    assert not r["cut_off"] and r["invented"] == 1


def test_summary_and_added_delay():
    base = [{"clip": "f1", "kind": "fluent", "cut_off": False, "understood": True, "delay_s": 0.8,
             "invented": 0, "turns": 1, "early_eos": 0, "confirms": 1},
            {"clip": "s1", "kind": "stammer", "cut_off": True, "understood": False, "delay_s": 0.9,
             "invented": 0, "turns": 2, "early_eos": 1, "confirms": 0}]
    test = [{**base[0], "delay_s": 1.3}, {**base[1], "cut_off": False, "understood": True, "early_eos": 1}]
    s = summarize(test)
    assert s["cut_offs"] == 0 and s["understood"] == 2 and s["fluent_delay_median_s"] == 1.3
    assert summarize(base)["cut_offs"] == 1
    assert added_delay(base, test) == {"n": 1, "median_s": 0.5, "p95_s": 0.5}
