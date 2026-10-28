"""Probe Muse Voice Transcribe realtime streaming.

Streams a WAV file at 1x speed and prints every server event with:
  wall  = seconds since the first audio frame was sent
  audio = audioProcessedMs from the server, in seconds
  lag   = wall - audio (rough speech-to-text delay)

Every event is also saved to runs/probe/{name}_{mode}.jsonl.

Usage:
  python scripts/probe_voice.py tests/fixtures/fluent.wav
  python scripts/probe_voice.py tests/fixtures/pause.wav --mode ENDPOINTING
  python scripts/probe_voice.py tests/fixtures/fluent.wav --insert-silence 1.5:8
  python scripts/probe_voice.py tests/fixtures/two_voices.wav --mode DIARIZATION
  python scripts/probe_voice.py tests/fixtures/fluent.wav --keywords Binula --keywords Matara

Env: META_API_KEY (or MODEL_API_KEY), optional META_BASE_URL. Read from the
shell or from .env in the current folder.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import wave
from pathlib import Path
from typing import Iterator

MODEL = "muse-voice-transcribe-1.0"
MODES = ("PUSH_TO_TALK", "ENDPOINTING", "DIARIZATION")
ENCODINGS = {16000: "PCM_16KHZ", 24000: "PCM_24KHZ"}
CHUNK_MS = 80
DEFAULT_BASE_URL = "https://api.meta.ai/v1"


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


def read_wav(path: str) -> tuple[bytes, int]:
    """Return (raw PCM bytes, sample rate). Needs mono 16-bit at 16 or 24 kHz."""
    with wave.open(path, "rb") as w:
        channels, width, rate = w.getnchannels(), w.getsampwidth(), w.getframerate()
        data = w.readframes(w.getnframes())
    if channels != 1 or width != 2 or rate not in ENCODINGS:
        raise ValueError(
            f"{path}: need mono 16-bit 16/24 kHz, got {channels}ch {width * 8}-bit {rate} Hz.\n"
            f"  Convert: ffmpeg -i {path} -ac 1 -ar 24000 -sample_fmt s16 out.wav"
        )
    return data, rate


def insert_silence(pcm: bytes, rate: int, at_s: float, length_s: float) -> bytes:
    """Insert digital silence at a time offset (to make long-pause test audio)."""
    pos = int(at_s * rate) * 2
    pos = min(pos, len(pcm))
    return pcm[:pos] + b"\x00\x00" * int(length_s * rate) + pcm[pos:]


def chunk_pcm(pcm: bytes, rate: int, chunk_ms: int = CHUNK_MS) -> Iterator[bytes]:
    size = int(rate * 2 * chunk_ms / 1000)
    for i in range(0, len(pcm), size):
        yield pcm[i : i + size]


def realtime_url(base_url: str) -> str:
    """https://api.meta.ai/v1 -> wss://api.meta.ai/v1/asr/realtime"""
    base = base_url.rstrip("/")
    if base.startswith("https://"):
        base = "wss://" + base[len("https://") :]
    elif base.startswith("http://"):
        base = "ws://" + base[len("http://") :]
    return base + "/asr/realtime"


def build_handshake(key: str, mode: str, encoding: str, keywords: list[str],
                    bearer_prefix: bool) -> dict:
    token = f"Bearer {key}" if bearer_prefix else key
    hs = {
        "mode": mode,
        "authorization": {"accessToken": token},
        "audioEncoding": encoding,
        "model": MODEL,
        "partialMode": "CUMULATIVE",
        "emitAudioProgress": False,
    }
    if keywords:
        hs["keywords"] = keywords
    return hs


def format_event(ev: dict, wall: float) -> str:
    kind = ev.get("type", "session" if "sessionId" in ev else "unknown")
    audio_ms = ev.get("audioProcessedMs")
    audio = f"{audio_ms / 1000:7.2f}" if isinstance(audio_ms, (int, float)) else "      -"
    lag = f"{wall - audio_ms / 1000:+5.2f}" if isinstance(audio_ms, (int, float)) else "    -"
    if kind == "transcript":
        tag = "FINAL  " if ev.get("final") else "partial"
        detail = f"{tag} {ev.get('transcript', '')!r}"
    elif kind == "speaker":
        detail = f"label={ev.get('label')}"
    elif kind in ("speechStart", "speechEnd"):
        detail = f"turn={ev.get('turnId')}"
    elif kind == "speechComplete":
        detail = f"turn={ev.get('turnId')} {ev.get('transcript', '')!r}"
    else:
        rest = {k: v for k, v in ev.items() if k not in ("type", "audioProcessedMs")}
        detail = json.dumps(rest)
    return f"[wall {wall:6.2f}s | audio {audio}s | lag {lag}] {kind:<14} {detail}"


async def run(args: argparse.Namespace) -> int:
    try:
        import websockets
    except ImportError:
        print("Install first: python -m pip install websockets", file=sys.stderr)
        return 1

    load_dotenv()
    key = os.environ.get("META_API_KEY") or os.environ.get("MODEL_API_KEY")
    if not key:
        print("Set META_API_KEY (or MODEL_API_KEY).", file=sys.stderr)
        return 1

    pcm, rate = read_wav(args.wav)
    for spec in args.insert_silence:
        at, length = (float(x) for x in spec.split(":"))
        pcm = insert_silence(pcm, rate, at, length)
    if args.tail_silence:
        pcm += b"\x00\x00" * int(args.tail_silence * rate)
    encoding = ENCODINGS[rate]
    total_s = len(pcm) / (rate * 2)

    out_dir = Path("runs/probe")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{Path(args.wav).stem}_{args.mode}.jsonl"

    url = realtime_url(os.environ.get("META_BASE_URL", DEFAULT_BASE_URL))
    print(f"Streaming {args.wav} ({total_s:.2f}s, {encoding}) mode={args.mode} -> {url}")
    handshake = build_handshake(key, args.mode, encoding, args.keywords, not args.raw_token)

    started = 0.0
    async with websockets.connect(url, max_size=None) as ws:
        await ws.send(json.dumps(handshake))

        async def send_audio() -> None:
            nonlocal started
            started = time.monotonic()
            sent = 0.0
            for chunk in chunk_pcm(pcm, rate):
                await ws.send(chunk)
                sent += len(chunk) / (rate * 2)
                behind = started + sent - time.monotonic()
                if behind > 0:
                    await asyncio.sleep(behind)
            print(f"[wall {time.monotonic() - started:6.2f}s] -- all audio sent, sending endStream")
            await ws.send(json.dumps({"type": "endStream"}))

        sender = asyncio.create_task(send_audio())
        with out_path.open("w", encoding="utf-8") as log:
            try:
                async for raw in ws:
                    if isinstance(raw, bytes):
                        continue
                    wall = time.monotonic() - started if started else 0.0
                    ev = json.loads(raw)
                    print(format_event(ev, wall))
                    log.write(json.dumps({"wall_s": round(wall, 3), **ev}) + "\n")
            except websockets.ConnectionClosed as exc:
                print(f"-- connection closed: code={exc.code} reason={exc.reason!r}")
            else:
                close = ws.close_code
                print(f"-- connection closed: code={close} reason={ws.close_reason!r}")
        sender.cancel()
    print(f"Saved events to {out_path}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("wav")
    p.add_argument("--mode", choices=MODES, default="ENDPOINTING")
    p.add_argument("--keywords", action="append", default=[])
    p.add_argument("--insert-silence", action="append", default=[], metavar="AT:LEN",
                   help="insert LEN seconds of silence at AT seconds (repeatable)")
    p.add_argument("--tail-silence", type=float, default=0.0,
                   help="seconds of silence to append before endStream")
    p.add_argument("--raw-token", action="store_true",
                   help="send the key without the 'Bearer ' prefix in the handshake")
    return asyncio.run(run(p.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
