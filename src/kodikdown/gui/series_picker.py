"""Choose a player, voice-over and episodes from a catalogue entry."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap, QResizeEvent
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListView,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from kodikdown.gui.icons import icon
from kodikdown.gui.widgets import CheckBox
from kodikdown.i18n import t
from kodikdown.sources import Choice, Episode, Series

_BRANDS = {
    "cvh": "cvh",
    "shizaproject": "shiza",
    "anidub": "anidub",
    "animedia": "animedia",
    "anilibria": "aniliberty",
    "aniliberty": "aniliberty",
}


def _brand(name: str, *, player: bool = False) -> QIcon:
    key = "".join(character for character in name.casefold() if character.isalnum())
    if asset := _BRANDS.get(key):
        directory = Path(__file__).with_name("brands")
        return QIcon(str(directory / f"brand_{asset}.png"))
    return icon("play", "#8c9db3", 16) if player else QIcon()


class SeriesPicker(QFrame):
    download_requested = Signal()
    favorite_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("card")
        self.series: Series | None = None
        self._busy = False
        self._checked: set[str] = set()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(10)
        self.title = QLabel()
        self.title.setObjectName("panel-title")
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        self.title.setWordWrap(True)
        layout.addWidget(self.title)
        self.info_toggle = QPushButton()
        self.info_toggle.setCheckable(True)
        self.info_toggle.setChecked(True)
        self.info_toggle.toggled.connect(self._toggle_info)
        shortcuts = QHBoxLayout()
        shortcuts.addWidget(self.info_toggle)
        self.favorite = QPushButton()
        self.favorite.clicked.connect(self.favorite_requested.emit)
        shortcuts.addWidget(self.favorite)
        shortcuts.addStretch(1)
        layout.addLayout(shortcuts)
        self.info = QFrame()
        info = QHBoxLayout(self.info)
        info.setContentsMargins(0, 0, 0, 0)
        self.poster = QLabel()
        self.poster.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.description = QLabel()
        self.description.setWordWrap(True)
        self.description.setTextFormat(Qt.TextFormat.PlainText)
        info.addWidget(self.poster)
        info.addWidget(self.description, 1)
        layout.addWidget(self.info)

        options = QHBoxLayout()
        self.player = QComboBox()
        self.voice = QComboBox()
        self.quality = QComboBox()
        self.labels = tuple(QLabel() for _ in range(3))
        for label, field in zip(self.labels, (self.player, self.voice, self.quality), strict=True):
            label.setObjectName("muted")
            label.setBuddy(field)
            field.setSizeAdjustPolicy(
                QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
            )
            field.currentTextChanged.connect(field.setToolTip)
            field.setIconSize(QSize(17, 17))
            options.addWidget(label)
            options.addWidget(field, 1)
        layout.addLayout(options)

        self.episode_label = QLabel()
        self.episode_label.setObjectName("muted")
        layout.addWidget(self.episode_label)
        self.episodes = QListWidget()
        self.episodes.setObjectName("episode-list")
        self.episode_label.setBuddy(self.episodes)
        self.episodes.setViewMode(QListView.ViewMode.IconMode)
        self.episodes.setFlow(QListView.Flow.LeftToRight)
        self.episodes.setResizeMode(QListView.ResizeMode.Adjust)
        self.episodes.setMovement(QListView.Movement.Static)
        self.episodes.setGridSize(QSize(56, 36))
        self.episodes.setFixedHeight(40)
        self.episodes.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self.episodes.itemSelectionChanged.connect(self._on_episodes_changed)
        layout.addWidget(self.episodes)

        self.unavailable = QLabel()
        self.unavailable.setObjectName("muted")
        self.unavailable.setTextFormat(Qt.TextFormat.PlainText)
        self.unavailable.setWordWrap(True)
        layout.addWidget(self.unavailable)

        actions = QHBoxLayout()
        self.select_all = QPushButton()
        self.select_all.clicked.connect(self._toggle_all)
        self.download = QPushButton()
        self.download.setObjectName("primary")
        self.download.setMinimumWidth(144)
        self.download.clicked.connect(self.download_requested.emit)
        actions.addWidget(self.select_all)
        self.group = CheckBox()
        actions.addWidget(self.group)
        actions.addStretch(1)
        actions.addWidget(self.download)
        layout.addLayout(actions)

        self.player.currentTextChanged.connect(self._refresh_voices)
        self.voice.currentTextChanged.connect(self._refresh_episodes)
        self.retranslate()
        self.hide()

    def retranslate(self) -> None:
        self.favorite.setText(t("save_favorite"))
        for label, key in zip(self.labels, ("player", "translation", "quality"), strict=True):
            label.setText(t(key))
        self.episode_label.setText(t("episodes"))
        self.episodes.setAccessibleName(t("episodes"))
        quality = self.quality.currentData()
        self.quality.clear()
        for height in (1080, 720, 480, 360, 240, 144):
            self.quality.addItem(f"{height}p", height)
        self.quality.setCurrentIndex(max(0, self.quality.findData(quality)))
        self._refresh_unavailable()
        self._refresh_buttons()
        self.group.setText(t("group_series"))
        self._toggle_info(self.info_toggle.isChecked())

    def set_series(self, series: Series, quality: int, group: bool) -> None:
        self.series = series
        self._checked.clear()
        self.title.setText(series.title)
        description = " ".join(series.description.split())
        self.description.setText(description[:470] + ("…" if len(description) > 470 else ""))
        self.description.setToolTip(description)
        self.description.setVisible(bool(description))
        poster = QPixmap()
        if series.poster:
            poster.loadFromData(series.poster)
        self.poster.setVisible(not poster.isNull())
        if not poster.isNull():
            self.poster.setPixmap(
                poster.scaled(
                    65,
                    92,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        self.info_toggle.setVisible(bool(description) or not poster.isNull())
        self._toggle_info(self.info_toggle.isChecked())
        self.group.setChecked(group)
        self.quality.setCurrentIndex(max(0, self.quality.findData(quality)))
        self.player.blockSignals(True)
        self.player.clear()
        players = dict.fromkeys(choice.player for choice in series.choices)
        for player in sorted(players, key=lambda name: name.casefold() != "kodik"):
            self.player.addItem(_brand(player, player=True), player)
        self.player.blockSignals(False)
        self._refresh_voices()
        self._refresh_unavailable()
        self.show()

    def clear(self) -> None:
        self.series = None
        self.hide()

    def _toggle_info(self, expanded: bool) -> None:
        self.info_toggle.setText(t("hide_details" if expanded else "show_details"))
        self.info.setVisible(
            expanded and bool(self.series and (self.series.description or self.series.poster))
        )

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.setEnabled(not busy)
        self._refresh_buttons()

    def _refresh_voices(self) -> None:
        previous = self.voice.currentText()
        player = self.player.currentText()
        self.voice.blockSignals(True)
        self.voice.clear()
        if self.series:
            for choice in self.series.choices:
                if choice.player == player:
                    self.voice.addItem(_brand(choice.voice), choice.voice or "—", choice.voice)
        index = self.voice.findText(previous)
        self.voice.setCurrentIndex(max(0, index))
        self.voice.blockSignals(False)
        self._refresh_episodes()

    def choice(self) -> Choice | None:
        if self.series:
            player, voice = self.player.currentText(), self.voice.currentData()
            return next(
                (
                    choice
                    for choice in self.series.choices
                    if (choice.player, choice.voice) == (player, voice)
                ),
                None,
            )
        return None

    def selected(self, choice: Choice) -> list[Episode]:
        return [episode for episode in choice.episodes if episode.number in self._checked]

    def select_source(self, player: str, voice: str) -> bool:
        index = self.player.findText(player)
        if index < 0:
            return False
        self.player.setCurrentIndex(index)
        index = self.voice.findData(voice)
        if index < 0:
            return False
        self.voice.setCurrentIndex(index)
        return True

    def select_episodes(self, numbers: set[str]) -> None:
        self.episodes.blockSignals(True)
        for index in range(self.episodes.count()):
            item = self.episodes.item(index)
            item.setSelected(item.text() in numbers)
        self.episodes.blockSignals(False)
        self._on_episodes_changed()

    def _refresh_episodes(self) -> None:
        choice = self.choice()
        self.episodes.blockSignals(True)
        self.episodes.clear()
        for episode in choice.episodes if choice else ():
            item = QListWidgetItem(episode.number, self.episodes)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item.setSizeHint(QSize(52, 32))
            item.setSelected(episode.number in self._checked)
        self.episodes.blockSignals(False)
        if self.episodes.count() and not self._selected_count:
            self.episodes.item(0).setSelected(True)
        self._fit_episode_grid()
        self._refresh_buttons()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._fit_episode_grid()

    def _fit_episode_grid(self) -> None:
        size = self.episodes.gridSize()
        columns = max(1, self.episodes.width() // size.width())
        rows = max(1, (self.episodes.count() + columns - 1) // columns)
        self.episodes.setFixedHeight(min(4, rows) * size.height() + 4)

    def _on_episodes_changed(self) -> None:
        choice = self.choice()
        if choice:
            self._checked.difference_update(episode.number for episode in choice.episodes)
            self._checked.update(item.text() for item in self.episodes.selectedItems())
        self._refresh_buttons()

    def _toggle_all(self) -> None:
        if self._selected_count == self.episodes.count():
            self.episodes.clearSelection()
        else:
            self.episodes.selectAll()

    @property
    def _selected_count(self) -> int:
        choice = self.choice()
        return len(self.selected(choice)) if choice else 0

    def _refresh_buttons(self) -> None:
        count = self._selected_count
        all_checked = count > 0 and count == self.episodes.count()
        self.select_all.setText(t("clear_episodes" if all_checked else "select_all_episodes"))
        self.download.setText(t("download_episodes", count=count) if count else t("download"))
        self.download.setEnabled(count > 0 and not self._busy)

    def _refresh_unavailable(self) -> None:
        names = self.series.unavailable if self.series else ()
        self.unavailable.setVisible(bool(names))
        self.unavailable.setText(t("unsupported_players", names=", ".join(names)) if names else "")
