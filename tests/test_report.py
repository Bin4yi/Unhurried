import json

from bench.metrics import summarize
from bench.report import build, set_of

ROWS = {
    "baseline": [
        {"clip": "s1", "kind": "talk", "cut_off": True, "cut_ins": 2, "understood": False, "delay_s": 0.8,
         "understanding_scored": False, "invented": 0, "turns": 3, "early_eos": 2, "confirms": 0},
        {"clip": "f1", "kind": "fluent", "cut_off": False, "cut_ins": 0, "understood": True, "delay_s": 0.8,
         "invented": 0, "turns": 1, "early_eos": 0, "confirms": 1}],
    "sound_spark": [
        {"clip": "s1", "kind": "talk", "cut_off": False, "cut_ins": 0, "understood": False, "delay_s": 1.1,
         "understanding_scored": False, "invented": 0, "turns": 1, "early_eos": 2, "confirms": 1},
        {"clip": "f1", "kind": "fluent", "cut_off": False, "cut_ins": 0, "understood": True, "delay_s": 1.2,
         "invented": 0, "turns": 1, "early_eos": 0, "confirms": 1}],
}


def test_report_has_one_table_per_set_with_numbers_from_files(tmp_path, monkeypatch):
    import bench.report as rep
    monkeypatch.setattr(rep, "ROOT", tmp_path)
    summary = {n: summarize(r) for n, r in ROWS.items()}
    summary["sound_spark"]["added_delay_vs_baseline"] = {"n": 1, "median_s": 0.4, "p95_s": 0.4}
    real = {"run": "r1", "set": "real_self", "date": "2026-11-05 01:00", "summary": summary,
            "rows": ROWS, "usd": 0.12, "failed": []}
    syn = {**real, "set": None, "clips_file": "bench/clips_synthetic.jsonl"}
    p1, p2 = tmp_path / "r1.json", tmp_path / "r2.json"
    p1.write_text(json.dumps(real))
    p2.write_text(json.dumps(syn))
    page = build([p1, p2])
    assert "Real: my own voice" in page and "Synthetic: text-to-speech" in page
    assert page.count("<table>") >= 2
    assert ">1 / 1<" in page and ">2<" in page          # baseline cut-offs and replies while talking
    assert "0.40 s" in page and "Early end-of-speech" in page
    assert set_of(syn) == "synthetic" and set_of(real) == "real_self"
