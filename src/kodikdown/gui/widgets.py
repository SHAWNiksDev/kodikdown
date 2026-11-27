"""Small self-contained widgets: elided labels, animated progress, toasts, rows."""

from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    QTimer,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QContextMenuEvent,
    QFontMetrics,
    QHideEvent,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QResizeEvent,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QStyle,
    QStyleOptionButton,
    QVBoxLayout,
    QWidget,
)

from kodikdown.downloader import ProgressSnapshot
from kodikdown.gui.icons import icon
from kodikdown.gui.theme import LIGHT, Palette
from kodikdown.i18n import t


class CheckBox(QCheckBox):
    """Keep an explicit check mark when the stylesheet paints the indicator."""

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        if not self.isChecked():
            return
        option = QStyleOptionButton()
        self.initStyleOption(option)
        rect = self.style().subElementRect(QStyle.SubElement.SE_CheckBoxIndicator, option, self)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor("#ffffff"), 2.1)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setOpacity(1.0 if self.isEnabled() else 0.5)
        check = QPainterPath()
        check.moveTo(rect.x() + rect.width() * 0.23, rect.y() + rect.height() * 0.50)
        check.lineTo(rect.x() + rect.width() * 0.43, rect.y() + rect.height() * 0.70)
        check.lineTo(rect.x() + rect.width() * 0.77, rect.y() + rect.height() * 0.29)
        painter.drawPath(check)


class SettingsSwitch(QCheckBox):
    """Keyboard-accessible checkbox painted as a readable Android-like switch."""

    def __init__(self) -> None:
        super().__init__()
        self._palette = LIGHT
        self._fraction = 0.0
        self._animation = QVariantAnimation(self)
        self._animation.setDuration(130)
        self._animation.valueChanged.connect(self._advance)
        self.toggled.connect(self._toggle)

    def apply_palette(self, palette: Palette) -> None:
        self._palette = palette
        self.update()

    def setChecked(self, checked: bool) -> None:
        if checked != self.isChecked():
            self._animation.stop()
            self._fraction = float(checked)
        super().setChecked(checked)

    def _toggle(self, checked: bool) -> None:
        self._animation.stop()
        self._animation.setStartValue(self._fraction)
        self._animation.setEndValue(float(checked))
        self._animation.start()

    def _advance(self, value: object) -> None:
        self._fraction = float(value)  # type: ignore[arg-type]
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(self.fontMetrics().horizontalAdvance(self.text()) + 54, 36)

    def hitButton(self, pos: QPoint) -> bool:
        return bool(self.rect().contains(pos))

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.isEnabled():
            painter.setOpacity(0.5)
        y = (self.height() - 22) / 2
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(
            QColor(self._palette.accent if self.isChecked() else self._palette.border_strong)
        )
        painter.drawRoundedRect(QRectF(0, y, 40, 22), 11, 11)
        painter.setBrush(QColor("#ffffff" if self.isChecked() else self._palette.text_muted))
        painter.drawEllipse(QRectF(3 + 18 * self._fraction, y + 3, 16, 16))
        painter.setPen(QColor(self._palette.text))
        text_rect = self.rect().adjusted(52, 0, 0, 0)
        text = self.fontMetrics().elidedText(
            self.text(), Qt.TextElideMode.ElideRight, text_rect.width()
        )
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter, text)
        if self.hasFocus():
            painter.setPen(QColor(self._palette.accent))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(self.rect().adjusted(0, 1, -1, -1), 6, 6)


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
        self._track = QColor("#e2e8f0")
        self._fill = QColor("#2563eb")
        self.setMinimumHeight(8)
        self.setMaximumHeight(8)
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
        if self.isVisible():
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

    def hideEvent(self, event: QHideEvent) -> None:
        self._busy_timer.stop()
        super().hideEvent(event)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if self._busy:
            self._busy_timer.start()

    def _on_animated(self, value: object) -> None:
        self._value = float(value)  # type: ignore[arg-type]
        self.update()

    def _tick(self) -> None:
        self._phase = (self._phase + 0.012) % 1.0
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        radius = self.height() / 2.0

        track = QPainterPath()
        track.addRoundedRect(0, 0, self.width(), self.height(), radius, radius)
        painter.fillPath(track, self._track)

        if self._busy:
            width = max(self.width() * 0.35, 60.0)
            travel = self.width() + width
            offset = self._phase * travel - width
            path = QPainterPath()
            path.addRoundedRect(offset, 0, width, self.height(), radius, radius)
            gradient = QLinearGradient(offset, 0, offset + width, 0)
            c = self._fill
            gradient.setColorAt(0.0, QColor(c.red(), c.green(), c.blue(), 0))
            gradient.setColorAt(0.5, c)
            gradient.setColorAt(1.0, QColor(c.red(), c.green(), c.blue(), 0))
            painter.setClipPath(track)
            painter.fillPath(path, gradient)
            return

        filled = self.width() * self._value / 100.0
        if filled <= 0.5:
            return
        path = QPainterPath()
        path.addRoundedRect(0, 0, filled, self.height(), radius, radius)
        gradient = QLinearGradient(0, 0, filled, 0)
        gradient.setColorAt(0.0, self._fill.lighter(115))
        gradient.setColorAt(1.0, self._fill)
        painter.fillPath(path, gradient)


class Toast(QFrame):
    """Transient message that slides up from the bottom of the window."""

    def __init__(
        self,
        text: str,
        severity: str,
        parent: QWidget,
        palette: Palette | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("toast")
        self.setProperty("severity", severity)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 9, 16, 9)
        layout.setSpacing(10)

        icon_name = (
            "check"
            if severity == "success"
            else "warning"
            if severity in ("error", "warning")
            else "info"
        )
        icon_color = (
            "#ffffff"
            if (palette is None or palette.is_dark or severity in ("error", "success", "warning"))
            else palette.surface
        )
        self._icon_label = QLabel()
        self._icon_label.setFixedSize(18, 18)
        self._icon_label.setPixmap(icon(icon_name, icon_color, 18).pixmap(18, 18))
        self._icon_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(self._icon_label)

        label = QLabel(text)
        label.setObjectName("toast-text")
        label.setWordWrap(True)
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(label, 1)

        self.adjustSize()
        self._effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._effect)
        self._effect.setOpacity(0.0)

        self._fade = QPropertyAnimation(self._effect, b"opacity", self)
        self._fade.setDuration(180)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)

    def show_at(self, x: int, y: int) -> None:
        if not self.isVisible():
            self.move(x, y + 14)
            self.show()
            self.raise_()
            self._fade.stop()
            self._fade.setStartValue(0.0)
            self._fade.setEndValue(1.0)
            self._fade.start()
        else:
            self.raise_()

        self._slide = QPropertyAnimation(self, b"pos", self)
        self._slide.setDuration(240)
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
    selection_requested = Signal(str)
    pause_requested = Signal(str)
    resume_requested = Signal(str)
    priority_requested = Signal(str)

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
        self._terminal = False
        self.setProperty("selected", False)
        self._assembling = False
        self._outcome = ""
        self._failure_detail = ""
        self._available = True
        self._last_snapshot: ProgressSnapshot | None = None
        self._stage = "starting"
        self._palette = palette

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(7)

        top = QHBoxLayout()
        top.setSpacing(8)
        self.title_label = ElidedLabel(title)
        self.title_label.setObjectName("row-title")
        self.status_icon = QLabel()
        self.status_icon.hide()
        self.badge = QLabel(f"{quality}p" if quality else t("quality_auto"))
        self.badge.setObjectName("badge")
        self.cancel_button = QPushButton()
        self.cancel_button.setObjectName("icon")
        self.cancel_button.setFixedSize(QSize(28, 28))
        self.cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_button.clicked.connect(
            lambda: (
                self.remove_requested.emit(self.job_id)
                if self._terminal
                else self.cancel_requested.emit(self.job_id)
            )
        )
        top.addWidget(self.title_label, 1)
        top.addWidget(self.status_icon)
        top.addWidget(self.badge)
        self.actions_button = QPushButton("…")
        self.actions_button.setObjectName("icon")
        self.actions_button.setFixedSize(QSize(28, 28))
        self.actions_button.clicked.connect(self._queue_menu)
        top.addWidget(self.actions_button)
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
        self.cancel_button.setToolTip(t("remove") if self._terminal else t("cancel"))
        self.actions_button.setToolTip(t("queue_actions"))
        self.actions_button.setAccessibleName(t("queue_actions"))
        self.open_button.setText(t("open_file"))
        self.open_button.setIcon(icon("play", palette.accent, 14))
        self.folder_button.setText(t("open_folder"))
        self.folder_button.setIcon(icon("folder", palette.accent, 14))
        state = self.property("state")
        if state == "done":
            self.status_icon.setPixmap(icon("check", palette.success, 16).pixmap(16, 16))
        elif state == "failed":
            self.status_icon.setPixmap(icon("warning", palette.danger, 16).pixmap(16, 16))
        self.bar.apply_palette(palette)
        self._restyle()

    def retranslate(self) -> None:
        self.apply_palette(self._palette)
        if self._outcome == "done":
            self.refresh_availability(self._available)
        elif self._outcome == "cancelled":
            self.detail.setText(t("cancelled"))
        elif self._outcome == "failed":
            self.detail.setText(t("failed", detail=self._failure_detail))
        elif self._last_snapshot is not None:
            self.update_progress(self._last_snapshot)
        else:
            self.detail.setText(t(self._stage))

    def refresh_availability(self, available: bool) -> None:
        if self._outcome != "done":
            return
        self._available = available
        self.setProperty("state", "done" if available else "missing")
        self.detail.setText(t("saved_to", path=self.path) if available else t("file_missing"))
        self.detail.setProperty("state", "success" if available else "")
        self.open_button.setVisible(available)
        self.folder_button.setVisible(available)
        self.status_icon.setPixmap(
            icon(
                "check" if available else "warning",
                self._palette.success if available else self._palette.text_muted,
                16,
            ).pixmap(16, 16)
        )
        self._restyle()

    def update_progress(self, snapshot: ProgressSnapshot) -> None:
        self._last_snapshot = snapshot
        if snapshot.source != "monitor":
            self._assembling = snapshot.stage in {"processing", "finished"}
        self.cancel_button.setVisible(not self._assembling)
        self.actions_button.setVisible(not self._assembling)
        if self._assembling:
            self.bar.set_busy()
            self.detail.setText(t("stage_processing"))
            self.detail.setProperty("state", "")
            self._restyle()
            return
        if snapshot.quality is not None:
            self.badge.setText(f"{snapshot.quality}p" if snapshot.quality else t("quality_auto"))
            self.bar.reset()
        if snapshot.source == "monitor":
            # Only the byte counter is known; keep whatever the bar shows.
            self.detail.setText(_progress_details(snapshot))
            self.detail.setProperty("state", "")
            self._restyle()
            return
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
        self._outcome = "done"
        self._available = True
        self.path = path
        self.setProperty("state", "done")
        self.bar.set_value(100.0)
        self.detail.setText(t("saved_to", path=path))
        self.detail.setProperty("state", "success")
        self._finish()
        self.actions_button.hide()
        self.status_icon.setPixmap(icon("check", self._palette.success, 16).pixmap(16, 16))
        self.status_icon.show()
        FadeMixin.fade_in(self.status_icon, duration=220)
        self.open_button.setIcon(icon("play", self._palette.accent, 14))
        self.folder_button.setIcon(icon("folder", self._palette.accent, 14))
        self.open_button.show()
        self.folder_button.show()
        self._restyle()

    def mark_cancelled(self) -> None:
        self._outcome = "cancelled"
        self.setProperty("state", "failed")
        self.detail.setText(t("cancelled"))
        self.detail.setProperty("state", "")
        self.bar.reset()
        self._finish()
        self.actions_button.hide()
        self.status_icon.setPixmap(icon("close", self._palette.text_muted, 16).pixmap(16, 16))
        self.status_icon.show()
        self._restyle()

    def mark_failed(self, detail: str) -> None:
        self._outcome = "failed"
        self._failure_detail = detail
        self.setProperty("state", "failed")
        self.detail.setText(t("failed", detail=detail))
        self.detail.setProperty("state", "error")
        self.bar.reset()
        self._finish()
        self.actions_button.show()
        self.status_icon.setPixmap(icon("warning", self._palette.danger, 16).pixmap(16, 16))
        self.status_icon.show()
        FadeMixin.fade_in(self.status_icon, duration=220)
        self._restyle()

    def mark_starting(self) -> None:
        self._stage = "starting"
        self.detail.setText(t("starting"))
        self.bar.set_busy()

    def mark_downloading(self) -> None:
        self._stage = "history_downloading"
        self.detail.setText(t(self._stage))

    def mark_queued(self) -> None:
        self._stage = "queued"
        self.detail.setText(t("queued"))
        self.bar.set_busy()

    def mark_cancelling(self) -> None:
        self._stage = "cancelling"
        self.detail.setText(t("cancelling"))
        self.actions_button.hide()

    def mark_paused(self) -> None:
        self._stage = "history_paused"
        self._last_snapshot = None
        self.bar.reset()
        self.detail.setText(t(self._stage))
        self.actions_button.show()

    def reset_for_queue(self) -> None:
        self._terminal = self._assembling = False
        self._outcome = ""
        self._last_snapshot = None
        self.setProperty("state", "active")
        self.setProperty("selected", False)
        self.setToolTip("")
        self.status_icon.hide()
        self.detail.setProperty("state", "")
        self.cancel_button.setToolTip(t("cancel"))
        self.mark_queued()
        self._restyle()

    def _queue_menu(self) -> None:
        menu = QMenu(self)
        if self._outcome == "failed":
            menu.addAction(t("download_again"), lambda: self.resume_requested.emit(self.job_id))
        elif self._stage == "history_paused":
            menu.addAction(t("resume_download"), lambda: self.resume_requested.emit(self.job_id))
        else:
            menu.addAction(t("pause_download"), lambda: self.pause_requested.emit(self.job_id))
            if self._stage in ("starting", "queued"):
                menu.addAction(
                    t("prioritize_download"), lambda: self.priority_requested.emit(self.job_id)
                )
        menu.exec(self.actions_button.mapToGlobal(self.actions_button.rect().bottomLeft()))
        menu.deleteLater()

    def _finish(self) -> None:
        self._terminal = True
        self.cancel_button.setEnabled(True)
        self.cancel_button.setToolTip(t("remove"))
        self.cancel_button.show()
        self.setToolTip(t("select_download_hint"))
        self._restyle()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if (
            self._terminal
            and event.button() == Qt.MouseButton.LeftButton
            and event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            self.selection_requested.emit(self.job_id)
            event.accept()
            return
        super().mousePressEvent(event)

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        menu = QMenu(self)
        if self._terminal:
            menu.addAction(t("remove"), lambda: self.remove_requested.emit(self.job_id))
        elif not self._assembling:
            menu.addAction(t("stop_download"), lambda: self.cancel_requested.emit(self.job_id))
        else:
            return
        menu.exec(event.globalPos())

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
    return " · ".join(parts) or t("history_downloading")


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
    """Short opacity effects for rows and progress indicators."""

    @staticmethod
    def fade_in(widget: QWidget, duration: int = 220, start: float = 0.0) -> None:
        if widget.window().property("kodikdownAnimations") is False:
            return
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
