"""The main window: paste a link, pick a track, watch the downloads."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QThreadPool, QTimer
from PySide6.QtGui import QCloseEvent, QGuiApplication, QKeyEvent, QResizeEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
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
    QVBoxLayout,
    QWidget,
)

from kodikdown import __version__
from kodikdown.config import ConfigStore, Settings
from kodikdown.gui.desktop import open_directory, open_path, reveal_path
from kodikdown.gui.icons import app_icon, icon
from kodikdown.gui.settings_dialog import SettingsDialog
from kodikdown.gui.theme import MODE_AUTO, MODE_DARK, MODE_LIGHT, palette_for, stylesheet
from kodikdown.gui.widgets import DownloadRow, FadeMixin, ProgressBar, Toast
from kodikdown.gui.workers import DownloadTask, ResolverWorker
from kodikdown.i18n import set_language, t
from kodikdown.kodik.models import ResolvedVideo, StreamVariant, Translation, referer_for

_MAX_TOASTS = 3
_TOAST_LIFETIME_MS = 4200
_QUEUE_HINT_MS = 1200


@dataclass
class _Job:
    task: DownloadTask
    row: DownloadRow
    url: str
    title: str
    started: bool = field(default=False)
    finished: bool = field(default=False)


class MainWindow(QMainWindow):
    def __init__(self, store: ConfigStore, settings: Settings) -> None:
        super().__init__()
        self.store = store
        self.settings = settings
        self._palette = palette_for(settings.theme)

        self.resolver = ResolverWorker(self)
        self.resolver.resolved.connect(self._on_resolved)
        self.resolver.failed.connect(self._on_resolve_failed)

        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(settings.concurrent_downloads)

        self._request_id = 0
        self._resolving = False
        self._resolved: ResolvedVideo | None = None
        self._variants: tuple[StreamVariant, ...] = ()
        self._quality: int | None = None
        self._jobs: dict[str, _Job] = {}
        self._url_in_use = ""
        self._resolved_url = ""
        self._name_edited = False
        self._active_urls: set[str] = set()
        self._toasts: list[Toast] = []

        self.setWindowTitle(t("app_title"))
        self.setWindowIcon(app_icon(self._palette.accent))
        self.setMinimumSize(QSize(660, 520))
        self.resize(QSize(820, 700))

        self._build()
        self.apply_theme(settings.theme)

    # -- construction ------------------------------------------------------
    def _build(self) -> None:
        central = QWidget()
        central.setObjectName("window")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())

        body = QVBoxLayout()
        body.setContentsMargins(18, 16, 18, 12)
        body.setSpacing(12)
        body.addWidget(self._build_url_row())
        body.addWidget(self._build_status_row())
        body.addWidget(self._build_result_card())
        body.addWidget(self._build_downloads_header())
        body.addWidget(self._build_downloads_area(), 1)
        root.addLayout(body, 1)
        root.addWidget(self._build_footer())

    def _build_header(self) -> QWidget:
        header = QWidget()
        header.setObjectName("header")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(18, 12, 12, 12)
        layout.setSpacing(8)

        brand_box = QVBoxLayout()
        brand_box.setSpacing(0)
        brand = QLabel(t("app_title"))
        brand.setObjectName("brand")
        self._brand_sub = QLabel(f"v{__version__}")
        self._brand_sub.setObjectName("brand-sub")
        brand_box.addWidget(brand)
        brand_box.addWidget(self._brand_sub)
        layout.addLayout(brand_box)
        layout.addStretch(1)

        self.theme_button = QPushButton()
        self.theme_button.setObjectName("icon")
        self.theme_button.setFixedSize(QSize(34, 34))
        self.theme_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.theme_button.setToolTip(t("toggle_theme"))
        self.theme_button.clicked.connect(self._toggle_theme)

        self.settings_button = QPushButton()
        self.settings_button.setObjectName("icon")
        self.settings_button.setFixedSize(QSize(34, 34))
        self.settings_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.settings_button.setToolTip(t("settings_title"))
        self.settings_button.clicked.connect(self.open_settings)

        layout.addWidget(self.theme_button)
        layout.addWidget(self.settings_button)
        return header

    def _build_url_row(self) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText(t("url_placeholder"))
        self.url_edit.setClearButtonEnabled(True)
        self.url_edit.returnPressed.connect(self._on_find)

        self.paste_button = QPushButton(t("paste"))
        self.paste_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.paste_button.clicked.connect(self._paste)

        self.find_button = QPushButton(t("resolve"))
        self.find_button.setObjectName("primary")
        self.find_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.find_button.setMinimumWidth(120)
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
        self.mp4_check = QCheckBox(t("download_mp4"))
        self.mp4_check.setChecked(self.settings.prefer_mp4)
        self.download_button = QPushButton(t("download"))
        self.download_button.setObjectName("primary")
        self.download_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.download_button.setMinimumWidth(130)
        self.download_button.clicked.connect(self._on_download)
        self.open_folder_button = QPushButton(t("open_folder"))
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
        self.clear_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_button.clicked.connect(self._clear_finished)

        layout.addWidget(self.downloads_caption)
        layout.addStretch(1)
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

        self.folder_label = QLabel(str(self.settings.download_dir))
        self.folder_label.setObjectName("muted")
        self.folder_button = QPushButton(t("open_folder"))
        self.folder_button.setObjectName("link")
        self.folder_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.folder_button.clicked.connect(lambda: self._open_folder(self.settings.download_dir))
        layout.addWidget(self.folder_label, 1)
        layout.addWidget(self.folder_button)
        return footer

    # -- theme and language ------------------------------------------------
    def apply_theme(self, mode: str, *, animate: bool = False) -> None:
        previous = self._palette
        self._palette = palette_for(mode)
        self.setStyleSheet(stylesheet(self._palette))
        self._refresh_icons()
        if animate and previous.mode != self._palette.mode:
            FadeMixin.fade_in(self.centralWidget() or self, duration=200, start=0.65)

    def _toggle_theme(self) -> None:
        target = MODE_LIGHT if self._palette.is_dark else MODE_DARK
        self.settings = self.settings.updated(theme=target)
        self.store.save(self.settings)
        self.apply_theme(target, animate=True)

    def _refresh_icons(self) -> None:
        colour = self._palette.text_muted
        self.theme_button.setIcon(icon("sun" if self._palette.is_dark else "moon", colour, 20))
        self.settings_button.setIcon(icon("settings", colour, 20))
        for job in self._jobs.values():
            job.row.apply_palette(self._palette)

    def retranslate(self) -> None:
        self.setWindowTitle(t("app_title"))
        self.url_edit.setPlaceholderText(t("url_placeholder"))
        self.paste_button.setText(t("paste"))
        self.find_button.setText(t("cancel") if self._resolving else t("resolve"))
        self.theme_button.setToolTip(t("toggle_theme"))
        self.settings_button.setToolTip(t("settings_title"))
        self.name_caption.setText(t("file_name"))
        self.translation_caption.setText(t("translation"))
        self.quality_caption.setText(t("quality"))
        self.download_button.setText(t("download"))
        self.mp4_check.setText(t("download_mp4"))
        self.open_folder_button.setText(t("open_folder"))
        self.downloads_caption.setText(t("downloads_section").upper())
        self.clear_button.setText(t("clear_finished"))
        self.downloads_empty.setText(t("downloads_empty"))
        self.folder_button.setText(t("open_folder"))
        if self._resolved is None:
            self.set_status(t("hint"))
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
            self.resolver.cancel()
            self._set_resolving(False)
            self.set_status("")
            return

        raw = self.url_edit.text().strip()
        if not raw:
            self._toast(t("link_required"), "warning")
            self.url_edit.setFocus()
            return
        # A voice-over only applies to the video it was listed for.
        translation = self._translation_for(raw)
        self._start_resolve(raw, translation)

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
        self.find_button.setText(t("cancel") if resolving else t("resolve"))
        self.download_button.setEnabled(not resolving and self._resolved is not None)
        if resolving:
            self.resolve_bar.set_busy()
            self.resolve_bar.show()
        else:
            self.resolve_bar.hide()

    def _on_resolved(self, request_id: int, resolved: ResolvedVideo) -> None:
        if request_id != self._request_id:
            return
        same_video = self._url_in_use == self._resolved_url and bool(self._resolved_url)
        self._resolved_url = self._url_in_use
        self._resolved = resolved
        self._variants = resolved.variants
        self._set_resolving(False)
        self._populate_result(resolved, self._quality if same_video else None)

    def _on_resolve_failed(self, request_id: int, kind: str, detail: str) -> None:
        if request_id != self._request_id:
            return
        self._resolved = None
        self._variants = ()
        self._set_resolving(False)
        self.result_card.hide()
        if kind == "network":
            self.set_status(t("network_error", detail=detail or "?"), state="error")
        elif kind == "unexpected":
            self.set_status(t("unexpected_error", detail=detail), state="error")
        else:
            self.set_status(t(kind), state="error")

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
            button.deleteLater()

        # Keep whatever the user had picked for this video, otherwise start
        # from the best stream the server offers.
        available = {variant.quality for variant in resolved.variants}
        selected = keep_quality if keep_quality in available else resolved.best.quality
        self._quality = selected

        for index, variant in enumerate(resolved.variants):
            label = f"{variant.quality}p"
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
    def _on_download(self) -> None:
        resolved = self._resolved
        variant = self._selected_variant()
        if resolved is None or variant is None:
            return

        use_mp4 = self.mp4_check.isChecked() and bool(variant.direct_mp4)
        url = variant.direct_mp4 if use_mp4 else variant.url
        assert url is not None

        if url in self._active_urls:
            self._toast(t("already_downloading"), "warning")
            return

        title = self.name_edit.text().strip() or resolved.title or t("title_unknown")
        job_id = uuid.uuid4().hex
        row = DownloadRow(job_id, title, variant.quality, self._palette)
        row.cancel_requested.connect(self._cancel_job)
        row.open_requested.connect(self._open_file)
        row.folder_requested.connect(self._reveal_file)
        row.mark_starting()

        task = DownloadTask(
            job_id,
            url,
            title,
            referer_for(url),
            self.settings.download_dir,
            concurrent_fragments=4 * self.settings.concurrent_downloads,
        )
        task.signals.started.connect(self._on_job_started)
        task.signals.progress.connect(self._on_progress)
        task.signals.finished.connect(self._on_job_finished)
        task.signals.failed.connect(self._on_job_failed)
        task.signals.cancelled.connect(self._on_job_cancelled)

        self._jobs[job_id] = _Job(task=task, row=row, url=url, title=title)
        self._active_urls.add(url)
        self._insert_row(row)
        self.pool.start(task)
        # Only claim the job is waiting when no worker picked it up.
        self._later(_QUEUE_HINT_MS, lambda: self._hint_queued(job_id))

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

        A running yt-dlp only notices between fragments, and one fragment can
        take a minute on a slow mirror, so the row is closed right away and the
        worker is left to unwind (it cleans up its partials on the way out).
        """
        job = self._jobs.get(job_id)
        if job is None or job.finished:
            return
        job.task.cancel()
        self.pool.tryTake(job.task)  # drop it from the queue if it never started
        self._on_job_cancelled(job_id)

    def _on_job_started(self, job_id: str) -> None:
        job = self._jobs.get(job_id)
        if job is not None:
            job.started = True

    def _on_progress(self, job_id: str, snapshot: object) -> None:
        job = self._jobs.get(job_id)
        # Late callbacks must not overwrite a row that already has an outcome.
        if job is not None and not job.finished:
            job.started = True
            job.row.update_progress(snapshot)  # type: ignore[arg-type]

    def _on_job_finished(self, job_id: str, path: str) -> None:
        job = self._jobs.get(job_id)
        if job is None or job.finished:
            return
        job.finished = True
        job.row.mark_done(path)
        self._active_urls.discard(job.url)
        self._toast(t("saved_to", path=Path(path).name), "success")

    def _on_job_failed(self, job_id: str, detail: str) -> None:
        job = self._jobs.get(job_id)
        if job is None or job.finished:
            return
        job.finished = True
        job.row.mark_failed(detail)
        self._active_urls.discard(job.url)

    def _on_job_cancelled(self, job_id: str) -> None:
        job = self._jobs.get(job_id)
        if job is None or job.finished:
            return
        job.finished = True
        job.row.mark_cancelled()
        self._active_urls.discard(job.url)
        self._toast(t("cancelled"))

    def _clear_finished(self) -> None:
        for job_id, job in list(self._jobs.items()):
            if not job.finished:
                continue
            job.row.setParent(None)
            job.row.deleteLater()
            del self._jobs[job_id]
        self._update_empty_state()

    def _update_empty_state(self) -> None:
        self.downloads_empty.setVisible(not self._jobs)

    # -- dialogs and helpers ----------------------------------------------
    def open_settings(self) -> None:
        dialog = SettingsDialog(self.settings, self.store, self)
        if dialog.exec() != SettingsDialog.DialogCode.Accepted:
            return
        updated = dialog.settings()
        language_changed = updated.language != self.settings.language
        self.settings = updated
        self.store.save(updated)
        self.pool.setMaxThreadCount(updated.concurrent_downloads)
        self.folder_label.setText(str(updated.download_dir))
        if language_changed:
            set_language(updated.language)
            self.retranslate()
        self.apply_theme(updated.theme, animate=updated.theme != MODE_AUTO)
        self._toast(t("settings_saved"), "success")

    def _open_folder(self, folder: Path) -> None:
        if not folder.is_dir():
            self._toast(t("folder_missing"), "warning")
            return
        if not open_directory(folder):
            self._toast(t("folder_open_failed", detail=folder), "error")

    def _open_file(self, path: str) -> None:
        target = Path(path)
        if not target.exists():
            self._toast(t("file_missing"), "warning")
            return
        if not open_path(target):
            self._open_folder(target.parent)

    def _reveal_file(self, path: str) -> None:
        target = Path(path)
        if not target.exists():
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
        toast = Toast(message, severity, self)
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
        bottom = self.height() - 24
        for toast in reversed(self._toasts):
            toast.adjustSize()
            x = (self.width() - toast.width()) // 2
            bottom -= toast.height() + 8
            toast.show_at(x, bottom)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape and self._resolving:
            self.resolver.cancel()
            self._set_resolving(False)
            self.set_status("")
            return
        super().keyPressEvent(event)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._layout_toasts()

    def closeEvent(self, event: QCloseEvent) -> None:
        active = [job for job in self._jobs.values() if not job.finished]
        if active:
            answer = QMessageBox.question(
                self,
                t("app_title"),
                t("quit_with_downloads", count=len(active)),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        for job in active:
            job.task.cancel()
        self.pool.clear()
        self.resolver.shutdown()
        self.pool.waitForDone(5000)
        super().closeEvent(event)
