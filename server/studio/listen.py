"""Model listening with a harness: Muse Spark hears the stammers, code proves them.

1. Listen   Muse Spark 1.2 hears each 8-15 s piece and writes exactly what was said,
            stammers included ("B- B- Binula", "my my my"). Strict JSON, one retry.
2. Ground   The model never gives times. wav2vec 2.0 aligns its words to the audio.
3. Drift    If the model's words disagree with Voice Transcribe in a piece, that piece
            falls back to the code rules.
4. Evidence Every cut must contain voice, align confidently, be followed by the word,
            and stay short. If wav2vec 2.0 independently heard the same sound there,
            the cut is "confirmed by two models" and on; otherwise it is shown, off.
5. Twice    Each piece is heard twice. A cut is on if wav2vec 2.0 heard it too, if both
            listens agree, or (for repeated words) if Voice Transcribe also wrote the word
            twice there. A cut only one listen heard waits for the person.
6. Limits   At most 35% of the recording is cut; the last attempt at a word is kept.
"""

from __future__ import annotations

import asyncio
import base64
import json
import re

import numpy as np

from server import llm
from server.studio import align, edits as E, render

LISTEN_MODEL = "muse-spark-1.2"   # the Muse Spark version Meta recommends for audio
CHUNK_MIN_S, CHUNK_MAX_S = 8.0, 15.0
MAX_CUT_S, MAX_SHARE = 2.5, 0.35
MIN_SCORE, DRIFT_MIN = 0.2, 0.55
PROMPT = (
    "You are a careful audio transcriber for a speech editing tool. The speech is in English. "
    "Write EXACTLY what is "
    "spoken, not what was meant. Keep every stammer: repeated sounds or syllables as "
    "fragments ending in '-' (\"B- B- Binula\", \"c- currently\"), repeated words as spoken "
    "(\"my my my\"), fillers as uh or um. Do not add words that are not spoken. Do not fix "
    'grammar. Reply with JSON only: {"verbatim": "..."}'
)


def wav16(x: np.ndarray) -> bytes:
    return render.wav_bytes(x, align.RATE)


def chunks(x16: np.ndarray) -> list[tuple[float, float]]:
    """Split at the quietest 20 ms between 8 and 15 s, so words are not cut in half."""
    hop = int(0.02 * align.RATE)
    rms = np.sqrt(np.convolve(x16 ** 2, np.ones(hop) / hop, "same"))[::hop]
    out, start, total = [], 0.0, len(x16) / align.RATE
    while total - start > CHUNK_MAX_S:
        lo, hi = int((start + CHUNK_MIN_S) / 0.02), int((start + CHUNK_MAX_S) / 0.02)
        cut = (lo + int(np.argmin(rms[lo:hi]))) * 0.02
        out.append((start, cut))
        start = cut
    out.append((start, total))
    return out


def parse_verbatim(content: str) -> str | None:
    try:
        v = json.loads(content).get("verbatim")
    except (json.JSONDecodeError, AttributeError):
        m = re.search(r'"verbatim"\s*:\s*"((?:[^"\\]|\\.)*)"', content or "")
        v = json.loads(f'"{m.group(1)}"') if m else None
    return v.strip() if isinstance(v, str) and v.strip() else None


async def listen(piece: np.ndarray, chat=llm.chat) -> str | None:
    b64 = base64.b64encode(wav16(piece)).decode()
    msgs = [{"role": "user", "content": [{"type": "text", "text": PROMPT},
             {"type": "input_audio", "input_audio": {"data": b64, "format": "wav"}}]}]
    for attempt in range(2):
        try:
            out = await chat(msgs, purpose="studio_listen", model=LISTEN_MODEL,
                             reasoning_effort="minimal", max_tokens=2500, timeout=60)
        except Exception:
            continue
        v = parse_verbatim(out["content"])
        if v:
            return v
        msgs = msgs + [{"role": "assistant", "content": out["content"] or ""},
                       {"role": "user", "content": 'Only JSON: {"verbatim": "..."}'}]
    return None


def stammer_marks(verbatim: str) -> int:
    """How many stammers a listen wrote down (fragments and repeated words)."""
    toks = verbatim.split()
    frag = sum(1 for t in toks if t.endswith("-"))
    rep_ = sum(1 for a, b in zip(toks, toks[1:]) if E.norm(a) and E.norm(a) == E.norm(b))
    return frag + rep_


def overlaps(e: dict, others: list[dict]) -> bool:
    return any(o["start"] < e["end"] and o["end"] > e["start"] for o in others)


async def ground(seg: np.ndarray, offset: float, verbatim: str) -> list[align.Word]:
    return [align.Word(w.text, round(w.start + offset, 3), round(w.end + offset, 3), w.score)
            for w in await asyncio.to_thread(align.align, seg, verbatim)]


def agreement(model_words: list[str], vt_words: list[str]) -> float:
    """Share of Voice Transcribe's words (3+ letters) the model also wrote."""
    said = {E.norm(w) for w in model_words}
    want = [E.norm(w) for w in vt_words if len(E.norm(w)) >= 3]
    return sum(1 for w in want if w in said) / len(want) if want else 1.0


def noise_floor(x16: np.ndarray) -> float:
    """Level of the quietest 20 ms frames (the room), kept between -48 and -34 dBFS."""
    hop = 320
    if len(x16) < hop:
        return 0.004
    fr = x16[: len(x16) // hop * hop].reshape(-1, hop)
    rms = np.sqrt((fr ** 2).mean(axis=1))
    return float(min(0.02, max(0.004, 2 * np.percentile(rms, 10))))


def voiced_share(x16: np.ndarray, a: float, b: float, floor: float) -> float:
    seg = x16[int(a * align.RATE):int(b * align.RATE)]
    if len(seg) < 160:
        return 0.0
    hop = 160
    fr = seg[: len(seg) // hop * hop].reshape(-1, hop)
    return float(np.mean(np.sqrt((fr ** 2).mean(axis=1)) > floor))


def heard_same(edit: dict, acoustic: list[dict], words: list[align.Word]) -> bool:
    """Did wav2vec 2.0, on its own, hear a matching sound inside this cut?"""
    first = E._fold(E.norm(words[edit["words"][0]].text).upper())[:1]
    inside = [a for a in acoustic if a["start"] < edit["end"] and a["end"] > edit["start"]]
    if edit["kind"] == "filler":
        return bool(inside)               # something was voiced there
    return any(E._fold(a["text"])[:1] == first for a in inside)


def transcript_heard_repeat(edit: dict, vt_words: list[align.Word]) -> bool:
    """Third witness: Voice Transcribe keeps repeated words in its own transcript. If it wrote
    the same word twice in a row at this spot, the repeat is confirmed."""
    if edit["kind"] != "repeat":
        return False
    target = E.norm(edit["text"].split()[0]) if edit["text"].split() else ""
    near = [w for w in vt_words if edit["start"] - 0.8 <= w.start <= edit["end"] + 0.8]
    return any(E.norm(a.text) == E.norm(b.text) == target for a, b in zip(near, near[1:]))


def check(edit: dict, words: list[align.Word], acoustic: list[dict], x16: np.ndarray,
          floor: float) -> tuple[bool, str | None]:
    """Evidence gates. Returns (confirmed, rejection reason or None)."""
    i, j = edit["words"]
    length = edit["end"] - edit["start"]
    short = edit["kind"] in ("sound", "filler")   # fragments and fillers align weakly by nature
    if length <= 0.03:
        return False, "too short to cut"
    if length > MAX_CUT_S:
        return False, f"longer than {MAX_CUT_S} s"
    if voiced_share(x16, edit["start"], edit["end"], floor) < 0.25:
        return False, "no voice there"
    if not short and min(words[k].score for k in range(i, j + 1)) < MIN_SCORE:
        return False, "could not find it in the audio"
    if edit["kind"] != "filler":
        if j + 1 >= len(words):
            return False, "no word after it"
        if words[j + 1].start - edit["end"] > 1.5:
            return False, "the word does not follow"
    return heard_same(edit, acoustic, words), None


async def scan(x16: np.ndarray, vt_words: list[align.Word], acoustic: list[dict],
               chat=llm.chat) -> dict:
    """Model-led scan with the harness. Returns {"words", "edits", "rejected", "pieces"}."""
    floor = noise_floor(x16)
    spans = chunks(x16)
    pieces_audio = [x16[int(a * align.RATE):int(b * align.RATE)] for a, b in spans]
    takes = await asyncio.gather(*[listen(seg, chat=chat) for seg in pieces_audio for _ in range(2)])
    heard = []
    for k in range(len(spans)):
        pair = sorted([t for t in takes[2 * k:2 * k + 2] if t], key=stammer_marks, reverse=True)
        heard.append(pair)
    all_words: list[align.Word] = []
    all_edits, rejected, pieces = [], [], []
    for (a, b), seg, pair in zip(spans, pieces_audio, heard):
        verbatim = pair[0] if pair else None
        vt_here = [w for w in vt_words if a <= w.start < b]
        piece = {"start": round(a, 2), "end": round(b, 2), "model": bool(verbatim), "listens": len(pair)}
        local: list[align.Word] = []
        second: list[dict] = []
        if verbatim:
            local = await ground(seg, a, verbatim)
            piece["agreement"] = round(agreement([w.text for w in local], [w.text for w in vt_here]), 2)
            if len(pair) > 1:
                other = await ground(seg, a, pair[1])
                second = E.find_sounds(other, []) + E.find_repeats(other) + E.find_fillers(other)
        if not verbatim or not local or piece.get("agreement", 0) < DRIFT_MIN:
            piece["used"] = "rules"           # model missing or drifted: fall back
            local = vt_here
            found = E.find_sounds(local, acoustic) + E.find_repeats(local) + E.find_fillers(local)
            for e in found:
                e["by"] = "rules"
        else:
            piece["used"] = "model"
            piece["verbatim"] = verbatim
            found = E.find_sounds(local, []) + E.find_repeats(local) + E.find_fillers(local)
            for e in found:
                confirmed, why = check(e, local, acoustic, x16, floor)
                e["by"] = "spark"
                if why:
                    rejected.append({"text": e["text"], "start": e["start"], "reason": why})
                    e["drop"] = True
                else:
                    e["confirmed"] = confirmed             # wav2vec 2.0 heard it too
                    e["agreed"] = overlaps(e, second)      # the second listen heard it too
                    e["transcript"] = transcript_heard_repeat(e, vt_here)   # Voice Transcribe too
                    e["on"] = confirmed or e["agreed"] or e["transcript"]   # else the person decides
        base = len(all_words)
        for e in found:
            if not e.pop("drop", False):
                e["words"] = [e["words"][0] + base, e["words"][1] + base]
                all_edits.append(e)
        all_words += local
        pieces.append(piece)
    limit_share(all_edits, len(x16) / align.RATE)
    return {"words": all_words, "edits": all_edits, "rejected": rejected, "pieces": pieces}


def limit_share(found: list[dict], duration: float) -> None:
    """Never cut more than MAX_SHARE of the recording: switch off model-only cuts first."""
    total = sum(e["end"] - e["start"] for e in found if e["on"])
    for e in sorted(found, key=lambda e: (e.get("confirmed", True), -(e["end"] - e["start"]))):
        if total <= MAX_SHARE * duration:
            break
        if e["on"]:
            e["on"] = False
            e["limited"] = True
            total -= e["end"] - e["start"]


def content_check(clean_audio: np.ndarray, rate: int, clean_text: str) -> dict:
    """After rendering: align the clean text to the clean audio. A meant word that was cut
    away gets squeezed into almost no time with a weak match."""
    from server.studio.jobs import to16k
    out = align.align(to16k(clean_audio, rate), clean_text)
    want = [w for w in clean_text.split() if E.norm(w)]
    found = [w for w in out if w.score >= 0.1 and w.end - w.start >= 0.04]
    missing = [w.text for w in out if not (w.score >= 0.1 and w.end - w.start >= 0.04)]
    return {"meant_words": len(want), "still_heard": len(found),
            "share": round(len(found) / len(want), 2) if want else 1.0, "weak": missing[:10]}
