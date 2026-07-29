# Speech2Picture — Setup Guide

## Overview

Speech2Picture captures audio from a microphone, transcribes it via OpenAI
Whisper, extracts keywords, and generates AI images (OpenAI DALL·E / GPT
image models).  It runs on macOS or Raspberry Pi in kiosk mode.

---

## Quick start

```bash
git clone https://github.com/jschrempp/speech2picture.git speech2picture
cd speech2picture
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 pyspeech.py
```

---

## Project structure (v2.1+)

```
speech2picture/
├── pyspeech.py              ← entry point, main loop, pipeline orchestration
├── s3_and_qr.py             ← S3 upload + QR-code helpers
├── requirements.txt
├── README.md
├── SETUP.md                 ← this file
├── s2p.desktop              ← RPi autostart desktop file
├── src/
│   ├── __init__.py
│   ├── config.py            ← Config, constants, CLI parsing, dependency check
│   ├── hardware.py          ← RPi GPIO, LED blink thread (no-op on macOS)
│   ├── audio.py             ← Platform-abstracted audio recording
│   ├── openai_client.py     ← OpenAI API: transcribe, summarise, keywords, images
│   ├── images.py            ← Image post-processing, compositing, error images
│   ├── display.py           ← Qt window management, image display, popups
│   └── ui/                  ← Qt Designer .ui files + Python loaders
│       ├── __init__.py
│       ├── main_window.ui
│       ├── message_dialog.ui
│       └── status_dialog.ui
├── history/                 ← generated images (auto-created)
├── errors/                  ← error images (auto-created)
├── idleDisplayFiles/        ← images shown when idle (auto-created)
└── addToIdleDisplayFiles/   ← drop PNGs here to add to rotation
```

---

## Platform-specific setup

### macOS

```bash
brew install portaudio
pip3 install sounddevice soundfile numpy
```

In Finder, go to `/Applications/Python 3.12` and double-click
"Install Certificates.command".

Make sure Terminal.app has **microphone permission** in
System Settings → Privacy & Security → Microphone.

### Raspberry Pi

```bash
sudo apt update && sudo apt-get full-upgrade
sudo apt-get install portaudio19-dev
sudo apt install python3-pyqt6
```

The venv **must** be created with `--system-site-packages` so PyQt6
(installed via `apt`) is visible.

```bash
python3 -m venv --system-site-packages .venv
```

Auto-start on boot:

```bash
cp s2p.desktop ~/Desktop
sudo cp ~/Desktop/s2p.desktop /usr/share/xsessions/s2p.desktop
```

---

## OpenAI API key

Set your key either as an environment variable:

```bash
export OPENAI_API_KEY='sk-...'
```

Or create a file called `creepy photo secret key` in the project root
containing only your key.

---

## Custom image styles

Create a file `ARTISTS_USER.txt` in the project root with one style per
line (e.g. `by Van Gogh`).  These replace the built-in style modifiers.

---

## Command-line usage

| Flag | Description |
|------|-------------|
| `-o` | Audio-only keywords (10-second recording, no extraction) |
| `-q` | Upload to S3 and display QR codes |
| `-g` | Kiosk mode (hardware button control) |
| `-m` | Single large image (DALL·E 3) instead of 4-grid |
| `-s` | Save intermediate files (debug) |
| `-d 1` | Debug: show prompts |
| `-d 2` | Debug: show prompts + API responses |
| `-w FILE` | Use audio from file |
| `-t FILE` | Use transcript from file |
| `-T FILE` | Use summary from file |
| `-k FILE` | Use keywords from file |
| `-i FILE` | Use image from file |

---

## Troubleshooting

- **No audio on macOS**: check microphone permission for Terminal.app.
- **No audio on RPi**: add your user to the `audio` group:
  `sudo usermod -a -G audio <username>`
- **ALSA/JACK error spam on RPi**: harmless — errors are suppressed internally.