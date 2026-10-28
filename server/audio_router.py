"""Browser audio -> Voice Transcribe stream -> simple events.

Times are in audio seconds since the session started (the server's clock is
the audio itself, so replayed benchmark clips get the same times as live use).

Events sent to the session:
  {"type": "partial",    "text", "t"}          live text of the current model turn
  {"type": "speech_start", "t"}
  {"type": "speech_end", "t", "end_t"}          model end-of-speech (end_t = reported end)
  {"type": "model_turn", "text", "t", "turn_id"}  model's final text for one turn
  {"type": "speaker",    "label", "t"}
  {"type": "error",      "message"}
"""

from __future__ import annotations

from collections import deque
from typing import Awaitable, Callable

import numpy as np

Emit = Callable[[dict], Awaitable[None]]


class AudioRouter:
    def __init__(self, stream, emit: Emit, rate: int = 24000, keep_seconds: float = 3.0):
        self.stream = stream
        self.emit = emit
        self.rate = rate
        self.audio_t = 0.0  # seconds of audio received
        self._recent: deque[np.ndarray] = deque()
        self._recent_samples = 0
        self._keep = int(keep_seconds * rate)

    async def feed(self, pcm: bytes) -> None:
        """Forward one chunk of 16-bit mono PCM and advance the audio clock."""
        if len(pcm) % 2:
            pcm = pcm[:-1]
        await self.stream.send(pcm)
        samples = np.frombuffer(pcm, dtype="<i2")
        self.audio_t += len(samples) / self.rate
        self._recent.append(samples)
        self._recent_samples += len(samples)
        while self._recent and self._recent_samples - len(self._recent[0]) >= self._keep:
            self._recent_samples -= len(self._recent.popleft())

    def recent_audio(self, seconds: float) -> np.ndarray:
        """Last `seconds` of audio as float32 in [-1, 1]."""
        if not self._recent:
            return np.zeros(0, dtype=np.float32)
        allx = np.concatenate(list(self._recent)).astype(np.float32) / 32768.0
        return allx[-int(seconds * self.rate):]

    def normalize(self, ev: dict) -> dict | None:
        kind = ev.get("type")
        ms = ev.get("audioProcessedMs")
        t = round(ms / 1000, 3) if isinstance(ms, (int, float)) else round(self.audio_t, 3)
        now = round(self.audio_t, 3)
        if kind == "transcript":
            if ev.get("final"):
                return None  # stream-final; model turns come from speechComplete
            return {"type": "partial", "text": (ev.get("transcript") or "").strip(), "t": now}
        if kind == "speechStart":
            return {"type": "speech_start", "t": now, "turn_id": ev.get("turnId")}
        if kind == "speechEnd":
            return {"type": "speech_end", "t": now, "end_t": t, "turn_id": ev.get("turnId")}
        if kind == "speechComplete":
            return {"type": "model_turn", "text": (ev.get("transcript") or "").strip(),
                    "t": now, "turn_id": ev.get("turnId")}
        if kind == "speaker":
            return {"type": "speaker", "label": ev.get("label"), "t": now}
        if kind == "error":
            return {"type": "error", "message": ev.get("message", "transcribe error")}
        return None

    async def pump(self) -> None:
        """Read server events until the stream closes."""
        async for ev in self.stream.events():
            out = self.normalize(ev)
            if out is not None:
                await self.emit(out)
