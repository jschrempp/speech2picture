"""Platform-abstracted audio recording.

Provides ``record_audio(duration_sec) -> str`` that returns the path to a
WAV file.  On macOS (sounddevice/soundfile) and on RPi (pyaudio/wave).
"""

from __future__ import annotations

import logging
import os

from src.config import config

logger = logging.getLogger(__name__)


def record_audio(duration_sec: float) -> str:
    """Record *duration_sec* seconds from the default microphone.

    Returns the path to ``recording.wav``.
    """
    sound_filename: str = "recording.wav"

    # Remove any stale recording
    try:
        os.remove(sound_filename)
    except FileNotFoundError:
        pass
    except Exception as exc:
        logger.warning("Failed to remove old recording: %s", exc)

    try:
        if config.isMacOS:
            _record_macos(duration_sec, sound_filename)
        elif config.isRPi:
            _record_rpi(duration_sec, sound_filename)
        else:
            raise RuntimeError("Unsupported platform for audio recording")
    except Exception as exc:
        logger.error("Failed to record audio: %s", exc)
        raise RuntimeError(f"Audio recording failed: {exc}") from exc

    logger.info("Successfully recorded audio to %s", sound_filename)
    return sound_filename


# ---------------------------------------------------------------------------
# macOS implementation
# ---------------------------------------------------------------------------

def _record_macos(duration_sec: float, filename: str) -> None:
    import sounddevice
    import soundfile

    sample_rate: int = int(
        sounddevice.query_devices(1)["default_samplerate"]
    )
    channels: int = 1

    logger.debug("sample_rate: %d; channels: %d", sample_rate, channels)
    logger.info("Recording %.1f seconds...", duration_sec)

    recording = sounddevice.rec(
        int(duration_sec * sample_rate),
        samplerate=sample_rate,
        channels=channels,
    )
    sounddevice.wait()
    soundfile.write(filename, recording, sample_rate)


# ---------------------------------------------------------------------------
# Raspberry Pi implementation
# ---------------------------------------------------------------------------

def _record_rpi(duration_sec: float, filename: str) -> None:
    import wave
    from ctypes import (
        CFUNCTYPE,
        c_char_p,
        c_int,
        cdll,
    )

    import pyaudio  # noqa: F821

    # Silence ALSA error messages
    ERROR_HANDLER_FUNC = CFUNCTYPE(None, c_char_p, c_int, c_char_p, c_int,
                                     c_char_p)

    def _py_error_handler(filename, line, function, err, fmt):
        pass

    c_error_handler = ERROR_HANDLER_FUNC(_py_error_handler)
    asound = cdll.LoadLibrary("libasound.so")
    asound.snd_lib_error_set_handler(c_error_handler)

    pa = pyaudio.PyAudio()
    asound.snd_lib_error_set_handler(None)

    stream = pa.open(
        format=pyaudio.paInt16,
        channels=1,
        rate=44100,
        input=True,
        frames_per_buffer=1024,
    )

    with wave.open(filename, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(pa.get_sample_size(pyaudio.paInt16))
        wf.setframerate(44100)

        try:
            for _ in range(int(44100 / 1024 * duration_sec)):
                data = stream.read(1024)
                wf.writeframes(data)
        finally:
            stream.close()