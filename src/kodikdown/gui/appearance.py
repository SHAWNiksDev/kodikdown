"""One bounded snapshot animation, without rebuilding the live interface."""

from __future__ import annotations

import math

from PySide6.QtCore import QEasingCurve, QPoint, QPointF, QRectF, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QPainter, QPainterPath, QPaintEvent, QPixmap, QRegion
from PySide6.QtWidgets import QWidget


class AppearanceOverlay(QWidget):
    finished = Signal()

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("appearance-overlay")
        self.hide()
        self._snapshot = QPixmap()
        self._origin = QPointF()
        self._progress = 0.0
        self._radius = 0.0
        self._circular = True
        self.animation = QVariantAnimation(self)
        self.animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.animation.valueChanged.connect(self._advance)
        self.animation.finished.connect(self.finish)

    @property
    def busy(self) -> bool:
        return not self._snapshot.isNull()

    def capture(self, origin: QPoint, *, circular: bool = True) -> None:
        self.finish()
        parent = self.parentWidget()
        if parent is None or not parent.isVisible():
            return
        # A half-resolution image keeps the effect inexpensive on HiDPI monitors.
        snapshot = parent.grab()
        self._snapshot = snapshot.scaled(max(1, parent.width()), max(1, parent.height()))
        self._snapshot.setDevicePixelRatio(1.0)
        self.setGeometry(parent.rect())
        self._origin = QPointF(origin)
        self._circular = circular
        self._progress = 0.0
        self._radius = math.hypot(
            max(origin.x(), self.width() - origin.x()), max(origin.y(), self.height() - origin.y())
        )
        self.show()
        self.raise_()

    def start(self) -> None:
        if not self.busy:
            return
        self.animation.setDuration(340 if self._circular else 180)
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self.animation.start()

    def _advance(self, value: object) -> None:
        self._progress = float(value)  # type: ignore[arg-type]
        if self._circular:
            radius = self._radius * self._progress
            circle = QRectF(
                self._origin.x() - radius, self._origin.y() - radius, radius * 2, radius * 2
            )
            # Expose the actual children as well as clipping our paint. Otherwise
            # Qt may leave opaque buttons unpainted under a full-sized overlay.
            self.setMask(
                QRegion(self.rect()).subtracted(
                    QRegion(circle.toRect(), QRegion.RegionType.Ellipse)
                )
            )
        self.update()

    def finish(self) -> None:
        was_busy = self.busy
        self.animation.stop()
        self.hide()
        self.clearMask()
        self._snapshot = QPixmap()
        if was_busy:
            self.finished.emit()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._circular:
            clip = QPainterPath()
            clip.setFillRule(Qt.FillRule.OddEvenFill)
            clip.addRect(QRectF(self.rect()))
            radius = self._radius * self._progress
            clip.addEllipse(self._origin, radius, radius)
            painter.setClipPath(clip)
        else:
            painter.setOpacity(1.0 - self._progress)
        painter.drawPixmap(self.rect(), self._snapshot)
