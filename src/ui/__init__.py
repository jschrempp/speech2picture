"""Qt UI Designer integration for Speech2Picture.

Uses pyuic6-generated .py files from the .ui sources.  If a .ui file is
newer than its .py counterpart, pyuic6 is invoked automatically at startup
so the .ui files remain the single source of truth.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from io import BytesIO
from pathlib import Path
from typing import Optional, Tuple

from PIL import Image
from PyQt6 import QtWidgets, QtCore, QtGui
from PyQt6.QtWidgets import QDialog, QLabel, QMainWindow, QPushButton

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Path helper
# ---------------------------------------------------------------------------
_UI_DIR = Path(__file__).resolve().parent


def _ui_path(filename: str) -> str:
    return str(_UI_DIR / filename)


# ---------------------------------------------------------------------------
# Auto-generate .py from .ui if needed
# ---------------------------------------------------------------------------

def _ensure_ui_compiled(ui_name: str) -> None:
    """Run pyuic6 if the .ui file is newer than the .py file."""
    ui_path = _UI_DIR / f"{ui_name}.ui"
    py_path = _UI_DIR / f"{ui_name}.py"

    if not ui_path.exists():
        return  # nothing to compile

    if py_path.exists() and py_path.stat().st_mtime >= ui_path.stat().st_mtime:
        return  # .py is up to date

    # Find pyuic6 — try venv first, then PATH
    pyuic = None
    venv_bin = Path(sys.executable).parent / "pyuic6"
    if venv_bin.exists():
        pyuic = str(venv_bin)
    else:
        # On Debian/Raspbian, pyuic6 may be at /usr/bin/pyuic6
        for candidate in ("/usr/bin/pyuic6", "pyuic6"):
            try:
                subprocess.run([candidate, "--version"],
                               capture_output=True, timeout=5)
                pyuic = candidate
                break
            except (FileNotFoundError, subprocess.TimeoutExpired):
                continue

    if pyuic is None:
        logger.warning(
            "pyuic6 not found — cannot compile %s. "
            "Install pyqt6-dev-tools (apt) or PyQt6 (pip).", ui_name,
        )
        return

    logger.info("Compiling %s.ui → %s.py", ui_name, ui_name)
    result = subprocess.run(
        [pyuic, str(ui_path), "-o", str(py_path)],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        logger.error("pyuic6 failed for %s: %s", ui_name, result.stderr)
        raise RuntimeError(f"Failed to compile {ui_name}.ui: {result.stderr}")


# Compile all three .ui files on import
_ensure_ui_compiled("main_window")
_ensure_ui_compiled("message_dialog")
_ensure_ui_compiled("status_dialog")

# Now safe to import the generated modules — or fall back to uic.loadUi
try:
    from src.ui.main_window import Ui_MainWindow
    from src.ui.message_dialog import Ui_MessageDialog
    from src.ui.status_dialog import Ui_StatusDialog
    _use_generated = True
except ImportError:
    # .py files not generated and pyuic6 not available — use uic at runtime
    try:
        from PyQt6 import uic  # noqa: F811
        _use_generated = False
    except ImportError:
        raise ImportError(
            "Cannot load UI files.  Install pyqt6-dev-tools:\n"
            "    sudo apt install pyqt6-dev-tools\n"
            "or (pip):\n"
            "    pip install PyQt6"
        )


# ===================================================================
# Main window
# ===================================================================

class MainWindow(QMainWindow):
    """Main application window loaded from main_window.ui."""

    # These are set by Ui_MainWindow.setupUi()
    labelInstructions: QLabel
    labelForImage: QLabel
    labelQR: QLabel
    labelQRText: QLabel
    labelCredits: QLabel
    labelCommandHint: QLabel
    buttonQuit: QPushButton
    buttonWindow: QPushButton

    qrContainer: Optional[QtWidgets.QWidget] = None
    labelQRForImage: Optional[QLabel] = None
    labelQRForImageText: Optional[QLabel] = None

    _image_pane_ratio: float = 0.52
    _instruction_font_max_px: int = 48
    _instruction_font_min_px: int = 24
    _instruction_font_family: str = ""

    def __init__(self, using_hardware_button: bool, version: str,
                 use_s3: bool, kiosk_mode: bool, parent=None):
        super().__init__(parent)
        self._using_hardware_button = using_hardware_button
        self._version = version
        self._use_s3 = use_s3
        self._kiosk_mode = kiosk_mode
        self._load_ui()
        self._configure_widgets()
        self._create_qr_overlay()
        self._configure_visibility()
        self._configure_geometry()

    def _load_ui(self) -> None:
        """Load the UI from the generated .py file, or fall back to uic."""
        if _use_generated:
            self.ui = Ui_MainWindow()
            self.ui.setupUi(self)
            # Copy widget references from self.ui to self so the rest of
            # the code can access them as self.labelInstructions etc.
            for attr in dir(self.ui):
                if not attr.startswith("_"):
                    obj = getattr(self.ui, attr, None)
                    if isinstance(obj, QtWidgets.QWidget):
                        setattr(self, attr, obj)
            # The generated code names the grid layout "mainGrid"
            self._main_grid = self.ui.mainGrid
        else:
            from PyQt6 import uic
            uic.loadUi(_ui_path("main_window.ui"), self)
            self._main_grid = self.centralWidget().layout()
        self._configure_grid()

    def _configure_grid(self) -> None:
        for col in range(8):
            self._main_grid.setColumnStretch(
                col, 1 if col < 6 else (14 if col == 6 else 0))
        for row, stretch in ((0, 3), (1, 3), (2, 1), (3, 1), (4, 1), (5, 1)):
            self._main_grid.setRowStretch(row, stretch)
        self._main_grid.setColumnMinimumWidth(2, 100)
        self._main_grid.setColumnMinimumWidth(3, 100)

        preferred = ["Noto Sans", "DejaVu Sans", "Verdana", "Arial", "Helvetica"]
        available = set(QtGui.QFontDatabase.families())
        self._instruction_font_family = next(
            (f for f in preferred if f in available),
            self.labelInstructions.font().family(),
        )

    def _configure_widgets(self) -> None:
        hint = self.labelCommandHint.text()
        self.labelCommandHint.setText(f"{hint}  v: {self._version}")
        self.buttonWindow.clicked.connect(self._on_exit_fullscreen)
        self.buttonQuit.clicked.connect(self._on_quit)

        qr_path = Path("S2PQR.png")
        if qr_path.exists():
            pix = QtGui.QPixmap(str(qr_path))
            pix = pix.scaled(150, 150, QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                             QtCore.Qt.TransformationMode.SmoothTransformation)
            self.labelQR.setPixmap(pix)

    def _create_qr_overlay(self) -> None:
        self.labelQRForImage = QLabel(self.labelForImage)
        self.labelQRForImage.setStyleSheet("background-color: #000000; border: none;")
        self.labelQRForImage.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)

        self.labelQRForImageText = QLabel("scan to download image", self.labelForImage)
        self.labelQRForImageText.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.labelQRForImageText.setStyleSheet(
            "font: 10px Helvetica; color: #000000; background-color: #FFFFFF;")

        self.qrContainer = QtWidgets.QWidget(self.labelForImage)
        self.qrContainer.setStyleSheet("background-color: #FFFFFF;")
        qr_layout = QtWidgets.QVBoxLayout(self.qrContainer)
        qr_layout.setContentsMargins(0, 0, 0, 0)
        qr_layout.setSpacing(0)
        qr_layout.addWidget(self.labelQRForImage)
        qr_layout.addWidget(self.labelQRForImageText)
        self.qrContainer.hide()

    def _configure_visibility(self) -> None:
        if self._using_hardware_button:
            self.buttonQuit.hide()
        if not self._kiosk_mode:
            self.buttonWindow.hide()

    def _configure_geometry(self) -> None:
        if self._kiosk_mode:
            import time
            time.sleep(4.0)
            self.showFullScreen()
        else:
            screen = QtWidgets.QApplication.primaryScreen().availableGeometry()
            w = int(screen.width() * 0.95)
            h = int(screen.height() * 0.95)
            x = int(screen.width() * 0.025)
            y = int(screen.height() * 0.025)
            self.setGeometry(x, y, w, h)

        self._apply_image_pane_width()
        self._fit_instructions_font()
        QtCore.QTimer.singleShot(0, self._apply_image_pane_width)
        QtCore.QTimer.singleShot(0, self._fit_instructions_font)

    def _apply_image_pane_width(self) -> None:
        margins = self._main_grid.contentsMargins()
        available = self.width() - margins.left() - margins.right()
        ratio = max(0.15, min(0.85, self._image_pane_ratio))
        target = int(max(0, available) * ratio)
        self._main_grid.setColumnMinimumWidth(6, max(400, target))
        other_total_stretch = 7
        image_stretch = max(1, int(round((other_total_stretch * ratio) / (1.0 - ratio))))
        self._main_grid.setColumnStretch(6, image_stretch)

    def _set_instructions_font_size(self, size_px: int) -> None:
        self.labelInstructions.setStyleSheet(
            f"font-size: {size_px}px; font-weight: 700; "
            f"font-family: '{self._instruction_font_family}'; "
            "color: #FFFFFF; background-color: #52837D;"
        )

    def _fit_instructions_font(self) -> None:
        text = self.labelInstructions.text()
        if not text:
            return
        rect = self.labelInstructions.contentsRect()
        if rect.width() <= 0 or rect.height() <= 0:
            return
        fit_flags = int(QtCore.Qt.TextFlag.TextWordWrap | QtCore.Qt.TextFlag.TextExpandTabs)
        best_size = self._instruction_font_min_px
        for size_px in range(self._instruction_font_max_px,
                             self._instruction_font_min_px - 1, -1):
            font = QtGui.QFont(self._instruction_font_family)
            font.setPixelSize(size_px)
            font.setWeight(QtGui.QFont.Weight.Bold)
            metrics = QtGui.QFontMetrics(font)
            text_rect = metrics.boundingRect(
                QtCore.QRect(0, 0, rect.width(), 20000), fit_flags, text)
            if text_rect.height() <= rect.height():
                best_size = size_px
                break
        self._set_instructions_font_size(best_size)

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        if event.key() == QtCore.Qt.Key.Key_Escape:
            self._on_quit()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        self.hide()
        from src.config import gw
        gw.isQuitting = True
        event.ignore()

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        self._apply_image_pane_width()
        self._fit_instructions_font()

    def _on_exit_fullscreen(self) -> None:
        self.showNormal()
        screen = QtWidgets.QApplication.primaryScreen().availableGeometry()
        w = int(screen.width() * 0.95)
        h = int(screen.height() * 0.95)
        x = int(screen.width() * 0.025)
        y = int(screen.height() * 0.025)
        self.setGeometry(x, y, w, h)

    def _on_quit(self) -> None:
        self.hide()
        from src.display import quit_button_pressed
        quit_button_pressed()


# ===================================================================
# Popup dialogs (message + status)
# ===================================================================

def create_message_window(parent=None) -> Tuple[QDialog, QLabel]:
    """Create the message popup dialog and its label."""
    dlg = QDialog(parent)
    dlg.setWindowFlags(
        dlg.windowFlags() | QtCore.Qt.WindowType.WindowStaysOnTopHint
    )
    if _use_generated:
        ui = Ui_MessageDialog()
        ui.setupUi(dlg)
        lbl = ui.label
    else:
        from PyQt6 import uic
        uic.loadUi(_ui_path("message_dialog.ui"), dlg)
        lbl = dlg.findChild(QLabel, "label")
    dlg.hide()
    return dlg, lbl


def create_status_window(parent=None) -> Tuple[QDialog, QLabel]:
    """Create the status popup dialog and its label."""
    dlg = QDialog(parent)
    dlg.setWindowFlags(
        dlg.windowFlags() | QtCore.Qt.WindowType.WindowStaysOnTopHint
    )
    if _use_generated:
        ui = Ui_StatusDialog()
        ui.setupUi(dlg)
        lbl = ui.label
    else:
        from PyQt6 import uic
        uic.loadUi(_ui_path("status_dialog.ui"), dlg)
        lbl = dlg.findChild(QLabel, "label")
    dlg.hide()
    return dlg, lbl


# ---------------------------------------------------------------------------
# Centering helper
# ---------------------------------------------------------------------------

def center_popup_over_parent(popup: QDialog) -> None:
    parent = popup.parentWidget()
    if parent is None:
        return
    pg = parent.geometry()
    pw, ph = pg.width(), pg.height()
    px, py = pg.x(), pg.y()
    dw, dh = popup.width(), popup.height()
    popup.move(px + (pw - dw) // 2, py + (ph - dh) // 2)


def _pil_to_qpixmap(pil_image: Image.Image) -> QtGui.QPixmap:
    """Convert a PIL Image to a QPixmap."""
    buffer = BytesIO()
    pil_image.save(buffer, format="PNG")
    pixmap = QtGui.QPixmap()
    pixmap.loadFromData(buffer.getvalue(), "PNG")
    return pixmap
