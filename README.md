# speech2picture

Use your voice and OpenAI to make new art. Or, monitor an ongoing conversation
and have the picture frame change to reflect the conversation — an
eavesdropping picture frame\!

- [Video of this project in action](https://www.youtube.com/watch?v=Wzuj7Vhyl8w)
- [Full write-up](https://www.jimschrempp.com/features/computer/speech_to_picture.htm)
- Based on the [WhisperFrame project on Hackaday](https://hackaday.com/2023/09/22/whisperframe-depicts-the-art-of-conversation/)

---

## How it works

1. Record audio from the default microphone
2. Transcribe it using OpenAI Whisper
3. Extract keywords from the transcript
4. Generate 4 AI images (different styles) and combine them into one
5. Display the composite image
6. Optionally, delay 60 seconds and repeat

Runs on macOS and Raspberry Pi.  RPi supports a hardware "Go" button and
kiosk mode (auto-start on boot).

---

## Quick start

```bash
git clone https://github.com/jschrempp/speech2picture.git
cd speech2picture
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 pyspeech.py
```

**Full setup instructions** (macOS, RPi, S3/QR, autostart): see **[SETUP.md](SETUP.md)**.

---

## Project structure (v2.1+)

```
speech2picture/
├── pyspeech.py              ← entry point, main loop, pipeline orchestration
├── requirements.txt
├── README.md
├── SETUP.md                 ← detailed platform setup guide
├── src/
│   ├── config.py            ← Config, constants, CLI parsing, dependency check
│   ├── hardware.py          ← RPi GPIO, LED blink thread (no-op on macOS)
│   ├── audio.py             ← Platform-abstracted audio recording
│   ├── openai_client.py     ← OpenAI API: transcribe, summarise, keywords, images
│   ├── images.py            ← Image post-processing, compositing, error images
│   ├── display.py           ← Qt window management, image display, popups
│   └── ui/                  ← Qt Designer .ui files + Python loaders
├── history/                 ← generated images (auto-created)
├── errors/                  ← error images (auto-created)
├── idleDisplayFiles/        ← images shown when idle (auto-created)
└── addToIdleDisplayFiles/   ← drop PNGs here to add to rotation
```

---

## Usage

```bash
python3 pyspeech.py          # interactive terminal menu
python3 pyspeech.py -o -q     # once, with S3 upload + QR codes
python3 pyspeech.py -g        # kiosk mode (hardware button)
python3 pyspeech.py -h        # show all CLI options
```

| Flag | Description |
|------|-------------|
| `-o` | Audio-only keywords (10 s recording, no extraction) |
| `-q` | Upload to S3 and display QR codes |
| `-g` | Kiosk mode (hardware button control) |
| `-m` | Single large image (DALL·E 3) |
| `-s` | Save intermediate files (debug) |
| `-d 1` | Debug: show prompts |
| `-d 2` | Debug: show prompts + API responses |
| `-w FILE` | Use audio from file |
| `-t FILE` | Use transcript from file |
| `-i FILE` | Use image from file |

---

## OpenAI API key

```bash
export OPENAI_API_KEY='sk-...'
```

Or create a file named `creepy photo secret key` in the project root.

---

## Important notes

### Image content safety

New images are saved in `./history/`.  Idle-display images come from
`./idleDisplayFiles/`.  Periodically review `./history/` and move acceptable
images into `./idleDisplayFiles/`.

**Remote management:**

```bash
mkdir temp && cd temp
scp -r <user>@<ip>:~/speech2picture/history .
# review files, remove questionable ones
scp -r . <user>@<ip>:~/speech2picture/idleDisplayFiles
```

### Microphone permissions

- **macOS**: System Settings → Privacy & Security → Microphone → enable Terminal.
- **Raspberry Pi**: `sudo usermod -a -G audio $USER`

---

## Version history

| Version | Changes |
|---------|---------|
| 2.2 | Refactored into `src/` modules (config, audio, openai, images, display, hardware) |
| 2.1 | Bug fixes: quit button, message/status window blank-on-startup |
| 2.0 | Migrated to gpt-image-1.5; 4 concurrent API calls; style modifiers replace artist names |
| 1.2 | AWS S3 storage + QR code download |
| 1.0 | Consolidated Qt GUI into single grid window |
| 0.5 | Initial release |

---

## Cost

OpenAI costs a few pennies per use.  Running for an hour typically costs
around $1.00.

## Credits

Based on the [WhisperFrame project on Hackaday](https://hackaday.com/2023/09/22/whisperframe-depicts-the-art-of-conversation/).

Author: **Jim Schrempp** 2023–2026
