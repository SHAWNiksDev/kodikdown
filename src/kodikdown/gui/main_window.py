"""The main window: paste a link, pick a track, watch the downloads."""

from __future__ import annotations

import contextlib
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QEvent, QSize, Qt, QThreadPool, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QCloseEvent,
    QDesktopServices,
    QGuiApplication,
    QKeyEvent,
    QKeySequence,
    QResizeEvent,
    QShortcut,
)
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from kodikdown import __version__
from kodikdown.config import ConfigStore, Settings
from kodikdown.downloader import (
    ProgressSnapshot,
    fallback_sources_for,
    is_pending_output,
    safe_filename,
)
from kodikdown.gui.appearance import AppearanceOverlay
from kodikdown.gui.desktop import open_directory, open_path, reveal_path
from kodikdown.gui.icons import app_icon, icon
from kodikdown.gui.media_page import MediaPage
from kodikdown.gui.media_store import (
    DeleteFiles,
    HistoryChanges,
    HistoryEntry,
    HistoryStore,
    MediaFile,
    MediaScan,
    readable_file,
)
from kodikdown.gui.save_indicator import SaveIndicator
from kodikdown.gui.series_picker import SeriesPicker
from kodikdown.gui.settings_page import SettingsPage
from kodikdown.gui.theme import MODE_AUTO, palette_for, stylesheet
from kodikdown.gui.tray import DesktopTray
from kodikdown.gui.widgets import (
    CheckBox,
    DownloadRow,
    ElidedLabel,
    FadeMixin,
    ProgressBar,
    Toast,
)
from kodikdown.gui.workers import (
    DownloadTask,
    EpisodeDownload,
    ResolverWorker,
)
from kodikdown.i18n import set_language, t
from kodikdown.kodik.errors import InvalidUrlError
from kodikdown.kodik.models import ResolvedVideo, StreamVariant, Translation
from kodikdown.kodik.parser import extract_embed
from kodikdown.sources import EpisodeRequest, Series, public_source, recognized_link

_MAX_TOASTS = 3
_TOAST_LIFETIME_MS = 4200
_QUEUE_HINT_MS = 1200


@dataclass
class _Job:
    task: DownloadTask
    row: DownloadRow
    url: str
    title: str
    directory: Path
    started: bool = field(default=False)
    finished: bool = field(default=False)
    cancelling: bool = field(default=False)
    status: str = "queued"
    percent: int | None = None


class MainWindow(QMainWindow):
    history_error = Signal(str)
    exit_requested = Signal()

    def __init__(self, store: ConfigStore, settings: Settings) -> None:
        super().__init__()
        self.store = store
        self.settings = settings
        self._palette = palette_for(settings.theme)

        self.resolver = ResolverWorker(self)
        self.resolver.resolved.connect(self._on_resolved)
        self.resolver.catalog_ready.connect(self._on_catalog_ready)
        self.resolver.failed.connect(self._on_resolve_failed)

        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(settings.concurrent_downloads)

        self._request_id = 0
        self._resolving = False
        self._resolved: ResolvedVideo | None = None
        self._variants: tuple[StreamVariant, ...] = ()
        self._quality: int | None = None
        self._jobs: dict[str, _Job] = {}
        self._selected_jobs: set[str] = set()
        self._url_in_use = ""
        self._resolved_url = ""
        self._name_edited = False
        self._active_urls: set[str] = set()
        self._toasts: list[Toast] = []
        self._settings_last_change = float("-inf")
        self._confirmation: QMessageBox | None = None
        self._retry_entry: HistoryEntry | None = None
        self._retry_translation = False
        self._availability: dict[str, bool] = {}
        self._media_generation = 0
        self._scan_running = False
        self._scan_again = False
        self._media_error = ""
        self._scan_task: MediaScan | None = None
        self._media_pool = QThreadPool(self)
        self._media_pool.setMaxThreadCount(1)
        self._current_tab = 0
        self._tab_backstack: list[int] = []
        self._last_clipboard = ""
        self._closing = False
        self._quit_requested = False
        self.history_error.connect(
            lambda detail: self._toast(t("history_save_failed", detail=detail), "error")
        )
        self.history = HistoryStore(store.path.with_name("history.json"), self.history_error.emit)
        self.library = HistoryStore(store.path.with_name("library.json"), self.history_error.emit)
        if not self.library.path.exists():
            self.library.put_many(
                entry for entry in self.history.entries if entry.status == "finished" and entry.path
            )
        self.destroyed.connect(self.history.close)
        self.destroyed.connect(self.library.close)

        self.setWindowTitle(t("app_title"))
        self.setWindowIcon(app_icon(self._palette.accent))
        self.setMinimumSize(QSize(760, 580))
        screen = QGuiApplication.primaryScreen()
        available = screen.availableGeometry().size() if screen else QSize(1024, 860)
        self.resize(QSize(min(940, available.width() - 48), min(780, available.height() - 48)))

        self._build()
        self.apply_theme(settings.theme)
        self.tray = DesktopTray(self)
        self.tray.show_requested.connect(self.restore_window)
        self.tray.quit_requested.connect(self.request_quit)
        QShortcut(QKeySequence("Ctrl+S"), self, self.open_settings)
        QShortcut(QKeySequence("Ctrl+Q"), self, self.request_quit)
        self._media_timer = QTimer(self)
        self._media_timer.setInterval(3000)
        self._media_timer.timeout.connect(self._poll_media)
        self._media_timer.start()
        self._request_media_refresh()
        hints = QGuiApplication.styleHints()
        hints.colorSchemeChanged.connect(self._system_theme_changed)

    def _system_theme_changed(self, scheme: Qt.ColorScheme) -> None:
        if self.settings.theme == MODE_AUTO and not self._closing:
            self.appearance_overlay.finish()
            self.apply_theme(MODE_AUTO, animate=True)

    # -- construction ------------------------------------------------------
    def _build(self) -> None:
        central = QWidget()
        central.setObjectName("window")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())

        self.pages = QStackedWidget()
        root.addWidget(self.pages, 1)
        self.downloads_page = QWidget()
        download_layout = QVBoxLayout(self.downloads_page)
        download_layout.setContentsMargins(0, 0, 0, 0)
        self.pages.addWidget(self.downloads_page)
        body = QVBoxLayout()
        body.setContentsMargins(18, 16, 18, 12)
        body.setSpacing(12)
        body.addWidget(self._build_url_row())
        body.addWidget(self._build_status_row())
        body.addWidget(self._build_result_card())
        self.series_picker = SeriesPicker()
        self.series_picker.download_requested.connect(self._download_episodes)
        body.addWidget(self.series_picker)
        body.addWidget(self._build_downloads_header())
        body.addWidget(self._build_downloads_area(), 1)
        download_layout.addLayout(body, 1)
        download_layout.addWidget(self._build_footer())
        self.library_page = MediaPage(history=False)
        self.history_page = MediaPage(history=True)
        self.settings_page = SettingsPage(self.settings)
        for page in (self.library_page, self.history_page, self.settings_page):
            self.pages.addWidget(page)
        self.library_page.play_requested.connect(self._open_file)
        self.library_page.reveal_requested.connect(self._reveal_file)
        self.library_page.delete_requested.connect(self._delete_media_files)
        self.history_page.play_requested.connect(self._open_file)
        self.history_page.retry_requested.connect(self._retry_history)
        self.history_page.copy_requested.connect(self._copy_history_link)
        self.history_page.delete_requested.connect(self._remove_history)
        for page in (self.library_page, self.history_page):
            page.refresh_requested.connect(self._request_media_refresh)
        self.settings_page.change_requested.connect(self._apply_settings)
        self.settings_page.reset_requested.connect(self._reset_settings)
        self.settings_page.clear_finished_requested.connect(self._clear_finished)
        self.settings_page.clear_history_requested.connect(self._clear_history)
        self.settings_page.github_requested.connect(self._open_github)
        navigation = QFrame()
        navigation.setObjectName("navigation")
        nav_layout = QHBoxLayout(navigation)
        nav_layout.setContentsMargins(12, 8, 12, 8)
        nav_layout.setSpacing(6)
        self.navigation_group = QButtonGroup(self)
        self.navigation_buttons: list[QPushButton] = []
        for index, key in enumerate(
            ("tab_downloads", "tab_library", "tab_history", "tab_settings")
        ):
            button = QPushButton(t(key))
            button.setObjectName("navigation-button")
            button.setCheckable(True)
            button.setMinimumHeight(40)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda checked=False, target=index: self._switch_tab(target))
            self.navigation_group.addButton(button, index)
            self.navigation_buttons.append(button)
            nav_layout.addWidget(button, 1)
        self.navigation_buttons[0].setChecked(True)
        root.addWidget(navigation)
        self.appearance_overlay = AppearanceOverlay(central)

    def _build_header(self) -> QWidget:
        header = QWidget()
        header.setObjectName("header")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(18, 12, 14, 12)
        layout.setSpacing(12)

        brand_row = QHBoxLayout()
        brand_row.setSpacing(10)
        self._logo_label = QLabel()
        self._logo_label.setFixedSize(28, 28)
        self._logo_label.setPixmap(
            app_icon(self._palette.accent).pixmap(QSize(28, 28), self.devicePixelRatioF())
        )

        brand_box = QVBoxLayout()
        brand_box.setSpacing(1)
        brand = QLabel(t("app_title"))
        brand.setObjectName("brand")
        self._brand_sub = QLabel(f"v{__version__}")
        self._brand_sub.setObjectName("brand-sub")
        self._brand_sub.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        brand_box.addWidget(brand)
        brand_box.addWidget(self._brand_sub)

        brand_row.addWidget(self._logo_label)
        brand_row.addLayout(brand_box)
        layout.addLayout(brand_row)
        layout.addStretch(1)

        self.save_indicator = SaveIndicator(header)
        layout.addWidget(self.save_indicator)

        return header

    def _build_url_row(self) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText(t("url_placeholder"))
        # The native clear icon follows the system theme, which can differ
        # from the app theme and leave a white icon on a white input.
        self.url_clear_action = self.url_edit.addAction(
            icon("close", self._palette.text_muted, 16), QLineEdit.ActionPosition.TrailingPosition
        )
        self.url_clear_action.setText(t("clear_link"))
        self.url_clear_action.setVisible(False)
        self.url_clear_action.triggered.connect(self.url_edit.clear)
        self.url_edit.textChanged.connect(lambda text: self.url_clear_action.setVisible(bool(text)))
        self.url_edit.textChanged.connect(self._on_link_changed)
        self.url_edit.returnPressed.connect(self._on_find)

        self.paste_button = QPushButton(t("paste"))
        self.paste_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.paste_button.setIcon(icon("clipboard", self._palette.text_muted, 15))
        self.paste_button.clicked.connect(self._paste)

        self.find_button = QPushButton(t("resolve"))
        self.find_button.setObjectName("primary")
        self.find_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.find_button.setIcon(icon("play", "#ffffff", 15))
        self.find_button.setMinimumWidth(125)
        self.find_button.clicked.connect(self._on_find)

        layout.addWidget(self.url_edit, 1)
        layout.addWidget(self.paste_button)
        layout.addWidget(self.find_button)
        return container

    def _build_status_row(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.status_label = QLabel(t("hint"))
        self.status_label.setObjectName("status")
        self.status_label.setWordWrap(True)

        self.resolve_bar = ProgressBar()
        self.resolve_bar.hide()

        layout.addWidget(self.status_label)
        layout.addWidget(self.resolve_bar)
        return container

    def _build_result_card(self) -> QWidget:
        self.result_card = QFrame()
        self.result_card.setObjectName("card")
        self.result_card.hide()

        layout = QVBoxLayout(self.result_card)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(10)

        self.title_label = QLabel()
        self.title_label.setObjectName("panel-title")
        self.title_label.setTextFormat(Qt.TextFormat.PlainText)
        self.title_label.setWordWrap(True)
        layout.addWidget(self.title_label)

        self.warning_label = QLabel()
        self.warning_label.setObjectName("warning")
        self.warning_label.setWordWrap(True)
        self.warning_label.hide()
        layout.addWidget(self.warning_label)

        name_row = QHBoxLayout()
        name_row.setSpacing(8)
        self.name_caption = QLabel(t("file_name"))
        self.name_caption.setObjectName("muted")
        self.name_caption.setMinimumWidth(84)
        self.name_edit = QLineEdit()
        self.name_edit.textEdited.connect(self._on_name_edited)
        name_row.addWidget(self.name_caption)
        name_row.addWidget(self.name_edit, 1)
        layout.addLayout(name_row)

        self.translation_row = QWidget()
        translation_layout = QHBoxLayout(self.translation_row)
        translation_layout.setContentsMargins(0, 0, 0, 0)
        translation_layout.setSpacing(8)
        self.translation_caption = QLabel(t("translation"))
        self.translation_caption.setObjectName("muted")
        self.translation_caption.setMinimumWidth(84)
        self.translation_combo = QComboBox()
        self.translation_combo.currentIndexChanged.connect(self._on_translation_changed)
        translation_layout.addWidget(self.translation_caption)
        translation_layout.addWidget(self.translation_combo, 1)
        self.translation_row.hide()
        layout.addWidget(self.translation_row)

        quality_row = QHBoxLayout()
        quality_row.setSpacing(8)
        self.quality_caption = QLabel(t("quality"))
        self.quality_caption.setObjectName("muted")
        self.quality_caption.setMinimumWidth(84)
        self.quality_caption.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.quality_box = QWidget()
        self.quality_layout = QHBoxLayout(self.quality_box)
        self.quality_layout.setContentsMargins(0, 0, 0, 0)
        self.quality_layout.setSpacing(6)
        self.quality_layout.addStretch(1)
        self.quality_group = QButtonGroup(self)
        self.quality_group.setExclusive(True)
        quality_row.addWidget(self.quality_caption)
        quality_row.addWidget(self.quality_box, 1)
        layout.addLayout(quality_row)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.mp4_check = CheckBox(t("download_mp4"))
        self.mp4_check.setChecked(self.settings.prefer_mp4)
        self.download_button = QPushButton(t("download"))
        self.download_button.setObjectName("primary")
        self.download_button.setIcon(icon("download", "#ffffff", 16))
        self.download_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.download_button.setMinimumWidth(130)
        self.download_button.clicked.connect(self._on_download)
        self.open_folder_button = QPushButton(t("open_folder"))
        self.open_folder_button.setIcon(icon("folder", self._palette.text_muted, 15))
        self.open_folder_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_folder_button.clicked.connect(
            lambda: self._open_folder(self.settings.download_dir)
        )

        actions.addWidget(self.mp4_check)
        actions.addStretch(1)
        actions.addWidget(self.open_folder_button)
        actions.addWidget(self.download_button)
        layout.addLayout(actions)
        return self.result_card

    def _build_downloads_header(self) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(2, 4, 2, 0)
        layout.setSpacing(8)

        self.downloads_caption = QLabel(t("downloads_section").upper())
        self.downloads_caption.setObjectName("section")
        self.clear_button = QPushButton(t("clear_finished"))
        self.clear_button.setObjectName("link")
        self.clear_button.setIcon(icon("trash", self._palette.accent, 14))
        self.clear_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_button.clicked.connect(self._clear_finished)

        self.remove_selected_button = QPushButton()
        self.remove_selected_button.setObjectName("link")
        self.remove_selected_button.hide()
        self.remove_selected_button.clicked.connect(self._remove_selected_downloads)
        layout.addWidget(self.downloads_caption)
        layout.addStretch(1)
        layout.addWidget(self.remove_selected_button)
        layout.addWidget(self.clear_button)
        return container

    def _build_downloads_area(self) -> QWidget:
        self.downloads_empty = QLabel(t("downloads_empty"))
        self.downloads_empty.setObjectName("muted")
        self.downloads_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.downloads_empty.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.downloads_container = QWidget()
        self.downloads_layout = QVBoxLayout(self.downloads_container)
        self.downloads_layout.setContentsMargins(0, 0, 0, 0)
        self.downloads_layout.setSpacing(8)
        self.downloads_layout.addWidget(self.downloads_empty)
        self.downloads_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.downloads_container)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.downloads_scroll = scroll
        return scroll

    def _build_footer(self) -> QWidget:
        footer = QWidget()
        footer.setObjectName("header")
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(18, 8, 12, 8)
        layout.setSpacing(8)

        self.folder_label = ElidedLabel(str(self.settings.download_dir))
        self.folder_label.setMinimumWidth(0)
        self.folder_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.folder_label.setObjectName("muted")
        self.folder_button = QPushButton(t("open_folder"))
        self.folder_button.setObjectName("link")
        self.folder_button.setIcon(icon("folder", self._palette.accent, 14))
        self.folder_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.folder_button.clicked.connect(lambda: self._open_folder(self.settings.download_dir))
        layout.addWidget(self.folder_label, 1)
        layout.addWidget(self.folder_button)
        return footer

    # -- theme and language ------------------------------------------------
    def apply_theme(
        self, mode: str, *, animate: bool = False, origin: QWidget | None = None
    ) -> None:
        target = palette_for(mode)
        central = self.centralWidget()
        if (
            animate
            and self.settings.animations
            and target.mode != self._palette.mode
            and self.isVisible()
            and central is not None
        ):
            point = (
                origin.mapTo(central, origin.rect().center())
                if origin is not None
                else central.rect().center()
            )
            self.appearance_overlay.capture(point)
        self._palette = target
        self.setStyleSheet(stylesheet(target))
        self._refresh_icons()
        self.appearance_overlay.start()

    def _refresh_icons(self) -> None:
        colour = self._palette.text_muted
        self._logo_label.setPixmap(
            app_icon(self._palette.accent).pixmap(QSize(28, 28), self.devicePixelRatioF())
        )
        self.save_indicator.apply_palette(self._palette)
        self.url_clear_action.setIcon(icon("close", colour, 16))
        self.paste_button.setIcon(icon("clipboard", colour, 15))
        self.find_button.setIcon(icon("close" if self._resolving else "play", "#ffffff", 15))
        self.download_button.setIcon(icon("download", "#ffffff", 16))
        self.open_folder_button.setIcon(icon("folder", colour, 15))
        self.clear_button.setIcon(icon("trash", self._palette.accent, 14))
        self.folder_button.setIcon(icon("folder", self._palette.accent, 14))
        self._refresh_navigation_icons()
        self.settings_page.apply_palette(self._palette)
        self.library_page.apply_palette(self._palette)
        self.history_page.apply_palette(self._palette)
        self.resolve_bar.apply_palette(self._palette)
        for job in self._jobs.values():
            job.row.apply_palette(self._palette)

    def _refresh_navigation_icons(self) -> None:
        colour = self._palette.text_muted
        for button, name in zip(
            self.navigation_buttons, ("download", "library", "history", "settings"), strict=True
        ):
            button.setIcon(icon(name, self._palette.accent if button.isChecked() else colour, 18))

    def retranslate(self) -> None:
        self.setWindowTitle(t("app_title"))
        if hasattr(self, "tray"):
            self.tray.retranslate()
        self.url_edit.setPlaceholderText(t("url_placeholder"))
        self.url_clear_action.setText(t("clear_link"))
        self.paste_button.setText(t("paste"))
        self.find_button.setText(t("cancel") if self._resolving else t("resolve"))
        self.name_caption.setText(t("file_name"))
        self.translation_caption.setText(t("translation"))
        self.quality_caption.setText(t("quality"))
        self.series_picker.retranslate()
        self.download_button.setText(t("download"))
        self.mp4_check.setText(t("download_mp4"))
        self.open_folder_button.setText(t("open_folder"))
        self.downloads_caption.setText(t("downloads_section").upper())
        self.clear_button.setText(t("clear_finished"))
        self.downloads_empty.setText(t("downloads_empty"))
        self.folder_button.setText(t("open_folder"))
        self._selection_changed()
        if self._resolving:
            self.set_status(t("resolving"))
        elif self._resolved is None and self.series_picker.isHidden():
            self.set_status(t("hint"))
        elif self._resolved is not None:
            self._build_quality_pills(self._resolved, self._quality)
            if self._resolved.warnings:
                self.warning_label.setText(t("warning_proxy"))
        for button, key in zip(
            self.navigation_buttons,
            ("tab_downloads", "tab_library", "tab_history", "tab_settings"),
            strict=True,
        ):
            button.setText(t(key))
        self.settings_page.retranslate()
        self.library_page.retranslate()
        self.history_page.retranslate()
        for job in self._jobs.values():
            job.row.retranslate()

    # -- lookup ------------------------------------------------------------
    def prefill(self, url: str) -> None:
        """Start a lookup for a link given on the command line."""
        self.url_edit.setText(url)
        self._on_find()

    def _paste(self) -> None:
        clipboard = QGuiApplication.clipboard()
        text = (clipboard.text() or "").strip() if clipboard else ""
        if not text:
            self._toast(t("paste_empty"), "warning")
            return
        self.url_edit.setText(text)
        self.url_edit.setFocus()

    def _on_find(self) -> None:
        if self._resolving:
            self._cancel_resolve()
            return

        raw = self.url_edit.text().strip()
        if not raw:
            self._toast(t("link_required"), "warning")
            self.url_edit.setFocus()
            return
        # A voice-over only applies to the video it was listed for.
        translation = self._translation_for(raw)
        self._start_resolve(raw, translation)

    def _on_link_changed(self, raw: str) -> None:
        if self._resolving and raw.strip() != self._url_in_use:
            self._cancel_resolve()
        matches = raw.strip() == self._resolved_url
        self.result_card.setVisible(matches and self._resolved is not None)
        self.series_picker.set_busy(self._resolving or not matches)

    def _translation_for(self, raw: str) -> Translation | None:
        if self._resolved is None or raw.strip() != self._resolved_url:
            return None
        if self.translation_row.isHidden():
            return self._resolved.translation
        key = self.translation_combo.currentData()
        for item in self._resolved.translations:
            if item.key == key:
                return item
        return self._resolved.translation

    def _cancel_resolve(self) -> None:
        self._retry_entry = None
        self.resolver.cancel()
        self._request_id += 1
        # The visible selection must describe the streams we still have.
        if self._resolved is not None and self._resolved.translations:
            active = self._resolved.translation or self._resolved.translations[0]
            index = self.translation_combo.findData(active.key)
            self.translation_combo.blockSignals(True)
            self.translation_combo.setCurrentIndex(index)
            self.translation_combo.blockSignals(False)
        self._url_in_use = self._resolved_url
        self._set_resolving(False)
        self.set_status("")

    def _start_resolve(self, raw: str, translation: Translation | None) -> None:
        self._request_id += 1
        self._url_in_use = raw.strip()
        self._set_resolving(True)
        self.set_status(t("resolving"))
        self.resolver.resolve(self._request_id, raw, translation)

    def _on_translation_changed(self) -> None:
        if self._url_in_use and not self._resolving:
            self._start_resolve(self._url_in_use, self._translation_for(self._url_in_use))

    def _on_name_edited(self, _text: str) -> None:
        self._name_edited = True

    def _set_resolving(self, resolving: bool) -> None:
        self._resolving = resolving
        self._update_settings_lock()
        self.find_button.setText(t("cancel") if resolving else t("resolve"))
        self.find_button.setIcon(
            icon("close", "#ffffff", 15) if resolving else icon("play", "#ffffff", 15)
        )
        matches = self.url_edit.text().strip() == self._resolved_url
        self.download_button.setEnabled(not resolving and self._resolved is not None)
        self.series_picker.set_busy(resolving or not matches)
        if resolving:
            self.resolve_bar.set_busy()
            self.resolve_bar.show()
            FadeMixin.fade_in(self.resolve_bar, duration=180)
        else:
            self.resolve_bar.reset()
            self.resolve_bar.hide()

    def _on_resolved(self, request_id: int, resolved: ResolvedVideo) -> None:
        if request_id != self._request_id:
            return
        retry = self._retry_entry
        if (
            retry is not None
            and retry.translation
            and EpisodeRequest.from_url(retry.retry_input or retry.source_input) is None
            and (resolved.translation is None or resolved.translation.title != retry.translation)
        ):
            track = next(
                (item for item in resolved.translations if item.title == retry.translation), None
            )
            if track is None or self._retry_translation:
                self._retry_entry = None
                self._set_resolving(False)
                self._toast(t("translation_unavailable"), "error")
                return
            self._retry_translation = True
            self._start_resolve(retry.retry_input or retry.source_input, track)
            return
        same_video = self._url_in_use == self._resolved_url and bool(self._resolved_url)
        if not same_video:
            self._name_edited = False
        self._resolved_url = self._url_in_use
        self._resolved = resolved
        self._variants = resolved.variants
        self.series_picker.hide()
        self._set_resolving(False)
        self._populate_result(
            resolved,
            resolved.pick(retry.quality).quality
            if retry
            else self._quality
            if same_video
            else None,
        )
        if retry is not None:
            self._retry_entry = None
            self.name_edit.setText(retry.file_name)
            self._name_edited = True
            self.mp4_check.setChecked(retry.prefer_mp4)
            self._on_download(confirmed=True, retry=retry)

    def _on_catalog_ready(self, request_id: int, series: Series) -> None:
        if request_id != self._request_id:
            return
        self._retry_entry = None
        self._resolved = None
        self._variants = ()
        self._resolved_url = self._url_in_use
        self._set_resolving(False)
        self.result_card.hide()
        quality = self.settings.default_quality
        self.series_picker.set_series(
            series, 1080 if quality == "ask" else int(quality), self.settings.group_series
        )
        self.set_status("")

    def _on_resolve_failed(self, request_id: int, kind: str, detail: str) -> None:
        if request_id != self._request_id:
            return
        self._retry_entry = None
        self._resolved = None
        self._variants = ()
        self._set_resolving(False)
        self.result_card.hide()
        self.series_picker.hide()
        if kind == "network":
            self.set_status(t("network_error", detail=detail or "?"), state="error")
        elif kind == "unexpected":
            self.set_status(t("unexpected_error", detail=detail), state="error")
        else:
            self.set_status(t(kind, detail=detail), state="error")

    def _populate_result(self, resolved: ResolvedVideo, keep_quality: int | None) -> None:
        self.title_label.setText(resolved.title or t("title_unknown"))
        if not self._name_edited:
            self.name_edit.setText(resolved.title or t("title_unknown"))

        self.warning_label.setVisible("proxy" in resolved.warnings)
        if resolved.warnings:
            self.warning_label.setText(t("warning_proxy"))

        has_choices = len(resolved.translations) > 1
        self.translation_row.setVisible(has_choices)
        if has_choices:
            self.translation_combo.blockSignals(True)
            self.translation_combo.clear()
            for item in resolved.translations:
                self.translation_combo.addItem(item.title, item.key)
            active = resolved.translation or resolved.translations[0]
            index = self.translation_combo.findData(active.key)
            self.translation_combo.setCurrentIndex(index if index >= 0 else 0)
            self.translation_combo.blockSignals(False)

        self._build_quality_pills(resolved, keep_quality)
        self.download_button.setEnabled(True)
        self.result_card.show()
        FadeMixin.fade_in(self.result_card)
        self.set_status("")

    def _build_quality_pills(self, resolved: ResolvedVideo, keep_quality: int | None) -> None:
        for button in list(self.quality_group.buttons()):
            self.quality_group.removeButton(button)
            self.quality_layout.removeWidget(button)
            button.hide()
            button.deleteLater()

        # Keep whatever the user had picked for this video, otherwise start
        # from the best stream the server offers.
        available = {variant.quality for variant in resolved.variants}
        preferred = (
            int(self.settings.default_quality) if self.settings.default_quality != "ask" else None
        )
        selected = keep_quality if keep_quality in available else resolved.pick(preferred).quality
        self._quality = selected

        for index, variant in enumerate(resolved.variants):
            label = variant.label if variant.quality else t("quality_auto")
            if index == 0:
                label += f" · {t('best_badge')}"
            pill = QPushButton(label)
            pill.setObjectName("quality")
            pill.setCheckable(True)
            pill.setChecked(variant.quality == selected)
            pill.setCursor(Qt.CursorShape.PointingHandCursor)
            pill.clicked.connect(
                lambda _checked=False, quality=variant.quality: self._select_quality(quality)
            )
            self.quality_group.addButton(pill)
            self.quality_layout.insertWidget(self.quality_layout.count() - 1, pill)
        self._refresh_mp4_hint()

    def _select_quality(self, quality: int) -> None:
        self._quality = quality
        self._refresh_mp4_hint()

    def _refresh_mp4_hint(self) -> None:
        variant = self._selected_variant()
        self.mp4_check.setVisible(bool(variant and variant.direct_mp4))

    def _selected_variant(self) -> StreamVariant | None:
        if not self._variants:
            return None
        quality = self._quality
        if quality is None:
            return self._variants[0]
        for variant in self._variants:
            if variant.quality == quality:
                return variant
        return self._variants[0]

    # -- downloads ---------------------------------------------------------
    def _on_download(self, *, confirmed: bool = False, retry: HistoryEntry | None = None) -> None:
        if self._resolving:
            return
        resolved = self._resolved
        variant = self._selected_variant()
        if resolved is None or variant is None:
            return

        use_mp4 = self.mp4_check.isChecked() and bool(variant.direct_mp4)
        url = variant.download_url(use_mp4)
        title = self.name_edit.text().strip() or resolved.title or t("title_unknown")

        directory = self._series_directory(retry.series if retry else "")
        if self._already_queued(url, title, directory):
            self._toast(t("already_downloading"), "warning")
            return
        if not confirmed:
            existing = self._existing_download_path(safe_filename(title))
            if existing:
                request_id = self._request_id

                def download_confirmed() -> None:
                    if self._request_id == request_id and self.url_edit.text().strip() == raw:
                        self._on_download(confirmed=True)

                raw = self.url_edit.text().strip()
                self._confirm_existing(title, existing, download_confirmed)
                return
        self._enqueue_download(
            url,
            title,
            variant.quality,
            public_source(retry.source_input if retry else self._resolved_url or self._url_in_use),
            retry.translation
            if retry
            else resolved.translation.title
            if resolved.translation
            else "",
            use_mp4,
            referer=variant.download_referer(use_mp4),
            resolved=resolved,
            retry_input=retry.retry_input or retry.source_input if retry else "",
            series=retry.series if retry else "",
        )

    def _already_queued(self, url: str, title: str, directory: Path) -> bool:
        filename = safe_filename(title).casefold()
        return url in self._active_urls or any(
            not job.finished
            and job.directory == directory
            and safe_filename(job.title).casefold() == filename
            for job in self._jobs.values()
        )

    def _download_episodes(self) -> None:
        picker = self.series_picker
        series, choice = picker.series, picker.choice()
        if not series or not choice or self._resolving:
            return
        if self.url_edit.text().strip() != self._resolved_url:
            return
        quality = int(picker.quality.currentData())
        prefer_mp4 = self.settings.prefer_mp4
        group = series.title if picker.group.isChecked() else ""
        original = public_source(self._resolved_url)
        saved = [
            entry for entry in self.library.entries if entry.path and readable_file(entry.path)
        ]
        saved_sources = {entry.retry_input or entry.source_input for entry in saved}
        directory = self._series_directory(group)
        queued: list[HistoryEntry] = []
        skipped = 0
        for episode in picker.selected(choice):
            request = EpisodeRequest(episode.number, choice.player, choice.voice)
            source = request.link(series.url)
            number = episode.number.zfill(2)
            title = t("episode_number", number=number)
            if not group:
                title += f" · {series.title[:72]}"
            if choice.voice:
                title = f"{title} · {choice.voice}"
            filename = safe_filename(title)
            if (
                source in saved_sources
                or self._already_queued(source, title, directory)
                or self._existing_download_path(
                    filename, directory=directory, include_history=False
                )
            ):
                skipped += 1
                continue
            queued.append(
                self._enqueue_download(
                    source,
                    title,
                    quality,
                    original,
                    choice.voice,
                    prefer_mp4,
                    retry_input=source,
                    series=group,
                    episode=EpisodeDownload(
                        series.title, choice, episode, quality or None, prefer_mp4
                    ),
                )
            )
        if queued:
            self.history.put_many(queued)
            self._render_history()
            self._update_settings_lock()
        message = t("episodes_queued", count=len(queued))
        if skipped:
            message += " " + t("episodes_skipped", count=skipped)
        self._toast(message, "info" if queued else "warning")

    def _enqueue_download(
        self,
        url: str,
        title: str,
        quality: int,
        source: str,
        voice: str,
        prefer_mp4: bool,
        *,
        referer: str = "",
        resolved: ResolvedVideo | None = None,
        episode: EpisodeDownload | None = None,
        retry_input: str = "",
        series: str = "",
    ) -> HistoryEntry:
        job_id = uuid.uuid4().hex
        row = DownloadRow(job_id, title, quality, self._palette)
        row.cancel_requested.connect(self._request_cancel_job)
        row.remove_requested.connect(self._remove_job)
        row.selection_requested.connect(self._toggle_download_selection)
        row.open_requested.connect(self._open_file)
        row.folder_requested.connect(self._reveal_file)
        row.mark_starting()

        directory = self._series_directory(series)
        task = DownloadTask(
            job_id,
            url,
            title,
            referer,
            directory,
            concurrent_fragments=4,
            fallback_sources=fallback_sources_for(resolved, quality, prefer_mp4)
            if resolved
            else (),
            episode=episode,
        )
        task.signals.started.connect(self._on_job_started)
        task.signals.progress.connect(self._on_progress)
        task.signals.finished.connect(self._on_job_finished)
        task.signals.failed.connect(self._on_job_failed)
        task.signals.cancelled.connect(self._on_job_cancelled)

        self._jobs[job_id] = _Job(task=task, row=row, url=url, title=title, directory=directory)
        self._active_urls.add(url)
        entry = HistoryEntry(
            job_id,
            title,
            safe_filename(title),
            source,
            quality,
            time.time(),
            translation=voice,
            prefer_mp4=prefer_mp4,
            retry_input=retry_input,
            series=series,
        )
        if episode is None:
            self.history.put(entry)
            self._render_history()
            self._update_settings_lock()
        self._insert_row(row)
        self.pool.start(task)
        # Only claim the job is waiting when no worker picked it up.
        self._later(_QUEUE_HINT_MS, lambda: self._hint_queued(job_id))
        return entry

    def _insert_row(self, row: DownloadRow) -> None:
        self.downloads_empty.hide()
        self.downloads_layout.insertWidget(self.downloads_layout.count() - 1, row)
        FadeMixin.fade_in(row, duration=200, start=0.0)

    def _hint_queued(self, job_id: str) -> None:
        job = self._jobs.get(job_id)
        if job is not None and not job.started and not job.finished:
            job.row.mark_queued()

    def _cancel_job(self, job_id: str) -> None:
        """Stop a transfer.

        Keep the running task alive until it confirms cancellation and has
        cleaned up its files. Queued tasks can be removed immediately.
        """
        job = self._jobs.get(job_id)
        if job is None or job.finished or job.status == "assembling":
            return
        job.cancelling = True
        job.task.cancel()
        if self.pool.tryTake(job.task):
            self._on_job_cancelled(job_id)
        else:
            job.row.mark_cancelling()

    def _on_job_started(self, job_id: str) -> None:
        job = self._jobs.get(job_id)
        if job is not None and not job.started and not job.finished and not job.cancelling:
            job.started = True
            job.status = "downloading"
            job.row.mark_downloading()
            self._update_tray()
            self.history.update(job_id, status="downloading")
            self._render_history()

    def _on_progress(self, job_id: str, snapshot: object) -> None:
        job = self._jobs.get(job_id)
        # Late callbacks must not overwrite a row that already has an outcome.
        if job is not None and not job.finished and not job.cancelling:
            job.started = True
            if isinstance(snapshot, ProgressSnapshot):
                status = (
                    job.status
                    if snapshot.source == "monitor"
                    else (
                        "assembling"
                        if snapshot.stage in {"processing", "finished"}
                        else "downloading"
                    )
                )
                changes: HistoryChanges = {}
                if status != job.status:
                    job.status = status
                    changes["status"] = status
                if snapshot.quality is not None:
                    changes["quality"] = snapshot.quality
                if changes:
                    self.history.update(job_id, **changes)
                    self._render_history()
                job.row.update_progress(snapshot)
                if snapshot.total:
                    job.percent = min(100, int(snapshot.downloaded * 100 / snapshot.total))
                    self._update_tray()

    def _on_job_finished(self, job_id: str, path: str) -> None:
        job = self._jobs.get(job_id)
        if job is None or job.finished:
            return
        job.finished = True
        path = str(Path(path).absolute())
        available = readable_file(path)
        self._availability[path] = available
        size = 0
        if available:
            with contextlib.suppress(OSError):
                size = Path(path).stat().st_size
        job.row.mark_done(path)
        job.row.refresh_availability(available)
        job.status = "finished"
        self.history.update(job_id, status="finished", path=path, file_size=size)
        if entry := self.history.get(job_id):
            self.library.put(entry)
        self._job_settled(job)
        self._toast(
            t("saved_to", path=Path(path).name) if available else t("file_missing"),
            "success" if available else "warning",
        )

    def _on_job_failed(self, job_id: str, detail: str) -> None:
        job = self._jobs.get(job_id)
        if job is None or job.finished:
            return
        job.finished = True
        job.row.mark_failed(detail)
        job.status = "failed"
        self.history.update(job_id, status="failed", error=detail)
        self._job_settled(job)

    def _on_job_cancelled(self, job_id: str) -> None:
        job = self._jobs.get(job_id)
        if job is None or job.finished:
            return
        job.finished = True
        job.row.mark_cancelled()
        job.status = "cancelled"
        self.history.update(job_id, status="cancelled")
        self._job_settled(job)
        self._toast(t("cancelled"))

    def _clear_finished(self) -> None:
        for job_id, job in list(self._jobs.items()):
            if not job.finished:
                continue
            job.row.setParent(None)
            job.row.deleteLater()
            del self._jobs[job_id]
        self._selected_jobs.intersection_update(self._jobs)
        self._selection_changed()
        self._update_empty_state()

    def _update_empty_state(self) -> None:
        self.downloads_empty.setVisible(not self._jobs)

    # -- dialogs and helpers ----------------------------------------------
    def open_settings(self) -> None:
        self._switch_tab(3)

    def _switch_tab(self, index: int, *, remember: bool = True) -> None:
        if not 0 <= index < self.pages.count():
            return
        if index != self._current_tab and remember:
            self._tab_backstack.append(self._current_tab)
        self._current_tab = index
        if self.appearance_overlay.busy:
            self.appearance_overlay.finish()
        self.pages.setCurrentIndex(index)
        self.navigation_buttons[index].setChecked(True)
        self._refresh_navigation_icons()
        if index in (1, 2):
            self._request_media_refresh()
        if index == 0:
            self._auto_paste()

    def _transfers_busy(self) -> bool:
        return self._resolving or any(not job.finished for job in self._jobs.values())

    def _update_settings_lock(self) -> None:
        self.settings_page.set_transfer_locked(self._transfers_busy())
        if hasattr(self, "tray"):
            self._update_tray()

    def _update_tray(self) -> None:
        active = [job for job in self._jobs.values() if not job.finished]
        current = next((job for job in active if job.started), None)
        self.tray.set_progress(
            len(active), current.title if current else "", current.percent if current else None
        )

    def _accept_settings_action(self) -> bool:
        now = time.monotonic()
        if self.appearance_overlay.busy or now - self._settings_last_change < 0.5:
            return False
        self._settings_last_change = now
        return True

    def _apply_settings(
        self, updated: Settings, origin: QWidget | None = None, *, force: bool = False
    ) -> None:
        if updated == self.settings:
            return
        transfer_fields = ("download_dir", "concurrent_downloads", "prefer_mp4", "default_quality")
        locked = self._transfers_busy() and any(
            getattr(updated, key) != getattr(self.settings, key) for key in transfer_fields
        )
        if locked or (not force and not self._accept_settings_action()):
            self.settings_page.bind(self.settings)
            return
        previous = self.settings
        try:
            if updated.download_dir != previous.download_dir:
                directory = updated.download_dir.expanduser().absolute()
                directory.mkdir(parents=True, exist_ok=True)
                updated = updated.updated(download_dir=directory)
            self.store.save(updated)
        except (OSError, RuntimeError, ValueError) as exc:
            self.settings_page.bind(previous)
            self._toast(t("settings_save_failed", detail=exc), "error")
            return
        language_changed = updated.language != previous.language
        theme_changed = updated.theme != previous.theme
        if language_changed and not theme_changed and updated.animations and self.isVisible():
            central = self.centralWidget()
            if central is not None:
                self.appearance_overlay.capture(central.rect().center(), circular=False)
        self.settings = updated
        self.pool.setMaxThreadCount(updated.concurrent_downloads)
        self.folder_label.setText(str(updated.download_dir))
        if updated.prefer_mp4 != previous.prefer_mp4:
            self.mp4_check.setChecked(updated.prefer_mp4)
        self.settings_page.bind(updated)
        if language_changed:
            set_language(updated.language)
            self.retranslate()
        if theme_changed:
            self.apply_theme(updated.theme, animate=True, origin=origin)
        else:
            self.appearance_overlay.start()
        if updated.default_quality != previous.default_quality and self._resolved is not None:
            self._build_quality_pills(self._resolved, None)
        if updated.download_dir != previous.download_dir:
            self._request_media_refresh()
        self.save_indicator.pulse(animated=updated.animations)

    def _ask(self, text: str, callback: Callable[[], None], *, action: str) -> None:
        if self._confirmation is not None:
            return
        dialog = QMessageBox(
            QMessageBox.Icon.Question,
            t("app_title"),
            text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            self,
        )
        self._confirmation = dialog
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.button(QMessageBox.StandardButton.Yes).setText(t(action))
        dialog.button(QMessageBox.StandardButton.No).setText(t("cancel"))
        dialog.setDefaultButton(QMessageBox.StandardButton.No)

        def finished(result: int) -> None:
            self._confirmation = None
            dialog.deleteLater()
            if result == QMessageBox.StandardButton.Yes:
                callback()

        dialog.finished.connect(finished)
        dialog.open()

    def _reset_settings(self) -> None:
        if self._transfers_busy() or not self._accept_settings_action():
            return
        self._ask(
            t("reset_defaults_confirm"),
            lambda: self._apply_settings(Settings(), self.settings_page.reset_button, force=True),
            action="reset_defaults",
        )

    def _open_github(self) -> None:
        if self._accept_settings_action():
            QDesktopServices.openUrl(QUrl("https://github.com/SHAWNiksDev"))

    def _request_cancel_job(self, identifier: str) -> None:
        job = self._jobs.get(identifier)
        if job is None or job.finished or job.cancelling:
            return
        if job.status == "assembling":
            self._toast(t("assembly_protected"), "warning")
            return
        if self.settings.confirm_cancel_download:
            self._ask(
                t("cancel_download_confirm", title=job.title),
                lambda: self._cancel_job(identifier),
                action="stop_download",
            )
        else:
            self._cancel_job(identifier)

    def _job_settled(self, job: _Job) -> None:
        self._active_urls.discard(job.url)
        self._update_settings_lock()
        self._render_history()
        self._request_media_refresh()

    def _remove_job(self, identifier: str) -> None:
        job = self._jobs.get(identifier)
        if job is None or not job.finished:
            return
        job.row.setParent(None)
        job.row.deleteLater()
        del self._jobs[identifier]
        self._selected_jobs.discard(identifier)
        self._selection_changed()
        self._update_empty_state()

    def _toggle_download_selection(self, identifier: str) -> None:
        job = self._jobs.get(identifier)
        if job is None or not job.finished:
            return
        if identifier in self._selected_jobs:
            self._selected_jobs.remove(identifier)
        else:
            self._selected_jobs.add(identifier)
        job.row.setProperty("selected", identifier in self._selected_jobs)
        job.row._restyle()
        self._selection_changed()

    def _selection_changed(self) -> None:
        self.remove_selected_button.setText(t("remove_selected", count=len(self._selected_jobs)))
        self.remove_selected_button.setVisible(bool(self._selected_jobs))

    def _remove_selected_downloads(self) -> None:
        identifiers = self._selected_jobs.copy()
        if not identifiers or identifiers & self._active_ids():
            return

        def remove() -> None:
            for identifier in identifiers:
                self._remove_job(identifier)

        if self.settings.confirm_delete:
            self._ask(
                t("remove_downloads_confirm", count=len(identifiers)), remove, action="remove"
            )
        else:
            remove()

    def _active_ids(self) -> set[str]:
        return {identifier for identifier, job in self._jobs.items() if not job.finished}

    def _render_history(self) -> None:
        self.history_page.set_history(self.history.entries, self._availability, self._active_ids())

    def _poll_media(self) -> None:
        if self.isVisible() and self.isActiveWindow() and not self._scan_running:
            self._request_media_refresh()

    def _request_media_refresh(self) -> None:
        if self._closing:
            return
        self._media_generation += 1
        if self._scan_running:
            self._scan_again = True
            return
        self._scan_running = True
        # Download rows outlive cleared history; their files still need checks.
        paths = tuple(
            dict.fromkeys(
                [entry.path for entry in self.history.entries if entry.path]
                + [job.row.path for job in self._jobs.values() if job.finished and job.row.path]
            )
        )
        entries = self.library.entries
        task = MediaScan(
            self._media_generation,
            entries,
            tuple(dict.fromkeys((*paths, *(entry.path for entry in entries)))),
        )
        self._scan_task = task
        task.signals.ready.connect(self._on_media_scanned)
        self._media_pool.start(task)

    def _on_media_scanned(
        self, generation: int, files: tuple[MediaFile, ...], available: dict[str, bool], error: str
    ) -> None:
        self._scan_running = False
        self._scan_task = None
        if self._closing:
            return
        if generation == self._media_generation:
            self._availability = available
            self.library_page.set_files(files)
            self._render_history()
            if error and self._current_tab == 1 and error != self._media_error:
                self._toast(t("folder_open_failed", detail=error), "warning")
                self._media_error = error
            elif not error:
                self._media_error = ""
            for job in self._jobs.values():
                if job.finished and job.row.path:
                    job.row.refresh_availability(available.get(job.row.path, False))
        if self._scan_again:
            self._scan_again = False
            self._request_media_refresh()

    def _remove_history(self, identifiers: set[str]) -> None:
        if identifiers & self._active_ids():
            return

        def remove() -> None:
            self.history.remove(identifiers, self._active_ids())
            self._render_history()

        if self.settings.confirm_delete:
            self._ask(t("remove_history_confirm", count=len(identifiers)), remove, action="remove")
        else:
            remove()

    def _clear_history(self) -> None:
        if not self._accept_settings_action():
            return

        def clear() -> None:
            self.history.clear(self._active_ids())
            self._render_history()

        self._ask(t("clear_history_confirm"), clear, action="clear_history")

    def _copy_history_link(self, identifier: str) -> None:
        entry = self.history.get(identifier)
        if entry is not None and entry.source_input:
            clipboard = QGuiApplication.clipboard()
            if clipboard is not None:
                clipboard.setText(public_source(entry.source_input))
                self._toast(t("link_copied"))

    def _series_directory(self, series: str) -> Path:
        return (
            self.settings.download_dir / safe_filename(series)
            if series
            else self.settings.download_dir
        )

    def _existing_download_path(
        self, file_name: str, *, directory: Path | None = None, include_history: bool = True
    ) -> str:
        if include_history:
            for entry in self.history.entries:
                if entry.file_name.casefold() == file_name.casefold() and readable_file(entry.path):
                    return entry.path
        for suffix in (".mp4", ".mkv", ".webm", ".ts"):
            path = (directory or self.settings.download_dir) / (file_name + suffix)
            if readable_file(str(path)):
                return str(path)
        return ""

    def _confirm_existing(self, title: str, path: str, callback: Callable[[], None]) -> None:
        if self._confirmation is not None:
            return
        dialog = QMessageBox(
            QMessageBox.Icon.Question,
            t("already_downloaded_title"),
            t("already_downloaded_message", title=title),
            parent=self,
        )
        self._confirmation = dialog
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        play = dialog.addButton(t("play"), QMessageBox.ButtonRole.AcceptRole)
        again = dialog.addButton(t("download_again"), QMessageBox.ButtonRole.ActionRole)
        cancel = dialog.addButton(t("cancel"), QMessageBox.ButtonRole.RejectRole)
        dialog.setDefaultButton(cancel)

        def finished(result: int) -> None:
            self._confirmation = None
            clicked = dialog.clickedButton()
            dialog.deleteLater()
            if clicked is play:
                self._open_file(path)
            elif clicked is again:
                callback()

        dialog.finished.connect(finished)
        dialog.open()

    def _retry_history(self, identifier: str) -> None:
        entry = self.history.get(identifier)
        if entry is None or identifier in self._active_ids() or self._resolving:
            return
        if not entry.source_input:
            self._toast(t("original_link_missing"), "warning")
            return

        def retry() -> None:
            if self._resolving or identifier in self._active_ids():
                return
            self._retry_entry = entry
            self._retry_translation = False
            source = entry.retry_input or entry.source_input
            self.url_edit.setText(source)
            self._switch_tab(0)
            self._start_resolve(source, None)

        existing = (
            entry.path
            if readable_file(entry.path)
            else self._existing_download_path(entry.file_name)
        )
        if existing:
            self._confirm_existing(entry.title, existing, retry)
        else:
            retry()

    def _delete_media_files(self, paths: set[str]) -> None:
        def delete() -> None:
            protected = {path for path in paths if is_pending_output(Path(path))}
            if protected:
                self._toast(t("assembly_protected"), "warning")
                return
            task = DeleteFiles(paths)
            task.signals.done.connect(self._media_deleted)
            self._media_pool.start(task)

        if self.settings.confirm_delete:
            self._ask(t("delete_selected_confirm", count=len(paths)), delete, action="delete_file")
        else:
            delete()

    def _media_deleted(self, paths: set[str], error: str) -> None:
        self.library.remove(
            {entry.id for entry in self.library.entries if entry.path in paths}, set()
        )
        for path in paths:
            self._availability[path] = False
        self._render_history()
        self._request_media_refresh()
        if error:
            self._toast(t("delete_failed", detail=error), "error")
        elif paths:
            self._toast(t("file_deleted"))

    def _auto_paste(self) -> None:
        if (
            not self.settings.auto_paste
            or self._resolving
            or self._retry_entry is not None
            or self.url_edit.text().strip()
        ):
            return
        clipboard = QGuiApplication.clipboard()
        raw = clipboard.text().strip() if clipboard is not None else ""
        if not raw or raw == self._last_clipboard:
            return
        if not recognized_link(raw):
            try:
                extract_embed(raw)
            except InvalidUrlError:
                return
        self._last_clipboard = raw
        self.prefill(raw)

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if (
            event.type() == QEvent.Type.ActivationChange
            and hasattr(self, "pages")
            and self.isActiveWindow()
        ):
            self._request_media_refresh()
            if self._current_tab == 0:
                self._auto_paste()

    def _open_folder(self, folder: Path) -> None:
        with contextlib.suppress(OSError):
            folder.mkdir(parents=True, exist_ok=True)
        if not folder.is_dir():
            self._toast(t("folder_missing"), "warning")
            return
        if not open_directory(folder):
            self._toast(t("folder_open_failed", detail=folder), "error")

    def _open_file(self, path: str) -> None:
        target = Path(path)
        if not readable_file(path):
            self._request_media_refresh()
            self._toast(t("file_missing"), "warning")
            return
        if not open_path(target):
            self._open_folder(target.parent)

    def _reveal_file(self, path: str) -> None:
        target = Path(path)
        if not readable_file(path):
            self._request_media_refresh()
            self._toast(t("file_missing"), "warning")
            return
        if not reveal_path(target):
            self._open_folder(target.parent)

    def set_status(self, text: str, *, state: str = "") -> None:
        if not text:
            self.status_label.hide()
            return
        self.status_label.show()
        self.status_label.setText(text)
        self.status_label.setProperty("state", state)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

    def _toast(self, message: str, severity: str = "info") -> None:
        toast = Toast(message, severity, self, self._palette)
        toast.setMaximumWidth(min(460, max(260, self.width() - 80)))
        self._toasts.append(toast)
        while len(self._toasts) > _MAX_TOASTS:
            self._dismiss_toast(self._toasts[0])
        self._layout_toasts()
        self._later(_TOAST_LIFETIME_MS, lambda: self._dismiss_toast(toast))

    def _later(self, milliseconds: int, callback: Callable[[], None]) -> None:
        """Run a callback later, but never after the window is gone.

        A bare QTimer.singleShot keeps firing while the application shuts
        down, which is a fine way to touch deleted widgets.
        """
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(callback)
        timer.timeout.connect(timer.deleteLater)
        timer.start(milliseconds)

    def _dismiss_toast(self, toast: Toast) -> None:
        """Drop a toast before its widget is gone, so layout never touches it."""
        if not any(item is toast for item in self._toasts):
            return
        self._toasts = [item for item in self._toasts if item is not toast]
        toast.dismiss()

    def _layout_toasts(self) -> None:
        bottom = self.height() - 82
        for toast in reversed(self._toasts):
            toast.adjustSize()
            x = (self.width() - toast.width()) // 2
            bottom -= toast.height() + 8
            toast.show_at(x, bottom)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape and self._resolving:
            self._retry_entry = None
            self._cancel_resolve()
            return
        if event.key() == Qt.Key.Key_Escape and self._current_tab != 0:
            self._switch_tab(
                self._tab_backstack.pop() if self._tab_backstack else 0, remember=False
            )
            return
        super().keyPressEvent(event)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._layout_toasts()
        if hasattr(self, "appearance_overlay"):
            self.appearance_overlay.finish()

    def restore_window(self) -> None:
        if self._closing:
            return
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self._request_media_refresh()

    def request_quit(self) -> bool:
        if self._confirmation is not None:
            self._confirmation.raise_()
            self._confirmation.activateWindow()
            return False
        self._quit_requested = True
        closed = bool(self.close())
        if not closed:
            self._quit_requested = False
        return closed

    def _confirm_quit(self, count: int) -> bool:
        dialog = QMessageBox(
            QMessageBox.Icon.Question,
            t("app_title"),
            t("quit_with_downloads", count=count),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            self,
        )
        dialog.button(QMessageBox.StandardButton.Yes).setText(t("tray_quit"))
        dialog.button(QMessageBox.StandardButton.No).setText(t("cancel"))
        dialog.setDefaultButton(QMessageBox.StandardButton.No)
        self._confirmation = dialog
        try:
            return bool(dialog.exec() == QMessageBox.StandardButton.Yes)
        finally:
            self._confirmation = None
            dialog.deleteLater()

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._quit_requested:
            self.appearance_overlay.finish()
            self.save_indicator.finish()
            if self.tray.ensure_visible():
                self.hide()
            else:
                # Some Linux shells have no tray host. Keep a taskbar entry so
                # the running downloader remains reachable there.
                self.showMinimized()
            event.ignore()
            return
        if self._confirmation is not None:
            event.ignore()
            self._confirmation.raise_()
            return
        active = [job for job in self._jobs.values() if not job.finished]
        if any(job.status == "assembling" for job in active):
            self._toast(t("assembly_protected"), "warning")
            event.ignore()
            return
        if active and not self._confirm_quit(len(active)):
            event.ignore()
            return
        self._closing = True
        self.tray.close()
        self.save_indicator.finish()
        self.appearance_overlay.finish()
        for identifier, job in self._jobs.items():
            if not job.finished:
                self.history.update(identifier, status="cancelled")
        for job in active:
            job.task.cancel()
        self.pool.clear()
        self.resolver.shutdown()
        self.pool.waitForDone(5000)
        self.history.close()
        self.library.close()
        self._media_pool.clear()
        self._media_timer.stop()
        super().closeEvent(event)
        self.exit_requested.emit()
