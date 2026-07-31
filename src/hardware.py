"""Raspberry Pi hardware integration: GPIO, LED blink thread.

This module is a no-op on non-RPi platforms.  Call ``setup_hardware()``
once at startup to initialise GPIO and launch the LED thread.
"""

from __future__ import annotations

import logging
import threading
import time
from queue import Empty, Queue

from src.config import (
    BLINK_DIE,
    BUTTON_GO,
    LED_RED,
    config,
)

logger = logging.getLogger(__name__)

# Module-level references — set by setup_hardware()
qBlinkControl: Queue | None = None
led_thread: threading.Thread | None = None


def setup_hardware() -> None:
    """Initialise GPIO pins and start the LED blink thread (RPi only)."""
    global qBlinkControl, led_thread

    if not config.isRPi:
        return

    # --------- Raspberry Pi specific code ---------------------------------
    logger.info("Setting up GPIO pins")

    # Deferred imports so non-RPi platforms never touch RPi.GPIO.
    import RPi.GPIO as GPIO  # noqa: F811

    GPIO.setmode(GPIO.BOARD)

    GPIO.setup(LED_RED, GPIO.OUT, initial=GPIO.LOW)
    GPIO.setup(BUTTON_GO, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    def _blink_led(q: Queue) -> None:
        """Thread target — reads (onTime, offTime) tuples from the queue."""
        logger.info("Starting LED thread")
        is_blinking: bool = False
        GPIO.output(LED_RED, GPIO.LOW)

        while True:
            try:
                blink_time = q.get_nowait()
            except queue.Empty:
                blink_time = None

            if blink_time is None:
                pass
            elif blink_time[0] == -2:          # BLINK_DIE
                logger.info("LED thread dying")
                break
            elif blink_time[0] == -1:          # BLINK_STOP
                GPIO.output(LED_RED, GPIO.LOW)
                is_blinking = False
            else:
                on_time, off_time = blink_time
                is_blinking = True

            if is_blinking:
                GPIO.output(LED_RED, GPIO.HIGH)
                time.sleep(on_time)
                GPIO.output(LED_RED, GPIO.LOW)
                time.sleep(off_time)

    logger.info("Creating LED thread")
    qBlinkControl = Queue()
    led_thread = threading.Thread(
        target=_blink_led, args=(qBlinkControl,), daemon=True,
    )
    led_thread.start()


def change_blink_rate(blink_rate: tuple[float, float]) -> None:
    """Post a new blink rate to the LED thread.

    On non-RPi platforms this is a no-op.
    """
    if qBlinkControl is not None:
        qBlinkControl.put(blink_rate)


def read_button() -> bool:
    """Return True if the hardware GO button is currently pressed.

    Always returns False on non-RPi platforms.
    """
    if not config.isRPi:
        return False
    import RPi.GPIO as GPIO  # noqa: F811
    return GPIO.input(BUTTON_GO) == GPIO.LOW


def shutdown_hardware() -> None:
    """Stop the LED thread and clean up GPIO pins."""
    global led_thread

    if not config.isRPi:
        return

    import RPi.GPIO as GPIO  # noqa: F811

    change_blink_rate(BLINK_DIE)
    if led_thread is not None:
        led_thread.join()
        led_thread = None
    GPIO.cleanup()
    logger.info("GPIO cleaned up")