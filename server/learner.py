"""Learner agent: after a session, propose small profile updates. The person decides.

Muse Spark reads a short summary of the session log (pauses, holds, sends,
Change taps, guard events; no audio) and calls tools to propose changes.
Every proposal is checked and clamped in code, explained in plain words, and
only applied in the browser after the person approves it. It tunes the app,
never judges the person: no scores, no tips, no "progress".
"""

from __future__ import annotations

import json
from pathlib import Path

from server import llm
from server.runlog import RUNS
from server.timing_profile import MAX_WAIT_MS, MIN_WAIT_MS

MAX_STEP_MS = 1000
PREFS = {"show_cue": (True, False), "confirm": ("important_only", "always"),
         "bot_pace": ("calm", "normal")}

SYSTEM = (
    "You tune a voice app that waits for people who pause or repeat sounds while speaking. "
    "You get a summary of one session. Propose at most 4 small changes to the app using the "
    "tools, only when the log clearly supports them. Each change needs a one-sentence reason "
    "in plain, simple English, about the app, never about the person's speech. Never judge, "
    "score or give speaking tips. If nothing needs changing, call no tools."
)

TOOLS = [
    {"type": "function", "function": {
        "name": "adjust_max_wait", "description": "Change how long the app waits during a pause.",
        "parameters": {"type": "object", "properties": {
            "new_ms": {"type": "integer"}, "reason": {"type": "string"}},
            "required": ["new_ms", "reason"]}}},
    {"type": "function", "function": {
        "name": "add_listen_word", "description": "Add a word the speech service should listen for.",
        "parameters": {"type": "object", "properties": {
            "word": {"type": "string"}, "reason": {"type": "string"}},
            "required": ["word", "reason"]}}},
    {"type": "function", "function": {
        "name": "add_switch", "description": "Suggest a personal word switch (said -> means).",
        "parameters": {"type": "object", "properties": {
            "said": {"type": "string"}, "means": {"type": "string"}, "reason": {"type": "string"}},
            "required": ["said", "means", "reason"]}}},
    {"type": "function", "function": {
        "name": "set_pref", "description": "Change a setting: show_cue, confirm or bot_pace.",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string"}, "value": {}, "reason": {"type": "string"}},
            "required": ["name", "value", "reason"]}}},
]


def _rows(session_dir: Path, name: str) -> list[dict]:
    p = session_dir / f"{name}.jsonl"
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def summarize_session(session_dir: Path, current_max_wait_ms: int) -> dict:
    decisions = _rows(session_dir, "decisions")
    turns = _rows(session_dir, "turns")
    confirms = _rows(session_dir, "confirms")
    holds = [d for d in decisions if d["decision"] == "hold"]
    max_wait_sends = [d for d in decisions if d.get("reason") in ("max_wait", "max_wait_empty")]
    resumed_pauses = [d["pause_ms"] for d in holds]
    return {
        "current_max_wait_ms": current_max_wait_ms,
        "turns": len(turns),
        "holds": len(holds),
        "longest_hold_pause_ms": max(resumed_pauses, default=0),
        "turns_sent_by_max_wait": len(max_wait_sends),
        "change_taps": [c.get("text") for c in confirms if c.get("answer") == "change"],
        "guard_events": [f for t in turns for f in t.get("guard_fails", [])][:10],
        "turn_texts": [t.get("clean") for t in turns][:20],
    }


def check_proposal(name: str, args: dict, current_max_wait_ms: int) -> dict | None:
    """Hard limits in code. Returns a clean proposal or None."""
    reason = str(args.get("reason", "")).strip()[:200]
    if name == "adjust_max_wait":
        try:
            want = int(args["new_ms"])
        except (KeyError, TypeError, ValueError):
            return None
        step = max(-MAX_STEP_MS, min(MAX_STEP_MS, want - current_max_wait_ms))
        new = max(MIN_WAIT_MS, min(MAX_WAIT_MS, current_max_wait_ms + step))
        if new == current_max_wait_ms:
            return None
        return {"tool": name, "args": {"new_ms": new}, "reason": reason,
                "text": f"Wait up to {new / 1000:.1f} s instead of {current_max_wait_ms / 1000:.1f} s. {reason}"}
    if name == "add_listen_word":
        word = str(args.get("word", "")).strip()
        if not word or len(word) > 40 or len(word.split()) > 3:
            return None
        return {"tool": name, "args": {"word": word}, "reason": reason,
                "text": f'Listen for "{word}". {reason}'}
    if name == "add_switch":
        said, means = str(args.get("said", "")).strip(), str(args.get("means", "")).strip()
        if not said or not means or len(said) > 60 or len(means) > 40:
            return None
        return {"tool": name, "args": {"said": said, "means": means}, "reason": reason,
                "text": f'When you say "{said}", read it as "{means}". {reason}'}
    if name == "set_pref":
        pref, value = args.get("name"), args.get("value")
        if pref not in PREFS or value not in PREFS[pref]:
            return None
        return {"tool": name, "args": {"name": pref, "value": value}, "reason": reason,
                "text": f"Set {pref} to {value}. {reason}"}
    return None


async def propose(session_id: str, current_max_wait_ms: int, chat=llm.chat,
                  root: Path = RUNS) -> list[dict]:
    session_dir = root / session_id
    if not session_dir.is_dir() or session_dir.resolve().parent != root.resolve():
        return []
    summary = summarize_session(session_dir, current_max_wait_ms)
    if not summary["turns"]:
        return []
    out = await chat([{"role": "system", "content": SYSTEM},
                      {"role": "user", "content": json.dumps(summary)}],
                     purpose="learner", tools=TOOLS, reasoning_effort="low", max_tokens=1200)
    proposals = []
    for call in out["tool_calls"][:4]:
        try:
            args = json.loads(call["function"].get("arguments") or "{}")
        except json.JSONDecodeError:
            continue
        p = check_proposal(call["function"]["name"], args, current_max_wait_ms)
        if p:
            proposals.append(p)
    return proposals
