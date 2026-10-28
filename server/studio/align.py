"""Word timings by CTC forced alignment with Meta's open wav2vec 2.0 model.

Muse Voice Transcribe returns turn-level times only, so Voice Studio aligns the
transcript to the audio itself: wav2vec 2.0 (facebook/wav2vec2-base-960h) gives
per-frame character probabilities, and a Viterbi pass over the CTC states finds
where each word starts and ends. Runs on CPU.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

MODEL_ID = "facebook/wav2vec2-base-960h"
RATE = 16000
FRAME_S = 0.02            # wav2vec 2.0 output stride: 320 samples at 16 kHz
WINDOW_S = 20.0           # emissions are computed in windows to bound memory
ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
        "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen",
        "eighteen", "nineteen"]
TENS = {2: "twenty", 3: "thirty", 4: "forty", 5: "fifty", 6: "sixty", 7: "seventy",
        8: "eighty", 9: "ninety"}


@dataclass
class Word:
    text: str        # as written in the transcript
    start: float     # seconds
    end: float
    score: float     # mean frame probability, 0..1


def say_number(n: int) -> str:
    if n < 20:
        return ONES[n]
    if n < 100:
        return TENS[n // 10] + ("" if n % 10 == 0 else " " + ONES[n % 10])
    return " ".join(ONES[int(d)] for d in str(n))


def spoken_tokens(word: str) -> str:
    """Letters the acoustic model can align: 'b-b-book' -> 'B B BOOK', '2' -> 'TWO'."""
    w = re.sub(r"\d+", lambda m: " " + say_number(int(m.group())) + " ", word)
    w = re.sub(r"[^A-Za-z' ]+", " ", w.replace("-", " "))
    return " ".join(w.upper().split())


def split_words(transcript: str) -> list[str]:
    """Transcript words, with sound repeats ('b-b-book') kept as separate parts."""
    out = []
    for raw in transcript.split():
        parts = [p for p in re.split(r"-", raw) if p]
        if len(parts) > 1 and all(len(p.strip(".,!?")) <= 3 for p in parts[:-1]):
            out += [p + "-" for p in parts[:-1]] + [parts[-1]]
        else:
            out.append(raw)
    return [w for w in out if spoken_tokens(w)]


@lru_cache(maxsize=1)
def _model():
    from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor
    proc = Wav2Vec2Processor.from_pretrained(MODEL_ID)
    model = Wav2Vec2ForCTC.from_pretrained(MODEL_ID)
    model.eval()
    return proc, model


def emissions(audio16: np.ndarray) -> tuple[np.ndarray, dict]:
    """Log-probabilities (frames x vocab) for 16 kHz mono float audio."""
    import torch
    proc, model = _model()
    step = int(WINDOW_S * RATE)
    parts = []
    with torch.inference_mode():
        for i in range(0, max(len(audio16), 1), step):
            chunk = audio16[i:i + step]
            if len(chunk) < 400:
                continue
            inp = proc(chunk, sampling_rate=RATE, return_tensors="pt").input_values
            logits = model(inp).logits[0]
            parts.append(torch.log_softmax(logits, dim=-1).numpy())
    vocab = proc.tokenizer.get_vocab()
    return (np.concatenate(parts) if parts else np.zeros((0, len(vocab)))), vocab


def viterbi(em: np.ndarray, tokens: list[int], blank: int) -> np.ndarray:
    """Frame index of each token's first frame, by CTC Viterbi over blank-interleaved states."""
    T, N = len(em), len(tokens)
    S = 2 * N + 1
    lab = np.full(S, blank)
    lab[1::2] = tokens
    NEG = -1e30
    dp = np.full(S, NEG)
    dp[0] = em[0, blank]
    if S > 1:
        dp[1] = em[0, lab[1]]
    back = np.zeros((T, S), dtype=np.int8)  # 0 stay, 1 from s-1, 2 from s-2
    skip_ok = np.zeros(S, dtype=bool)
    skip_ok[3::2] = lab[3::2] != lab[1:-2:2]
    for t in range(1, T):
        stay = dp
        prev1 = np.concatenate(([NEG], dp[:-1]))
        prev2 = np.where(skip_ok, np.concatenate(([NEG, NEG], dp[:-2])), NEG)
        stack = np.vstack([stay, prev1, prev2])
        back[t] = np.argmax(stack, axis=0)
        dp = stack[back[t], np.arange(S)] + em[t, lab]
    s = S - 1 if S == 1 or dp[S - 1] >= dp[S - 2] else S - 2
    states = np.zeros(T, dtype=int)
    for t in range(T - 1, -1, -1):
        states[t] = s
        s -= back[t, s]
    return states


def acoustic_words(em: np.ndarray, vocab: dict, gap_frames: int = 8) -> list[dict]:
    """What the acoustic model itself heard (greedy CTC), with times. Catches sound
    repeats like 'B B BOOK' that a transcript often smooths away."""
    inv = {v: k for k, v in vocab.items()}
    blank, sep = vocab.get("<pad>", 0), vocab.get("|", 4)
    out: list[dict] = []
    cur, first, last, prev = "", 0, -100, blank

    def flush():
        nonlocal cur
        if cur:
            out.append({"text": cur, "start": round(first * FRAME_S, 3),
                        "end": round((last + 1) * FRAME_S, 3)})
        cur = ""

    for t, k in enumerate(em.argmax(axis=1)):
        k = int(k)
        if k == sep or (k == blank and cur and t - last > gap_frames):
            flush()
        elif k != blank:
            ch = inv.get(k, "")
            if (ch.isalpha() or ch == "'") and k != prev:
                if not cur:
                    first = t
                cur += ch
            last = t
        prev = k
    flush()
    return out


def align(audio16: np.ndarray, transcript: str) -> list[Word]:
    return align_all(audio16, transcript)[0]


def align_all(audio16: np.ndarray, transcript: str) -> tuple[list[Word], list[dict]]:
    """Word start/end times for the transcript, plus what the model heard acoustically."""
    words = split_words(transcript)
    if not words or len(audio16) < RATE // 10:
        return [], []
    em, vocab = emissions(audio16)
    acoustic = acoustic_words(em, vocab)
    blank, sep = vocab.get("<pad>", 0), vocab.get("|", 4)
    tokens, owner = [], []
    for wi, w in enumerate(words):
        for part_i, part in enumerate(spoken_tokens(w).split()):
            if tokens or part_i:
                tokens.append(sep)
                owner.append(-1)
            for ch in part:
                if ch in vocab:
                    tokens.append(vocab[ch])
                    owner.append(wi)
    if not tokens or len(em) < len(tokens):
        return [], acoustic
    states = viterbi(em, tokens, blank)
    probs = np.exp(em)
    spans: dict[int, list[int]] = {}
    for t, s in enumerate(states):
        if s % 2 == 1:
            wi = owner[s // 2]
            if wi >= 0:
                spans.setdefault(wi, []).append(t)
    out = []
    for wi, w in enumerate(words):
        frames = spans.get(wi)
        if not frames:
            continue
        score = float(np.mean([probs[t, tokens[states[t] // 2]] for t in frames]))
        out.append(Word(w, round(frames[0] * FRAME_S, 3), round((frames[-1] + 1) * FRAME_S, 3), round(score, 3)))
    return out, acoustic
