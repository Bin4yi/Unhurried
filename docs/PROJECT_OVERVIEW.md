# Unhurried: project overview

What we built for the Meta Global AI Developer Hackathon (Indie track, Theme 1 "Build for Your World"), how it works, what we measured, and what is still open. All code in this repository was written between Oct 28 and Nov 4, 2026.

---

## 1. The idea in one paragraph

Voice AI is built for fluent speech. When a person who stammers has a block (a silent pause in the middle of a sentence), voice bots treat the silence as "finished" and reply too early. Repeated sounds ("b-b-book") also confuse them. **Unhurried is a voice layer that sits between a person and any voice AI.** It decides when the person has really finished, removes repeated sounds without changing the meaning, and asks before important actions. A second tool, **Voice Studio**, cleans recordings: it removes repeated sounds, fillers and long blocks from the person's *own* voice.

Unhurried changes how the machine listens. It never scores, rates or coaches anyone's speech.

---

## 2. The problem, measured on Meta's own model

Before building anything, we tested Muse Voice Transcribe's streaming API ([probe report](../scripts/probe_report.md)):

- With a 3-second pause after "Book a table for", the default end-of-speech **ended the turn about 0.5 s after the last word**. The next words became a separate turn. This is exactly the cut-off Unhurried fixes.
- The stream itself stays open through long pauses (we tested 8 s), as long as audio keeps arriving. So Unhurried can join several model turns into one sentence.
- End-of-speech cannot be tuned or turned off. Mode is fixed per session.
- Keyword biasing works: names went from "Pinula" / "Mattera" to "Binula" / "Matara".
- Live text arrives about 0.3 s behind speech. The end-of-speech signal arrives about 0.8 s after the real end.

In the benchmark (section 9), the default end-of-speech fired in the middle of a pause in **10 of 16** stammer clips.

---

## 3. What is in the project

| Part | What it is | Where |
| --- | --- | --- |
| Live voice layer | Browser mic → server → Muse Voice Transcribe → turn engine → assistant | `server/` |
| Turn engine | Decides on every pause: wait, or send | `server/turn_controller.py`, `engine.py`, `sound.py`, `completeness.py` |
| Meaning rebuild + guard | Clean sentence for the bot, never adds content | `server/rebuild.py`, `guard.py` |
| Confirm gate | Yes / Change before booking or cancelling | `server/confirm.py` |
| Assistants | General voice assistant, and a restaurant booking demo with tools | `server/bot/booking_bot.py` |
| **Studio** (live testing page) | Talk live and see why each turn was held or sent | `web/studio.html` |
| **Voice Studio** | Clean a recording in your own voice; optional AI voice | `web/voice-studio.html`, `server/studio/` |
| Voice Passport | Personal settings, encrypted in the browser | `web/passport*.js`, `server/passport_store.py` |
| Learner agent | Suggests small setting changes after a session; the person approves each | `server/learner.py` |
| Benchmark | Same audio through 5 turn-engine setups, scored automatically | `bench/` |
| Split-screen demo | Normal bot vs Unhurried on the same audio | `web/demo.html` |

About 6,100 lines of code, 147 automated tests (Python and JavaScript), 25 commits.

---

## 4. The live voice layer: how one turn works

1. **Browser.** The microphone is captured at 24 kHz and sent in 80 ms pieces over a WebSocket. While the assistant is speaking, the browser sends silence instead of mic audio, so the speech service does not hear the assistant. (The stream must keep receiving audio, or the service closes it after 10 s.)
2. **Audio router** (`server/audio_router.py`). Forwards audio to Muse Voice Transcribe and turns its events into simple ones: live text, speech start, speech end, model turn. It also runs its own **zero-lag voice check** on the raw audio (level above an adaptive noise floor). Voice Transcribe reports "speech started again" about 0.8 s late; our check knows at once.
3. **Turn engine** decides, on every pause, whether to hold or send (section 5).
4. **Meaning rebuild** makes the clean sentence (section 6).
5. **Confirm gate** asks before important actions (section 7).
6. **Assistant** replies; the browser speaks the reply at a calm rate.

Every event, decision and turn is logged per session in `runs/{session}/` as JSON lines. Every Meta API call is logged with time taken and cost in `runs/llm_calls.jsonl`. All Meta calls go through one file, `server/llm.py`.

---

## 5. The turn engine: hold or send?

Three signals, combined in code. Models are only asked when code is not sure.

**1. Words (code rules, about a millisecond).** The sentence is unfinished if it ends on a linking word ("for", "to", "the", "and", "my" …), a cut word ("b-"), a repeated word ("I I"), a filler ("uh"), or has no real words yet. Then: hold, and show "Take your time". There is no timer or countdown anywhere.

**2. Sound (our own audio code, `server/sound.py`).** On the last 0.5 s before the pause:
- pitch direction (finished statements often fall),
- volume fade (a finished sentence fades; a block often stops suddenly),
- voicing inside the pause (a held sound means the person is still trying).
These give a "sounds finished" score from 0 to 1. If words and sound both say finished, the turn is sent at once, **with no model call**. Voicing inside the pause always holds.

**3. Muse Spark completeness check** ("is this a complete request?"), used as the tie-breaker. Spark takes about 1–2 s per call, so checks are started early on live text and cached; at the pause the engine waits at most 700 ms, then sends rather than keep the person waiting.

**Personal max wait.** Unhurried learns how long *this* person's pauses inside a sentence last: 90th percentile + 1 s, kept between 2 and 6 s. A pause alone never ends a turn before the max wait. The max wait counts from the last moment the voice check heard a voice, not from the speech service's delayed signal.

**Type any time.** Typing mid-sentence joins the open turn (including words not yet final) and sends it.

---

## 6. Meaning rebuild and the no-new-content guard

The assistant gets a clean sentence, but Unhurried may only remove or fix, never invent.

1. **Code pass.** Joins repeated sounds ("b-b-book" → "book"), repeated words and phrases up to 8 words ("I'm going to talk about I'm going to talk about" → once), removes fillers. Each change is shown as a chip ("I I I I → I").
2. **Muse Spark pass**, only when the text has a correction pattern ("no", "I mean", "sorry", "actually"): resolves self-corrections ("two, no, three people" → "three people").
3. **Guard (code).** Every number, day, time, name and word in the clean text must appear in what the person said (after normalizing "two" = 2, "seven pm" = 19:00, "Fri" = Friday), or come from a word switch the person approved. If not, Unhurried does not guess: it asks the person to confirm.

The person can always tap "show what I said".

---

## 7. Confirm gate, assistants and calm pace

- Before `book_table` or `cancel_booking`, and when the guard could not verify a rebuild, the page shows one line, for example "Book a table for 2 at 7 PM on Friday?", with **Yes / Change**. Saying "yes" or "no" also works. Questions never need a confirm.
- **General assistant** (default in the Studio): talks about whatever the person says.
- **Booking assistant** (demo): Muse Spark with tools `book_table`, `cancel_booking`, `list_bookings`.
- **Calm pace** for both: short replies, never finish the person's sentence, never comment on how they speak, never repeat the last question, never say "sorry, I didn't catch that" twice in a row. Replies are spoken at rate 0.9.

---

## 8. The two main pages

### Studio (live testing): `web/studio.html`

- Your words appear large as you speak. A breathing circle follows your voice level. When Unhurried is waiting, it turns clay-coloured and says "Take your time." No timer.
- **Three modes:** Unhurried; Normal bot (feel the problem); Side by side (both on the same microphone; the normal bot's replies are marked "replied while you were mid-sentence").
- **Inspector:** for every pause, the decision in plain words ("Your sentence ended on 'for', so more was coming"), the three signals (words, voice score, Spark answer and time), a timeline of every pause, and session stats: *times a normal bot would have cut in*, longest pause you were given, turns, repairs.
- Settings: choose the assistant and the turn engine, words to listen for, Voice Passport.
- Design: warm paper and ink colours, Fraunces and Instrument Sans fonts, dark mode, keyboard focus styles, reduced-motion support.

### Voice Studio: `web/voice-studio.html`

Record (or upload) a voice note, talk or narration. Voice Studio cuts repeated sounds, repeated words, fillers, self-corrections and long blocks out of **your own recording**. You check every cut.

**How it finds the stammers: the model listens, code proves it.**

| Step | What happens |
| --- | --- |
| Transcribe | Muse Voice Transcribe gives the text (turn-level times only). |
| Listen | **Muse Spark 1.2 listens to the audio** in 8–15 s pieces (split at quiet points), **twice**, and writes exactly what was spoken, stammers included: "B- B- Binula", "ca- ca- currently", "my my my". Strict JSON, one retry. Voice Transcribe had smoothed these away. |
| Ground | Spark's own timestamps are not reliable, so it is never asked for times. **Meta's wav2vec 2.0** aligns the model's words to the audio with our own CTC Viterbi aligner, giving each word and fragment its real start and end. |
| Drift check | If the model's words disagree with Voice Transcribe in a piece, that piece falls back to code rules. |
| Evidence gates | Every cut must contain voice, be followed by the real word, be under 2.5 s, and the total may not exceed 35% of the recording. |
| Second source | A cut is switched on only if wav2vec 2.0 independently heard the same sound there, or both listens agree. Otherwise it is shown, switched off, for the person to decide. |
| Re-check | After rendering, the clean text is aligned to the clean audio to check the meant words are still there. |

Code also understands that acoustic models mix up voiced and voiceless twins (b/p, d/t, g/k/c, f/v, s/z), so "p-p-period" heard as "B B B" still counts.

The page shows, for every cut, why it was made ("Spark heard it · heard again on a second listen · wav2vec 2.0 heard it too"), and lists what the checks turned down.

**Real-voice output (default):** the original audio, cut and joined with short crossfades. Long blocks are shortened to 0.3 s, not removed. Every sound in the file is from the recording.

**AI voice (optional):** a clone of the person's voice reads the clean words (Chatterbox by Resemble AI, MIT licence, runs locally). Rules enforced in code:
1. Only your own voice: the recording must be made live in Voice Studio (not uploaded), and you must read a random sentence aloud that must match.
2. Only your own words: the clone reads the clean text, which only has words you said.
3. Every file carries an inaudible AI watermark (verified: detector score 1.0 on our output, 0.0 on normal speech) and is labelled "AI voice".

Example from a real test recording:

> said: "My my my name is B- B- Binula … I am ca- ca- currently … I use meta ma- ma- mouse"
> clean: "My name is Binula … I am currently … I use Meta mouse"

---

## 9. Benchmark and results

The benchmark measures the AI, never the person. Each clip is streamed at 1x speed through the live server once per turn-engine setup.

Measured: **cut-offs** (a turn sent before the real end of speech), **understanding** (the bot called the right tool with the right details), **added delay on fluent speech**, **invented content**.

Run on Oct 28, 2026, on a **synthetic set** of 24 clips made with Windows text-to-speech (16 with silent blocks, repeats, fillers or a self-correction; 8 fluent). Full results: [`bench/results/20261028_141053.json`](../bench/results/20261028_141053.json), [`bench/results.html`](../bench/results.html).

| Turn engine | Cut-offs (stammer clips) | Understood | Added delay on fluent speech (median / p95) |
| --- | --- | --- | --- |
| Default end-of-speech (baseline) | **9 / 16** | 23 / 24 | – |
| Words only | 0 / 15 * | 21 / 23 * | 0.32 s / 0.61 s |
| Words + Spark check | 1 / 16 | 24 / 24 | 0.72 s / 0.90 s |
| Words + sound | 3 / 16 | 23 / 24 | 0.04 s / 0.29 s |
| Words + sound + Spark | 2 / 16 | 23 / 24 | 0.04 s / 0.40 s |

\* One run failed (connection closed) and is left out, not counted as a success.

- **Invented content: 0** in every setup.
- Spark's completeness check was correct on **28 of 29** decision points (median 1.37 s per call). All 6 self-correction rebuilds passed the guard.
- Cost of this benchmark run: $0.53.

What it shows: code rules remove most cut-offs; the Spark check catches one more case but adds delay; the sound signal makes fluent speech almost as fast as the baseline, but on synthetic voices (which end every text piece with falling pitch) it lets a few mid-sentence pauses through. Real recordings will settle that trade-off.

Tools: `bench/record.html` (record and label clips; volunteer audio always stays private), `bench/run_bench.py`, `bench/report.py`, `bench/compare_models.py` (Spark vs Glimmer on the same turns).

---

## 10. Voice Passport and the learner agent

**Voice Passport.** Personal settings (pause timing, words to listen for, approved word switches, preferences), **encrypted in the browser** with AES-256-GCM, key from a passphrase via PBKDF2-SHA-256 with 600,000 rounds. The server stores only the locked blob, checks its shape, and cannot read it. At session start only what the session needs (max wait, word list, switches, settings) is sent, kept in memory, and forgotten at the end. Export, import and delete are one button each. It never stores audio or any score of speech.

**Learner agent** (`server/learner.py`). After a session, Muse Spark reads a summary of the log (pauses, holds, sends, Change taps, guard events; no audio) and proposes up to four small changes through tools: `adjust_max_wait`, `add_listen_word`, `add_switch`, `set_pref`. Code limits every proposal (max wait 2–6 s, at most 1 s per step, known settings only). Each one is shown in plain words, for example "Wait up to 3.8 s instead of 3.0 s. You paused up to 3.4 s inside sentences today." It only goes into the passport after the person approves it.

---

## 11. Meta models used

| Model | How Unhurried uses it |
| --- | --- |
| **Muse Voice Transcribe** (`muse-voice-transcribe-1.0`) | Realtime: live text and end-of-speech as *one signal, not the decision*; per-person keyword biasing. File endpoint: Voice Studio transcripts and the live sentence check for the AI voice. |
| **Muse Spark 1.3** | Completeness check, meaning rebuild, the learner agent's tool calls, both assistants (tool calling for bookings), self-correction ranges in Voice Studio. |
| **Muse Spark 1.2 (audio)** | Listens to recordings and writes stammers verbatim. Its output is grounded and checked by code before any cut. |
| **wav2vec 2.0** (`facebook/wav2vec2-base-960h`, Meta open model) | Word timing by forced alignment (Voice Transcribe has no word times), independent "what was heard" check, and the after-render check. Runs on CPU. |
| **Muse Glimmer** | Supported as a provider for the completeness check and rebuild; the comparison script runs when a Glimmer host is configured. Not run yet. |

---

## 12. Privacy, consent and ground rules

- Not a speech coach or a medical tool. Unhurried never scores, rates or tracks speech and never gives speaking tips.
- Live audio is not stored. Only text is kept, and it can be deleted.
- Voice Studio keeps a recording on the local machine until the person deletes it (one button).
- Benchmark clips need written consent ([form](consent_form.md)). The builder's real recordings are not published, only their counts; the public clips are synthetic voices. Volunteers' audio also stays private and only their counts are published, because the hackathon rules give the organizers broad rights to the submission.
- SEP-28k is not used: its non-commercial licence conflicts with the submission terms.
- Privacy page: [`web/privacy.html`](../web/privacy.html).

---

## 13. Engineering notes

- **Tests:** 147 automated tests: turn rules (20 example sentences), timing, sound signal, rebuild and guard, confirm gate, benchmark scoring, Voice Studio cut finder, the model harness gates, the Studio API, and the browser encryption round trip (run in Node).
- **Decisions in code first:** models are asked only where code cannot decide, always with a time limit and a fallback.
- **Bugs the benchmark found and we fixed:** benchmark sessions used a learned profile; the speech service's end time is up to ~1 s early or late (pauses are now anchored on our own voice check); more than 3 parallel streams made results noisy; a Voice Studio crash on recordings longer than a few seconds; missed sound repeats written as one made-up token ("BBV").
- **Cost:** every call is logged with its price. Voice Transcribe is $0.18 per hour of audio; a full 120-run benchmark cost $0.53.

---

## 14. Honest limits

- The benchmark set is small and synthetic. Real stammered speech (tension, breath, partial sounds) is the real test.
- Muse Spark takes 1–2 s per call, longer than the 700 ms budget for the completeness check, so it adds delay on fluent speech.
- A pause after a complete-looking phrase ("Book a table for two … at seven") is still hard for the words signal; the sound signal is meant for it and needs real recordings to prove itself.
- Voice Studio takes about 35–55 s per minute of audio (each piece is listened to twice). The model's verbatim text can still include small errors; cuts it is unsure about are left off for the person.
- The AI voice runs on CPU on a laptop: several minutes per recording.

---

## 15. Not built yet / next steps

1. **Record real clips** with the builder's own voice and rerun the benchmark: the most important next step.
2. **SAM 3.1 sight signal** (opt-in camera): mouth still open or moving during a pause = still trying to speak.
3. **Muse Spark Open audio tie-breaker** through Baseten (needs credits).
4. **Glimmer comparison run** once a host is configured.
5. Echo guard with speaker labels (DIARIZATION mode is slower; the current fix sends silence while the assistant speaks).
6. Publish the benchmark as an open test: "How often does voice AI cut off people who stammer?"

---

## 16. How to run

```powershell
python -m pip install -r requirements.txt
Copy-Item .env.example .env       # then add META_API_KEY
python -m uvicorn server.main:app --port 8000
```

- Studio (live): http://127.0.0.1:8000
- Voice Studio: http://127.0.0.1:8000/web/voice-studio.html
- Split-screen clip demo: http://127.0.0.1:8000/web/demo.html
- Record benchmark clips: http://127.0.0.1:8000/bench/record.html
- Tests: `python -m pytest`

The AI voice is optional and installed separately (about 2.2 GB): Chatterbox into `.clone-pkgs/`, run with Python 3.12.

---

## 17. Timeline (Oct 28, 2026)

1. Voice Transcribe probe and report
2. Live audio path with captions
3. Demo booking bot and baseline mode
4. Turn controller (word rules, hold, max wait)
5. Spark completeness check, personal timing, keyword biasing
6. Meaning rebuild with no-new-content guard
7. Confirm gate
8. Calm bot pace, type any time
9. Encrypted Voice Passport
10. Clip recording page, consent form, synthetic clip set
11. Benchmark runner; timing fixes found by the benchmark
12. Split-screen demo
13. Sound signal (pitch, fade, voicing)
14. Learner agent with approval step
15. Results page, model comparison, README
16. Studio page for live testing
17. General assistant; repeat cleanup fixes
18. Voice Studio: alignment, cut finder, real-voice output, optional AI voice
19. Sound repeats before a word; Muse Spark listening inside a code harness
