# Unhurried

**A voice layer that stops voice AI from cutting people off during a stammer, and passes on a clean version of what they meant.**

Unhurried sits between a person and any voice bot. It decides when the person has really finished, removes repeated sounds without changing the meaning, and confirms before important actions. It is accessibility infrastructure for voice AI. It fixes the machine, not the speaker: it never scores, rates or coaches anyone's speech.

Built for the Meta Global AI Developer Hackathon (Indie track, Theme 1 "Build for Your World").

## The problem

Voice AI is built for fluent speech. A stammer block is often a silent pause, and voice bots treat silence as "finished". They reply in the middle of a sentence. Repeated sounds ("b-b-book") confuse them, so they mishear the request. Knowing the bot will cut in adds pressure, and many people stop using voice.

We measured this on Meta's own streaming speech model: with a 3-second pause after "Book a table for", Muse Voice Transcribe's default end-of-speech ended the turn about 0.5 s after the last word ([probe report](scripts/probe_report.md)).

## How it works

![Architecture](docs/architecture.svg)

1. The browser streams 24 kHz audio to the Unhurried server.
2. The audio router forwards it to **Muse Voice Transcribe** and gets live text and end-of-speech events. A zero-lag audio level check runs on the same audio.
3. The **turn engine** decides on every pause: hold or send.
   - **Words:** code rules. A sentence ending on a linking word ("for", "to", "the"), a cut word ("b-"), a repeated word, a filler or no words yet is unfinished, so it holds.
   - **Sound:** our own audio code on the last 0.5 s before the pause: pitch direction, volume fade, and voicing inside the pause.
   - **Muse Spark:** "is this a complete request?" when the code is not sure. Checks start early on live text, with a 700 ms limit at the pause.
   - **Personal max wait:** learned from the person's pauses inside sentences (90th percentile + 1 s, 2 to 6 s). It never ends a turn just because a pause was long, until the max wait.
   - While holding, the screen shows "Take your time". There is no timer or countdown.
4. The **meaning rebuild** joins repeated sounds and words and removes fillers in code. Muse Spark resolves self-corrections ("two, no, three" becomes "three") only when the text has a correction pattern. A **no-new-content guard** checks that every number, day, time, name and word in the clean text was actually said. If not, Unhurried does not guess: it asks the person.
5. The **confirm gate** shows one line ("Book a table for 2 at 7 PM on Friday?") with Yes / Change before booking or cancelling, and for any rebuild the guard could not verify.
6. The bot gets the clean sentence. The person can always tap "show what I said".

The benchmark streams recorded clips through the same server, so the numbers come from the real pipeline.

## Meta models used

| Model | What it does in Unhurried |
| --- | --- |
| **Muse Voice Transcribe** (`muse-voice-transcribe-1.0`, realtime) | Live text, end-of-speech as *one signal, not the decision*, and per-person **keyword biasing** from the Voice Passport. The benchmark reports how often its default end-of-speech fires inside a pause. |
| **Muse Spark** (`muse-spark-1.3`) | Four jobs: completeness check on live text, meaning rebuild for self-corrections, the learner agent's tool calls, and the brain of the demo booking bot (tool calling). |
| **Muse Glimmer** (optional) | The same completeness check and rebuild on Meta's open model, for a private mode. `bench/compare_models.py` compares Spark and Glimmer on the same turns when a Glimmer host is configured. |

## Built during the hackathon

All code in this repository was written between Oct 28 and Nov 4, 2026.

- `server/llm.py`: all Meta API calls, with time and cost logged for every call
- `server/audio_router.py`: browser audio to Voice Transcribe, events back, zero-lag voice check
- `server/turn_controller.py`, `server/engine.py`, `server/sound.py`, `server/completeness.py`: the turn engine
- `server/timing_profile.py`: personal max wait
- `server/rebuild.py`, `server/guard.py`: meaning rebuild and no-new-content guard
- `server/confirm.py`: confirm gate
- `server/learner.py`: learner agent (proposes profile changes after a session; the person approves each)
- `server/bot/booking_bot.py`: demo restaurant booking bot (Muse Spark + tools)
- `web/`: live page, split-screen demo, encrypted Voice Passport, privacy page
- `bench/`: clip recorder, benchmark runner, scoring, results page, model comparison
- `scripts/probe_voice.py`: the day-1 probe of Voice Transcribe's streaming behaviour

## Run it

```sh
python -m pip install -r requirements.txt
cp .env.example .env          # add META_API_KEY
python -m uvicorn server.main:app --port 8000
```

- Live page: http://127.0.0.1:8000/web/index.html
- Split-screen demo: http://127.0.0.1:8000/web/demo.html (or `sh scripts/demo.sh`)
- Record benchmark clips: http://127.0.0.1:8000/bench/record.html
- Tests: `python -m pytest`

Benchmark:

```sh
python bench/run_bench.py --clips bench/clips_synthetic.jsonl --configs baseline,words,unhurried
python bench/report.py        # writes bench/results.html
python bench/compare_models.py
```

## Results

Run on Oct 28, 2026 ([results file](bench/results/20261028_141053.json), [results page](bench/results.html)). **Synthetic set:** 24 clips (16 with silent blocks, repeats, fillers or a self-correction; 8 fluent), made with Windows text-to-speech. These test the pipeline, not real stammered speech. Real recordings come next. Same audio, streamed at 1x through the live server, once per turn-engine setup.

| Turn engine | Cut-offs (stammer clips) | Understood | Added delay on fluent speech vs baseline (median / p95) |
| --- | --- | --- | --- |
| Default end-of-speech (baseline) | **9 / 16** | 23 / 24 | – |
| Words only (code rules) | 0 / 15 * | 21 / 23 * | 0.32 s / 0.61 s |
| Words + Spark completeness check | 1 / 16 | 24 / 24 | 0.72 s / 0.90 s |
| Words + sound | 3 / 16 | 23 / 24 | 0.04 s / 0.29 s |
| Words + sound + Spark tie-break | 2 / 16 | 23 / 24 | 0.04 s / 0.40 s |

\* One run in this setup failed (the connection closed); it is left out, not counted as a success.

- **Invented content: 0** turns in every setup. The no-new-content guard found nothing to block.
- **Voice Transcribe's default end-of-speech** fired in the middle of 10 of the 16 stammer clips in the baseline run, ending the turn during a pause.
- **What the setups show:** the code rules remove most cut-offs. The Spark check catches one more case, but Spark takes about 1.4 s per call (median), so it adds delay. The sound signal makes fluent speech almost as fast as the baseline, but on synthetic voices every text piece ends with falling pitch, so it lets through some mid-sentence pauses after complete-looking phrases ("Book a table for two … at seven"). That trade-off needs real recordings to settle.
- **Understanding** is high even in the baseline, because the demo bot asks a follow-up question when it gets half a sentence. In the misses we looked at, the bot asked "9 AM or 9 PM?" instead of booking, or Voice Transcribe dropped words.

**Model check** ([file](bench/results/models_20261028_141053.json)): Muse Spark's completeness check was correct on 28 of 29 decision points (labels from the clips: did the person keep talking?), median 1.37 s per call. All 6 self-correction rebuilds passed the guard. Muse Glimmer was not run yet (no host configured).

Cost of this benchmark run: $0.53.

## Voice Passport (privacy)

The personal profile is encrypted in the browser (AES-256-GCM, key from a passphrase via PBKDF2-SHA-256 with 600,000 rounds). The server stores only the locked blob and cannot read it. At session start the browser sends only what the session needs: max wait, word list, approved word switches and settings. The profile never holds audio or any score of the person's speech. Export, import and delete are one button each.

Honest limit: the word list is sent to Voice Transcribe during a session for keyword biasing, and the text of each turn is sent to Muse Spark. See [web/privacy.html](web/privacy.html).

## Ground rules

- **Not a speech coach or a medical tool.** Unhurried changes how the AI listens. It never scores, rates or tracks a person's speech, and never gives speaking tips.
- **Measure only the AI:** cut-offs, understanding, added delay, invented content.
- **Privacy:** live audio is not stored. Only text is kept, and it can be deleted.
- **Consent:** benchmark clips are recorded with written consent ([form](docs/consent_form.md)). Only the builder's own voice and synthetic voices are public. Volunteers' audio stays private; only their counts are published.
- **No SEP-28k:** its non-commercial license conflicts with the hackathon's submission terms, so none of its audio or labels are used.

## Honest limits

- The benchmark set is small. Counts are shown, not only percentages.
- The synthetic clips use text-to-speech with silent pauses. They test the pipeline, but they are not real stammered speech: real blocks have tension, breath and partial sounds. The synthetic voice also ends each text piece with falling pitch, so the sound signal cannot be judged on them.
- Muse Spark takes about 1 to 2 s per call, longer than the 700 ms budget for the completeness check. Most checks time out, and the turn is then sent. This adds delay on fluent speech. The sound signal is meant to skip the model call when words and sound agree.
- A pause after a complete-looking phrase ("Book a table for two … at seven") is still hard: the words look finished. Real audio (tense voicing, no fade) is where the sound signal should help.
- Echo: while the bot speaks, the browser sends silence instead of mic audio.
