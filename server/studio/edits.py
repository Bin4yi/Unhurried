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


VOWELS = set("AEIOUY")
CHAIN_GAP_S = 0.7     # sounds closer than this belong to one attempt at the word
HEAD_MAX = 3          # a repeated sound is at most this many letters ("B", "BI", "PER")
LOOK_BACK_S = 1.5     # how far before the word's aligned start repeats may be found


SHORT_WORDS = set("""a i an at is in on my me we to do go so no up us it of or be by he if am as ok
oh hi the and for you are was his her our can not but all any how why who use get has had one two
out see new now way may day too man did let put say she try own yes ask big end far few got run
set top yet its him they them this that with from have""".split())


def is_sound_token(tok: str, next_word: str) -> bool:
    """Tokens that are attempts at the next word, not words: 'BBV', 'Pp', 'b-', 'ma' (mouse)."""
    t, n = norm(tok).upper(), norm(next_word).upper()
    if not t or not n or len(t) > 4 or t == n or _fold(t)[0] != _fold(n)[0]:
        return False
    if tok.endswith("-") or not (set(t) & VOWELS):
        return True       # real words almost always have a vowel; "BBV", "Pp", "ppp" do not
    # a very short piece that is not a common word, right before a longer word with its sound
    return len(t) <= 2 and t.lower() not in SHORT_WORDS and len(n) >= 4


# Voiced and voiceless pairs sound alike to an acoustic model ("p" is often heard as "b").
SOUND_CLASS = {"P": "B", "T": "D", "K": "G", "C": "G", "Q": "G", "V": "F", "Z": "S"}


def _fold(text: str) -> str:
    """Map the first letter to its sound class (b=p, d=t, g=k=c, f=v, s=z), for matching."""
    if not text:
        return text
    return SOUND_CLASS.get(text[0], text[0]) + text[1:]


def acoustic_chains(word: Word, prev_end: float, acoustic: list[dict]) -> dict | None:
    """Short sounds heard just before (or at the start of) a word that begin the word,
    then the word itself: 'B B BI | BE-NOLEDI' for 'Binula', 'B B B | DIAN' for 'period'.
    Returns the part to cut."""
    target = _fold(norm(word.text).upper())
    if not target:
        return None
    first = target[0]
    # the speech model often stretches the word before a block over the repeats,
    # so look back a little before this word's aligned start
    window = [a for a in acoustic if prev_end - LOOK_BACK_S <= a["start"] <= word.end]
    chain: list[dict] = []
    for k, a in enumerate(window):
        t = _fold(a["text"])
        if t[:1] != first:
            if a["start"] < word.start:
                chain = []          # something else was said in between
            elif chain:
                break               # the rest of the word: the chain is complete
            continue
        if chain and a["start"] - chain[-1]["end"] > CHAIN_GAP_S:
            chain = []
        chain.append({**a, "fold": t, "next": window[k + 1]["start"] if k + 1 < len(window) else None})
    if len(chain) < 2:
        return None
    heads, body = chain[:-1], chain[-1]
    # the last attempt must be the word itself: its first letters, a long take of it,
    # or a short onset that runs straight on into the rest of the word
    runs_on = body["next"] is not None and body["next"] - body["end"] < 0.35
    if not (body["fold"][:2] == target[:2] or (len(body["fold"]) >= 4 and len(target) >= 4) or runs_on):
        return None
    for h in heads:
        if h["fold"] == target or len(h["fold"]) > HEAD_MAX:
            return None     # a whole repeated word (repeat finder) or another real word
        if not (target.startswith(h["fold"]) or len(h["fold"]) == 1):
            return None
    if body["start"] - heads[0]["start"] < 0.12:
        return None
    return {"start": heads[0]["start"], "end": body["start"],
            "text": " ".join(h["text"].lower() + "-" for h in heads)}


def find_sounds(words: list[Word], acoustic: list[dict]) -> list[dict]:
    out = []
    for i, w in enumerate(words):
        nxt = words[i + 1] if i + 1 < len(words) else None
        if nxt and is_sound_token(w.text, nxt.text):
            # the whole token is a repeated sound: cut it up to where the word starts
            out.append(_edit("sound", words, i, i, end=nxt.start))
            continue
        if i > 0 and out and out[-1]["words"] == [i - 1, i - 1]:
            continue        # the token before this word was already cut as a sound
        prev_end = words[i - 1].end if i > 0 else 0.0
        c = acoustic_chains(w, prev_end, acoustic)
        if c:
            out.append({"kind": "sound", "start": round(c["start"], 3), "end": round(c["end"], 3),
                        "text": c["text"], "words": [i, i], "on": True, "partial": True})
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
                    kind = "sound" if words[i].text.endswith("-") else "repeat"
                    out.append(_edit(kind, words, i, j - 1, end=words[j].start))
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
