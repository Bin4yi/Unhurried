"""No-new-content guard.

Every number, day, time and name in the clean text must appear in what the
person said (after normalizing: "two" = 2, "seven pm" = 19:00, "Fri" =
Friday) or come from a switch the person approved. Every other word in the
clean text must also appear in what they said. Anything else is "invented".
"""

from __future__ import annotations

import re

NUMBER_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
}
DAYS = {"monday": "monday", "mon": "monday", "tuesday": "tuesday", "tue": "tuesday",
        "tues": "tuesday", "wednesday": "wednesday", "wed": "wednesday",
        "thursday": "thursday", "thu": "thursday", "thur": "thursday", "thurs": "thursday",
        "friday": "friday", "fri": "friday", "saturday": "saturday", "sat": "saturday",
        "sunday": "sunday", "sun": "sunday", "today": "today", "tonight": "today",
        "tomorrow": "tomorrow"}
COMMON_CAPS = {"i", "i'm", "i'd", "i'll", "i've", "ok", "okay", "yes", "no", "hi", "hello",
               "please", "thanks", "sorry", "pm", "am"}
_TOKEN = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?|\d+(?::\d{2})?")
_TIME = re.compile(
    r"\b(\d{1,2}|" + "|".join(NUMBER_WORDS) + r")(?::(\d{2})|\s+(thirty|fifteen|forty[- ]five))?"
    r"\s*(a\.?m\.?|p\.?m\.?|o'clock)?", re.I)


def words(text: str) -> list[str]:
    return _TOKEN.findall(text)


def num(tok: str) -> int | None:
    t = tok.lower()
    if t.isdigit():
        return int(t)
    return NUMBER_WORDS.get(t)


def times(text: str) -> set[str]:
    """Times written with am/pm, o'clock or HH:MM, as 24h 'HH:MM'."""
    out = set()
    for m in _TIME.finditer(text):
        hour_tok, mins, mins_word, suffix = m.groups()
        if not suffix and not mins:
            continue
        h = num(hour_tok)
        if h is None or h > 23:
            continue
        mm = int(mins) if mins else {"thirty": 30, "fifteen": 15}.get((mins_word or "").lower(), 45 if mins_word else 0)
        s = (suffix or "").lower().replace(".", "")
        if s == "pm" and h < 12:
            h += 12
        if s == "am" and h == 12:
            h = 0
        out.add(f"{h:02d}:{mm:02d}")
    return out


def items(text: str) -> dict[str, set]:
    """Numbers, days, times and names found in text."""
    toks = words(text)
    nums = {n for t in toks if ":" not in t for n in [num(t)] if n is not None}
    days = {DAYS[t.lower()] for t in toks if t.lower() in DAYS}
    names = set()
    for i, t in enumerate(toks):
        if i > 0 and t[:1].isupper() and t.lower() not in COMMON_CAPS and t.lower() not in DAYS:
            names.add(t.lower())
    return {"numbers": nums, "days": days, "times": times(text), "names": names}


def vocabulary(text: str) -> set[str]:
    """All word forms in text, with numbers in both digit and word form."""
    vocab = set()
    for t in words(text):
        low = t.lower()
        vocab.add(low)
        n = num(low.split(":")[0])
        if n is not None:
            vocab.add(str(n))
        if low in DAYS:
            vocab.add(DAYS[low])
    return vocab


def check(raw: str, clean: str, switches: list[dict] | None = None) -> list[dict]:
    """Return guard failures: [{"kind": ..., "item": ...}]. Empty list = safe."""
    approved = " ".join(s.get("means", "") for s in (switches or []) if s.get("approved"))
    said = items(raw + " " + approved)
    got = items(clean)
    fails = []
    for kind in ("numbers", "days", "times", "names"):
        for it in sorted(got[kind], key=str):
            if it not in said[kind]:
                fails.append({"kind": kind, "item": it})
    vocab = vocabulary(raw + " " + approved)
    for w in words(clean):
        low = w.lower()
        if ":" in low:
            continue  # clock times are checked as times above
        n = num(low)
        if low in vocab or (n is not None and str(n) in vocab):
            continue
        if low in DAYS and DAYS[low] in vocab:
            continue
        if low in {"pm", "am"} and any(":" in x for x in got["times"]) and got["times"] <= said["times"]:
            continue
        fails.append({"kind": "word", "item": low})
    return fails
