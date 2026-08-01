"""Display helpers: Qt window management, image display, popups.

These functions bridge the gap between the UI classes in ``src.ui`` and
the application logic.
"""

from __future__ import annotations

import datetime
import logging
import os
import random
import shutil
import socket
import time

from PIL import Image
from PyQt6 import QtCore, QtWidgets

from src.config import (
    config,
    gw,
    voice_command_functions,
)
from src.ui import (
    MainWindow,
    _pil_to_qpixmap,
    center_popup_over_parent,
    create_message_window,
    create_status_window,
)

logger = logging.getLogger(__name__)
logToFile = logging.getLogger("s2plog")


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

def create_main_window(using_hardware_button: bool) -> tuple:
    """Create the main window and return (image_label, qr_label, qr_text_label)."""
    win = MainWindow(
        using_hardware_button=using_hardware_button,
        version=config.version,
        use_s3=gw.useS3,
        kiosk_mode=gw.kiosk_mode,
    )
    win.show()
    QtWidgets.QApplication.processEvents()
    gw.windowMain = win
    return win.labelForImage, win.labelQRForImage, win.labelQRForImageText


def update_main_window() -> None:
    """Process pending Qt events."""
    if gw.isQuitting:
        return
    QtWidgets.QApplication.processEvents()


def quit_button_pressed() -> None:
    """Set quit flag — main loop exits naturally."""
    gw.isQuitting = True


# ---------------------------------------------------------------------------
# Popup windows (message / status)
# ---------------------------------------------------------------------------

def _create_msg_win():
    """Lazy-create the message popup."""
    if gw.windowForMessages is None:
        dlg, lbl = create_message_window(parent=gw.windowMain)
        gw.windowForMessages = dlg
        gw.labelForMessage = lbl
    return gw.windowForMessages, getattr(gw, "labelForMessage", None)


def _create_sts_win():
    """Lazy-create the status popup."""
    if gw.windowForStatus is None:
        dlg, lbl = create_status_window(parent=gw.windowMain)
        gw.windowForStatus = dlg
    return gw.windowForStatus


def display_text_in_status_window(
    message: str | None = None,
    label_to_use: object = None,
) -> None:
    """Show/hide the status popup."""
    if gw.isQuitting:
        return
    try:
        dlg = _create_sts_win()
        if message is None or label_to_use is None:
            if dlg is not None:
                dlg.hide()
        else:
            label_to_use.setText(message)
            center_popup_over_parent(dlg)
            dlg.show()

        QtWidgets.QApplication.processEvents()
        display_text_in_message_window()
        if gw.windowForMessages is not None and gw.windowForMessages.isVisible():
            QtWidgets.QApplication.processEvents()
    except Exception:
        logger.exception("Error in display_text_in_status_window")


def display_text_in_message_window(
    message: str | None = None,
    label_to_use: object = None,
) -> None:
    """Show/hide the message popup."""
    if gw.isQuitting:
        return
    try:
        dlg, _ = _create_msg_win()
        if message is None or label_to_use is None:
            if dlg is not None:
                dlg.hide()
        else:
            label_to_use.setText(message)
            label_to_use.repaint()  # Force synchronous paint — macOS compositor
            center_popup_over_parent(dlg)             # may defer async updates across processEvents().
            dlg.show()
        time.sleep(0.05)  # Allow Qt to process events and repaint the label
        QtWidgets.QApplication.processEvents()
        QtCore.QCoreApplication.processEvents() # needed for macOS to force repaint of the label
    except Exception:
        logger.exception("Error in display_text_in_message_window")


# ---------------------------------------------------------------------------
# Image display
# ---------------------------------------------------------------------------

def display_image(
    image_path: str,
    label: object = None,
    label_qr: object = None,
    label_qr_text: object = None,
) -> object | None:
    """Display an image in the main window (on *label*)."""
    if gw.isQuitting:
        return None

    logger.debug("display_image: %s", image_path)
    logToFile.debug("display_image: %s", image_path)

    if label is None:
        logger.warning("label is None in display_image")
        return None

    skip_qr: bool = False

    try:
        img = Image.open(image_path)
        pixmap = _pil_to_qpixmap(img)

        QtWidgets.QApplication.processEvents()
        available_size = label.contentsRect().size()
        if available_size.width() <= 1 or available_size.height() <= 1:
            available_size = label.size()
        min_size = label.minimumSize()
        available_size = QtCore.QSize(
            max(available_size.width(), min_size.width()),
            max(available_size.height(), min_size.height()),
        )

        scaled_pixmap = pixmap.scaled(
            available_size,
            QtCore.Qt.AspectRatioMode.KeepAspectRatio,
            QtCore.Qt.TransformationMode.SmoothTransformation,
        )
        label.setPixmap(scaled_pixmap)

        update_main_window()
    except Exception as exc:
        logger.error("Error with image file: %s", image_path)
        logger.error(str(exc))
        skip_qr = True

    # -- QR overlay ------------------------------------------------------------
    if label_qr and not skip_qr and gw.useS3:
        qr_file: str = image_path.replace("-image.png", "-s3_url.jpg")
        if os.path.exists(qr_file):
            qr_img = Image.open(qr_file)
            new_w = scaled_pixmap.width() if "scaled_pixmap" in dir() else 100
            new_h = scaled_pixmap.height() if "scaled_pixmap" in dir() else 100
            qr_size: int = int(0.15 * min(new_w, new_h))
            qr_img = qr_img.resize((qr_size, qr_size), Image.NEAREST)

            label_qr.setPixmap(_pil_to_qpixmap(qr_img))
            label_qr.setFixedSize(qr_size, qr_size)

            if label_qr_text:
                label_qr_text.setFixedWidth(qr_size)

            container = label_qr.parentWidget()
            if container:
                container.adjustSize()
                container.move(
                    label.width() - qr_size,
                    label.height() - container.height(),
                )
                container.show()
                container.raise_()
        else:
            container = label_qr.parentWidget() if label_qr else None
            if container:
                container.hide()
    elif label_qr:
        container = label_qr.parentWidget()
        if container:
            container.hide()

    update_main_window()
    return label


def display_random_history_image(
    label_for_image: object,
    label_qr: object = None,
    label_qr_text: object = None,
) -> None:
    """Display a random image from ``idleDisplayFiles/``, throttled to 15 s."""
    if not hasattr(display_random_history_image, "last_time"):
        display_random_history_image.last_time = 0.0  # type: ignore[attr-defined]
    if not hasattr(display_random_history_image, "idle_files"):
        display_random_history_image.idle_files: list[str] = []  # type: ignore[attr-defined]

    if time.time() - display_random_history_image.last_time > 15:  # type: ignore[attr-defined]
        display_random_history_image.last_time = time.time()  # type: ignore[attr-defined]

        idle_folder: str = "./idleDisplayFiles"

        # Refill the list when exhausted
        if not display_random_history_image.idle_files:  # type: ignore[attr-defined]
            logger.debug("Refilling idle files list from %s", idle_folder)
            try:
                all_files = os.listdir(idle_folder)
            except FileNotFoundError:
                logger.warning("Idle folder not found: %s", idle_folder)    
                return
            display_random_history_image.idle_files = [  # type: ignore[attr-defined]
                f for f in all_files if f.endswith(".png")
            ]
            if not display_random_history_image.idle_files:  # type: ignore[attr-defined]
                logger.warning("No PNG files found in %s", idle_folder) 
                return
            random.shuffle(display_random_history_image.idle_files)  # type: ignore[attr-defined]

        # Pop the next image so it won't repeat until the list is exhausted
        next_file = display_random_history_image.idle_files.pop(0)  # type: ignore[attr-defined]
        display_image(
            f"{idle_folder}/{next_file}",
            label_for_image, label_qr, label_qr_text,
        )


# ---------------------------------------------------------------------------
# Status / command overlays
# ---------------------------------------------------------------------------

def show_status(label_for_status: object = None) -> None:
    """Show system status in the status popup."""
    # IP address
    ip_addr: str = ""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(1)
            sock.connect(("8.8.8.8", 80))
            ip_addr = sock.getsockname()[0]
    except OSError:
        pass

    if not ip_addr:
        try:
            ip_addr = os.popen("hostname -I").read().strip().split(" ")[0]
        except Exception:
            ip_addr = ""

    ip_msg: str = f"IP Address: {ip_addr}" if ip_addr else "IP Address: unavailable"
    print(ip_msg)

    directory: str = "history"
    png_files: list[str] = []
    history_count: int = 0
    for dirpath, _dirnames, files in os.walk(directory):
        history_count += len(files)
        for f in files:
            if f.lower().endswith(".png"):
                fp: str = os.path.join(dirpath, f)
                if os.path.isfile(fp):
                    png_files.append(fp)

    history_msg: str = f"Number of files in history: {history_count}"
    print(history_msg)

    oldest_msg: str = "Oldest file in history: none"
    if png_files:
        existing = [f for f in png_files if os.path.exists(f)]
        if existing:
            oldest = min(existing, key=os.path.getctime)
            dt = datetime.datetime.fromtimestamp(os.path.getctime(oldest), tz=datetime.timezone.utc)
            oldest_msg = f"Oldest file in history: {dt:%m-%d-%Y}"

    print(oldest_msg)

    idle_count: int = 0
    try:
        idle_count = len(os.listdir("idleDisplayFiles"))
    except FileNotFoundError:
        pass

    _total, _used, free = shutil.disk_usage("/")
    free_gb: str = f"{free / (1024 ** 3):.2f} GB"

    msg: str = (
        f"Status:\n\n{ip_msg}\n{history_msg}\n{oldest_msg}\n"
        f"Number of files in idleDisplayFiles: {idle_count}\n"
        f"Free Space: {free_gb}"
    )

    display_text_in_status_window(msg, label_for_status)
    time.sleep(10)
    display_text_in_status_window()


def show_commands(label_for_status: object = None) -> None:
    """Show valid spoken commands in the status popup."""
    msg: str = (
        "Valid Spoken Commands:\n\n"
        "    show status\n"
        "    show commands\n"
    )
    display_text_in_status_window(msg, label_for_status)
    time.sleep(10)
    display_text_in_status_window()


# Register voice commands
voice_command_functions["show status"] = show_status
voice_command_functions["show commands"] = show_commands