"""Find edits in an aligned recording. Every edit only removes audio, never adds.

  sound     repeated sounds before a word ("b- b- book"), found in the transcript or
            acoustically (wav2vec 2.0 heard a short prefix of the word just before it)
  repeat    repeated words and phrases ("I I I", "in depth in depth"): earlier copies go
  filler    uh, um, er
  correction self-corrections ("two, no, three"), suggested by Muse Spark as word ranges
  block     long silent blocks between words, shortened (not removed)
"""

from __future__ import annotations

import json
import re

from server import llm
from server.studio.align import Word

FILLERS = {"uh", "um", "er", "erm", "uhm", "hmm", "ah", "eh", "mm", "umm", "uhh"}
BLOCK_S, KEEP_GAP_S = 0.7, 0.3
MAX_PHRASE = 8

SPARK_SYSTEM = (
    "You get a numbered list of words from a recording. Find self-corrections, where the "
    "speaker said something and then replaced it (\"two, no, three\" -> remove \"two, no,\"). "
    "Return only ranges of word numbers to delete so the rest reads as what they finally "
    "meant. Never delete words that are not part of a correction. "
    'JSON only: {"remove": [[first, last], ...]}. Empty list if none.'
)


def norm(w: str) -> str:
    return re.sub(r"[^a-z0-9']", "", w.lower())


def _edit(kind: str, words: list[Word], i: int, j: int, start: float | None = None,
          end: float | None = None) -> dict:
    return {"kind": kind, "start": round(words[i].start if start is None else start, 3),
            "end": round(words[j].end if end is None else end, 3),
            "text": " ".join(w.text for w in words[i:j + 1]), "words": [i, j], "on": True}


def find_sounds(words: list[Word], acoustic: list[dict]) -> list[dict]:
    out = []
    for i, w in enumerate(words):
        if w.text.endswith("-") and i + 1 < len(words):
            out.append(_edit("sound", words, i, i, end=words[i + 1].start))
            continue
        # acoustic: short prefixes of this word heard inside its aligned span
        target = norm(w.text).upper()
        inside = [a for a in acoustic if a["start"] >= w.start - 0.05 and a["end"] <= w.end + 0.05]
        if len(inside) >= 2 and target:
            last = inside[-1]
            heads = [a for a in inside[:-1] if target.startswith(a["text"]) and len(a["text"]) <= 3]
            if heads and last["text"][:1] == target[:1] and last["start"] - w.start > 0.15:
                out.append({"kind": "sound", "start": round(w.start, 3), "end": round(last["start"], 3),
                            "text": " ".join(a["text"].lower() + "-" for a in heads), "words": [i, i],
                            "on": True, "partial": True})
    return out


def find_repeats(words: list[Word]) -> list[dict]:
    """Consecutive repeated n-grams; keeps the last copy. Single words first."""
    toks = [norm(w.text) for w in words]
    out, covered = [], set()
    for n in range(1, MAX_PHRASE + 1):
        i = 0
        while i + 2 * n <= len(toks):
            if any(k in covered for k in range(i, i + n)) or not all(toks[i:i + n]):
                i += 1
                continue
            j = i
            while j + 2 * n <= len(toks) and toks[j:j + n] == toks[j + n:j + 2 * n]:
                j += n
            if j > i and not any(k in covered for k in range(i, j + n)):
                if not (n == 1 and toks[i] in FILLERS):
                    out.append(_edit("repeat", words, i, j - 1, end=words[j].start))
                    covered.update(range(i, j))
                i = j + n
            else:
                i += 1
    return out


def find_fillers(words: list[Word]) -> list[dict]:
    return [_edit("filler", words, i, i) for i, w in enumerate(words) if norm(w.text) in FILLERS]


def find_blocks(words: list[Word]) -> list[dict]:
    out = []
    for i in range(len(words) - 1):
        gap = words[i + 1].start - words[i].end
        if gap > BLOCK_S:
            pad = KEEP_GAP_S / 2
            out.append({"kind": "block", "start": round(words[i].end + pad, 3),
                        "end": round(words[i + 1].start - pad, 3),
                        "text": f"{gap:.1f} s pause", "words": None, "on": True})
    return out


async def find_corrections(words: list[Word], chat=llm.chat) -> list[dict]:
    text = " ".join(w.text.lower() for w in words)
    if not re.search(r"\b(no|i mean|sorry|actually|wait|rather|make (it|that)|i meant)\b", text):
        return []
    numbered = " ".join(f"{i}:{w.text}" for i, w in enumerate(words))
    try:
        out = await chat([{"role": "system", "content": SPARK_SYSTEM},
                          {"role": "user", "content": numbered}],
                         purpose="studio_corrections", json_mode=True,
                         reasoning_effort="minimal", max_tokens=1200, timeout=20)
        ranges = json.loads(out["content"]).get("remove", [])
    except Exception:
        return []
    edits, removed = [], 0
    for r in ranges:
        if not (isinstance(r, list) and len(r) == 2 and all(isinstance(x, int) for x in r)):
            continue
        a, b = sorted(r)
        if a < 0 or b >= len(words) or b - a > 12:
            continue
        removed += b - a + 1
        end = words[b + 1].start if b + 1 < len(words) else words[b].end
        edits.append(_edit("correction", words, a, b, end=end))
    # code guard: a "correction" may never remove most of the recording
    return edits if removed <= max(3, len(words) // 3) else []


def clean_text(words: list[Word], edits: list[dict]) -> str:
    gone = set()
    for e in edits:
        if e["on"] and e.get("words") and not e.get("partial"):
            gone.update(range(e["words"][0], e["words"][1] + 1))
    return " ".join(w.text for i, w in enumerate(words) if i not in gone and not w.text.endswith("-"))


async def find_edits(words: list[Word], acoustic: list[dict], use_spark: bool = True,
                     chat=llm.chat) -> list[dict]:
    # Self-corrections win: a repeat or filler inside a correction is part of it.
    edits = await find_corrections(words, chat=chat) if use_spark else []
    taken = {k for e in edits for k in range(e["words"][0], e["words"][1] + 1)}
    for e in find_sounds(words, acoustic) + find_repeats(words) + find_fillers(words):
        if not taken & set(range(e["words"][0], e["words"][1] + 1)):
            edits.append(e)
    edits += find_blocks(words)
    edits.sort(key=lambda e: e["start"])
    for n, e in enumerate(edits, 1):
        e["id"] = f"e{n}"
    return edits
