"""Paginated image browser for Speech2Picture.

Displays thumbnails from idleDisplayFiles, addToIdleDisplayFiles, and history
folders.  Supports pagination, preview pane, and right-click file operations
(move / delete) that also handle associated S3 QR code files.
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QGridLayout,
    QLabel,
    QMenu,
    QWidget,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_UI_DIR = Path(__file__).resolve().parent / "ui"
_use_generated: bool

try:
    from src.ui.image_browser import Ui_ImageBrowserDialog  # type: ignore[attr-defined]
    _use_generated = True
except ImportError:
    _use_generated = False


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

THUMBNAIL_SIZE: int = 150
FOLDERS: dict[str, str] = {
    "Idle Display": "./idleDisplayFiles",
    "Add to Idle": "./addToIdleDisplayFiles",
    "History": "./history",
}
CONSIDER_DELETION: str = "./considerForDeletion"

# S3 QR code suffix pattern:  {basename}-image.png  →  {basename}-s3_url.jpg
_IMAGE_SUFFIX: str = "-image.png"
_S3_SUFFIX: str = "-s3_url.jpg"


def _find_s3_counterpart(image_path: str) -> str | None:
    """Return the S3 QR code path for *image_path*, or None if it doesn't exist."""
    if image_path.endswith(_IMAGE_SUFFIX):
        s3_path = image_path[: -len(_IMAGE_SUFFIX)] + _S3_SUFFIX
    else:
        base, _ext = os.path.splitext(image_path)
        s3_path = base + _S3_SUFFIX
    return s3_path if os.path.exists(s3_path) else None


def _collect_image_files(folder: str) -> list[str]:
    """Return sorted list of .png image paths in *folder*, newest first."""
    if not os.path.isdir(folder):
        return []
    result: list[str] = []
    for fname in sorted(os.listdir(folder), reverse=True):
        if not fname.lower().endswith(".png"):
            continue
        result.append(os.path.join(folder, fname))
    return result


# ---------------------------------------------------------------------------
# Thumbnail widget
# ---------------------------------------------------------------------------

class _ThumbnailLabel(QLabel):
    """A clickable thumbnail.  Emits ``image_clicked(path)`` on left-click."""

    clicked = QtCore.pyqtSignal(str)
    right_clicked = QtCore.pyqtSignal(str, QtCore.QPoint)
    image_clicked = QtCore.pyqtSignal(str)

    def __init__(self, image_path: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._image_path: str = image_path
        self._loaded: bool = False
        self._selected: bool = False
        self.setFixedSize(THUMBNAIL_SIZE + 4, THUMBNAIL_SIZE + 4)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setText("…")
        self.setStyleSheet(
            "border: 2px solid #555; background-color: #222; color: #888;"
            "font: 24px Helvetica;"
        )

    @property
    def image_path(self) -> str:
        return self._image_path

    def set_selected(self, selected: bool) -> None:
        """Highlight (red border) or un-highlight this thumbnail."""
        self._selected = selected
        if selected:
            self.setStyleSheet("border: 3px solid #FF3333; background-color: #222;")
        elif self._loaded:
            self.setStyleSheet("border: 2px solid #555; background-color: #222;")
        else:
            self.setStyleSheet(
                "border: 2px solid #555; background-color: #222; color: #888;"
                "font: 24px Helvetica;"
            )

    def load(self) -> None:
        """Load the thumbnail image from disk and scale to 150px."""
        if self._loaded:
            return
        self._loaded = True
        try:
            pix = QtGui.QPixmap(self._image_path)
            thumb = pix.scaled(
                THUMBNAIL_SIZE, THUMBNAIL_SIZE,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.setPixmap(thumb)
            # Preserve selection state
            if self._selected:
                self.setStyleSheet("border: 3px solid #FF3333; background-color: #222;")
            else:
                self.setStyleSheet("border: 2px solid #555; background-color: #222;")
        except Exception:
            logger.exception("Failed to load thumbnail: %s", self._image_path)
            self.setText("⚠")

    def mousePressEvent(self, event: QtGui.QMouseEvent | None) -> None:
        if event is None:
            return
        if event.button() == Qt.MouseButton.RightButton:
            self.right_clicked.emit(
                self._image_path, event.globalPosition().toPoint(),
            )
        elif event.button() == Qt.MouseButton.LeftButton:
            self.image_clicked.emit(self._image_path)
        super().mousePressEvent(event)


# ---------------------------------------------------------------------------
# Main Image Browser dialog
# ---------------------------------------------------------------------------

class ImageBrowser(QDialog):
    """Paginated browser for generated images across three folders."""

    # Typed widget references populated by _load_ui
    folderCombo: QtWidgets.QComboBox
    countLabel: QLabel
    closeButton: QtWidgets.QPushButton
    thumbnailScroll: QtWidgets.QScrollArea
    gridContainer: QWidget
    previewLabel: QLabel
    pageLabel: QLabel
    fileNameLabel: QLabel
    perPageCombo: QtWidgets.QComboBox
    prevButton: QtWidgets.QPushButton
    nextButton: QtWidgets.QPushButton

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._current_folder_key: str = "Idle Display"
        self._current_page: int = 0
        self._per_page: int = 50
        self._images: list[str] = []
        self._preview_pixmap: QtGui.QPixmap | None = None
        self._selected_thumb: _ThumbnailLabel | None = None

        self._load_ui()
        self._load_folder()

    # ------------------------------------------------------------------
    # UI loading (from .ui file, following the __init__.py convention)
    # ------------------------------------------------------------------

    def _load_ui(self) -> None:
        if _use_generated:
            ui = Ui_ImageBrowserDialog()
            ui.setupUi(self)
            for attr in dir(ui):
                if not attr.startswith("_"):
                    obj = getattr(ui, attr, None)
                    if isinstance(obj, (QtWidgets.QWidget, QtWidgets.QLayout, QtWidgets.QLabel)):
                        setattr(self, attr, obj)
        else:
            from PyQt6 import uic
            uic.loadUi(str(_UI_DIR / "image_browser.ui"), self)

        # Set up the dynamic thumbnail grid inside the scroll area
        self._grid = QGridLayout(self.gridContainer)
        self._grid.setSpacing(6)
        self._grid.setContentsMargins(8, 8, 8, 8)
        self._grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        # Wire signals
        self.closeButton.clicked.connect(self.hide)
        self.folderCombo.addItems(list(FOLDERS.keys()))
        self.folderCombo.currentTextChanged.connect(self._on_folder_changed)
        self.perPageCombo.addItems(["10", "50", "100"])
        self.perPageCombo.setCurrentText("50")
        self.perPageCombo.currentTextChanged.connect(self._on_per_page_changed)
        self.prevButton.clicked.connect(self._prev_page)
        self.nextButton.clicked.connect(self._next_page)

    # ------------------------------------------------------------------
    # Folder / page management
    # ------------------------------------------------------------------

    def _load_folder(self) -> None:
        folder_path = FOLDERS[self._current_folder_key]
        self._images = _collect_image_files(folder_path)
        self._current_page = 0
        self._refresh_view()

    def _refresh_view(self) -> None:
        """Rebuild the thumbnail grid for the current page."""
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        total = len(self._images)
        total_pages = max(1, (total + self._per_page - 1) // self._per_page)
        start = self._current_page * self._per_page
        end = min(start + self._per_page, total)

        folder_path = FOLDERS[self._current_folder_key]
        self.countLabel.setText(f"{total} image(s) in {folder_path}")

        self.pageLabel.setText(
            f"Page {self._current_page + 1} of {total_pages}"
            if total > 0 else "No images"
        )

        self.prevButton.setEnabled(self._current_page > 0)
        self.nextButton.setEnabled(self._current_page < total_pages - 1)

        cols = 4

        self._pending_thumbs: list[_ThumbnailLabel] = []
        for i in range(start, end):
            thumb = _ThumbnailLabel(self._images[i])
            thumb.right_clicked.connect(self._on_right_click)
            thumb.image_clicked.connect(self._on_image_clicked)
            row = (i - start) // cols
            col = (i - start) % cols
            self._grid.addWidget(thumb, row, col)
            self._pending_thumbs.append(thumb)

        if total > 0:
            self._show_full_image(self._images[0])
            if self._pending_thumbs:
                self._pending_thumbs[0].set_selected(True)
                self._selected_thumb = self._pending_thumbs[0]

        self._load_index = 0
        QtCore.QTimer.singleShot(0, self._load_next_thumbnail)

    def _load_next_thumbnail(self) -> None:
        if not hasattr(self, "_pending_thumbs") or not self._pending_thumbs:
            return
        if self._load_index >= len(self._pending_thumbs):
            return
        self._pending_thumbs[self._load_index].load()
        self._load_index += 1
        if self._load_index < len(self._pending_thumbs):
            QtCore.QTimer.singleShot(0, self._load_next_thumbnail)

    def _on_folder_changed(self, key: str) -> None:
        self._current_folder_key = key
        self._load_folder()

    def _on_per_page_changed(self, text: str) -> None:
        self._per_page = int(text)
        self._current_page = 0
        self._refresh_view()

    def _prev_page(self) -> None:
        if self._current_page > 0:
            self._current_page -= 1
            self._refresh_view()

    def _next_page(self) -> None:
        total_pages = max(1, (len(self._images) + self._per_page - 1) // self._per_page)
        if self._current_page < total_pages - 1:
            self._current_page += 1
            self._refresh_view()

    def _on_image_clicked(self, image_path: str) -> None:
        # Deselect previous, select new
        if self._selected_thumb is not None:
            self._selected_thumb.set_selected(False)
        sender = self.sender()
        if isinstance(sender, _ThumbnailLabel):
            sender.set_selected(True)
            self._selected_thumb = sender
        self._show_full_image(image_path)

    def _show_full_image(self, image_path: str) -> None:
        try:
            self._preview_pixmap = QtGui.QPixmap(image_path)
        except Exception:
            logger.exception("Failed to load preview: %s", image_path)
            self.previewLabel.clear()
            self._preview_pixmap = None
            self.fileNameLabel.setText("")
            return
        self._fit_preview_to_pane()
        self.fileNameLabel.setText(os.path.basename(image_path))

    def _fit_preview_to_pane(self) -> None:
        if self._preview_pixmap is None:
            return
        available = self.previewLabel.size()
        if available.width() <= 1:
            available = QtCore.QSize(400, 400)
        scaled = self._preview_pixmap.scaled(
            available,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.previewLabel.setPixmap(scaled)

    def resizeEvent(self, event: QtGui.QResizeEvent | None) -> None:
        super().resizeEvent(event)
        self._fit_preview_to_pane()

    def closeEvent(self, event: QtGui.QCloseEvent | None) -> None:
        """Hide instead of closing — allows Ctrl+C / 'q' in main loop."""
        self.hide()
        if event is not None:
            event.ignore()

    # ------------------------------------------------------------------
    # Right-click context menu
    # ------------------------------------------------------------------

    def _on_right_click(self, image_path: str, global_pos: QtCore.QPoint) -> None:
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background-color: #444; color: #FFF; border: 1px solid #888; }"
            "QMenu::item { padding: 6px 24px; }"
            "QMenu::item:selected { background-color: #666; }"
        )

        current_folder = FOLDERS[self._current_folder_key]

        for label, dest in FOLDERS.items():
            if dest != current_folder:
                action = menu.addAction(f"Move to {label}")
                action.triggered.connect(
                    lambda checked, d=dest, p=image_path: self._move_file(p, d),
                )

        menu.addSeparator()

        del_action = menu.addAction("Move to considerForDeletion")
        del_action.triggered.connect(
            lambda: self._move_file(image_path, CONSIDER_DELETION),
        )

        menu.addSeparator()

        poster_action = menu.addAction("Copy to Poster")
        poster_action.triggered.connect(
            lambda: self._copy_file(image_path, "goodForPoster"),
        )

        menu.addSeparator()

        delete_action = menu.addAction("🗑 Delete")
        delete_action.triggered.connect(
            lambda: self._delete_file(image_path),
        )

        menu.exec(global_pos)

    def _move_file(self, image_path: str, dest_folder: str) -> None:
        os.makedirs(dest_folder, exist_ok=True)

        fname = os.path.basename(image_path)
        dest_path = os.path.join(dest_folder, fname)

        try:
            shutil.move(image_path, dest_path)
            logger.info("Moved %s → %s", image_path, dest_path)
        except OSError:
            logger.exception("Failed to move %s", image_path)
            return

        s3_path = _find_s3_counterpart(image_path)
        if s3_path:
            s3_dest = os.path.join(dest_folder, os.path.basename(s3_path))
            try:
                shutil.move(s3_path, s3_dest)
                logger.info("Moved S3 QR %s → %s", s3_path, s3_dest)
            except OSError:
                logger.exception("Failed to move S3 QR %s", s3_path)

        self._load_folder()

    def _copy_file(self, image_path: str, dest_folder: str) -> None:
        """Copy *image_path* (image only, no S3 QR) to *dest_folder*."""
        os.makedirs(dest_folder, exist_ok=True)

        fname = os.path.basename(image_path)
        dest_path = os.path.join(dest_folder, fname)

        try:
            shutil.copy2(image_path, dest_path)
            logger.info("Copied %s → %s", image_path, dest_path)
        except OSError:
            logger.exception("Failed to copy %s", image_path)

    def _delete_file(self, image_path: str) -> None:
        fname = os.path.basename(image_path)
        reply = QtWidgets.QMessageBox.question(
            self, "Confirm Delete",
            f"Permanently delete\n\n{fname}\n\nand its S3 QR code (if any)?",
            QtWidgets.QMessageBox.StandardButton.Yes
            | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No,
        )
        if reply != QtWidgets.QMessageBox.StandardButton.Yes:
            return

        try:
            os.remove(image_path)
            logger.info("Deleted %s", image_path)
        except OSError:
            logger.exception("Failed to delete %s", image_path)

        s3_path = _find_s3_counterpart(image_path)
        if s3_path:
            try:
                os.remove(s3_path)
                logger.info("Deleted S3 QR %s", s3_path)
            except OSError:
                logger.exception("Failed to delete S3 QR %s", s3_path)

        self._load_folder()