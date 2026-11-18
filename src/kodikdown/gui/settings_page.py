"""Settings inside the main window; edits are applied and persisted immediately."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from kodikdown import __version__
from kodikdown.config import Settings
from kodikdown.gui.icons import icon
from kodikdown.gui.theme import Palette
from kodikdown.gui.widgets import SettingsSwitch
from kodikdown.i18n import t


class NoWheelSpinBox(QSpinBox):
    def wheelEvent(self, event: QWheelEvent) -> None:
        event.ignore()


class NoWheelComboBox(QComboBox):
    def wheelEvent(self, event: QWheelEvent) -> None:
        event.ignore()


class SettingsPage(QScrollArea):
    change_requested = Signal(object, object)
    reset_requested = Signal()
    clear_finished_requested = Signal()
    clear_history_requested = Signal()
    github_requested = Signal()

    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._settings = settings
        self._labels: list[tuple[QLabel | QPushButton, str]] = []
        self._transfer_controls: list[QWidget] = []
        body = QWidget()
        self.setWidget(body)
        root = QVBoxLayout(body)
        root.setContentsMargins(22, 18, 22, 24)
        root.setSpacing(12)
        self._label(root, "settings_title", "page-title")
        self._label(root, "settings_appearance", "section")
        appearance = self._card(root)
        self._label(appearance, "theme")
        self.theme_buttons = self._choices(appearance, ("auto", "light", "dark"), "theme")
        self._label(appearance, "language")
        self.language_buttons = self._choices(appearance, ("auto", "ru", "en"), "language")
        self._check(appearance, "animations", "animations")

        self._label(root, "settings_downloads", "section")
        downloads = self._card(root)
        self.lock_hint = self._label(downloads, "settings_transfer_locked", "warning")
        self.lock_hint.hide()
        self._label(downloads, "download_dir")
        folder_row = QHBoxLayout()
        self.folder_edit = QLineEdit()
        self.folder_edit.setMinimumWidth(120)
        self.folder_edit.editingFinished.connect(self._folder_edited)
        self.browse_button = QPushButton()
        self._labels.append((self.browse_button, "browse"))
        self.browse_button.clicked.connect(self._browse)
        self.folder_reset_button = QPushButton()
        self._labels.append((self.folder_reset_button, "reset_folder"))
        self.folder_reset_button.clicked.connect(
            lambda: self._change("download_dir", Settings().download_dir, self.folder_reset_button)
        )
        folder_row.addWidget(self.folder_edit, 1)
        folder_row.addWidget(self.browse_button)
        folder_row.addWidget(self.folder_reset_button)
        downloads.addLayout(folder_row)
        self._transfer_controls.extend(
            (self.folder_edit, self.browse_button, self.folder_reset_button)
        )
        concurrent_row = QHBoxLayout()
        self._label(concurrent_row, "concurrent_downloads").setWordWrap(False)
        concurrent_row.addStretch(1)
        self.concurrent_spin = NoWheelSpinBox()
        self.concurrent_spin.setObjectName("concurrency-stepper")
        self.concurrent_spin.setRange(1, 5)
        # NoButtons collapses the styled editor to one pixel on some Qt versions.
        # Hide native arrow subcontrols in the stylesheet instead.
        self.concurrent_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.concurrent_spin.setFixedWidth(54)
        self.minus_button = QPushButton("-")
        self.plus_button = QPushButton("+")
        for button in (self.minus_button, self.plus_button):
            button.setFixedWidth(38)
            button.setMinimumHeight(36)
        self.minus_button.clicked.connect(self.concurrent_spin.stepDown)
        self.plus_button.clicked.connect(self.concurrent_spin.stepUp)
        self.concurrent_spin.valueChanged.connect(
            lambda value: self._change("concurrent_downloads", value, self.concurrent_spin)
        )
        concurrent_row.addWidget(self.minus_button)
        concurrent_row.addWidget(self.concurrent_spin)
        concurrent_row.addWidget(self.plus_button)
        downloads.addLayout(concurrent_row)
        self._transfer_controls.extend((self.concurrent_spin, self.minus_button, self.plus_button))
        self._label(downloads, "default_quality")
        self.quality_combo = NoWheelComboBox()
        for value in ("ask", "1080", "720", "480", "360"):
            self.quality_combo.addItem(value, value)
        self.quality_combo.currentIndexChanged.connect(
            lambda: self._change(
                "default_quality", self.quality_combo.currentData(), self.quality_combo
            )
        )
        downloads.addWidget(self.quality_combo)
        self._transfer_controls.append(self.quality_combo)
        self._transfer_controls.append(self._check(downloads, "prefer_mp4", "prefer_mp4"))
        self._label(downloads, "prefer_mp4_hint", "muted")
        self._check(downloads, "auto_paste", "auto_paste")
        self._check(downloads, "group_series", "group_series")

        self._label(root, "settings_controls", "section")
        controls = self._card(root)
        self._check(controls, "confirm_cancel_download", "confirm_cancel_download")
        self._check(controls, "confirm_delete", "confirm_delete")
        self._label(root, "settings_storage", "section")
        storage = self._card(root)
        self.clear_finished_button = self._action(
            storage, "clear_finished", self.clear_finished_requested.emit
        )
        self.clear_history_button = self._action(
            storage, "clear_history", self.clear_history_requested.emit
        )
        self.reset_button = self._action(storage, "reset_defaults", self.reset_requested.emit)
        self._transfer_controls.append(self.reset_button)
        self._label(root, "about_section", "section")
        about = self._card(root)
        about.addWidget(QLabel(f"KodikDown {__version__}"))
        self.github_button = self._action(about, "GitHub", self.github_requested.emit)
        root.addStretch(1)
        self.bind(settings)
        self.retranslate()

    def _label(self, layout: QVBoxLayout | QHBoxLayout, key: str, role: str = "") -> QLabel:
        label = QLabel()
        label.setWordWrap(True)
        if role:
            label.setObjectName(role)
        self._labels.append((label, key))
        layout.addWidget(label)
        return label

    @staticmethod
    def _card(layout: QVBoxLayout) -> QVBoxLayout:
        card = QFrame()
        card.setObjectName("card")
        inner = QVBoxLayout(card)
        inner.setContentsMargins(16, 14, 16, 14)
        inner.setSpacing(12)
        layout.addWidget(card)
        return inner

    def _choices(
        self, layout: QVBoxLayout, choices: tuple[str, ...], field: str
    ) -> dict[str, QPushButton]:
        row = QHBoxLayout()
        group = QButtonGroup(self)
        group.setExclusive(True)
        buttons = {}
        for value in choices:
            button = QPushButton()
            button.setObjectName("setting-choice")
            button.setCheckable(True)
            button.setMinimumHeight(38)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            group.addButton(button)
            button.clicked.connect(
                lambda checked=False, code=value, origin=button: self._change(field, code, origin)
            )
            row.addWidget(button, 1)
            buttons[value] = button
        layout.addLayout(row)
        return buttons

    def _check(self, layout: QVBoxLayout, field: str, key: str) -> QCheckBox:
        check = SettingsSwitch()
        check.setObjectName("setting-switch")
        check.setMinimumHeight(32)
        check.setCursor(Qt.CursorShape.PointingHandCursor)
        setattr(self, field + "_check", check)
        check.toggled.connect(lambda value: self._change(field, value, check))
        # Labels for checkboxes are translated separately, without rebuilding controls.
        check.setProperty("translation_key", key)
        layout.addWidget(check)
        return check

    def _action(self, layout: QVBoxLayout, key: str, callback: object) -> QPushButton:
        button = QPushButton()
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._labels.append((button, key))
        button.clicked.connect(callback)
        layout.addWidget(button)
        return button

    def _change(self, field: str, value: object, origin: QWidget) -> None:
        # Field names and value types come only from the controls wired above.
        changes: dict[str, Any] = {field: value}
        self.change_requested.emit(replace(self._settings, **changes), origin)

    def _folder_edited(self) -> None:
        raw = self.folder_edit.text().strip()
        if raw:
            self._change("download_dir", Path(raw), self.folder_edit)
        else:
            self.folder_edit.setText(str(self._settings.download_dir))

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, t("download_dir"), str(self._settings.download_dir)
        )
        if folder:
            self._change("download_dir", Path(folder), self.browse_button)

    def bind(self, settings: Settings) -> None:
        self._settings = settings
        self.folder_edit.setText(str(settings.download_dir))
        self.theme_buttons[settings.theme].setChecked(True)
        self.language_buttons[settings.language].setChecked(True)
        with QSignalBlocker(self.concurrent_spin):
            self.concurrent_spin.setValue(settings.concurrent_downloads)
        with QSignalBlocker(self.quality_combo):
            self.quality_combo.setCurrentIndex(
                max(0, self.quality_combo.findData(settings.default_quality))
            )
        for field in (
            "prefer_mp4",
            "auto_paste",
            "confirm_cancel_download",
            "confirm_delete",
            "animations",
            "group_series",
        ):
            check = getattr(self, field + "_check")
            with QSignalBlocker(check):
                check.setChecked(getattr(settings, field))

    def set_transfer_locked(self, locked: bool) -> None:
        self.lock_hint.setVisible(locked)
        for control in self._transfer_controls:
            control.setEnabled(not locked)

    def apply_palette(self, palette: Palette) -> None:
        self.browse_button.setIcon(icon("folder", palette.text_muted, 16))
        self.github_button.setIcon(icon("github", palette.accent, 18))
        for switch in self.findChildren(SettingsSwitch):
            switch.apply_palette(palette)

    def retranslate(self) -> None:
        for widget, key in self._labels:
            widget.setText(t(key))
        for value, button in self.theme_buttons.items():
            button.setText(t("theme_" + value))
        for value, button in self.language_buttons.items():
            button.setText(
                t("language_auto") if value == "auto" else "Русский" if value == "ru" else "English"
            )
        for check in self.findChildren(QCheckBox):
            check.setText(t(check.property("translation_key")))
        with QSignalBlocker(self.quality_combo):
            self.quality_combo.setItemText(0, t("quality_ask"))
            for index in range(1, self.quality_combo.count()):
                self.quality_combo.setItemText(index, f"{self.quality_combo.itemData(index)}p")
