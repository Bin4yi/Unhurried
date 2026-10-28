import sys
import wave
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import probe_voice as pv  # noqa: E402


def write_wav(path: Path, rate: int, seconds: float, channels: int = 1) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x01\x00" * int(rate * seconds) * channels)


def test_read_wav_ok(tmp_path):
    f = tmp_path / "a.wav"
    write_wav(f, 24000, 0.5)
    pcm, rate = pv.read_wav(str(f))
    assert rate == 24000
    assert len(pcm) == 24000


def test_read_wav_rejects_stereo_and_bad_rate(tmp_path):
    stereo = tmp_path / "s.wav"
    write_wav(stereo, 24000, 0.1, channels=2)
    with pytest.raises(ValueError):
        pv.read_wav(str(stereo))
    bad = tmp_path / "b.wav"
    write_wav(bad, 44100, 0.1)
    with pytest.raises(ValueError):
        pv.read_wav(str(bad))


def test_insert_silence_adds_zeros_at_offset():
    rate = 16000
    pcm = b"\x01\x00" * rate  # 1 s
    out = pv.insert_silence(pcm, rate, 0.5, 2.0)
    assert len(out) == len(pcm) + 2 * rate * 2
    start = int(0.5 * rate) * 2
    assert out[start : start + 2 * rate * 2] == b"\x00" * (2 * rate * 2)
    assert out[:start] == pcm[:start]


def test_chunk_pcm_80ms():
    rate = 24000
    chunks = list(pv.chunk_pcm(b"\x00" * rate * 2, rate))  # 1 s
    assert len(chunks[0]) == 3840  # 1,920 samples
    assert sum(len(c) for c in chunks) == rate * 2


def test_realtime_url():
    assert pv.realtime_url("https://api.meta.ai/v1/") == "wss://api.meta.ai/v1/asr/realtime"
    assert pv.realtime_url("http://localhost:9/v1") == "ws://localhost:9/v1/asr/realtime"


def test_handshake_fields():
    hs = pv.build_handshake("k", "ENDPOINTING", "PCM_24KHZ", ["Binula"], bearer_prefix=True)
    assert hs["authorization"] == {"accessToken": "Bearer k"}
    assert hs["model"] == "muse-voice-transcribe-1.0"
    assert hs["keywords"] == ["Binula"]
    raw = pv.build_handshake("k", "DIARIZATION", "PCM_16KHZ", [], bearer_prefix=False)
    assert raw["authorization"] == {"accessToken": "k"}
    assert "keywords" not in raw


def test_format_event_lag():
    line = pv.format_event({"type": "transcript", "transcript": "hi", "final": False,
                            "audioProcessedMs": 1000}, wall=1.4)
    assert "partial" in line and "+0.40" in line
    assert "label=A" in pv.format_event({"type": "speaker", "label": "A"}, wall=0.0)


def test_load_dotenv_skips_empty_and_keeps_shell(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("# c\nPROBE_A=1\nPROBE_EMPTY=\nPROBE_B=\"x\"\n", encoding="utf-8")
    monkeypatch.delenv("PROBE_A", raising=False)
    monkeypatch.delenv("PROBE_EMPTY", raising=False)
    monkeypatch.setenv("PROBE_B", "shell")
    pv.load_dotenv(str(env))
    import os
    assert os.environ["PROBE_A"] == "1"
    assert "PROBE_EMPTY" not in os.environ
    assert os.environ["PROBE_B"] == "shell"
