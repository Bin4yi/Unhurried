"""Build bench/results.html: one table per set (real voice, synthetic). Sets are never mixed.
Every number comes from a results file in bench/results/.

Usage: python bench/report.py                 (latest results file of each set)
       python bench/report.py FILE [FILE ...]  (these files)
"""

from __future__ import annotations

import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LABELS = {"baseline": "Normal voice bot (default end-of-speech)", "words": "Unhurried: words only",
          "unhurried": "Unhurried: words + Spark check", "sound": "Unhurried: words + voice",
          "sound_spark": "Unhurried: words + voice + Spark (default)"}
SET_TITLES = {"real_self": "Real: my own voice (free talk)", "synthetic": "Synthetic: text-to-speech with silent pauses"}
SET_NOTES = {
    "real_self": "Recordings of the builder's own spontaneous speech, recorded live in Voice Studio "
                 "(own voice, own consent). The real end of speech is measured from the audio.",
    "synthetic": "Windows text-to-speech with silent pauses. They test the pipeline, not real "
                 "stammered speech; the synthetic voice ends every piece with falling pitch.",
}

CSS = """
:root{--bg:#f4efe6;--card:#fbf8f2;--ink:#1e1b16;--muted:#5b544a;--line:#ddd4c3;--good:#4f6e4b;--bad:#b8532c}
@media (prefers-color-scheme:dark){:root{--bg:#16130f;--card:#211d17;--ink:#efe7da;--muted:#b9ae9d;--line:#383128;--good:#93b38d;--bad:#e07c55}}
body{margin:0;background:var(--bg);color:var(--ink);font:17px/1.55 "Instrument Sans","Segoe UI",system-ui,sans-serif}
main{max-width:1200px;margin:0 auto;padding:28px 24px 64px}
h1{font:400 36px/1.15 Fraunces,Georgia,serif;margin:0 0 6px}h2{font:400 26px/1.2 Fraunces,Georgia,serif;margin:0 0 10px}
.sub{color:var(--muted);margin:0 0 22px}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:20px 22px;margin-bottom:20px;overflow-x:auto}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-weight:600;color:var(--muted);font-size:.85rem}
td.big{font:400 22px/1.2 Fraunces,Georgia,serif}
.cut{color:var(--bad);font-weight:600}.ok{color:var(--good)}.muted{color:var(--muted);font-size:.9rem}
body.demo{font-size:20px}body.demo h1{font-size:44px}body.demo .muted.src{display:none}
"""


def latest_per_set() -> list[Path]:
    """Newest run file of each set (run files start with the date; models_* files are skipped)."""
    best: dict[str, Path] = {}
    for p in sorted((ROOT / "bench/results").glob("2*.json")):
        best[set_of(json.loads(p.read_text(encoding="utf-8")))] = p
    if not best:
        raise SystemExit("No results yet. Run bench/run_bench.py first.")
    return [best[s] for s in ("real_self", "synthetic") if s in best]


def set_of(res: dict) -> str:
    if res.get("set"):
        return res["set"]
    return "synthetic" if "synthetic" in res.get("clips_file", "") else "unknown"


def fmt_s(v) -> str:
    return "–" if v is None else f"{v:.2f} s"


def frac(a, b) -> str:
    return f"{a} / {b}" if b else "–"


def summary_table(res: dict) -> str:
    rows = []
    for name, s in res["summary"].items():
        ad = s.get("added_delay_vs_baseline") or {}
        cut_ins = s.get("cut_ins", s["cut_offs"])
        rows.append(
            f"<tr><td>{html.escape(LABELS.get(name, name))}</td>"
            f"<td class=big>{frac(s['cut_offs'], s['stammer_clips'])}</td>"
            f"<td class=big>{cut_ins}</td>"
            f"<td>{s['early_eos_stammer']}</td>"
            f"<td>{frac(s['understood'], s.get('understanding_clips', s['clips']))}</td>"
            f"<td>{fmt_s(ad.get('median_s'))} / {fmt_s(ad.get('p95_s'))}</td>"
            f"<td>{s['invented_turns']} / {s['turns']}</td></tr>")
    return ("<table><tr><th>Turn engine</th><th>Cut-offs<br>(clips)</th>"
            "<th>Replies while<br>still talking</th><th>Early end-of-speech<br>(signal only)</th>"
            "<th>Understood</th><th>Added delay, fluent<br>median / p95</th>"
            "<th>Invented content<br>(turns)</th></tr>" + "".join(rows) + "</table>")


def clip_table(res: dict) -> str:
    names = list(res["rows"])
    by_clip: dict[str, dict] = {}
    for n in names:
        for r in res["rows"][n]:
            by_clip.setdefault(r["clip"], {"kind": r.get("kind")})[n] = r
    head = "".join(f"<th>{html.escape(LABELS.get(n, n))}</th>" for n in names)
    out = [f"<table><tr><th>Clip</th><th>Kind</th>{head}</tr>"]
    for cid in sorted(by_clip):
        cells = []
        for n in names:
            r = by_clip[cid].get(n)
            if not r or "error" in r:
                cells.append("<td class=muted>failed</td>")
                continue
            n_cut = r.get("cut_ins", int(r["cut_off"]))
            cut = f"<span class=cut>{n_cut} early</span>" if r["cut_off"] else "<span class=ok>waited</span>"
            cells.append(f"<td>{cut} · {r['turns']} turn(s) · end delay {fmt_s(r['delay_s'])}</td>")
        out.append(f"<tr><td>{cid}</td><td>{by_clip[cid]['kind']}</td>{''.join(cells)}</tr>")
    return "".join(out) + "</table>"


def section(path: Path) -> str:
    res = json.loads(path.read_text(encoding="utf-8"))
    s_name = set_of(res)
    any_s = next(iter(res["summary"].values()))
    failed = res.get("failed") or []
    fail_line = (f"<p class=muted>{len(failed)} runs failed after 3 tries and are left out: "
                 + ", ".join(f"{f['config']}/{f['clip']}" for f in failed) + "</p>") if failed else ""
    return f"""<section class="card"><h2>{html.escape(SET_TITLES.get(s_name, s_name))}</h2>
<p class=muted>{SET_NOTES.get(s_name, "")} Run {html.escape(res['date'])}. {any_s['clips']} clips
({any_s['stammer_clips']} with pauses or repeats, {any_s['fluent_clips']} fluent). Small set: counts, not percentages.</p>
{summary_table(res)}{fail_line}
<details><summary class=muted>Per clip</summary>{clip_table(res)}</details>
<p class="muted src">Source: {html.escape(str(path.relative_to(ROOT)))} · spend ${res.get('usd', 0):.2f}</p></section>"""


def build(paths: list[Path]) -> str:
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Unhurried Results</title>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400&family=Instrument+Sans:wght@400;600&display=swap" rel="stylesheet">
<style>{CSS}</style>
<link rel="stylesheet" href="/web/studio.css"></head>
<body data-demo-badge="Results file" data-demo-start="Benchmark · same audio through every setup · numbers from bench/results/">
<script type="module" src="/web/demo-mode.js"></script><main>
<script>if (new URLSearchParams(location.search).get("demo") === "1") document.body.classList.add("demo");</script>
<h1>Does voice AI cut people off?</h1>
<p class="sub">Unhurried benchmark. It measures the AI, never the person.</p>
{''.join(section(p) for p in paths)}
<section class="card"><p class=muted><strong>Cut-offs</strong>: a turn was actually sent to the bot before
the real end of speech (the bot replied while the person was still talking). <strong>Early end-of-speech</strong>:
Voice Transcribe's end-of-speech signal fired during a pause inside the speech; it is a signal, not a reply,
and Unhurried decides whether to act on it. <strong>Understood</strong>: the bot called the expected tool with the
expected people, time and day (not scored for free talk). <strong>Invented content</strong>: turns where the
rebuild added a word that was not said.</p></section>
</main></body></html>"""


def main() -> int:
    paths = [Path(a).resolve() for a in sys.argv[1:]] or latest_per_set()
    out = ROOT / "bench/results.html"
    out.write_text(build(paths), encoding="utf-8")
    print(f"Wrote {out.relative_to(ROOT)} from " + ", ".join(p.name for p in paths))
    return 0


if __name__ == "__main__":
    sys.exit(main())
