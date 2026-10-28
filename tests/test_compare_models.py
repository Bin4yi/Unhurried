import json

import bench.compare_models as cm


def test_decision_points_label_pauses_and_final_text(tmp_path, monkeypatch):
    monkeypatch.setattr(cm, "ROOT", tmp_path)
    d = tmp_path / "runs" / "bench_r1_words_syn_01"
    d.mkdir(parents=True)
    rows = [{"dir": "in", "type": "model_turn", "text": "Book a table for"},
            {"dir": "out", "type": "model_text", "text": "Book a table for"},
            {"dir": "in", "type": "model_turn", "text": "two at seven on Friday"}]
    (d / "events.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
    run = {"run": "r1", "rows": {"words": [{"clip": "syn_01"}]}}
    assert cm.decision_points(run) == [
        ("Book a table for", "no"),
        ("Book a table for two at seven on Friday", "yes"),
    ]
