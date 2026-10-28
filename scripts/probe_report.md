# Voice Transcribe probe report

Run on Oct 28, 2026 against `muse-voice-transcribe-1.0` (realtime WebSocket).
Test audio: synthetic Windows voices (`scripts/make_fixtures.ps1`), 24 kHz mono.
Real stammered speech still needs to be tested; synthetic pauses are clean
digital silence, so real blocks (breath, tense voicing) may behave differently.
Raw event logs: `runs/probe/*.jsonl` (not committed).

Sources:
- https://dev.meta.ai/docs/speech-to-text/
- https://github.com/meta-models/meta-model-cookbook/tree/main/06_muse_voice/01_voice_api_fundamentals
- https://dev.meta.ai/docs/models

## Basics

- Model: `muse-voice-transcribe-1.0`. Realtime: `wss://api.meta.ai/v1/asr/realtime`.
- Auth: first JSON frame, `{"authorization": {"accessToken": "Bearer <key>"}}`.
  **Works with the `Bearer ` prefix** (tested).
- Handshake fields used: `mode`, `authorization`, `audioEncoding`, `model`,
  `partialMode` (`CUMULATIVE`), `emitAudioProgress`, `keywords`.
- Audio: raw PCM s16le mono, 80 ms binary frames, paced at 1x.
- Session ack (`{"sessionId": ...}`) arrives **1.0-2.0 s after connect**.
  Open the stream before the user starts talking (e.g. on page load / Start).
- End: `{"type": "endStream"}` → final `transcript` → close code 1000.
- Close codes (docs): 1008 = bad handshake, >5 s backlog, or audio slower than
  real time for 10 s; 1011 = server error / 60-minute limit; 1013 = rate limit.
- Price: $0.18 per hour of audio.

## 1. Can we get partial text while the person is still talking?

**Yes.** Cumulative partials arrive every 1-3 words.
In `ENDPOINTING` the partial text **resets at each new turn**; in
`PUSH_TO_TALK` it keeps growing for the whole session.

## 2. Does the API close the turn by itself after a pause?

**Depends on the mode (fixed for the whole session). No setting to tune it.**

| Mode | 3 s pause after "Book a table for" |
| --- | --- |
| `ENDPOINTING` | **Cuts the turn**: `speechComplete` = "Book a table for", then a new turn "two at seven on Friday" |
| `DIARIZATION` | Ends turns too, but later than ENDPOINTING (see 6) |
| `PUSH_TO_TALK` | **Never ends a turn.** One partial grows through the pause; final only after `endStream` |

ENDPOINTING timing: `speechEnd` is sent about **0.5 s of silence** after the
last word (wall-clock arrival about 0.75 s after the speech end time it reports).
This is exactly the cut-off Unhurried fixes. It is also our benchmark baseline.

`speechEnd` ends the **model's turn only, not the WebSocket**. Later speech
gets a new `turnId` on the same stream.

**Decision for Unhurried:** use `ENDPOINTING` for both modes.
- Baseline mode: send the turn to the bot on `speechComplete` (normal voice bot).
- Unhurried mode: treat `speechEnd` as one signal. The turn controller joins
  `speechComplete` texts from several model turns into one user turn.
- No audio buffering needed.
- Why not `PUSH_TO_TALK`: only `endStream` finalises, and that ends the
  session, so every user turn would need a new connection (1-2 s handshake).
  It also gives no end-of-speech signal to log for the benchmark.

## 3. Can we keep one stream open across long pauses (5+ seconds)?

**Yes.** 8 s of silence in the middle of a clip: stream stayed open, next
speech became turn 1. Requirement: **keep sending audio frames during pauses**
(silence frames are fine). Docs: no audio for 10 s → close 1008.

Change for Prompt 4 (echo fix): while the bot is speaking, **send silence
frames instead of stopping the mic upload**.

## 4. How does keyword biasing work?

`"keywords": ["Binula", "Matara", "Weligama"]` in the handshake. Only at
session start, so the Voice Passport word list must be loaded before the
stream opens.

| Keywords | Transcript |
| --- | --- |
| none | My name is **Pinula** and I live in **Mattera**, near Weligama. |
| Binula, Matara, Weligama | My name is **Binula** and I live in **Matara**, near Weligama. |

Also available: `"languageBias": ["English"]` (25 languages; check Sinhala/Tamil later).

## 5. Typical delay from speech to text

- Partials: **0.25-0.35 s** behind the audio (steady state).
- End of speech: `speechEnd` arrives **about 0.75-0.8 s** after the speech end
  time it reports (about 0.5 s of silence plus the lag).
- First seconds of a session show higher lag (server catching up after the
  handshake).

## 6. How do speaker labels work in streaming?

Only in `DIARIZATION` mode. Test: two voices, 0.8 s gaps (A, B, A).
- Labels were **correct**: A / B / A, same letter for the same voice.
- The `speaker` event arrives **at the end of each turn**, together with
  `speechEnd`, not during speech.
- **Turn end is much slower than ENDPOINTING**: `speechEnd` about **0.9 s**
  after the reported end, and the turn was only closed after about **1.5-2 s
  of silence** (ENDPOINTING: about 0.5 s).
- Text quality was worse in one case: "I would like to book **like to book** a
  table" (a duplicated phrase that ENDPOINTING did not have).

**Echo guard (Prompt 17), options:**
1. Run the whole live session in DIARIZATION. Slower turn signals, but Unhurried
   holds turns anyway, so this mostly hurts the baseline comparison. Risk:
   worse text.
2. Second parallel stream in DIARIZATION only for the echo guard (+$0.18/h).
3. Keep the simple fix (send silence while the bot speaks) and test labels
   only in the benchmark.
Recommendation: start with 3, try 2 on Nov 2. Note: the two test voices
were very different synthetic voices. Real echo from laptop speakers is harder.

## Commands

```
python scripts/probe_voice.py tests/fixtures/fluent.wav --tail-silence 4
python scripts/probe_voice.py tests/fixtures/pause.wav --tail-silence 4
python scripts/probe_voice.py tests/fixtures/pause.wav --mode PUSH_TO_TALK --tail-silence 2
python scripts/probe_voice.py tests/fixtures/fluent.wav --insert-silence 1.0:8 --tail-silence 3
python scripts/probe_voice.py tests/fixtures/names.wav --tail-silence 2 --keywords Binula --keywords Matara
python scripts/probe_voice.py tests/fixtures/two_voices.wav --mode DIARIZATION --tail-silence 2
```

Use `--tail-silence`: without it, `endStream` arrives right after the last word
and forces the turn end, so the endpointing timing is hidden.

## Still to test with real audio

- My own stammered speech: does a real block (not digital silence) trigger
  `speechEnd`? Repeated sounds ("b-b-book") in the text?
- Real echo from laptop speakers in DIARIZATION.
