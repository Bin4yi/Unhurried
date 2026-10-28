"""Meaning rebuild: a clean version of what the person meant. Remove or fix, never add.

1. Code pass: join repeated sounds and words, remove fillers.
2. Spark pass (only when the text has a correction pattern): resolve
   self-corrections and word switches.
3. Guard (code): nothing in the clean text may be new (see server/guard.py).
   If the guard fails, needs_confirm = True so the person checks it.
"""

from __future__ import annotations

import json
import re

from server import guard, llm

FILLERS = r"(?:uh+|um+|uhm+|erm|er|hmm+|ah+|eh|mm+)"
_FILLER = re.compile(r"(?:,\s*)?\b" + FILLERS + r"\b[,.]?\s*", re.I)
_SOUND_REPEAT = re.compile(r"\b((?:[A-Za-z]{1,3}-\s*){1,6})([A-Za-z][\w']*)")
_WORD_HYPHEN_REPEAT = re.compile(r"\b([A-Za-z']+)(?:-\1\b)+", re.I)
_STRETCH = re.compile(r"\b([A-Za-z])\1{2,}(?=[a-z])", re.I)
CORRECTION = re.compile(r"\b(no|i mean|sorry|actually|wait|rather|make (?:it|that)|scratch that"
                        r"|i meant|not)\b", re.I)
CONFIRM_BELOW = 0.8

SPARK_SYSTEM = (
    "You clean up a speech-to-text transcript from a person who sometimes corrects "
    "themselves mid-sentence. Resolve self-corrections and word switches so the text says "
    "what they finally meant (\"for two, no, three people\" -> \"for three people\"). "
    "Rules: only remove or replace words with words the person actually said; never add "
    "new information, numbers, names, days or times; keep their wording otherwise. "
    "Known personal word switches (the person approved these): {switches}. "
    'Reply with JSON only: {{"clean": str, "changes": [{{"from": str, "to": str}}], '
    '"confidence": number between 0 and 1}}.'
)


def _sound_repeat(m: re.Match) -> str:
    prefixes = [p.strip(" -").lower() for p in m.group(1).split("-") if p.strip(" -")]
    word = m.group(2)
    if all(word.lower().startswith(p) for p in prefixes):
        return word
    return m.group(0)


def code_pass(raw: str) -> tuple[str, list[dict]]:
    """Join repeated sounds ("b-b-book"), repeated words ("I I I"), remove fillers."""
    changes: list[dict] = []
    text = raw

    def sub(pattern: re.Pattern, repl, kind: str) -> None:
        nonlocal text
        out, last = [], 0
        for m in pattern.finditer(text):
            new = repl(m) if callable(repl) else m.expand(repl)
            if new != m.group(0):
                changes.append({"from": m.group(0).strip(" ,"), "to": new.strip(" ,"), "kind": kind})
            out.append(text[last:m.start()] + new)
            last = m.end()
        text = "".join(out) + text[last:]

    sub(_SOUND_REPEAT, _sound_repeat, "repeat")
    sub(_WORD_HYPHEN_REPEAT, lambda m: m.group(1), "repeat")
    sub(_STRETCH, lambda m: m.group(1), "stretch")
    sub(_FILLER, lambda m: " ", "filler")
    # repeated words and short phrases: "I I I want" -> "I want", "I want I want" -> "I want"
    for n in range(1, 9):  # single words first, so "I I I I" is one change, not two
        pat = re.compile(r"\b((?:[\w']+\s+){%d}[\w']+)(?:[\s,]+\1\b)+" % (n - 1), re.I)
        sub(pat, lambda m: m.group(1), "repeat")
    text = re.sub(r"\s+([,.?!])", r"\1", re.sub(r"\s{2,}", " ", text)).strip(" ,")
    if text[:1].islower() and raw[:1].isupper():
        text = text[:1].upper() + text[1:]
    return text, [c for c in changes if c["from"].lower() != c["to"].lower()]


async def spark_pass(text: str, switches: list[dict], provider: str = "spark",
                     chat=llm.chat) -> dict:
    approved = [f'"{s["said"]}" means "{s["means"]}"' for s in switches if s.get("approved")]
    system = SPARK_SYSTEM.format(switches="; ".join(approved) or "none")
    out = await chat([{"role": "system", "content": system}, {"role": "user", "content": text}],
                     purpose="rebuild", provider=provider, json_mode=True,
                     reasoning_effort="minimal", max_tokens=1500, timeout=10)
    data = json.loads(out["content"])
    return {"clean": str(data.get("clean", text)).strip(),
            "changes": [{"from": c.get("from", ""), "to": c.get("to", ""), "kind": "correction"}
                        for c in data.get("changes", []) if isinstance(c, dict)],
            "confidence": float(data.get("confidence", 0.5)), "ms": out["ms"]}


async def rebuild(raw: str, switches: list[dict] | None = None, *, use_spark: bool = True,
                  provider: str = "spark", chat=llm.chat) -> dict:
    """Returns {raw, clean, changes, confidence, needs_confirm, guard_fails, spark}."""
    switches = switches or []
    clean, changes = code_pass(raw)
    confidence, spark_info = 1.0, None
    has_switch = any(s.get("approved") and s.get("said", "").lower() in clean.lower()
                     for s in switches)
    if use_spark and clean and (CORRECTION.search(clean) or has_switch):
        try:
            sp = await spark_pass(clean, switches, provider=provider, chat=chat)
            clean, confidence = sp["clean"] or clean, max(0.0, min(1.0, sp["confidence"]))
            changes += sp["changes"]
            spark_info = {"ms": round(sp["ms"]), "confidence": confidence}
        except Exception as exc:
            spark_info = {"error": type(exc).__name__}
    fails = guard.check(raw, clean, switches)
    return {"raw": raw, "clean": clean, "changes": changes, "confidence": round(confidence, 2),
            "needs_confirm": bool(fails) or confidence < CONFIRM_BELOW,
            "guard_fails": fails, "spark": spark_info}
