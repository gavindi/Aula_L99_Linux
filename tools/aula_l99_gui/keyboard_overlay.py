"""Clickable per-key overlay on the keyboard layout image.

Owns only geometry/paint state (which key is selected, which keys have a
swatch colour to show) -- matches color_wheel.py's idiom of a self-contained
widget that emits a Signal on interaction rather than mutating shared state
itself. The tab that embeds this decides what selection/swatches actually
mean.
"""
from __future__ import annotations

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from . import key_layout, theme

SWATCH_ALPHA = 180
SELECTION_BORDER_WIDTH = 2


class KeyboardOverlay(QWidget):
    keyClicked = Signal(int)  # key_id, or -1 for "deselected"

    def __init__(self, display_width: int = 640) -> None:
        super().__init__()
        pixmap = QPixmap(str(theme.KEYBOARD_LAYOUT_IMAGE))
        if not pixmap.isNull():
            pixmap = pixmap.scaledToWidth(display_width, Qt.TransformationMode.SmoothTransformation)
        self._pixmap = pixmap
        self.setFixedSize(pixmap.size())

        scale = display_width / key_layout.LAYOUT_WIDTH
        self._rects: dict[int, QRect] = {
            key_id: QRect(
                round(rect.left * scale), round(rect.top * scale),
                round(rect.width * scale), round(rect.height * scale),
            )
            for key_id, rect in key_layout.KEY_RECTS.items()
        }

        self._selected: int | None = None
        self._swatches: dict[int, tuple[int, int, int]] = {}

    def select_key(self, key_id: int | None) -> None:
        self._selected = key_id
        self.update()

    def set_swatches(self, colors: dict[int, tuple[int, int, int]]) -> None:
        self._swatches = colors
        self.update()

    def clear_swatches(self) -> None:
        self._swatches = {}
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)

        # Swatches paint underneath the layout image, not on top of it -- the
        # per-key art has transparent cutouts, so a colour behind it reads as
        # that key lighting up instead of a flat rectangle stamped over the
        # artwork.
        for key_id, rgb in self._swatches.items():
            rect = self._rects.get(key_id)
            if rect is not None:
                painter.fillRect(rect, QColor(*rgb, SWATCH_ALPHA))

        painter.drawPixmap(0, 0, self._pixmap)

        if self._selected is not None:
            rect = self._rects.get(self._selected)
            if rect is not None:
                pen = painter.pen()
                pen.setColor(QColor(theme.ACCENT))
                pen.setWidth(SELECTION_BORDER_WIDTH)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(rect)

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position().toPoint()
        for key_id, rect in self._rects.items():
            if rect.contains(pos):
                if key_id == self._selected:
                    self.select_key(None)
                    self.keyClicked.emit(-1)
                else:
                    self.select_key(key_id)
                    self.keyClicked.emit(key_id)
                return
