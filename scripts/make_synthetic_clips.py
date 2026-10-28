"""Make a synthetic benchmark set with the Windows built-in voices (no real people).

Stammer-like clips are built from text pieces with silent blocks between them.
Synthetic voices cannot reproduce real stammering (tense blocks, real sound
repeats), so this set only checks that the pipeline works end to end and shows
how the turn logic behaves on silent blocks. Real numbers need real clips.

Writes bench/audio/syn_XX.wav and bench/clips_synthetic.jsonl.
Usage: python scripts/make_synthetic_clips.py   (Windows only)
"""

from __future__ import annotations

import json
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

OUT = Path("bench/audio")
LABELS = Path("bench/clips_synthetic.jsonl")

BOOK = "book_table"
# (kind, features, pieces [(text, pause_ms_after)], expected args or tool)
CLIPS = [
    ("stammer", ["silent_block"], [("Book a table for", 2500), ("two at seven on Friday.", 0)], {"people": 2, "time": "19:00", "day": "friday"}),
    ("stammer", ["silent_block"], [("I want to", 3000), ("book a table for four at eight tomorrow.", 0)], {"people": 4, "time": "20:00", "day": "tomorrow"}),
    ("stammer", ["repeat_sound", "silent_block"], [("Buh, buh,", 1500), ("book a table for three at six on Sunday.", 0)], {"people": 3, "time": "18:00", "day": "sunday"}),
    ("stammer", ["filler", "silent_block"], [("Book a table for two, uh,", 2000), ("at nine on Monday.", 0)], {"people": 2, "time": "21:00", "day": "monday"}),
    ("stammer", ["repeat_word", "silent_block"], [("I, I, I", 1500), ("want a table for five at noon on Tuesday.", 0)], {"people": 5, "time": "12:00", "day": "tuesday"}),
    ("stammer", ["silent_block"], [("Book a table for two", 2500), ("at seven on Friday.", 0)], {"people": 2, "time": "19:00", "day": "friday"}),
    ("stammer", ["silent_block"], [("Please book a table for", 4000), ("six at eight on Thursday.", 0)], {"people": 6, "time": "20:00", "day": "thursday"}),
    ("stammer", ["word_switch", "silent_block"], [("Book a table for four, no,", 1500), ("five people at seven on Sunday.", 0)], {"people": 5, "time": "19:00", "day": "sunday"}),
    ("stammer", ["silent_block"], [("Can you book a", 3500), ("table for two at eight tonight.", 0)], {"people": 2, "time": "20:00", "day": "today"}),
    ("stammer", ["repeat_word", "silent_block"], [("Book a table for", 1200), ("for", 1200), ("four at seven on Wednesday.", 0)], {"people": 4, "time": "19:00", "day": "wednesday"}),
    ("stammer", ["silent_block"], [("I'd like to book", 2500), ("a table for two at eight on Saturday.", 0)], {"people": 2, "time": "20:00", "day": "saturday"}),
    ("stammer", ["filler", "silent_block"], [("Um", 2500), ("book a table for three at seven on Monday.", 0)], {"people": 3, "time": "19:00", "day": "monday"}),
    ("stammer", ["silent_block"], [("Book a table for two at", 3000), ("half past seven on Friday.", 0)], {"people": 2, "time": "19:30", "day": "friday"}),
    ("stammer", ["silent_block"], [("Book a table for two at seven on", 3000), ("Friday.", 0)], {"people": 2, "time": "19:00", "day": "friday"}),
    ("stammer", ["silent_block"], [("What are", 2500), ("my bookings?", 0)], "list_bookings"),
    ("stammer", ["silent_block", "repeat_sound"], [("Book a table for f, f,", 2000), ("four at eight on Saturday.", 0)], {"people": 4, "time": "20:00", "day": "saturday"}),
    ("fluent", [], [("Book a table for two at seven on Friday.", 0)], {"people": 2, "time": "19:00", "day": "friday"}),
    ("fluent", [], [("I want to book a table for four at eight tomorrow.", 0)], {"people": 4, "time": "20:00", "day": "tomorrow"}),
    ("fluent", [], [("Book a table for three at six on Sunday.", 0)], {"people": 3, "time": "18:00", "day": "sunday"}),
    ("fluent", [], [("What are my bookings?", 0)], "list_bookings"),
    ("fluent", [], [("Please book a table for five at noon on Tuesday.", 0)], {"people": 5, "time": "12:00", "day": "tuesday"}),
    ("fluent", [], [("Book a table for six at eight on Thursday.", 0)], {"people": 6, "time": "20:00", "day": "thursday"}),
    ("fluent", [], [("Can I book a table for two at nine tonight?", 0)], {"people": 2, "time": "21:00", "day": "today"}),
    ("fluent", [], [("I need a table for one at one pm on Wednesday.", 0)], {"people": 1, "time": "13:00", "day": "wednesday"}),
]


def ps_quote(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def build_ps(jobs: list[tuple[str, str, list]]) -> str:
    lines = [
        "Add-Type -AssemblyName System.Speech",
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer",
        "$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(24000,"
        " [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,"
        " [System.Speech.AudioFormat.AudioChannel]::Mono)",
    ]
    for path, voice, pieces in jobs:
        lines.append("$p = New-Object System.Speech.Synthesis.PromptBuilder")
        lines.append(f"$p.StartVoice({ps_quote(voice)})")
        for text, pause in pieces:
            lines.append(f"$p.AppendText({ps_quote(text)})")
            if pause:
                lines.append(f"$p.AppendBreak([TimeSpan]::FromMilliseconds({pause}))")
        lines.append("$p.EndVoice()")
        lines.append(f"$s.SetOutputToWaveFile({ps_quote(path)}, $fmt); $s.Speak($p); $s.SetOutputToNull()")
    lines.append("$s.Dispose()")
    return "\n".join(lines)


def speech_end(path: Path, threshold: float = 0.01) -> float:
    with wave.open(str(path)) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768
        rate = w.getframerate()
    loud = np.nonzero(np.abs(x) > threshold)[0]
    return round(float(loud[-1]) / rate + 0.05, 2) if len(loud) else 0.0


def main() -> int:
    if sys.platform != "win32":
        print("Needs Windows (System.Speech).")
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    voices = ["Microsoft David Desktop", "Microsoft Zira Desktop"]
    jobs, rows = [], []
    for i, (kind, feats, pieces, expected) in enumerate(CLIPS, 1):
        cid = f"syn_{i:02d}"
        path = (OUT / f"{cid}.wav").resolve()
        jobs.append((str(path), voices[i % 2], pieces))
        exp = {"tool": expected, "args": {}} if isinstance(expected, str) else {"tool": BOOK, "args": expected}
        rows.append({"id": cid, "file": f"bench/audio/{cid}.wav", "kind": kind, "features": feats,
                     "speech_end_s": None, "expected": exp,
                     "script": " ... ".join(t for t, _ in pieces), "consent": "synthetic",
                     "public_audio": True})
    subprocess.run(["powershell", "-NoProfile", "-Command", "-"], input=build_ps(jobs) + "\n",
                   text=True, check=True)
    with LABELS.open("w", encoding="utf-8") as out:
        for row in rows:
            row["speech_end_s"] = speech_end(Path(row["file"]))
            out.write(json.dumps(row) + "\n")
    print(f"Wrote {len(rows)} clips to {OUT} and {LABELS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
