"""Voice clone worker. Runs in its own Python (3.12) with Chatterbox installed in .clone-pkgs.

Reads only the person's own clean words and their own voice sample, and writes a WAV.
Chatterbox (Resemble AI, MIT licence) adds an inaudible Perth watermark to every
output, marking it as AI-generated. The server labels the file "AI voice".

Usage: python clone_worker.py --text "..." --ref sample.wav --out clone.wav
"""

from __future__ import annotations

import argparse
import re
import sys


def sentences(text: str, limit: int = 220) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    out: list[str] = []
    for p in parts:
        while len(p) > limit:
            cut = p.rfind(" ", 0, limit)
            cut = cut if cut > 40 else limit
            out.append(p[:cut])
            p = p[cut:].strip()
        if p:
            out.append(p)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", required=True)
    ap.add_argument("--ref", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    import torch
    import torchaudio
    from chatterbox.tts import ChatterboxTTS

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = ChatterboxTTS.from_pretrained(device=device)
    pieces = []
    gap = torch.zeros(1, int(model.sr * 0.25))
    for i, s in enumerate(sentences(args.text)):
        wav = model.generate(s, audio_prompt_path=args.ref)  # watermark applied inside
        pieces += [wav.cpu(), gap]
        print(f"sentence {i + 1} done", flush=True)
    if not pieces:
        print("nothing to say", file=sys.stderr)
        return 1
    torchaudio.save(args.out, torch.cat(pieces[:-1], dim=1), model.sr)
    print("ok", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
