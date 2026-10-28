"""Build bench/results.html from a results file. Every number comes from that file.

Usage: python bench/report.py [bench/results/<run>.json]   (default: latest)
"""

from __future__ import annotations

import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LABELS = {"baseline": "Default end-of-speech (baseline)", "words": "Unhurried: words only",
          "unhurried": "Unhurried: words + Spark check", "sound": "Unhurried: words + sound",
          "sound_spark": "Unhurried: words + sound + Spark tie-break"}

CSS = """
:root{--bg:#f6f4ef;--card:#fff;--ink:#1f2328;--muted:#6b6f76;--line:#e3e0d8;--good:#2f6f62;--bad:#9a3b2b}
@media (prefers-color-scheme:dark){:root{--bg:#15171a;--card:#1e2125;--ink:#e8e6e1;--muted:#9a9ea6;--line:#2e3237;--good:#6fbfae;--bad:#e08a7a}}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:980px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:1.6rem;margin:0 0 4px}.sub{color:var(--muted);margin:0 0 20px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px;margin-bottom:16px;overflow-x:auto}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}
th,td{text-align:left;padding:6px 10px;border-bottom:1px solid var(--line);white-space:nowrap}
th{font-weight:600;color:var(--muted);font-size:.9rem}
.cut{color:var(--bad);font-weight:600}.ok{color:var(--good)}.muted{color:var(--muted);font-size:.9rem}
"""


def latest() -> Path:
    files = sorted((ROOT / "bench/results").glob("2*.json"))  # run files, not models_*.json
    if not files:
        raise SystemExit("No results yet. Run bench/run_bench.py first.")
    return files[-1]


def fmt_s(v) -> str:
    return "–" if v is None else f"{v:.2f} s"


def frac(a, b) -> str:
    return f"{a} / {b}" + (f" ({100 * a / b:.0f}%)" if b else "")


def summary_table(res: dict) -> str:
    rows = []
    for name, s in res["summary"].items():
        ad = s.get("added_delay_vs_baseline") or {}
        rows.append(
            f"<tr><td>{html.escape(LABELS.get(name, name))}</td>"
            f"<td>{frac(s['cut_offs'], s['stammer_clips'])}</td>"
            f"<td>{frac(s['understood'], s['clips'])}</td>"
            f"<td>{fmt_s(s['fluent_delay_median_s'])} / {fmt_s(s['fluent_delay_p95_s'])}</td>"
            f"<td>{fmt_s(ad.get('median_s'))} / {fmt_s(ad.get('p95_s'))}</td>"
            f"<td>{s['invented_turns']} / {s['turns']}</td>"
            f"<td>{s['confirms']}</td><td>{s.get('slow_runs', 0)}</td></tr>")
    return ("<table><tr><th>Turn engine</th><th>Cut-offs (stammer clips)</th><th>Understood</th>"
            "<th>Fluent delay median / p95</th><th>Added delay vs baseline median / p95</th>"
            "<th>Invented content (turns)</th><th>Confirms</th><th>Slow runs</th></tr>"
            + "".join(rows) + "</table>")


def eos_line(res: dict) -> str:
    s = res["summary"].get("baseline")
    if not s:
        return ""
    return (f"<p>Voice Transcribe's default end-of-speech fired in the middle of "
            f"<strong>{s['stammer_clips_with_early_eos']} of {s['stammer_clips']}</strong> stammer clips "
            f"({s['early_eos_stammer']} times in total), treating a pause as the end of the turn.</p>")


def clip_table(res: dict) -> str:
    names = list(res["rows"])
    by_clip: dict[str, dict] = {}
    for n in names:
        for r in res["rows"][n]:
            by_clip.setdefault(r["clip"], {"kind": r.get("kind")})[n] = r
    head = "".join(f"<th>{html.escape(n)}</th>" for n in names)
    out = [f"<table><tr><th>Clip</th><th>Kind</th>{head}</tr>"]
    for cid in sorted(by_clip):
        cells = []
        for n in names:
            r = by_clip[cid].get(n)
            if not r or "error" in r:
                cells.append("<td class=muted>error</td>")
                continue
            cut = "<span class=cut>cut off</span>" if r["cut_off"] else "<span class=ok>held</span>"
            und = "understood" if r["understood"] else "<span class=cut>missed</span>"
            cells.append(f"<td>{cut} · {und} · {r['turns']} turn(s) · {fmt_s(r['delay_s'])}</td>")
        out.append(f"<tr><td>{cid}</td><td>{by_clip[cid]['kind']}</td>{''.join(cells)}</tr>")
    return "".join(out) + "</table>"


def build(path: Path) -> str:
    res = json.loads(path.read_text(encoding="utf-8"))
    any_s = next(iter(res["summary"].values()))
    synthetic = "synthetic" in res.get("clips_file", "")
    note = ("These clips are <strong>synthetic</strong> (Windows text-to-speech with silent pauses), "
            "not real stammered speech. They test the pipeline, not real-world accuracy."
            if synthetic else "Clips are real recordings with written consent.")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Unhurried Results</title><style>{CSS}</style></head><body><main>
<h1>Does voice AI cut people off?</h1>
<p class="sub">Unhurried benchmark, run {html.escape(res['date'])}. Measures the AI, never the person.</p>
<section class="card"><p><strong>Small set:</strong> {any_s['clips']} clips
({any_s['stammer_clips']} with pauses or repeats, {any_s['fluent_clips']} fluent). {note}
Counts matter more than percentages here.</p>{eos_line(res)}</section>
<section class="card"><h2>Summary</h2>{summary_table(res)}
<p class="muted">Cut-off: a turn was sent to the bot before the real end of speech.
Understood: the bot called the expected tool with the expected people, time and day.
Delay: time from the real end of speech to the turn being sent.
Slow runs: the speech service lagged more than 2 s (less reliable).</p></section>
<section class="card"><h2>Per clip</h2>{clip_table(res)}</section>
<p class="muted">Source: {html.escape(str(path.relative_to(ROOT)))}. Spend for this run: ${res.get('usd', 0):.2f}.</p>
</main></body></html>"""


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else latest()
    out = ROOT / "bench/results.html"
    out.write_text(build(path.resolve()), encoding="utf-8")
    print(f"Wrote {out.relative_to(ROOT)} from {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
