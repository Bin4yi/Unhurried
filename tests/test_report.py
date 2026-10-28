import json

from bench.metrics import summarize
from bench.report import build

ROWS = {
    "baseline": [
        {"clip": "s1", "kind": "stammer", "cut_off": True, "understood": False, "delay_s": 0.8,
         "invented": 0, "turns": 2, "early_eos": 1, "confirms": 0, "model_lag_s": 0.8},
        {"clip": "f1", "kind": "fluent", "cut_off": False, "understood": True, "delay_s": 0.8,
         "invented": 0, "turns": 1, "early_eos": 0, "confirms": 1, "model_lag_s": 0.8}],
    "words": [
        {"clip": "s1", "kind": "stammer", "cut_off": False, "understood": True, "delay_s": 1.1,
         "invented": 0, "turns": 1, "early_eos": 1, "confirms": 1, "model_lag_s": 0.9},
        {"clip": "f1", "kind": "fluent", "cut_off": False, "understood": True, "delay_s": 1.2,
         "invented": 0, "turns": 1, "early_eos": 0, "confirms": 1, "model_lag_s": 0.9}],
}


def test_report_uses_numbers_from_results(tmp_path, monkeypatch):
    import bench.report as rep
    monkeypatch.setattr(rep, "ROOT", tmp_path)
    summary = {n: summarize(r) for n, r in ROWS.items()}
    summary["words"]["added_delay_vs_baseline"] = {"n": 1, "median_s": 0.4, "p95_s": 0.4}
    res = {"run": "r1", "date": "2026-11-02 10:00", "clips_file": "bench/clips_synthetic.jsonl",
           "summary": summary, "rows": ROWS, "usd": 0.12}
    p = tmp_path / "r1.json"
    p.write_text(json.dumps(res))
    page = build(p)
    assert "1 / 1 (100%)" in page          # baseline cut-offs
    assert "0 / 1 (0%)" in page            # words cut-offs
    assert "0.40 s" in page and "synthetic" in page
    assert "1 of 1</strong> stammer clips" in page
