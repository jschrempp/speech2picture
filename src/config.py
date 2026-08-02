"""Central configuration, constants, and CLI parsing for Speech2Picture.

All shared state lives here.  The `config` and `gw` singletons are the
single source of truth for the application.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
from enum import IntEnum

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ProcessStep(IntEnum):
    """Pipeline steps.  CLI args can jump into the middle of the process."""
    NoneSpecified = 0
    CaptureAudio = 1
    Audio = 2
    Transcribe = 3
    Summarize = 4
    Keywords = 5
    ImageCreate = 6
    Done = 7
    UseAudioFile = 8
    UseTranscriptFile = 9
    UseSummaryFile = 10
    UseKeywordsFile = 11
    UseImageFile = 12
    DisplayImage = 13


# ---------------------------------------------------------------------------
# Config singleton (replaces the old Config class inline in pyspeech.py)
# ---------------------------------------------------------------------------

class Config:
    """Central configuration class.

    Thread safety: All attributes are written once at startup (main thread)
    and read-only thereafter.  The ``_lock`` is available for any future
    mutable state that needs cross-thread protection.
    """
    def __init__(self) -> None:
        self.isMacOS: bool = False
        self.isRPi: bool = False
        self.version: str = "2.2"
        self.useS3: bool = False
        self.kiosk_mode: bool = False
        self.single_image: bool = False
        self.isQuitting: bool = False

        # Window references (only accessed from the main / Qt thread)
        self.windowMain: object | None = None
        self.windowForMessages: object | None = None
        self.windowForStatus: object | None = None

        # Lock for protecting any future mutable shared state
        self._lock = threading.Lock()


config = Config()


# ---------------------------------------------------------------------------
# Global window variables (used by display & main loop)
# ---------------------------------------------------------------------------


class GlobalWindowVars:
    windowMain: object | None = None
    windowForMessages: object | None = None
    windowForStatus: object | None = None
    isQuitting: bool = False
    goTriggered: bool = False
    lastTranscript: str = ""


gw = GlobalWindowVars()


# ---------------------------------------------------------------------------
# Runtime arguments (populated by parse_command_line_args)
# ---------------------------------------------------------------------------

class RuntimeArgs:
    duration: int = 120
    isUsingHardwareButtons: bool = False
    isAudioKeywords: bool = False
    numLoops: int = 1
    autoLoopDelay: int = 0
    nextProcessStep: ProcessStep = ProcessStep.CaptureAudio
    inputFileName: str | None = None
    isSaveFiles: bool = False
    useS3: bool = True
    kiosk_mode: bool = False
    single_image: bool = False


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LOOPS_MAX: int = 10

PROMPT_FOR_ABSTRACTION: str = (
    "In 15 words or less, what are the most interesting concepts in the "
    "following text expressing the answer as a noun phrase, but not in a "
    "full sentence "
)

IMAGE_MODIFIERS: list[str] = [
    "as a painting in the style of cubism",
    "as a watercolor in the style of surrealism",
    "as a sketch in the style of surrealism",
    "as a vivid color painting in the style of impressionism",
    "as a painting in the style of the French Breakthrough",
    "as a painting in the style of Surreal mathematical art, paradox art, impossible architecture, op-art", # escher, MC Escher, Salvador Dali, Rene Magritte
    "in the style of mathematical graphic art",
    "in the style of the Dutch Golden Age, Baroque painting using intense chiaroscuro, psychological realism, Dominated by rich earthy tones",
    "in the style of the Italian Renaissance using chiaroscuro, sfumato, dramatic lighting, realistic anatomy, rich color palette",
    "in the style of the German Expressionist movement",
    "as a photograph in the style of purist landscape photography",
    "as a painting in the style of American Realism",
    "as a painting in the style of exaggerated realism",
    "in the style of steam punk",
    "in the style of abstract expressionism",
    "in the style of pop art",
    "in the style of impressionism",
    "in the style of Art Nouveau",
    "as a watercolor",
    "as a stained glass window",
    "as a pencil sketch",
    "emphasizing material transparency, natural geometry, and intricate shadows", # ruth asawa
    "with SAMO graffiti aesthetic, primitive abstraction, and poetic symbolism", # jean-michel basquiat
    "Biomorphic Surrealism, organic abstraction, Catalan modernist avant-garde", # joan miró

]

# Allow user override via ARTISTS_USER.txt
if os.path.exists("ARTISTS_USER.txt"):
    prefix = "in the style of "
    new_mods: list[str] = []
    with open("ARTISTS_USER.txt", "r") as file:
        for line in file:
            new_mods.append(prefix + str(line.strip()))
    if new_mods:
        IMAGE_MODIFIERS = new_mods

# LED blink tuple constants (onTime, offTime)
BLINK_FAST: tuple[float, float] = (0.1, 0.1)
BLINK_SLOW: tuple[float, float] = (0.5, 0.5)
BLINK_FOR_AUDIO_CAPTURE: tuple[float, float] = (0.05, 0.05)
BLINK1: tuple[float, float] = (0.5, 0.2)
BLINK2: tuple[float, float] = (0.4, 0.2)
BLINK3: tuple[float, float] = (0.3, 0.2)
BLINK4: tuple[float, float] = (0.2, 0.2)
BLINK_STOP: tuple[int, int] = (-1, -1)
BLINK_DIE: tuple[int, int] = (-2, -2)

# GPIO pin constants (RPi only, but safe to define everywhere)
LED_RED: int = 8
BUTTON_GO: int = 10

# S3 bucket name
S3_BUCKET_TO_STORE_IN: str = "amzn-s3-speech2picture"

# Voice command registry — populated by display module
voice_command_functions: dict[str, object] = {}


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------

def parse_command_line_args() -> RuntimeArgs:
    """Parse sys.argv and return a populated RuntimeArgs."""
    rtn = RuntimeArgs()

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-s", "--savefiles", help="save the files", action="store_true",
    )
    parser.add_argument(
        "-d", "--debug", help="0:info, 1:prompts, 2:responses", type=int,
    )
    parser.add_argument(
        "-w", "--wav", help="use audio from file", type=str, default=0,
    )
    parser.add_argument(
        "-t", "--transcript", help="use transcript from file", type=str,
        default=0,
    )
    parser.add_argument(
        "-T", "--summary", help="use summary from file", type=str, default=0,
    )
    parser.add_argument(
        "-k", "--keywords", help="use keywords from file", type=str,
        default=0,
    )
    parser.add_argument(
        "-i", "--image", help="use image from file", type=str, default=0,
    )
    parser.add_argument(
        "-o", "--onlykeywords",
        help="use audio directly without extracting keywords",
        action="store_true",
    )
    parser.add_argument(
        "-g", "--gokiosk", help="jump into Kiosk mode", action="store_true",
    )
    parser.add_argument(
        "-q", "--use_s3",
        help="try to store image files to AWS S3, and generate QR codes",
        action="store_true",
    )
    parser.add_argument(
        "-m", "--mono_image",
        help="create a single, large image using dall-e-3",
        action="store_true",
    )
    args = parser.parse_args()

    # -- debug levels ----------------------------------------------------------
    loggerTrace = logging.getLogger("Prompts")

    logging.root.setLevel(logging.INFO)
    if args.debug == 1:
        logging.root.setLevel(logging.DEBUG)
        logging.debug("Debug level set to show prompts")
    elif args.debug == 2:
        logging.root.setLevel(logging.DEBUG)
        loggerTrace.setLevel(logging.DEBUG)
        logging.debug("Debug level set to show prompts and response JSON")

    # -- S3 -------------------------------------------------------------------
    if args.use_s3:
        rtn.useS3 = True
        print("\r\nUsing AWS S3 for image storage and QR code generation\r\n")
    else:
        rtn.useS3 = False

    # -- Single / mono image --------------------------------------------------
    rtn.single_image = bool(args.mono_image)

    # -- Kiosk / hardware buttons ---------------------------------------------
    rtn.isUsingHardwareButtons = False
    if args.gokiosk:
        print("\r\nKiosk mode enabled\r\n")
        rtn.isUsingHardwareButtons = True
        rtn.isAudioKeywords = True
        rtn.numLoops = 1
        rtn.autoLoopDelay = 0
        rtn.nextProcessStep = ProcessStep.NoneSpecified
        rtn.kiosk_mode = True
    else:
        rtn.kiosk_mode = False
        rtn.nextProcessStep = ProcessStep.NoneSpecified

        # Check in reverse order so the latest applicable step wins.
        if args.image != 0:
            rtn.nextProcessStep = ProcessStep.UseImageFile
            rtn.inputFileName = args.image
        elif args.keywords != 0:
            rtn.nextProcessStep = ProcessStep.UseKeywordsFile
            rtn.inputFileName = args.keywords
        elif args.summary != 0:
            rtn.nextProcessStep = ProcessStep.UseSummaryFile
            rtn.inputFileName = args.summary
        elif args.transcript != 0:
            rtn.nextProcessStep = ProcessStep.UseTranscriptFile
            rtn.inputFileName = args.transcript
        elif args.wav != 0:
            rtn.nextProcessStep = ProcessStep.UseAudioFile
            rtn.inputFileName = args.wav

        rtn.isAudioKeywords = bool(args.onlykeywords)
        if rtn.isAudioKeywords:
            rtn.duration = 10

        rtn.isSaveFiles = bool(args.savefiles)

    return rtn


# ---------------------------------------------------------------------------
# Platform detection helper
# ---------------------------------------------------------------------------

def detect_platform() -> None:
    """Set ``config.isMacOS`` / ``config.isRPi`` based on the current host."""
    if sys.platform == "darwin":
        config.isMacOS = True
    else:
        try:
            with open("/proc/device-tree/model", "r") as f:
                config.isRPi = "raspberry pi" in f.read().lower()
        except Exception:
            config.isRPi = False
        print(
            f"Running on {'Raspberry Pi' if config.isRPi else 'non-RPi Linux'}"
        )


# ---------------------------------------------------------------------------
# Dependency checker
# ---------------------------------------------------------------------------

def check_dependencies() -> bool:
    """Check for required hardware and software dependencies at startup.

    Returns ``True`` if everything critical is available.
    """
    import importlib.util

    all_ok: bool = True
    issues: list[str] = []
    warnings: list[str] = []

    # --- OpenAI API key ----------------------------------------------------
    api_key: str = os.environ.get("OPENAI_API_KEY", "")
    secret_key_file: str = "creepy photo secret key"
    if not api_key and os.path.exists(secret_key_file):
        try:
            with open(secret_key_file, "r") as f:
                api_key = f.read().strip()
        except Exception:
            pass
    if not api_key:
        issues.append(
            "OpenAI API key not found.  Set the OPENAI_API_KEY environment "
            "variable or create a file named 'creepy photo secret key' "
            "containing your key."
        )
        all_ok = False

    # --- Pillow ------------------------------------------------------------
    if importlib.util.find_spec("PIL") is None:
        issues.append("Pillow is not installed.  Run: pip install Pillow")
        all_ok = False

    # --- PyQt6 -------------------------------------------------------------
    if importlib.util.find_spec("PyQt6") is None:
        issues.append("PyQt6 is not installed.  Run: pip install PyQt6")
        all_ok = False

    # --- Platform-specific audio -------------------------------------------
    if config.isMacOS:
        if importlib.util.find_spec("sounddevice") is None:
            issues.append(
                "sounddevice is not installed.  Run: pip install sounddevice"
            )
            all_ok = False
        if importlib.util.find_spec("soundfile") is None:
            issues.append(
                "soundfile is not installed.  Run: pip install soundfile"
            )
            all_ok = False
    elif config.isRPi:
        if importlib.util.find_spec("pyaudio") is None:
            issues.append(
                "pyaudio is not installed.  Run: pip install pyaudio"
            )
            all_ok = False
        if importlib.util.find_spec("RPi") is None:
            issues.append(
                "RPi.GPIO is not installed.  Run: pip install RPi.GPIO"
            )
            all_ok = False

    # --- Optional: S3 / QR --------------------------------------------------
    if importlib.util.find_spec("s3_and_qr") is None:
        warnings.append(
            "s3_and_qr module not found.  S3 upload and QR code features "
            "will be unavailable."
        )

    for w in warnings:
        print(f"WARNING: {w}")
    for i in issues:
        print(f"ERROR: {i}")

    return all_ok