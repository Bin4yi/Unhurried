import wave
from pathlib import Path

import numpy as np

from server.sound import analyze, pitch_track, verdict

RATE = 24000
FIX = Path(__file__).parent / "fixtures"


def tone(f0_start, f0_end, seconds, amp_start=0.3, amp_end=0.3):
    t = np.arange(int(seconds * RATE)) / RATE
    f0 = np.linspace(f0_start, f0_end, len(t))
    phase = 2 * np.pi * np.cumsum(f0) / RATE
    amp = np.linspace(amp_start, amp_end, len(t))
    # a few harmonics so it looks like a voice to the pitch tracker
    return (amp * (np.sin(phase) + 0.5 * np.sin(2 * phase) + 0.25 * np.sin(3 * phase)) / 1.75).astype(np.float32)


def test_pitch_track_follows_tone():
    f0 = pitch_track(tone(200, 200, 0.3), RATE)
    assert np.nanmedian(f0) == np.float64(np.nanmedian(f0))
    assert abs(np.nanmedian(f0) - 200) < 10


def test_falling_fading_voice_sounds_finished():
    s = analyze(tone(220, 150, 0.5, 0.3, 0.01), np.zeros(RATE // 2, np.float32), RATE)
    assert s["pitch_falling"] is True and s["fade"] > 0.5 and not s["voiced_in_pause"]
    assert verdict(s) == "finished"


def test_flat_voice_that_stops_suddenly_is_not_finished():
    s = analyze(tone(180, 185, 0.5), np.zeros(RATE // 2, np.float32), RATE)
    assert s["pitch_falling"] is False and s["fade"] < 0.3
    assert verdict(s) != "finished"


def test_held_sound_in_pause_means_still_trying():
    s = analyze(tone(220, 150, 0.5, 0.3, 0.01), tone(150, 150, 0.4, 0.1, 0.1), RATE)
    assert s["voiced_in_pause"] is True and verdict(s) == "unfinished"


def test_no_audio_is_unsure():
    assert verdict(None) == "unsure"
    s = analyze(np.zeros(0, np.float32), np.zeros(0, np.float32), RATE)
    assert s["pitch_falling"] is None and not s["voiced_in_pause"]


def load(name):
    with wave.open(str(FIX / name)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float32) / 32768


def test_real_clip_end_of_sentence_has_some_fade():
    x = load("fluent.wav")
    loud = np.nonzero(np.abs(x) > 0.01)[0]
    end = loud[-1] + 1
    s = analyze(x[end - RATE // 2:end], np.zeros(RATE // 2, np.float32), RATE)
    assert s["score"] > 0 and not s["voiced_in_pause"]
