# How to record the voice-over and make the before/after

All commands are for **PowerShell** on Windows.

## 1. Start the app

```powershell
cd C:\Users\User\Desktop\Hackthons\meta
python -m uvicorn server.main:app --port 8000
```

Keep this window open. Open **Chrome**.

## 2. Record each shot in Voice Studio

1. Open **http://127.0.0.1:8000/web/voice-studio.html**
2. Put on **headphones**. Quiet room. Same microphone for every shot.
3. Open `docs/DEMO_SCRIPT.md` next to it.
4. Press the round **record** button. Say **one shot** (for example Shot 1) in your own words. Do not rush. Press the button again to stop.
5. Wait about 30–60 seconds. Voice Studio shows your words and the cuts (crossed out in clay).
6. Check the cuts. Tap a crossed-out word to **keep** it if it was not a stammer. Tap a word to **cut** it if a stammer was missed.
7. Press **Make the clean version**.
8. Press **Open in the voice-over player**.

Do this for each shot (1 to 8). One recording per shot is easier to edit in the video.

Tip: record Shot 5 in one take. That is the one you will play with voice editing off and on in the video.

## 3. Get the files for the video

On the voice-over page (**http://127.0.0.1:8000/web/voice-over.html**):

- Choose the recording in the **Recording** list.
- **Download clean voice-over**: this is the narration for that shot (your voice, stammers cut). Put it on the audio track under the screen recording.
- **Before/after clip**: set the start second (where a stammer happens) and a length (5–10 s), then **Download before/after**. It plays the original, a short pause, then the same words cleaned.

## 4. Film the before/after on screen (Shot 5)

1. Open **http://127.0.0.1:8000/web/voice-over.html?demo=1** (bigger text).
2. Choose the Shot 5 recording.
3. Start your screen recorder (OBS or Xbox Game Bar: `Win + Alt + R`).
4. Press **Off**, then play (or press `Space`) for about 5 seconds.
5. Press **On** (or `E`). Playback continues from the same words, now clean.
6. Stop the screen recorder.

In the video, the viewer sees the switch, the crossed-out words, and hears the difference.

## 5. Tell me when you are done

Say "voice-over done". I will:

- add your new recordings to the real benchmark set (`python bench/import_studio.py`), only if you agree,
- show the before/after for each shot,
- fill the **TBD** numbers in the script from the results file.

## Checklist

- [ ] Headphones on, quiet room
- [ ] One recording per shot, in Voice Studio (live, not uploaded)
- [ ] Cuts checked for every shot
- [ ] Clean voice-over downloaded for every shot
- [ ] Shot 5 before/after filmed with the On/Off switch
- [ ] No API keys, file paths or private data on screen
