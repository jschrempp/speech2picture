"""Qt UI Designer integration for Speech2Picture.

Provides loaders for each .ui file in src/ui/.  Windows created this way
expose all the named widgets from the designer so callers can connect
signals, set pixmaps, update text, etc. without any programmatic layout.
"""

from __future__ import annotations

import logging
from io import BytesIO
from pathlib import Path
from typing import Optional, Tuple

from PIL import Image
try:
    from PyQt6 import uic, QtWidgets, QtCore, QtGui
    _uic_available = True
except ImportError:
    # On Debian/Raspbian, PyQt6.uic may be in a separate apt package
    # (pyqt6-dev-tools).  Fall back to QUiLoader.
    from PyQt6 import QtWidgets, QtCore, QtGui
    _uic_available = False

from PyQt6.QtWidgets import QMainWindow, QDialog, QLabel, QPushButton

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Path helper -- resolve .ui files relative to this module's directory
# ---------------------------------------------------------------------------
_UI_DIR = Path(__file__).resolve().parent


def _ui_path(filename: str) -> str:
    return str(_UI_DIR / filename)


def _load_ui_file(filename: str, widget: QtWidgets.QWidget) -> None:
    """Load a .ui file onto *widget*, using uic if available, else QUiLoader."""
    if _uic_available:
        uic.loadUi(_ui_path(filename), widget)
    else:
        from PyQt6.QtUiTools import QUiLoader
        from PyQt6.QtCore import QFile

        ui_file = QFile(_ui_path(filename))
        ui_file.open(QFile.OpenModeFlag.ReadOnly)
        loader = QUiLoader()
        loaded = loader.load(ui_file, widget)
        ui_file.close()
        if loaded is None:
            raise RuntimeError(f"Failed to load UI file: {filename}")
        # QUiLoader creates a new widget tree; transfer children to *widget*.
        # For QMainWindow, set the central widget from the loaded widget.
        if isinstance(widget, QMainWindow):
            widget.setCentralWidget(loaded.findChild(QtWidgets.QWidget, loaded.metaObject().className()) or loaded)


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    """Main application window loaded from main_window.ui."""

    # Public references so pyspeech.py can wire things up without
    # knowing the internal widget names.  set after load_ui().
    labelInstructions: QLabel
    labelForImage: QLabel
    labelQR: QLabel
    labelQRText: QLabel
    labelCredits: QLabel
    labelCommandHint: QLabel
    buttonQuit: QPushButton
    buttonWindow: QPushButton

    # QR-overlay widgets are NOT in the .ui file -- they are created
    # dynamically at runtime just like the original code.
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

    # -- UI loading ---------------------------------------------------------

    def _load_ui(self) -> None:
        """Load the .ui file and bind named widgets."""
        _load_ui_file("main_window.ui", self)

        # The central widget and its grid layout.
        self._main_grid = self.centralWidget().layout()

        # Resolve widgets by objectName
        self.labelInstructions = self.findChild(QLabel, "labelInstructions")
        self.labelForImage = self.findChild(QLabel, "labelForImage")
        self.labelQR = self.findChild(QLabel, "labelQR")
        self.labelQRText = self.findChild(QLabel, "labelQRText")
        self.labelCredits = self.findChild(QLabel, "labelCredits")
        self.labelCommandHint = self.findChild(QLabel, "labelCommandHint")
        self.buttonQuit = self.findChild(QPushButton, "buttonQuit")
        self.buttonWindow = self.findChild(QPushButton, "buttonWindow")

        # Column stretches (match original: 0-5→1, 6→14, 7→0)
        for col in range(8):
            self._main_grid.setColumnStretch(
                col, 1 if col < 6 else (14 if col == 6 else 0))

        # Row stretches
        for row, stretch in ((0, 3), (1, 3), (2, 1), (3, 1), (4, 1), (5, 1)):
            self._main_grid.setRowStretch(row, stretch)

        self._main_grid.setColumnMinimumWidth(2, 100)
        self._main_grid.setColumnMinimumWidth(3, 100)

        # ---------- Font selection for instructions ----------
        preferred = ["Noto Sans", "DejaVu Sans", "Verdana", "Arial", "Helvetica"]
        available = set(QtGui.QFontDatabase.families())
        self._instruction_font_family = next(
            (f for f in preferred if f in available),
            self.labelInstructions.font().family(),
        )

    # -- Widget configuration ------------------------------------------------

    def _configure_widgets(self) -> None:
        """Wire signals and set custom properties after .ui load."""
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
        """Create the dynamic QR-code overlay (child of labelForImage)."""
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
        """Hide/show widgets based on launch flags."""
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

    # -- Layout helpers ------------------------------------------------------

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

    # -- Event overrides -----------------------------------------------------

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        if event.key() == QtCore.Qt.Key.Key_Escape:
            self._on_quit()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        """Set quit flag; main loop handles actual shutdown."""
        self.hide()
        from src.config import gw
        gw.isQuitting = True
        event.ignore()

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        self._apply_image_pane_width()
        self._fit_instructions_font()

    # -- Signal handlers -----------------------------------------------------

    def _on_exit_fullscreen(self) -> None:
        self.showNormal()
        screen = QtWidgets.QApplication.primaryScreen().availableGeometry()
        w = int(screen.width() * 0.95)
        h = int(screen.height() * 0.95)
        x = int(screen.width() * 0.025)
        y = int(screen.height() * 0.025)
        self.setGeometry(x, y, w, h)

    def _on_quit(self) -> None:
        """Forward quit to display module (sets gw.isQuitting)."""
        self.hide()
        from src.display import quit_button_pressed
        quit_button_pressed()


# ---------------------------------------------------------------------------
# Popup dialogs (message + status)
# ---------------------------------------------------------------------------

class _PopupDialog(QDialog):
    """Base popup loaded from a .ui file.  Looks for a QLabel named 'label'."""

    label: QLabel

    def __init__(self, ui_filename: str, parent=None):
        super().__init__(parent)
        _load_ui_file(ui_filename, self)
        self.setWindowFlags(
            self.windowFlags() | QtCore.Qt.WindowType.WindowStaysOnTopHint
        )
        self.label = self.findChild(QLabel, "label")
        self.hide()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        """Hide normally; accept only when force-closing (during app quit)."""
        if getattr(self, '_force_close', False):
            event.accept()
        else:
            self.hide()
            event.ignore()


def create_message_window(parent=None) -> Tuple[QDialog, QLabel]:
    dlg = _PopupDialog("message_dialog.ui", parent)
    return dlg, dlg.label


def create_status_window(parent=None) -> Tuple[QDialog, QLabel]:
    dlg = _PopupDialog("status_dialog.ui", parent)
    return dlg, dlg.label


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
