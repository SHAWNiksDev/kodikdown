"""Small self-contained widgets: elided labels, animated progress, toasts, rows."""

from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    QSize,
    Qt,
    QTimer,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFontMetrics,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QResizeEvent,
)
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from kodikdown.downloader import ProgressSnapshot
from kodikdown.gui.icons import icon
from kodikdown.gui.theme import Palette
from kodikdown.i18n import t


class ElidedLabel(QLabel):
    """A label that shortens its text with an ellipsis instead of clipping."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full_text = text
        self.setText(text)

    def setText(self, text: str) -> None:
        self._full_text = text
        self.setToolTip(text)
        self._refresh()

    def text(self) -> str:
        return self._full_text

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._refresh()

    def _refresh(self) -> None:
        metrics = QFontMetrics(self.font())
        available = max(0, self.width() - 2)
        if available <= 0:
            super().setText(self._full_text)
            return
        super().setText(metrics.elidedText(self._full_text, Qt.TextElideMode.ElideRight, available))


class ProgressBar(QWidget):
    """Rounded progress bar with a soft animation and a busy mode."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._value = 0.0
        self._target = 0.0
        self._busy = False
        self._phase = 0.0
        self._track = QColor("#d8dce4")
        self._fill = QColor("#2f6fed")
        self.setMinimumHeight(6)
        self.setMaximumHeight(6)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self._animation = QVariantAnimation(self)
        self._animation.setDuration(260)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animation.valueChanged.connect(self._on_animated)

        self._busy_timer = QTimer(self)
        self._busy_timer.setInterval(16)
        self._busy_timer.timeout.connect(self._tick)

    def apply_palette(self, palette: Palette) -> None:
        self._track = QColor(palette.surface_alt if not palette.is_dark else palette.border)
        self._fill = QColor(palette.accent)
        self.update()

    def set_value(self, percent: float) -> None:
        self._stop_busy()
        self._target = max(0.0, min(100.0, percent))
        self._animation.stop()
        self._animation.setStartValue(self._value)
        self._animation.setEndValue(self._target)
        self._animation.start()

    def set_busy(self) -> None:
        if self._busy:
            return
        self._busy = True
        self._animation.stop()
        self._value = 0.0
        self._busy_timer.start()
        self.update()

    def reset(self) -> None:
        self._stop_busy()
        self._value = self._target = 0.0
        self.update()

    def _stop_busy(self) -> None:
        if self._busy:
            self._busy = False
            self._busy_timer.stop()

    def _on_animated(self, value: object) -> None:
        self._value = float(value)  # type: ignore[arg-type]
        self.update()

    def _tick(self) -> None:
        self._phase = (self._phase + 0.012) % 1.0
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        radius = self.height() / 2

        track = QPainterPath()
        track.addRoundedRect(0, 0, self.width(), self.height(), radius, radius)
        painter.fillPath(track, self._track)

        if self._busy:
            width = max(self.width() * 0.28, 40)
            travel = self.width() + width
            offset = self._phase * travel - width
            path = QPainterPath()
            path.addRoundedRect(offset, 0, width, self.height(), radius, radius)
            painter.setClipPath(track)
            painter.fillPath(path, self._fill)
            return

        filled = self.width() * self._value / 100.0
        if filled <= 0.5:
            return
        path = QPainterPath()
        path.addRoundedRect(0, 0, filled, self.height(), radius, radius)
        painter.fillPath(path, self._fill)


class Toast(QFrame):
    """Transient message that slides up from the bottom of the window."""

    def __init__(self, text: str, severity: str, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("toast")
        self.setProperty("severity", severity)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        label = QLabel(text)
        label.setWordWrap(True)
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(label)

        self.adjustSize()
        self._effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._effect)
        self._effect.setOpacity(0.0)

        self._fade = QPropertyAnimation(self._effect, b"opacity", self)
        self._fade.setDuration(180)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)

    def show_at(self, x: int, y: int) -> None:
        self.move(x, y + 12)
        self.show()
        self.raise_()
        self._fade.stop()
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.start()

        self._slide = QPropertyAnimation(self, b"pos", self)
        self._slide.setDuration(220)
        self._slide.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._slide.setStartValue(self.pos())
        self._slide.setEndValue(self.pos().__class__(x, y))
        self._slide.start()

    def dismiss(self) -> None:
        self._fade.stop()
        self._fade.setStartValue(self._effect.opacity())
        self._fade.setEndValue(0.0)
        self._fade.finished.connect(self.deleteLater)
        self._fade.start()


class DownloadRow(QFrame):
    """One download: name, quality badge, progress and its actions."""

    cancel_requested = Signal(str)
    open_requested = Signal(str)
    folder_requested = Signal(str)
    remove_requested = Signal(str)

    def __init__(
        self,
        job_id: str,
        title: str,
        quality: int,
        palette: Palette,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("download-row")
        self.setProperty("state", "active")
        self.job_id = job_id
        self.path = ""
        self._palette = palette

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(7)

        top = QHBoxLayout()
        top.setSpacing(8)
        self.title_label = ElidedLabel(title)
        self.title_label.setObjectName("row-title")
        self.badge = QLabel(f"{quality}p")
        self.badge.setObjectName("badge")
        self.cancel_button = QPushButton()
        self.cancel_button.setObjectName("icon")
        self.cancel_button.setFixedSize(QSize(28, 28))
        self.cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_button.clicked.connect(lambda: self.cancel_requested.emit(self.job_id))
        top.addWidget(self.title_label, 1)
        top.addWidget(self.badge)
        top.addWidget(self.cancel_button)

        self.bar = ProgressBar()
        self.detail = ElidedLabel("")
        self.detail.setObjectName("row-detail")

        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        bottom.addWidget(self.detail, 1)
        self.open_button = QPushButton()
        self.open_button.setObjectName("link")
        self.open_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_button.clicked.connect(lambda: self.open_requested.emit(self.path))
        self.open_button.hide()
        self.folder_button = QPushButton()
        self.folder_button.setObjectName("link")
        self.folder_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.folder_button.clicked.connect(lambda: self.folder_requested.emit(self.path))
        self.folder_button.hide()
        bottom.addWidget(self.open_button)
        bottom.addWidget(self.folder_button)

        layout.addLayout(top)
        layout.addWidget(self.bar)
        layout.addLayout(bottom)
        self.apply_palette(palette)

    def apply_palette(self, palette: Palette) -> None:
        self._palette = palette
        self.cancel_button.setIcon(icon("close", palette.text_muted, 16))
        self.open_button.setText(t("open_file"))
        self.folder_button.setText(t("open_folder"))
        self.bar.apply_palette(palette)
        self._restyle()

    def retranslate(self) -> None:
        self.apply_palette(self._palette)

    def update_progress(self, snapshot: ProgressSnapshot) -> None:
        if snapshot.total:
            self.bar.set_value(100.0 * snapshot.downloaded / snapshot.total)
        elif (
            not snapshot.total and snapshot.stage in {"processing", "finished"}
        ) or snapshot.downloaded:
            self.bar.set_busy()

        if snapshot.stage == "processing":
            self.detail.setText(t("stage_processing"))
            self.detail.setProperty("state", "")
        elif snapshot.stage == "finished":
            self.detail.setText(t("stage_finished"))
            self.detail.setProperty("state", "")
        else:
            self.detail.setText(_progress_details(snapshot))
            self.detail.setProperty("state", "")
        self._restyle()

    def mark_done(self, path: str) -> None:
        self.path = path
        self.setProperty("state", "done")
        self.bar.set_value(100.0)
        self.detail.setText(t("saved_to", path=path))
        self.detail.setProperty("state", "success")
        self._finish()
        self.open_button.show()
        self.folder_button.show()
        self._restyle()

    def mark_cancelled(self) -> None:
        self.setProperty("state", "failed")
        self.detail.setText(t("cancelled"))
        self.detail.setProperty("state", "")
        self.bar.reset()
        self._finish()

    def mark_failed(self, detail: str) -> None:
        self.setProperty("state", "failed")
        self.detail.setText(t("failed", detail=detail))
        self.detail.setProperty("state", "error")
        self.bar.reset()
        self._finish()

    def mark_queued(self) -> None:
        self.detail.setText(t("queued"))
        self.bar.set_busy()

    def _finish(self) -> None:
        self.cancel_button.hide()
        self._restyle()

    def _restyle(self) -> None:
        for widget in (self, self.detail):
            widget.style().unpolish(widget)
            widget.style().polish(widget)


def _progress_details(snapshot: ProgressSnapshot) -> str:
    parts: list[str] = []
    if snapshot.fragments:
        if snapshot.total:
            parts.append(f"{snapshot.downloaded}/{snapshot.total}")
    elif snapshot.total:
        parts.append(f"{_size(snapshot.downloaded)} / {_size(snapshot.total)}")
    elif snapshot.downloaded:
        parts.append(_size(snapshot.downloaded))
    if snapshot.speed:
        parts.append(_speed(snapshot.speed))
    if snapshot.eta:
        parts.append(t("eta", time=_duration(snapshot.eta)))
    elif not snapshot.fragments and snapshot.total and snapshot.speed and snapshot.downloaded:
        remaining = (snapshot.total - snapshot.downloaded) / snapshot.speed
        if remaining > 0:
            parts.append(t("eta", time=_duration(remaining)))
    return " · ".join(parts)


def _size(value: float | int | None) -> str:
    if not value:
        return "0 B"
    number = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if number < 1024 or unit == "TB":
            return f"{number:.0f} {unit}" if unit == "B" else f"{number:.1f} {unit}"
        number /= 1024
    return ""


def _speed(value: float) -> str:
    number = float(value)
    for unit in ("B/s", "KB/s", "MB/s", "GB/s"):
        if number < 1024 or unit == "GB/s":
            return f"{number:.1f} {unit}"
        number /= 1024
    return ""


def _duration(seconds: float) -> str:
    total = int(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


class FadeMixin:
    """Helper for the short opacity animation used when panels appear."""

    @staticmethod
    def fade_in(widget: QWidget, duration: int = 220, start: float = 0.0) -> None:
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
        effect.setOpacity(start)
        animation = QPropertyAnimation(effect, b"opacity", widget)
        animation.setDuration(duration)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.setStartValue(start)
        animation.setEndValue(1.0)
        # Drop the effect once it is done: a live opacity effect forces the
        # whole subtree through an offscreen buffer on every repaint.
        animation.finished.connect(
            lambda: widget.setGraphicsEffect(None)  # type: ignore[arg-type]
        )
        animation.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
