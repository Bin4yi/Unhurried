"""Benchmark scoring. Measures the AI pipeline, never the person.

One run = one clip streamed through one config. From the run's events:
  cut_off     a turn was sent before the person's real end of speech ("cut-off")
  cut_ins     how many turns were sent before the real end (the bot replied while the
              person was still talking; for free talk there can be several)
  understood  the bot ran the expected tool with the expected details
  delay_s     last turn sent time minus real end of speech
  invented    the rebuild produced content the person did not say (guard fails)
  early_eos   Voice Transcribe's end-of-speech fired during a pause inside the speech
              ("early end-of-speech"): a signal only, not a reply
"""

from __future__ import annotations

import re
import statistics

CUT_TOLERANCE_S = 0.1
SLOW_LAG_S = 2.0  # speech service lag above this makes a run unreliable
DAYS = {"mon": "monday", "tue": "tuesday", "tues": "tuesday", "wed": "wednesday",
        "thu": "thursday", "thur": "thursday", "thurs": "thursday", "fri": "friday",
        "sat": "saturday", "sun": "sunday", "tonight": "today", "this evening": "today"}


def norm_day(d) -> str:
    s = str(d or "").strip().lower()
    if s in DAYS:
        return DAYS[s]
    return DAYS.get(s[:3], s)


def norm_time(t) -> str:
    m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?", str(t or "").strip())
    return f"{int(m.group(1)):02d}:{int(m.group(2) or 0):02d}" if m else str(t).strip().lower()


def args_match(expected: dict, got: dict) -> bool:
    for k, v in expected.items():
        g = got.get(k)
        if k == "people":
            try:
                if int(g) != int(v):
                    return False
            except (TypeError, ValueError):
                return False
        elif k == "time":
            if norm_time(g) != norm_time(v):
                return False
        elif k == "day":
            if norm_day(g) != norm_day(v):
                return False
        elif str(g).lower() != str(v).lower():
            return False
    return True


def understood(expected: dict, tool_calls: list[dict]) -> bool:
    tool = (expected or {}).get("tool")
    if not tool:
        return not any(c.get("name") in ("book_table", "cancel_booking") for c in tool_calls)
    for c in tool_calls:
        if c.get("name") == tool and c.get("confirmed", True) and args_match(expected.get("args", {}), c.get("args", {})):
            return True
    return False


def score_run(clip: dict, events: list[dict]) -> dict:
    end = float(clip["speech_end_s"])
    turns = [e for e in events if e.get("type") == "turn"]
    calls = [c for e in events if e.get("type") == "bot" for c in e.get("tool_calls", [])]
    stopped = next((e for e in events if e.get("type") == "stopped"), {})
    early = [e for e in events if e.get("type") == "speech_end" and e.get("end_t", 1e9) < end - 0.3]
    cut = [t for t in turns if t.get("sent_t", 1e9) < end - CUT_TOLERANCE_S]
    last_sent = max((t["sent_t"] for t in turns), default=None)
    lags = [e["t"] - e["start_t"] for e in events
            if e.get("type") == "speech_start" and e.get("start_t") is not None]
    return {
        "clip": clip["id"], "kind": clip["kind"],
        "turns": len(turns), "cut_off": bool(cut), "cut_ins": len(cut),
        "understood": understood(clip.get("expected", {}), calls),
        "understanding_scored": clip["kind"] != "talk",
        "delay_s": round(last_sent - end, 3) if last_sent is not None else None,
        "invented": sum(1 for t in turns if t.get("guard_fails")),
        "guard_events": [f for t in turns for f in t.get("guard_fails", [])],
        "early_eos": len(early),
        "confirms": stopped.get("confirms", 0),
        "model_lag_s": round(max(lags), 2) if lags else None,
        "reasons": [t.get("reason") for t in turns],
        "tool_calls": [{"name": c.get("name"), "args": c.get("args")} for c in calls],
        # the words of private recordings never go into a results file
        "texts": [t.get("clean") for t in turns] if clip.get("public_audio") else [],
    }


def pct(values: list[float], p: float) -> float | None:
    if not values:
        return None
    xs = sorted(values)
    k = (len(xs) - 1) * p / 100
    lo = int(k)
    hi = min(lo + 1, len(xs) - 1)
    return round(xs[lo] + (xs[hi] - xs[lo]) * (k - lo), 3)


def summarize(rows: list[dict]) -> dict:
    """Counts per config: cut-offs on stammer clips, understanding, fluent delay."""
    st = [r for r in rows if r["kind"] in ("stammer", "talk")]   # clips with pauses or repeats
    us = [r for r in rows if r.get("understanding_scored", True)]
    fl = [r for r in rows if r["kind"] == "fluent"]
    fl_delay = [r["delay_s"] for r in fl if r["delay_s"] is not None]
    return {
        "clips": len(rows), "stammer_clips": len(st), "fluent_clips": len(fl),
        "cut_offs": sum(r["cut_off"] for r in st),
        "cut_ins": sum(r.get("cut_ins", int(r["cut_off"])) for r in st),
        "understanding_clips": len(us),
        "cut_offs_fluent": sum(r["cut_off"] for r in fl),
        "understood": sum(r["understood"] for r in us),
        "understood_stammer": sum(r["understood"] for r in st),
        "understood_fluent": sum(r["understood"] for r in fl),
        "fluent_delay_median_s": round(statistics.median(fl_delay), 3) if fl_delay else None,
        "fluent_delay_p95_s": pct(fl_delay, 95),
        "invented_turns": sum(r["invented"] for r in rows),
        "turns": sum(r["turns"] for r in rows),
        "early_eos_stammer": sum(r["early_eos"] for r in st),
        "stammer_clips_with_early_eos": sum(1 for r in st if r["early_eos"]),
        "confirms": sum(r["confirms"] for r in rows),
        "slow_runs": sum(1 for r in rows if (r.get("model_lag_s") or 0) > SLOW_LAG_S),
    }


def added_delay(base_rows: list[dict], test_rows: list[dict]) -> dict:
    """Per fluent clip: test delay minus baseline delay (same clip)."""
    base = {r["clip"]: r["delay_s"] for r in base_rows if r["kind"] == "fluent"}
    diffs = [r["delay_s"] - base[r["clip"]] for r in test_rows
             if r["kind"] == "fluent" and r["delay_s"] is not None and base.get(r["clip"]) is not None]
    return {"n": len(diffs), "median_s": round(statistics.median(diffs), 3) if diffs else None,
            "p95_s": pct(diffs, 95)}
