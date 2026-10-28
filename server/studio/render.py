"""Real-voice output: cut the enabled edits out of the recording and join it smoothly.

Only cutting, never adding: every output sample comes from the original audio.
Joins use short equal-power crossfades so cuts do not click. Long silent blocks
are shortened, not removed, so speech keeps a natural rhythm.
"""

from __future__ import annotations

import io
import wave

import numpy as np

FADE_S = 0.015


def read_wav_bytes(data: bytes) -> tuple[np.ndarray, int]:
    with wave.open(io.BytesIO(data)) as w:
        if w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise ValueError("need mono 16-bit WAV")
        rate = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float32) / 32768
    return x, rate


def wav_bytes(x: np.ndarray, rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
    return buf.getvalue()


def keep_ranges(duration: float, cuts: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Complement of the (merged) cut ranges inside [0, duration]."""
    merged: list[list[float]] = []
    for a, b in sorted((max(0.0, a), min(duration, b)) for a, b in cuts if b > a):
        if merged and a <= merged[-1][1] + 0.01:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    keep, t = [], 0.0
    for a, b in merged:
        if a - t > 0.005:
            keep.append((t, a))
        t = b
    if duration - t > 0.005:
        keep.append((t, duration))
    return keep


def join(x: np.ndarray, rate: int, keep: list[tuple[float, float]]) -> np.ndarray:
    fade = int(FADE_S * rate)
    out = np.zeros(0, dtype=np.float32)
    for a, b in keep:
        seg = x[int(a * rate):int(b * rate)].astype(np.float32)
        if not len(seg):
            continue
        if len(out) >= fade and len(seg) >= fade:
            ramp = np.linspace(0, np.pi / 2, fade, dtype=np.float32)
            mixed = out[-fade:] * np.cos(ramp) + seg[:fade] * np.sin(ramp)
            out = np.concatenate([out[:-fade], mixed, seg[fade:]])
        else:
            out = np.concatenate([out, seg])
    return out


def render(x: np.ndarray, rate: int, edits: list[dict]) -> np.ndarray:
    """Apply enabled edits. 'block' edits shorten a pause; others remove a span."""
    cuts = [(e["start"], e["end"]) for e in edits if e.get("on")]
    return join(x, rate, keep_ranges(len(x) / rate, cuts))


def output_map(duration: float, edits: list[dict]) -> list[dict]:
    """Where each kept range lands in the output (for the before/after view)."""
    keep = keep_ranges(duration, [(e["start"], e["end"]) for e in edits if e.get("on")])
    out, t = [], 0.0
    for a, b in keep:
        out.append({"src": [round(a, 3), round(b, 3)], "dst": round(t, 3)})
        t += b - a
    return out
