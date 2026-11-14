"""Library and history pages with native desktop multiple selection."""

from __future__ import annotations

from PySide6.QtCore import QDateTime, QLocale, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from kodikdown.gui.icons import icon
from kodikdown.gui.media_store import HistoryEntry, MediaFile
from kodikdown.gui.theme import Palette
from kodikdown.i18n import current_language, t


class MediaPage(QWidget):
    play_requested = Signal(str)
    reveal_requested = Signal(str)
    retry_requested = Signal(str)
    copy_requested = Signal(str)
    delete_requested = Signal(object)
    refresh_requested = Signal()

    def __init__(self, *, history: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.is_history = history
        self._palette: Palette | None = None
        self._history: tuple[HistoryEntry, ...] = ()
        self._files: tuple[MediaFile, ...] = ()
        self._available: dict[str, bool] = {}
        self._active: set[str] = set()
        self._signature: object = None
        self._paths: dict[str, str] = {}
        self._entries: dict[str, HistoryEntry] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 14)
        layout.setSpacing(14)
        header = QHBoxLayout()
        self.heading = QLabel()
        self.heading.setObjectName("page-title")
        header.addWidget(self.heading)
        header.addStretch(1)
        self.count = QLabel()
        self.count.setObjectName("muted")
        header.addWidget(self.count)
        self.refresh_button = QPushButton()
        self.refresh_button.clicked.connect(self.refresh_requested.emit)
        header.addWidget(self.refresh_button)
        layout.addLayout(header)
        self.table = QTreeWidget()
        self.table.setObjectName("media-list")
        self.table.setRootIsDecorated(False)
        self.table.setUniformRowHeights(True)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setFrameShape(QFrame.Shape.NoFrame)
        self.table.setColumnCount(4)
        self.table.setIndentation(0)
        self.table.header().setStretchLastSection(False)
        self.table.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column, width in ((1, 180 if history else 100), (2, 90), (3, 155)):
            self.table.setColumnWidth(column, width)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.table.itemDoubleClicked.connect(lambda *_: self._play())
        layout.addWidget(self.table, 1)
        self.empty = QLabel()
        self.empty.setObjectName("muted")
        self.empty.setWordWrap(True)
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.empty, 1)
        actions = QHBoxLayout()
        self.play_button = QPushButton()
        self.play_button.setObjectName("primary")
        self.play_button.clicked.connect(self._play)
        actions.addWidget(self.play_button)
        self.retry_button = QPushButton()
        self.retry_button.clicked.connect(self._retry)
        self.retry_button.setVisible(history)
        actions.addWidget(self.retry_button)
        self.reveal_button = QPushButton()
        self.reveal_button.clicked.connect(self._reveal)
        self.reveal_button.setVisible(not history)
        actions.addWidget(self.reveal_button)
        self.copy_button = QPushButton()
        self.copy_button.clicked.connect(self._copy)
        self.copy_button.setVisible(history)
        actions.addWidget(self.copy_button)
        actions.addStretch(1)
        self.delete_button = QPushButton()
        self.delete_button.setObjectName("danger")
        self.delete_button.clicked.connect(lambda: self.delete_requested.emit(self.selected_ids()))
        actions.addWidget(self.delete_button)
        layout.addLayout(actions)
        self.retranslate()

    def selected_ids(self) -> set[str]:
        return {item.data(0, Qt.ItemDataRole.UserRole) for item in self.table.selectedItems()}

    def set_history(
        self, entries: tuple[HistoryEntry, ...], available: dict[str, bool], active: set[str]
    ) -> None:
        self._history, self._available, self._active = entries, available, active
        self._populate()

    def set_files(self, files: tuple[MediaFile, ...]) -> None:
        self._files = files
        self._populate()

    def _populate(self, *, force: bool = False) -> None:
        signature = (
            (self._history, tuple(self._available.items()), frozenset(self._active))
            if self.is_history
            else self._files
        )
        if not force and signature == self._signature:
            return
        self._signature = signature
        selected = self.selected_ids()
        scroll = self.table.verticalScrollBar().value()
        self.table.blockSignals(True)
        self.table.clear()
        self._paths.clear()
        self._entries = {entry.id: entry for entry in self._history}
        locale = QLocale(current_language())
        if self.is_history:
            for entry in self._history:
                available = self._available.get(entry.path, False)
                status = (
                    t("file_missing")
                    if entry.status == "finished" and not available
                    else t("history_" + entry.status)
                )
                row = QTreeWidgetItem(
                    [
                        entry.title,
                        f"{entry.quality}p · {status}",
                        _size(entry.file_size) if entry.file_size else "—",
                        locale.toString(
                            QDateTime.fromSecsSinceEpoch(int(entry.created)), "dd MMM HH:mm"
                        ),
                    ]
                )
                row.setToolTip(
                    0, entry.title + (" · " + entry.translation if entry.translation else "")
                )
                row.setToolTip(1, entry.error or status)
                row.setData(0, Qt.ItemDataRole.UserRole, entry.id)
                self._paths[entry.id] = entry.path
                if self._palette is not None:
                    colour = (
                        self._palette.success
                        if entry.status == "finished" and available
                        else self._palette.danger
                        if entry.status == "failed"
                        else self._palette.text_muted
                    )
                    row.setForeground(1, QColor(colour))
                self.table.addTopLevelItem(row)
                row.setSelected(entry.id in selected)
        else:
            for file in self._files:
                row = QTreeWidgetItem(
                    [
                        file.title,
                        t("available"),
                        _size(file.size),
                        locale.toString(
                            QDateTime.fromSecsSinceEpoch(int(file.modified)), "dd MMM HH:mm"
                        ),
                    ]
                )
                row.setData(0, Qt.ItemDataRole.UserRole, file.path)
                row.setToolTip(0, file.path)
                self._paths[file.path] = file.path
                self.table.addTopLevelItem(row)
                row.setSelected(file.path in selected)
        self.table.blockSignals(False)
        self.table.verticalScrollBar().setValue(scroll)
        count = self.table.topLevelItemCount()
        self.count.setText(t("video_count", count=count))
        self.table.setVisible(count > 0)
        self.empty.setVisible(count == 0)
        self._selection_changed()

    def _selection_changed(self) -> None:
        selected = self.selected_ids()
        single = next(iter(selected)) if len(selected) == 1 else None
        path = self._paths.get(single, "") if single else ""
        available = bool(path) and (self._available.get(path, False) if self.is_history else True)
        self.play_button.setEnabled(available)
        self.reveal_button.setEnabled(available)
        self.retry_button.setEnabled(single is not None and single not in self._active)
        entry = self._entries.get(single) if single else None
        self.copy_button.setEnabled(entry is not None and bool(entry.source_input))
        self.delete_button.setEnabled(bool(selected) and not bool(selected & self._active))

    def _play(self) -> None:
        if self.play_button.isEnabled():
            identifier = next(iter(self.selected_ids()))
            self.play_requested.emit(self._paths[identifier])

    def _reveal(self) -> None:
        if self.reveal_button.isEnabled():
            self.reveal_requested.emit(self._paths[next(iter(self.selected_ids()))])

    def _retry(self) -> None:
        if self.retry_button.isEnabled():
            self.retry_requested.emit(next(iter(self.selected_ids())))

    def _copy(self) -> None:
        if self.copy_button.isEnabled():
            self.copy_requested.emit(next(iter(self.selected_ids())))

    def apply_palette(self, palette: Palette) -> None:
        self._palette = palette
        for button, name in (
            (self.play_button, "play"),
            (self.retry_button, "download"),
            (self.reveal_button, "folder"),
            (self.copy_button, "clipboard"),
            (self.delete_button, "trash"),
            (self.refresh_button, "refresh"),
        ):
            button.setIcon(
                icon(name, "#ffffff" if button is self.play_button else palette.text_muted, 16)
            )
        self._populate(force=True)

    def retranslate(self) -> None:
        self.heading.setText(t("tab_history" if self.is_history else "tab_library"))
        self.empty.setText(t("history_empty" if self.is_history else "library_empty"))
        self.table.setHeaderLabels([t("file_name"), t("status"), t("file_size"), t("date")])
        for button, key in (
            (self.play_button, "play"),
            (self.retry_button, "download_again"),
            (self.reveal_button, "open_folder"),
            (self.copy_button, "copy_link"),
            (self.delete_button, "remove" if self.is_history else "delete_file"),
            (self.refresh_button, "refresh"),
        ):
            button.setText(t(key))
        self._populate(force=True)


def _size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return ""
