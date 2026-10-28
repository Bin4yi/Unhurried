"""Sound signal: does the voice *sound* finished? Our own audio code, no model.

Measured on the last 0.5 s of speech before a pause:
  pitch_falling   finished statements often end with falling pitch
  fade            a finished sentence usually fades out; a block often stops mid-sound
  voiced_in_pause a held sound or tense voicing during the "silence" = still trying
Combined into a "sounds finished" score from 0 to 1. A few thresholds, no training.
"""

from __future__ import annotations

import numpy as np

FRAME_S, HOP_S = 0.04, 0.01
F0_MIN, F0_MAX = 70.0, 400.0
VOICED_CORR = 0.45        # autocorrelation peak needed to call a frame voiced
FALL_SEMITONES = -1.0     # pitch change over the window that counts as falling
SEND_SCORE, HOLD_SCORE = 0.6, 0.35


def frames(x: np.ndarray, rate: int) -> np.ndarray:
    n, h = int(FRAME_S * rate), int(HOP_S * rate)
    if len(x) < n:
        return np.zeros((0, n), dtype=np.float32)
    idx = np.arange(n)[None, :] + h * np.arange((len(x) - n) // h + 1)[:, None]
    return x[idx]


def pitch_track(x: np.ndarray, rate: int) -> np.ndarray:
    """F0 in Hz per frame (NaN when unvoiced), by normalized autocorrelation."""
    fr = frames(x, rate)
    out = np.full(len(fr), np.nan)
    lo, hi = int(rate / F0_MAX), int(rate / F0_MIN)
    for i, f in enumerate(fr):
        f = f - f.mean()
        energy = float(np.dot(f, f))
        if energy < 1e-6:
            continue
        ac = np.correlate(f, f, mode="full")[len(f) - 1:]
        seg = ac[lo:hi]
        if not len(seg):
            continue
        lag = int(np.argmax(seg)) + lo
        if ac[lag] / energy >= VOICED_CORR:
            out[i] = rate / lag
    return out


def rms_db(x: np.ndarray, rate: int) -> np.ndarray:
    fr = frames(x, rate)
    if not len(fr):
        return np.zeros(0)
    return 20 * np.log10(np.sqrt(np.mean(fr ** 2, axis=1)) + 1e-6)


def analyze(before: np.ndarray, pause: np.ndarray, rate: int, noise_floor: float = 0.003) -> dict:
    """before: last ~0.5 s up to the end of speech; pause: audio after the end of speech."""
    f0 = pitch_track(before, rate)
    voiced = f0[~np.isnan(f0)]
    pitch_falling = None
    if len(voiced) >= 4:
        semis = 12 * np.log2(voiced / np.median(voiced))
        k = max(2, len(semis) // 3)
        pitch_falling = bool(np.median(semis[-k:]) - np.median(semis[:k]) <= FALL_SEMITONES)

    db = rms_db(before, rate)
    fade = 0.0
    if len(db) >= 6:
        peak = float(np.max(db))
        tail = float(np.mean(db[-5:]))
        fade = float(np.clip((peak - tail) / 20.0, 0.0, 1.0))  # 20 dB drop = full fade

    p_db = rms_db(pause, rate)
    floor_db = 20 * np.log10(noise_floor + 1e-6)
    p_f0 = pitch_track(pause, rate) if len(pause) else np.zeros(0)
    voiced_frames = int(np.sum(~np.isnan(p_f0) & (p_db[: len(p_f0)] > floor_db + 12))) if len(p_db) else 0
    voiced_in_pause = voiced_frames >= 8   # about 80 ms of voicing inside the pause

    score = 0.5 * fade + (0.5 if pitch_falling else 0.15 if pitch_falling is None else 0.0)
    if voiced_in_pause:
        score = min(score, 0.2)
    return {"pitch_falling": pitch_falling, "fade": round(fade, 2),
            "voiced_in_pause": voiced_in_pause, "score": round(float(score), 2)}


def verdict(sound: dict | None) -> str:
    """'finished', 'unfinished' or 'unsure'."""
    if not sound:
        return "unsure"
    if sound["voiced_in_pause"] or sound["score"] <= HOLD_SCORE:
        return "unfinished"
    if sound["score"] >= SEND_SCORE:
        return "finished"
    return "unsure"
