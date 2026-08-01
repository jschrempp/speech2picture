"""Speech2Picture — turn spoken words into AI-generated images.

This is the entry-point module.  All application logic lives in ``src/``.

Usage::

    python3 pyspeech.py          # interactive menu
    python3 pyspeech.py -o -q     # once, with S3/QR
    python3 pyspeech.py -g        # kiosk mode
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import random
import select
import shutil
import string
import sys
import time

from PyQt6 import QtWidgets

from src.audio import record_audio
from src.config import (
    BLINK_FOR_AUDIO_CAPTURE,
    BLINK_STOP,
    BLINK1,
    BLINK3,
    BLINK4,
    BLINK_SLOW,
    LOOPS_MAX,
    ProcessStep,
    check_dependencies,
    config,
    detect_platform,
    gw,
    parse_command_line_args,
    voice_command_functions,
)
from src.display import (
    create_main_window,
    display_image,
    display_random_history_image,
    display_text_in_message_window,
    display_text_in_status_window,
    quit_button_pressed,
    update_main_window,
)
from src.hardware import (
    change_blink_rate,
    read_button,
    setup_hardware,
    shutdown_hardware,
)
from src.images import combine_images
from src.openai_client import (
    extract_abstract,
    generate_images,
    transcribe_audio,
)
from src.ui import create_message_window, create_status_window

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)
loggerTrace = logging.getLogger("Prompts")

logging.basicConfig(
    level=logging.WARNING,
    format=" %(asctime)s - %(levelname)s - %(message)s",
)

logToFile = logging.getLogger("s2plog")
logToFile.setLevel(logging.INFO)
_handler = logging.handlers.TimedRotatingFileHandler(
    "s2plog.log", when="midnight", interval=7, backupCount=10,
)
_handler.setFormatter(
    logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"),
)
logToFile.addHandler(_handler)

# ---------------------------------------------------------------------------
# Qt application (must exist before any widgets)
# ---------------------------------------------------------------------------

app = QtWidgets.QApplication(sys.argv)
app.setQuitOnLastWindowClosed(False)


# ---------------------------------------------------------------------------
# Pipeline: audio → picture
# ---------------------------------------------------------------------------

def audio_to_picture(
    settings,
    label_image,
    label_message,
    label_status,
    file_prefix,
    label_qr=None,
    label_qr_text=None,
) -> None:
    """Run one cycle: record → transcribe → keywords → images → display."""
    timestr: str = time.strftime("%Y%m%d-%H%M%S")
    sound_file: str = ""
    transcript: str = ""
    keywords: str = ""
    new_image_file: str = ""
    step: ProcessStep = settings.nextProcessStep

    print(f"nextProcessStep: {step}")

    # ---- Handle file-based input (CLI args) --------------------------------
    if step == ProcessStep.UseAudioFile:
        sound_file = settings.inputFileName
        logger.info("Using audio file: %s", settings.inputFileName)
        step = ProcessStep.Transcribe

    if step == ProcessStep.UseTranscriptFile:
        with open(settings.inputFileName, "r") as f:
            transcript = f.read()
        logger.info("Using transcript file: %s", settings.inputFileName)
        step = ProcessStep.Summarize

    if step == ProcessStep.UseSummaryFile:
        with open(settings.inputFileName, "r") as f:
            keywords = f.read()
        logger.info("Using summary file: %s", settings.inputFileName)
        step = ProcessStep.ImageCreate

    if step == ProcessStep.UseKeywordsFile:
        with open(settings.inputFileName, "r") as f:
            keywords = f.read()
        logger.info("Using abstract file: %s", settings.inputFileName)
        step = ProcessStep.ImageCreate

    if step == ProcessStep.UseImageFile:
        new_image_file = settings.inputFileName
        logger.info("Using image file: %s", settings.inputFileName)
        step = ProcessStep.DisplayImage

    # ---- Capture audio -----------------------------------------------------
    if step == ProcessStep.CaptureAudio:
        change_blink_rate(BLINK_FOR_AUDIO_CAPTURE)

        if config.isMacOS:
            os.system('say "Now recording."')

        display_text_in_message_window(
            "Speak Now\r\nYou have 10 seconds", label_message,
        )
        # Force the message window to render before blocking on audio I/O.
        # macOS gets a natural delay from `say`, but RPi needs explicit pump.
        for _ in range(5):
            QtWidgets.QApplication.processEvents()
            time.sleep(0.05)
        sound_file = record_audio(settings.duration)
        display_text_in_message_window(
            "Recording Complete, now analyzing", label_message,
        )
        if config.isMacOS:
            os.system('say "Recording complete."')

        if settings.isSaveFiles:
            dest: str = f"history/{file_prefix}{timestr}-recording.wav"
            shutil.copy(sound_file, dest)
            sound_file = dest

        change_blink_rate(BLINK_STOP)
        step = ProcessStep.Transcribe

    # ---- Transcribe --------------------------------------------------------
    if step == ProcessStep.Transcribe:
        change_blink_rate(BLINK1)

        transcript = transcribe_audio(sound_file)
        logToFile.info("Transcript: %s", transcript)

        if settings.isSaveFiles:
            path: str = f"history/{file_prefix}{timestr}-rawtranscript.txt"
            with open(path, "w") as f:
                f.write(transcript)

        msg: str = (
            f'I heard you say:\n\r "{transcript}" \n\r\n\r'
            "Now we wait for the images."
        )
        display_text_in_message_window(msg, label_message)
        gw.lastTranscript = transcript
        step = ProcessStep.Summarize

        change_blink_rate(BLINK_STOP)

    # ---- Voice command check -----------------------------------------------
    if transcript:
        for keyword, func in voice_command_functions.items():
            if keyword.lower() in transcript.lower():
                func(label_status)
                print("voice command done")
                step = ProcessStep.Done
                break

    # ---- Summarise (skipped for now) ---------------------------------------
    if step == ProcessStep.Summarize:
        step = ProcessStep.Keywords

    # ---- Keywords ----------------------------------------------------------
    if step == ProcessStep.Keywords:
        change_blink_rate(BLINK3)

        if transcript.count(" ") > 20:
            keywords = extract_abstract(transcript)
            logToFile.info("Keywords: %s", keywords)

            if settings.isSaveFiles:
                path = f"history/{file_prefix}{timestr}-keywords.txt"
                with open(path, "w") as f:
                    f.write(keywords)
        else:
            keywords = transcript

        change_blink_rate(BLINK_STOP)
        step = ProcessStep.ImageCreate

    # ---- Image generation --------------------------------------------------
    if step == ProcessStep.ImageCreate:
        change_blink_rate(BLINK4)

        try:
            image_urls, modifiers = generate_images(
                keywords,
                single_image=gw.single_image,
                progress_callback=display_text_in_message_window,
                progress_label=getattr(gw, "labelForMessage", None),
            )

            display_text_in_message_window(
                "Image generation complete, now combining", label_message,
            )

            new_image_file = combine_images(
                image_urls, keywords, timestr, file_prefix,
            )

            logger.debug("image file: %s", new_image_file)
            logToFile.info("Image file: %s", new_image_file)

            if gw.useS3:
                display_text_in_message_window(
                                "Uploading to S3...", label_message,
                            )
                from s3_and_qr import upload_to_s3_and_generate_qr
                upload_to_s3_and_generate_qr(
                    file_path=new_image_file, S3_dir="idleDisplayFiles",
                )

            change_blink_rate(BLINK_STOP)
            step = ProcessStep.DisplayImage

        except Exception as exc:
            logger.error("AI Image Error: %s", exc, exc_info=True)
            logToFile.info("AI Image Error: %s", exc, exc_info=True)

            error_text: str = str(exc).lower()
            msg: str

            if any(x in error_text for x in (
                "insufficient_quota", "rate limit", "error code: 429",
            )):
                msg = (
                    "OpenAI API quota/rate limit reached. "
                    "Please check your OpenAI billing/quota, then try again."
                )
            elif "content_policy_violation" in error_text:
                msg = "The AI Safety System rejected this prompt. Please try again."
            elif "safety" in error_text:
                msg = "The AI Safety System rejected this prompt. Please try again."
            elif "something went wrong" in error_text:
                msg = "Image generation failed. Please try again."
            elif "server had an error" in error_text:
                msg = "OpenAI had a server error. Please try again."
            else:
                msg = f'We had an error:\n\r "{exc}" \n\r\n\rPlease try again.'

            display_text_in_message_window(msg, label_message)
            for _ in range(100):
                QtWidgets.QApplication.processEvents()
                time.sleep(0.1)
            display_text_in_message_window()
            update_main_window()

            change_blink_rate(BLINK_STOP)
            step = ProcessStep.Done

    # ---- Display -----------------------------------------------------------
    if step == ProcessStep.DisplayImage:
        change_blink_rate(BLINK_SLOW)
        logger.info("Displaying image...")

        try:
            display_image(
                new_image_file, label_image, label_qr, label_qr_text,
            )
            display_text_in_message_window()
        except Exception as exc:
            logger.error(
                "Error displaying image: %s", new_image_file, exc_info=True,
            )

        update_main_window()
        change_blink_rate(BLINK_STOP)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Application entry point."""
    # ---- Platform detection (must be first — check_dependencies uses it) ----
    detect_platform()

    # ---- Startup checks ----------------------------------------------------
    if not check_dependencies():
        print("\nFATAL: One or more required dependencies are missing.")
        print("Please fix the errors above and try again.")
        sys.exit(1)

    # ---- Ensure directories exist ------------------------------------------
    for d in ("history", "errors", "idleDisplayFiles"):
        os.makedirs(d, exist_ok=True)

    # ---- Read / create config file -----------------------------------------
    if os.path.exists("s2pconfig.json"):
        with open("s2pconfig.json") as f:
            app_cfg = json.load(f)
    else:
        random_str: str = "".join(
            random.choices(string.ascii_uppercase, k=3),
        )
        app_cfg = {"Installation Id": random_str}
        with open("s2pconfig.json", "w") as f:
            json.dump(app_cfg, f)

    file_prefix: str = app_cfg["Installation Id"] + "-"

    # ---- Hardware setup ----------------------------------------------------
    setup_hardware()

    # ---- Parse command line ------------------------------------------------
    settings = parse_command_line_args()
    gw.useS3 = settings.useS3
    gw.kiosk_mode = settings.kiosk_mode
    gw.single_image = settings.single_image

    # ---- Create main window ------------------------------------------------
    label_image, label_qr, label_qr_text = create_main_window(
        settings.isUsingHardwareButtons,
    )
    display_random_history_image(label_image, label_qr, label_qr_text)

    # ---- Message window ----------------------------------------------------
    dlg_msg, label_msg = create_message_window()
    gw.windowForMessages = dlg_msg
    gw.labelForMessage = label_msg
    display_text_in_message_window()

    # ---- Status window -----------------------------------------------------
    dlg_sts, label_sts = create_status_window()
    gw.windowForStatus = dlg_sts
    display_text_in_status_window()

    # ---- Warm up audio driver on RPi ---------------------------------------
    record_audio(0.25)

    # ==================================================================
    # Main loop
    # ==================================================================

    settings.autoLoopDelay = 60
    random_display_mode: bool = True
    last_command_time: float = 0.0

    while not gw.isQuitting:
        execute_generation: bool = True

        if settings.nextProcessStep > ProcessStep.CaptureAudio:
            settings.numLoops = 1
            settings.autoLoopDelay = 1
        else:
            # ---- Terminal menu -------------------------------------------
            if not settings.isUsingHardwareButtons:
                print("\r\n\n\n")
                print("Commands:")
                print("   o: Once, record and display; default")
                print("   a: Auto mode, record, display, and loop")
                if not config.isMacOS:
                    print("   h: Hardware control")
                print("   q: Quit")

                input_command: str = ""
                while input_command == "" and not gw.isQuitting:
                    if select.select([sys.stdin], [], [], 0)[0]:
                        while sys.stdin in select.select(
                            [sys.stdin], [], [], 0,
                        )[0]:
                            input_command += sys.stdin.read(1)
                        input_command = input_command.strip()

                        random_display_mode = False
                        print(f"Command input: {input_command}")

                        if input_command == "h":
                            settings.isUsingHardwareButtons = True
                            print("\r\nHardware control enabled")

                        elif input_command == "q":
                            gw.isQuitting = True
                            settings.numLoops = 0
                            settings.autoLoopDelay = 0

                        elif input_command == "a":
                            settings.numLoops = LOOPS_MAX
                            print(f"Will loop: {settings.numLoops} times")

                        elif input_command == "o":
                            last_command_time = time.time()
                            settings.nextProcessStep = ProcessStep.CaptureAudio
                            settings.numLoops = 1
                            settings.autoLoopDelay = 0

                        elif input_command == "x":
                            last_command_time = time.time()
                            voice_command_functions["show status"](label_sts)
                            execute_generation = False

                        else:
                            print(f"No action input {input_command}")
                            input_command = ""

                    # Idle timeout → display random history image
                    if time.time() - last_command_time > 90:
                        last_command_time = time.time()
                        random_display_mode = True

                    if random_display_mode:
                        display_random_history_image(
                            label_image, label_qr, label_qr_text,
                        )

                    update_main_window()

            # ---- Hardware button mode (RPi) --------------------------------
            if settings.isUsingHardwareButtons:
                is_button_pressed: bool = False

                while not is_button_pressed:
                    update_main_window()

                    if read_button():
                        settings.isAudioKeywords = True
                        settings.numLoops = 1
                        is_button_pressed = True
                        last_command_time = time.time()
                        random_display_mode = False
                        logToFile.info("Button pressed")
                        settings.nextProcessStep = ProcessStep.CaptureAudio

                    else:
                        if time.time() - last_command_time > 90:
                            last_command_time = time.time()
                            random_display_mode = True

                    if random_display_mode:
                        display_random_history_image(
                            label_image, label_qr, label_qr_text,
                        )

        # ---- Set duration for audio-keywords mode --------------------------
        if settings.isAudioKeywords:
            settings.duration = 10

        # ---- Execute image generation --------------------------------------
        if execute_generation and not gw.isQuitting:
            for _ in range(settings.numLoops):
                if gw.isQuitting:
                    break
                try:
                    audio_to_picture(
                        settings, label_image, label_msg,
                        label_sts, file_prefix, label_qr, label_qr_text,
                    )
                except Exception as exc:
                    error_lower: str = str(exc).lower()
                    if any(x in error_lower for x in (
                        "insufficient_quota", "rate limit", "error code: 429",
                    )):
                        msg = (
                            "OpenAI API quota/rate limit reached. "
                            "Please check your OpenAI billing/quota."
                        )
                        display_text_in_message_window(msg, label_msg)
                        for _ in range(100):
                            QtWidgets.QApplication.processEvents()
                            time.sleep(0.1)
                        display_text_in_message_window()
                        update_main_window()
                        change_blink_rate(BLINK_STOP)
                        logger.warning("Quota/rate-limit handled.", exc_info=True)
                    else:
                        raise

                if not settings.isUsingHardwareButtons and settings.numLoops > 1:
                    print(f"delaying {settings.autoLoopDelay} seconds...")
                    time.sleep(settings.autoLoopDelay)

            last_command_time = time.time()
            random_display_mode = False

        update_main_window()

        # ---- Quit after file-based CLI run ---------------------------------
        if settings.nextProcessStep in {
            ProcessStep.UseAudioFile,
            ProcessStep.UseTranscriptFile,
            ProcessStep.UseSummaryFile,
            ProcessStep.UseKeywordsFile,
            ProcessStep.UseImageFile,
        }:
            gw.isQuitting = True
            print("Done with command line file argument. Pause for 15 seconds.")
            time.sleep(15)

    # ---- Cleanup -----------------------------------------------------------
    shutdown_hardware()
    app.quit()
    print("\r\n")


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logToFile.info("Starting Speech2Picture")

    try:
        main()
    except Exception as exc:
        print("\n\n\n")
        print(exc)
        print("\n\n\n")
        logToFile.error(exc, exc_info=True)

    sys.exit()