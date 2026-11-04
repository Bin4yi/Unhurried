# Demo shot list

The video is a **screen recording of the real app**, with my voice explaining it. Not a promo.

## Rules for the video

- Every feature shown is the real app, live or from a real recording. No mock screens; cards only at the start and the end.
- Show the result of each action on screen (the held turn, the booking, the cut list, the numbers).
- Speed up waiting time 2x–4x, with a small "2x" / "4x" label while sped up (`video_build/speedups.json`).
- Captions on everything (from `docs/DEMO_SCRIPT.md`).
- Total length: **3:00 or less**.
- Every number on screen comes from a file in `bench/results/`.

## Shot list (3:00 or less)

Intro (12 s) and end card (9 s) leave **2:39 for shots 01–08**. The times below are a guide; `build_video.py` prints the real length.

| # | Time | Shot (real app, `?demo=1` on every page) | What I say (short) |
| --- | --- | --- | --- |
| 00 | 0:00–0:12 | Intro card: name, headline, real result (cut-offs baseline vs default engine, set `real_self`) | – |
| 01 | 0:12–0:24 | Studio, idle, my face-free screen. Title of the problem. | "I have a stammer. Voice AI cuts me off. I measured it." |
| 02 | 0:24–0:57 | `studio.html?demo=1`, **Side by side** mode. A real sentence with a block. Normal bot replies mid-sentence (marked). Unhurried shows "Take your time" and sends the full sentence. | "Same mic, same sentence. Left: normal end-of-speech. Right: Unhurried." |
| 03 | 0:57–1:17 | Inspector: reason card ("ended on 'for'"), the three signals (words, voice score, Spark answer + time), session stats. | "Every pause is decided by code first: words, then my own audio check, then Muse Spark only if unsure." |
| 04 | 1:17–1:42 | Booking assistant: clean text with change chips, "show what I said", "two, no, three people", the **confirm gate** (Yes / Change). Type any time (2x). | "It only removes, never adds. A code guard checks every name, number and time." |
| 05 | 1:42–2:22 | `voice-studio.html?demo=1`: my recording, cut list with evidence, turn one cut off, make the clean version; then `voice-over.html?demo=1`: Voice editing **Off**, then **On**. AI voice: live sentence check and "AI voice (watermarked)" label (2x). | "Muse Spark 1.2 listens for stammers. Meta's wav2vec 2.0 and my own aligner prove where each one is. I approve every cut." |
| 06 | 2:22–2:42 | `bench/results.html?demo=1`: Real (my voice) table. Baseline vs default engine cut-offs, invented content, delay. 2 s of the benchmark running in the terminal (4x). | "Measured on my own voice: 14 → 2 replies while I was still talking. Zero invented words." |
| 07 | 2:42–2:52 | Voice Passport: lock, then unlock. Learner: one suggestion with its reason, I approve it (2x). | "My settings are encrypted in the browser. The learner only suggests; I decide." |
| 08 | optional | A very short closing shot, only if there is time. The end card follows. | "Unhurried. Teaching machines to wait." |
| End | last 9 s | End card: Meta models used, repo link, "Unhurried teaches machines to wait." | – |

Files: `video_build/shots/01.mp4` … `08.mp4` (OBS, 1080p, 30 fps). The intro and end cards are rendered into `video_build/cards/`.

## Recording checklist

- Run `python scripts/demo_reset.py` before each take, then restart the server.
- Chrome, 1920×1080, 100% zoom, `?demo=1` on every page, notifications off.
- **Headphones on** (echo), quiet room, good mic.
- OBS at 1080p, 30 fps. Record each shot separately.
- No API keys, file paths or private data on screen.
- Export: MP4, 1080p, 3:00 or less. Upload, set public or unlisted, test the link in a private window.
