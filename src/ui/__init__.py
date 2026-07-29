"""Qt UI Designer integration for Speech2Picture.

On macOS (pip-installed PyQt6), uses ``PyQt6.uic.loadUi``.
On Debian/Raspbian (apt-installed pyqt6), parses .ui XML directly —
no extra packages needed, and the .ui files remain the single source of truth.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from io import BytesIO
from pathlib import Path
from typing import Any, Optional, Tuple

from PIL import Image
try:
    from PyQt6 import uic, QtWidgets, QtCore, QtGui
    _uic_available = True
except ImportError:
    from PyQt6 import QtWidgets, QtCore, QtGui
    _uic_available = False

from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QLabel,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Path helper
# ---------------------------------------------------------------------------
_UI_DIR = Path(__file__).resolve().parent


def _ui_path(filename: str) -> str:
    return str(_UI_DIR / filename)


# ===================================================================
# Lightweight .ui XML loader (for platforms without PyQt6.uic)
# ===================================================================

def _load_ui_from_xml(filename: str, target: QtWidgets.QWidget) -> dict[str, Any]:
    """Parse a .ui XML file and build widgets onto *target*.

    Returns a dict of ``{objectName: widget}`` for all named widgets.
    Supports: QMainWindow, QDialog, QWidget, QGridLayout, QHBoxLayout,
    QVBoxLayout, QLabel, QPushButton, QFrame, QSpacerItem.
    """
    tree = ET.parse(_ui_path(filename))
    root = tree.getroot()

    widget_map: dict[str, Any] = {}
    _ns = ""  # no XML namespace in our .ui files

    def _apply_properties(w: QtWidgets.QWidget, el: ET.Element) -> None:
        """Apply common properties from a widget element."""
        for prop in el.findall("property"):
            name = prop.get("name", "")
            if name == "styleSheet":
                ss = prop.find("string")
                if ss is not None and ss.text:
                    w.setStyleSheet(ss.text)
            elif name == "minimumSize":
                sz = _parse_size(prop)
                if sz:
                    w.setMinimumSize(*sz)
            elif name == "maximumSize":
                sz = _parse_size(prop)
                if sz:
                    w.setMaximumSize(*sz)
            elif name == "sizePolicy":
                h_pol = _enum_prop(prop, "hsizetype", "Expanding")
                v_pol = _enum_prop(prop, "vsizetype", "Expanding")
                h_map = {"Fixed": 0, "Minimum": 1, "Maximum": 4, "Preferred": 5,
                         "Expanding": 7, "MinimumExpanding": 3, "Ignored": 6}
                w.setSizePolicy(
                    QtWidgets.QSizePolicy.Policy(h_map.get(h_pol, 7)),
                    QtWidgets.QSizePolicy.Policy(h_map.get(v_pol, 7)),
                )
            elif name == "minimumHeight":
                h = _int_prop(prop)
                if h:
                    w.setMinimumHeight(h)

    def _parse_size(el: ET.Element) -> Optional[Tuple[int, int]]:
        w_el = el.find("size/width")
        h_el = el.find("size/height")
        if w_el is not None and h_el is not None:
            return (int(w_el.text or 0), int(h_el.text or 0))
        return None

    def _int_prop(el: ET.Element) -> Optional[int]:
        for child in el:
            if child.text:
                return int(child.text.strip())
        return None

    def _enum_prop(el: ET.Element, child_name: str, default: str) -> str:
        c = el.find(child_name)
        if c is not None and c.text:
            return c.text
        return default

    def _build_layout(layout_el: ET.Element, parent_w: Optional[QtWidgets.QWidget] = None):
        """Recursively build a layout and its children."""
        cls = layout_el.get("class", "")
        lay_cls = {
            "QGridLayout": QtWidgets.QGridLayout,
            "QHBoxLayout": QtWidgets.QHBoxLayout,
            "QVBoxLayout": QtWidgets.QVBoxLayout,
        }.get(cls)
        if lay_cls is None:
            return

        layout = lay_cls()
        for prop in layout_el.findall("property"):
            name = prop.get("name", "")
            if name == "spacing":
                v = _int_prop(prop)
                if v is not None:
                    layout.setSpacing(v)
            elif name in ("leftMargin", "topMargin", "rightMargin", "bottomMargin"):
                pass  # handled via setContentsMargins below

        # Gather margins
        margins = {"leftMargin": 0, "topMargin": 0, "rightMargin": 0, "bottomMargin": 0}
        for prop in layout_el.findall("property"):
            n = prop.get("name", "")
            if n in margins:
                v = _int_prop(prop)
                if v is not None:
                    margins[n] = v
        layout.setContentsMargins(
            margins["leftMargin"], margins["topMargin"],
            margins["rightMargin"], margins["bottomMargin"],
        )

        if parent_w is not None:
            parent_w.setLayout(layout)

        # Process children
        for item in layout_el.findall("item"):
            # Layout-in-layout
            sub = item.find("layout")
            if sub is not None:
                sub_lay = _build_layout(sub)
                if isinstance(layout, QtWidgets.QGridLayout):
                    row = int(item.get("row", 0))
                    col = int(item.get("column", 0))
                    rs = int(item.get("rowspan", 1))
                    cs = int(item.get("colspan", 1))
                    layout.addLayout(sub_lay, row, col, rs, cs)
                else:
                    layout.addLayout(sub_lay)
                continue

            # Widget
            w_el = item.find("widget")
            if w_el is not None:
                w_cls = w_el.get("class", "")
                w_name = w_el.get("name", "")
                widget = _make_widget(w_cls, w_el)
                if widget is not None and w_name:
                    widget.setObjectName(w_name)
                    widget_map[w_name] = widget

                # Special properties on QLabel
                if w_cls == "QLabel" and widget is not None:
                    for prop in w_el.findall("property"):
                        pn = prop.get("name", "")
                        if pn == "text":
                            t = prop.find("string")
                            if t is not None and t.text:
                                widget.setText(t.text)
                        elif pn == "alignment":
                            a = prop.find("set")
                            if a is not None and a.text:
                                widget.setAlignment(_parse_alignment(a.text))
                        elif pn == "wordWrap":
                            b = prop.find("bool")
                            if b is not None:
                                widget.setWordWrap(b.text == "true")
                        elif pn == "fixedWidth":
                            n = _int_prop(prop)
                            if n:
                                widget.setFixedWidth(n)

                if isinstance(layout, QtWidgets.QGridLayout) and widget is not None:
                    row = int(item.get("row", 0))
                    col = int(item.get("column", 0))
                    rs = int(item.get("rowspan", 1))
                    cs = int(item.get("colspan", 1))
                    layout.addWidget(widget, row, col, rs, cs)
                elif widget is not None:
                    layout.addWidget(widget)

            # Spacer
            sp_el = item.find("spacer")
            if sp_el is not None:
                orient = QtCore.Qt.Orientation.Horizontal
                for prop in sp_el.findall("property"):
                    if prop.get("name") == "orientation":
                        e = prop.find("enum")
                        if e is not None and e.text:
                            orient = QtCore.Qt.Orientation.Vertical if "Vertical" in e.text else QtCore.Qt.Orientation.Horizontal
                spacer = QtWidgets.QSpacerItem(40, 20,
                    QtWidgets.QSizePolicy.Policy.Expanding if orient == QtCore.Qt.Orientation.Horizontal else QtWidgets.QSizePolicy.Policy.Minimum,
                    QtWidgets.QSizePolicy.Policy.Minimum if orient == QtCore.Qt.Orientation.Horizontal else QtWidgets.QSizePolicy.Policy.Expanding,
                )
                if isinstance(layout, QtWidgets.QGridLayout):
                    row = int(item.get("row", 0))
                    col = int(item.get("column", 0))
                    layout.addItem(spacer, row, col, 1, 1)
                else:
                    layout.addItem(spacer)

        return layout

    def _make_widget(cls: str, el: ET.Element) -> Optional[QtWidgets.QWidget]:
        if cls == "QLabel":
            return QLabel()
        elif cls == "QPushButton":
            btn = QPushButton()
            for prop in el.findall("property"):
                if prop.get("name") == "text":
                    t = prop.find("string")
                    if t is not None and t.text:
                        btn.setText(t.text)
            return btn
        elif cls == "QFrame":
            return QFrame()
        elif cls == "QWidget":
            return QtWidgets.QWidget()
        return None

    def _parse_alignment(text: str) -> QtCore.Qt.AlignmentFlag:
        flags = QtCore.Qt.AlignmentFlag(0)
        for part in text.split("|"):
            part = part.strip()
            m = {
                "Qt::AlignLeft": QtCore.Qt.AlignmentFlag.AlignLeft,
                "Qt::AlignRight": QtCore.Qt.AlignmentFlag.AlignRight,
                "Qt::AlignHCenter": QtCore.Qt.AlignmentFlag.AlignHCenter,
                "Qt::AlignTop": QtCore.Qt.AlignmentFlag.AlignTop,
                "Qt::AlignBottom": QtCore.Qt.AlignmentFlag.AlignBottom,
                "Qt::AlignVCenter": QtCore.Qt.AlignmentFlag.AlignVCenter,
                "Qt::AlignCenter": QtCore.Qt.AlignmentFlag.AlignCenter,
            }.get(part)
            if m is not None:
                flags |= m
        return flags

    # -- Top-level widget ----------------------------------------------------
    ui_class = root.find("widget")
    if ui_class is None:
        return widget_map

    w_cls = ui_class.get("class", "")

    # Apply window title
    for prop in ui_class.findall("property"):
        if prop.get("name") == "windowTitle":
            t = prop.find("string")
            if t is not None and t.text:
                target.setWindowTitle(t.text)
        elif prop.get("name") == "styleSheet":
            ss = prop.find("string")
            if ss is not None and ss.text:
                target.setStyleSheet(ss.text)

    # Find the root layout
    for child in ui_class:
        if child.tag == "widget":
            w_cls_inner = child.get("class", "")
            w_name = child.get("name", "")
            # This is the central widget / outer widget
            inner_widget: Optional[QtWidgets.QWidget] = None
            if w_cls == "QMainWindow":
                inner_widget = QtWidgets.QWidget(target)
                target.setCentralWidget(inner_widget)
            elif w_cls in ("QDialog", ""):
                inner_widget = target

            if inner_widget is not None:
                # Apply properties to the inner widget
                for prop in child.findall("property"):
                    if prop.get("name") == "styleSheet":
                        ss = prop.find("string")
                        if ss is not None and ss.text:
                            inner_widget.setStyleSheet(ss.text)

            # Find layout inside this widget
            layout_el = child.find("layout")
            if layout_el is not None and inner_widget is not None:
                _build_layout(layout_el, inner_widget)

            # Also scan for widgets directly inside (for non-layout setups)
            for w_el in child.findall("widget"):
                w_name2 = w_el.get("name", "")
                w_cls2 = w_el.get("class", "")
                w = _make_widget(w_cls2, w_el)
                if w is not None and w_name2:
                    w.setObjectName(w_name2)
                    widget_map[w_name2] = w
                    _apply_properties(w, w_el)

        elif child.tag == "layout":
            # Direct layout under root (e.g. QDialog)
            _build_layout(child, target)

    return widget_map


# ===================================================================
# Main window
# ===================================================================

class MainWindow(QMainWindow):
    """Main application window loaded from main_window.ui."""

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
        if _uic_available:
            uic.loadUi(_ui_path("main_window.ui"), self)
        else:
            widget_map = _load_ui_from_xml("main_window.ui", self)

        # Resolve named widgets (works for both paths)
        self.labelInstructions = self.findChild(QLabel, "labelInstructions")
        self.labelForImage = self.findChild(QLabel, "labelForImage")
        self.labelQR = self.findChild(QLabel, "labelQR")
        self.labelQRText = self.findChild(QLabel, "labelQRText")
        self.labelCredits = self.findChild(QLabel, "labelCredits")
        self.labelCommandHint = self.findChild(QLabel, "labelCommandHint")
        self.buttonQuit = self.findChild(QPushButton, "buttonQuit")
        self.buttonWindow = self.findChild(QPushButton, "buttonWindow")

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
    dlg.setWindowTitle("Messages")
    dlg.setMinimumSize(500, 500)
    dlg.setMaximumSize(500, 500)
    dlg.setWindowFlags(
        dlg.windowFlags() | QtCore.Qt.WindowType.WindowStaysOnTopHint
    )

    if _uic_available:
        uic.loadUi(_ui_path("message_dialog.ui"), dlg)
        lbl = dlg.findChild(QLabel, "label")
    else:
        widget_map = _load_ui_from_xml("message_dialog.ui", dlg)
        lbl = widget_map.get("label") or dlg.findChild(QLabel, "label")

    dlg.hide()
    return dlg, lbl


def create_status_window(parent=None) -> Tuple[QDialog, QLabel]:
    """Create the status popup dialog and its label."""
    dlg = QDialog(parent)
    dlg.setWindowTitle("Status")
    dlg.setMinimumSize(800, 600)
    dlg.setMaximumSize(800, 600)
    dlg.setWindowFlags(
        dlg.windowFlags() | QtCore.Qt.WindowType.WindowStaysOnTopHint
    )

    if _uic_available:
        uic.loadUi(_ui_path("status_dialog.ui"), dlg)
        lbl = dlg.findChild(QLabel, "label")
    else:
        widget_map = _load_ui_from_xml("status_dialog.ui", dlg)
        lbl = widget_map.get("label") or dlg.findChild(QLabel, "label")

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
