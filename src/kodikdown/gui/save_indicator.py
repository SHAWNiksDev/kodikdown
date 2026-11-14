"""One quiet, bounded save animation, shared by all settings actions."""

from __future__ import annotations

from PySide6.QtCore import QElapsedTimer, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QWidget

from kodikdown.gui.theme import LIGHT, Palette
from kodikdown.i18n import t


class SaveIndicator(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(28, 28)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._palette = LIGHT
        self._elapsed = QElapsedTimer()
        self._spin_duration = 400
        self.state = "idle"
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self._advance)

    def apply_palette(self, palette: Palette) -> None:
        self._palette = palette
        self.update()

    def pulse(self, *, animated: bool = True) -> None:
        self._spin_duration = 400 if animated else 0
        self._elapsed.start()
        self._set_state("saving" if animated else "saved")
        self.timer.start()
        self.update()

    def _set_state(self, state: str) -> None:
        self.state = state
        description = t("settings_saving" if state == "saving" else "settings_saved")
        self.setAccessibleName(description if state != "idle" else "")
        self.setToolTip(description if state != "idle" else "")

    def _advance(self) -> None:
        elapsed = self._elapsed.elapsed()
        if elapsed >= self._spin_duration + 900:
            self.finish()
            return
        if elapsed >= self._spin_duration and self.state == "saving":
            self._set_state("saved")
        self.update()

    def finish(self) -> None:
        self.timer.stop()
        self._set_state("idle")
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        if self.state == "idle":
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(
            QColor(self._palette.accent if self.state == "saving" else self._palette.success)
        )
        pen.setWidthF(2.2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        if self.state == "saving":
            angle = -(self._elapsed.elapsed() % 650) * 360 / 650
            painter.drawArc(QRectF(6, 6, 16, 16), int(angle * 16), 265 * 16)
        else:
            painter.drawLine(7, 14, 12, 19)
            painter.drawLine(12, 19, 21, 9)
