"""All Meta API calls: Voice Transcribe (realtime) and Muse Spark (chat).

Every call is logged to runs/llm_calls.jsonl with time taken and cost.
Optional "glimmer" provider: any OpenAI-compatible host serving Muse Glimmer
(GLIMMER_BASE_URL, GLIMMER_API_KEY, GLIMMER_MODEL).
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any, AsyncIterator

import httpx

DEFAULT_BASE_URL = "https://api.meta.ai/v1"
TRANSCRIBE_MODEL = "muse-voice-transcribe-1.0"
SPARK_MODEL = "muse-spark-1.3"
TRANSCRIBE_USD_PER_HOUR = 0.18
# USD per 1M tokens (standard mode): input, cached input, output
SPARK_PRICES = {"input": 1.25, "cached": 0.15, "output": 4.25}
CALL_LOG = Path("runs/llm_calls.jsonl")


def load_dotenv(path: str = ".env") -> None:
    """Load KEY=VALUE lines into os.environ. Shell values win; empty values are skipped."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        if value:
            os.environ.setdefault(name.strip(), value)


load_dotenv()


def api_key() -> str:
    key = os.environ.get("META_API_KEY") or os.environ.get("MODEL_API_KEY")
    if not key:
        raise RuntimeError("Set META_API_KEY in .env or the shell.")
    return key


def base_url() -> str:
    return os.environ.get("META_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


def realtime_url(base: str) -> str:
    if base.startswith("https://"):
        base = "wss://" + base[len("https://"):]
    elif base.startswith("http://"):
        base = "ws://" + base[len("http://"):]
    return base.rstrip("/") + "/asr/realtime"


def spark_cost(usage: dict | None) -> float:
    if not usage:
        return 0.0
    cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0) or 0
    fresh = max(0, usage.get("prompt_tokens", 0) - cached)
    out = usage.get("completion_tokens", 0)
    p = SPARK_PRICES
    return (fresh * p["input"] + cached * p["cached"] + out * p["output"]) / 1_000_000


def transcribe_cost(audio_seconds: float) -> float:
    return int(audio_seconds) * TRANSCRIBE_USD_PER_HOUR / 3600


def log_call(kind: str, model: str, ms: float, usd: float, **extra: Any) -> None:
    CALL_LOG.parent.mkdir(parents=True, exist_ok=True)
    row = {"ts": time.time(), "kind": kind, "model": model, "ms": round(ms, 1),
           "usd": round(usd, 6), **extra}
    with CALL_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


# ---------------------------------------------------------------- chat

_client: httpx.AsyncClient | None = None


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=30)
    return _client


def _provider(name: str) -> tuple[str, str, str]:
    """Return (url, key, model) for 'spark' or 'glimmer'."""
    if name == "glimmer":
        url = os.environ.get("GLIMMER_BASE_URL")
        if not url:
            raise RuntimeError("Set GLIMMER_BASE_URL, GLIMMER_API_KEY, GLIMMER_MODEL for Glimmer.")
        return (url.rstrip("/") + "/chat/completions", os.environ.get("GLIMMER_API_KEY", ""),
                os.environ.get("GLIMMER_MODEL", "muse-glimmer"))
    return base_url() + "/chat/completions", api_key(), os.environ.get("SPARK_MODEL", SPARK_MODEL)


async def chat(messages: list[dict], *, purpose: str, provider: str = "spark",
               tools: list[dict] | None = None, json_mode: bool = False,
               reasoning_effort: str | None = "minimal", max_tokens: int = 600,
               timeout: float | None = None) -> dict:
    """One chat completion. Returns {"content", "tool_calls", "ms", "usd", "model"}."""
    url, key, model = _provider(provider)
    body: dict[str, Any] = {"model": model, "messages": messages, "max_tokens": max_tokens}
    if tools:
        body["tools"] = tools
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    if reasoning_effort and provider == "spark":
        body["reasoning_effort"] = reasoning_effort
    start = time.monotonic()
    try:
        coro = _http().post(url, json=body, headers={"Authorization": f"Bearer {key}"})
        resp = await (asyncio.wait_for(coro, timeout) if timeout else coro)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        ms = (time.monotonic() - start) * 1000
        log_call("chat", model, ms, 0.0, purpose=purpose, provider=provider,
                 error=type(exc).__name__)
        raise
    ms = (time.monotonic() - start) * 1000
    usage = data.get("usage")
    usd = spark_cost(usage) if provider == "spark" else 0.0
    log_call("chat", model, ms, usd, purpose=purpose, provider=provider, usage=usage)
    msg = (data.get("choices") or [{}])[0].get("message") or {}
    return {"content": msg.get("content") or "", "tool_calls": msg.get("tool_calls") or [],
            "ms": ms, "usd": usd, "model": model}


# ---------------------------------------------------------- transcribe

class TranscribeStream:
    """Realtime Voice Transcribe session. Send PCM bytes, read server events."""

    def __init__(self, *, mode: str = "ENDPOINTING", keywords: list[str] | None = None,
                 rate: int = 24000):
        self.mode = mode
        self.keywords = [k for k in (keywords or []) if k][:100]
        self.rate = rate
        self.encoding = {16000: "PCM_16KHZ", 24000: "PCM_24KHZ"}[rate]
        self.audio_seconds = 0.0
        self.session_id: str | None = None
        self._ws = None
        self._opened = 0.0

    def handshake(self, key: str) -> dict:
        hs = {"mode": self.mode, "authorization": {"accessToken": f"Bearer {key}"},
              "audioEncoding": self.encoding, "model": TRANSCRIBE_MODEL,
              "partialMode": "CUMULATIVE", "emitAudioProgress": False}
        if self.keywords:
            hs["keywords"] = self.keywords
        return hs

    async def open(self) -> None:
        import websockets
        self._opened = time.monotonic()
        self._ws = await websockets.connect(realtime_url(base_url()), max_size=None)
        await self._ws.send(json.dumps(self.handshake(api_key())))

    async def send(self, pcm: bytes) -> None:
        self.audio_seconds += len(pcm) / (self.rate * 2)
        await self._ws.send(pcm)

    async def events(self) -> AsyncIterator[dict]:
        import websockets
        try:
            async for raw in self._ws:
                if isinstance(raw, bytes):
                    continue
                ev = json.loads(raw)
                if "type" not in ev and "sessionId" in ev:
                    self.session_id = ev["sessionId"]
                    ev = {"type": "session", "sessionId": ev["sessionId"]}
                yield ev
        except websockets.ConnectionClosed:
            return

    async def close(self) -> None:
        if self._ws is None:
            return
        try:
            await self._ws.send(json.dumps({"type": "endStream"}))
            await asyncio.sleep(0.3)
            await self._ws.close()
        except Exception:
            pass
        ms = (time.monotonic() - self._opened) * 1000
        log_call("transcribe", TRANSCRIBE_MODEL, ms, transcribe_cost(self.audio_seconds),
                 audio_s=round(self.audio_seconds, 2), session=self.session_id,
                 keywords=len(self.keywords))
        self._ws = None
