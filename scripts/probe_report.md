# Voice Transcribe probe report

Status: **docs read, live run not done yet** (no API key / test WAVs on Oct 28).
Answers marked **DOCS** come from the Meta docs and cookbook. Lines marked
**TO MEASURE** need the live run, using the commands at the bottom.

Sources:
- https://dev.meta.ai/docs/speech-to-text/
- https://github.com/meta-models/meta-model-cookbook/tree/main/06_muse_voice/01_voice_api_fundamentals
- https://dev.meta.ai/docs/models

## Basics (DOCS)

- Model: `muse-voice-transcribe-1.0`
- Realtime: `wss://api.meta.ai/v1/asr/realtime` (optional `?sessionId=`)
- Auth: inside the first JSON frame, `{"authorization": {"accessToken": ...}}`.
  The HTTP `Authorization` header is ignored on the WebSocket.
  The docs page says "Bearer <key>"; the cookbook passes a token. **Unclear**,
  so the probe sends `Bearer <key>` and has `--raw-token` to try without it.
- Handshake must arrive within 10 s. Fields we use: `mode`, `authorization`,
  `audioEncoding` (`PCM_16KHZ` / `PCM_24KHZ`), `model`, `partialMode`,
  `emitAudioProgress`, `keywords`. The docs say there are 9 fields in total;
  the full list is in the API reference.
- Audio: raw PCM s16le mono, binary frames, paced at real time, 80 ms frames.
  24 kHz is native; 16 kHz is resampled by the server.
- Events: `speechStart`, `transcript` (`final` true/false), `speaker`,
  `speechEnd`, `speechComplete`, `audioProgress`, `error`. Match by `turnId`.
- End: send `{"type": "endStream"}`, then read until close code 1000.
- Close codes: 1008 = bad handshake, >5 s backlog, or **audio slower than
  real time for 10 s**; 1011 = server error or 60-minute limit; 1013 = rate limit.
- Price: $0.18 per hour of audio.

## 1. Can we get partial text while the person is still talking?

**DOCS: Yes.** `transcript` events with `final: false`, cumulative (each one
replaces the previous). Partials have no `turnId`.
**TO MEASURE:** how often partials arrive (expect about every few hundred ms).

## 2. Does the API close the turn by itself after a pause?

**DOCS:** It depends on the mode, and the mode is fixed for the whole session:
- `PUSH_TO_TALK` (default): the model does **not** end turns. The client ends
  input with `endStream`, which also ends the session.
- `ENDPOINTING`: the model ends turns (`speechEnd` → `speechComplete`).
  **There is no documented silence timeout setting and no way to tune or turn
  off endpointing.** There is no client-side "commit turn" in realtime.
- `DIARIZATION`: like `ENDPOINTING` plus `speaker` events.

Important: in `ENDPOINTING`, a `speechEnd` closes the *model's* turn, **not the
WebSocket**. The stream stays open and later speech starts a new `turnId`.
**TO MEASURE:** how long after the last word `speechEnd` fires (silence before
`speechEnd`), using `pause.wav` and the `--insert-silence` runs.

**What this means for Unhurried (expected, confirm after the run):**
Use `ENDPOINTING` and treat `speechEnd` / `speechComplete` as **one signal,
not the decision**. Our turn controller joins several model turns into one
user turn. This matches the plan ("end-of-speech as one signal"), so no audio
buffering is needed, *if* question 3 below passes.

## 3. Can we keep one stream open across long pauses (5+ seconds)?

**DOCS:** Yes, as long as we **keep sending audio frames during the pause**
(silence is fine). If audio stops arriving for 10 s, the server closes with
1008. So the browser must keep streaming mic audio during blocks. Never pause
the upload.
Open question: echo fix in Prompt 4 says "stop sending mic chunks while the
bot speaks". **Change this: send silence frames instead of stopping**, or the
stream may close during long bot replies.
**TO MEASURE:** `--insert-silence 1.5:5` and `1.5:8` stay open, one or two turns.

## 4. How does keyword biasing work?

**DOCS:** `"keywords": ["Binula", "Matara"]` in the handshake. It's a hint, not
a guarantee of spelling. It **can only be set at session start**, so the Voice
Passport word list must be loaded before we open the stream.
There is also `"languageBias": ["English"]` (25 languages, auto-detect if
left out). Check later for Sinhala/Tamil.
Example: `python scripts/probe_voice.py tests/fixtures/fluent.wav --keywords Binula --keywords Matara`
**TO MEASURE:** same clip with and without keywords; compare the text.

## 5. Typical delay from speech to text

**DOCS:** not stated.
**TO MEASURE:** the `lag` column (wall clock minus `audioProcessedMs`) for
partials, and the time from end of the last word to `speechEnd`.

## 6. How do speaker labels work in streaming?

**DOCS:** Only in `DIARIZATION` mode. `speaker` events carry a bare letter
(`A`, `B`) that is the same for the whole session. Each label covers the audio
since the previous `speechStart` or `speaker` event (it comes **after** the
speech). Non-overlapping speech only. The docs say it **is not tuned for
low-latency voice commands**.
**Risk for the echo guard (Prompt 17):** because the mode is fixed per session,
using speaker labels means running all live turns in `DIARIZATION` mode, which
may be slower. Options: (a) use DIARIZATION for everything if latency is OK,
(b) a second parallel stream in DIARIZATION only for the echo guard (double
cost, still $0.36/h). **TO MEASURE** with `two_voices.wav` in both modes.

## Commands for the live run

```
python -m pip install -r requirements.txt
# put META_API_KEY in .env (copy from .env.example), or set it in the shell
python scripts/probe_voice.py tests/fixtures/fluent.wav
python scripts/probe_voice.py tests/fixtures/fluent.wav --mode PUSH_TO_TALK
python scripts/probe_voice.py tests/fixtures/pause.wav
python scripts/probe_voice.py tests/fixtures/fluent.wav --insert-silence 1.5:5
python scripts/probe_voice.py tests/fixtures/fluent.wav --insert-silence 1.5:8 --tail-silence 3
python scripts/probe_voice.py tests/fixtures/fluent.wav --keywords Binula --keywords Matara
python scripts/probe_voice.py tests/fixtures/two_voices.wav --mode DIARIZATION
python scripts/probe_voice.py tests/fixtures/two_voices.wav --mode ENDPOINTING
```

If auth fails, try again with `--raw-token`. Event logs go to `runs/probe/`.
WAVs must be mono 16-bit at 16 or 24 kHz:
`ffmpeg -i in.m4a -ac 1 -ar 24000 -sample_fmt s16 tests/fixtures/fluent.wav`
