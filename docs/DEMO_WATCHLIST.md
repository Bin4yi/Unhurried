# Final watch-list

Watch `video_build/unhurried_demo.mp4` once from start to end, with sound.

## Features visible (real app)

- [ ] Side by side: the normal bot replies mid-sentence; Unhurried shows "Take your time" and sends the full sentence
- [ ] Inspector: the reason for a pause, and the words, voice and Spark signals
- [ ] Clean text with repair chips, and "show what I said"
- [ ] A self-correction ("two, no, three people")
- [ ] Confirm gate (Yes / Change) before a booking
- [ ] Type any time
- [ ] Voice Studio: cut list with evidence, one cut turned off, clean version made
- [ ] Voice editing Off, then On, on the same words
- [ ] Results page: Real table
- [ ] Voice Passport lock and unlock; one learner suggestion approved
- [ ] AI voice is shown only if you really made one, and it is labelled "AI voice (watermarked)"

## Numbers (must match `bench/results/20261105_000043_real_self.json`)

- [ ] Normal voice bot: 14 replies while still talking, 8 of 15 recordings
- [ ] Default engine (words + voice + Spark): 2 replies, 2 of 15 recordings
- [ ] Invented content, default engine: 0 of 17 turns
- [ ] "15 recordings of my own free speech" is said or shown; no number without its set
- [ ] You do not say "TBD" (re-record Shot 6)

## On screen

- [ ] No API keys, `.env`, file paths, personal folders, browser bookmarks or notifications
- [ ] `?demo=1` on every page: label bar visible, badge correct
- [ ] Every sped-up part shows "2x" or "4x"
- [ ] Captions readable on a phone, and they do not cover the part you are showing

## Sound and length

- [ ] Narration matches the shot on screen; no echo of the assistant's voice
- [ ] Length 3:00 or less (`build_video.py` prints it)
- [ ] Your voice is in the video. The rules let the organizers reuse it, so publish only what you are comfortable with

## Before you submit

- [ ] Replace `VIDEO_LINK` in `README.md`
- [ ] `git status`: no `CLAUDE.md`, `.env`, `studio_data`, `video_build`, `HANDOFF.md`, `bench/audio/real_self`
- [ ] `git ls-files | Select-String real_self` shows only result and script files, no `.wav`
- [ ] Test the video link in a private window
- [ ] Submit: https://cerebralvalley.ai/e/meta-ai-developer-hackathon/hackathon/submit
