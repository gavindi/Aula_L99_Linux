"""A click/drag-to-pick color wheel, rendered from the vendor's own
`img_circlepalette.png` sprite.

Rather than computing RGB from a clicked angle/radius against some assumed
hue-wheel formula, this samples the actual pixel under the cursor -- the
vendor art doesn't distribute hue linearly by angle (checked empirically:
red to yellow sweeps ~120 degrees of the wheel, yellow to green only ~30),
so a formula would drift visibly out of sync with what's drawn. Sampling is
exact by construction and needs no calibration.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from . import theme

WHEEL_SIZE = 130
# Keeps clicks off the vendor art's dark outline ring (empirically the color
# fill runs to ~91% of the half-width before the border starts).
USABLE_RADIUS_RATIO = 0.90


class ColorWheel(QWidget):
    colorPicked = Signal(QColor)

    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(WHEEL_SIZE, WHEEL_SIZE)
        # IgnoreAspectRatio rather than Keep: the source is 116x117, not
        # perfectly square, and Keep would leave the scaled image a pixel
        # short of WHEEL_SIZE on one axis -- a mismatch between the image
        # bounds sampled from and the widget bounds clicks arrive in. The
        # <1% stretch this introduces is imperceptible.
        pixmap = QPixmap(str(theme.COLOR_WHEEL_IMAGE)).scaled(
            WHEEL_SIZE, WHEEL_SIZE, Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._image = pixmap.toImage()
        self._marker: QPoint | None = None

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.drawImage(0, 0, self._image)
        if self._marker is not None:
            painter.setPen(Qt.GlobalColor.white)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(self._marker, 5, 5)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._pick(event.position().toPoint())

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._pick(event.position().toPoint())

    def _pick(self, pos: QPoint) -> None:
        center = QPoint(WHEEL_SIZE // 2, WHEEL_SIZE // 2)
        dx, dy = pos.x() - center.x(), pos.y() - center.y()
        distance = math.hypot(dx, dy)
        usable_radius = (WHEEL_SIZE / 2) * USABLE_RADIUS_RATIO
        if distance > usable_radius:
            scale = usable_radius / distance
            dx, dy = dx * scale, dy * scale
        clamped = QPoint(int(center.x() + dx), int(center.y() + dy))
        color = self._image.pixelColor(clamped)
        if color.alpha() == 0:
            return
        self._marker = clamped
        self.update()
        self.colorPicked.emit(color)
