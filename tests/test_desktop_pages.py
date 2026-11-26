from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, QTimer
from PySide6.QtWidgets import QApplication, QDialog, QLineEdit, QMessageBox

from kodikdown.config import ConfigStore, Settings
from kodikdown.downloader import ProgressSnapshot, release_target, unique_target
from kodikdown.gui.appearance import AppearanceOverlay
from kodikdown.gui.favorites import Favorites
from kodikdown.gui.main_window import MainWindow
from kodikdown.gui.media_store import HistoryEntry, HistoryStore, MediaFile, MediaScan
from kodikdown.i18n import t
from kodikdown.kodik.models import ResolvedVideo, StreamVariant, Translation
from kodikdown.sources import Choice, Episode, EpisodeRequest, Series

SOURCE = '<iframe src="https://kodikplayer.com/video/42/abcdef0123456789/720p"></iframe>'


def video(url: str = "https://cdn.example/fresh-720?signature=new") -> ResolvedVideo:
    return ResolvedVideo(
        "Episode", (StreamVariant(720, url), StreamVariant(480, "https://cdn.example/fresh-480"))
    )


@pytest.fixture
def window(qtbot, tmp_path):
    settings = Settings(download_dir=tmp_path / "videos", theme="light")
    store = ConfigStore(tmp_path / "settings.json")
    store.save(settings)
    window = MainWindow(store, settings)

    def cleanup(widget):
        widget._quit_requested = True
        if widget._confirmation is not None:
            widget._confirmation.reject()
        for job in widget.downloads.jobs.values():
            if not job.finished:
                job.task.cancel()
                job.finished = True
        widget.resolver.shutdown()
        widget.downloads.pool.waitForDone(5000)

    qtbot.addWidget(window, before_close_func=cleanup)
    yield window
    cleanup(window)
    window.close()
    window.media.pool.waitForDone(2000)


def enqueue(window, monkeypatch):
    monkeypatch.setattr(window.downloads.pool, "start", lambda task: None)
    window.url_edit.setText(SOURCE)
    window._url_in_use = SOURCE
    window._on_resolved(window._request_id, video())
    window._on_download()
    return next(iter(window.downloads.jobs.items()))


def test_settings_are_a_page_and_preserve_downloader_inputs(window):
    window.url_edit.setText(SOURCE)
    window._on_resolved(window._request_id, video())
    window.result_card.name_edit.setText("My episode")
    result = window._resolved
    window.open_settings()
    assert window.pages.currentWidget() is window.settings_page
    assert window.settings_page.window() is window
    assert window.findChildren(QDialog) == []
    assert not hasattr(window, "theme_button")
    assert not hasattr(window, "settings_button")
    window.navigation_buttons[0].click()
    assert window.url_edit.text() == SOURCE
    assert window.result_card.name_edit.text() == "My episode"
    assert window._resolved is result


def test_theme_reveal_and_language_spam_preserve_jobs(window, monkeypatch, qtbot):
    identifier, job = enqueue(window, monkeypatch)
    window._on_progress(identifier, ProgressSnapshot(downloaded=6, total=10, fragments=True))
    window.show()
    window.open_settings()
    qtbot.wait(40)
    window.settings_page.theme_buttons["dark"].click()
    assert window._palette.mode == "dark"
    assert window.appearance_overlay.busy
    assert window.appearance_overlay.animation.duration() == 340
    qtbot.wait(100)
    button = window.settings_page.theme_buttons["dark"]
    point = button.mapTo(window.centralWidget(), button.rect().center() + QPoint(0, -10))
    image = window.centralWidget().grab().toImage()
    assert image.pixelColor(point).name() == window._palette.accent_soft
    assert image.pixelColor(5, 5).name() == "#ffffff"
    for _ in range(30):
        window.settings_page.theme_buttons["light"].click()
        window.settings_page.language_buttons["ru"].click()
    assert window.settings.theme == "dark"
    assert window.settings.language == "auto"
    assert len(window.findChildren(AppearanceOverlay)) == 1
    assert window.downloads.jobs[identifier] is job
    assert job.row.bar._target == 60
    qtbot.waitUntil(lambda: not window.appearance_overlay.busy, timeout=1500)
    qtbot.wait(520)
    window.settings_page.language_buttons["ru"].click()
    assert window.settings.language == "ru"
    assert window.find_button.text() == "Найти видео"
    assert window.downloads.jobs[identifier] is job
    assert job.row.bar._target == 60
    assert not job.finished
    assert window.pages.currentWidget() is window.settings_page


def test_settings_save_failure_rolls_back_the_controls(window, monkeypatch):
    def fail(settings):
        raise OSError("disk full")

    monkeypatch.setattr(window.store, "save", fail)
    window.open_settings()
    window.settings_page.theme_buttons["dark"].click()
    assert window.settings.theme == "light"
    assert window._palette.mode == "light"
    assert window.settings_page.theme_buttons["light"].isChecked()


def test_transfer_settings_lock_for_lookup_queue_and_assembly(window, monkeypatch):
    window._set_resolving(True)
    assert not window.settings_page.folder_edit.isEnabled()
    assert not window.settings_page.concurrent_spin.isEnabled()
    window._apply_settings(window.settings.updated(download_dir=Path("/never-changed")))
    assert window.settings.download_dir != Path("/never-changed")
    window._set_resolving(False)
    identifier, job = enqueue(window, monkeypatch)
    cancelled = []
    monkeypatch.setattr(job.task, "cancel", lambda: cancelled.append(True))
    assert not window.settings_page.prefer_mp4_check.isEnabled()
    window._on_progress(identifier, ProgressSnapshot(stage="processing"))
    assert job.status == "assembling"
    assert job.row.cancel_button.isHidden()
    window._cancel_job(identifier)
    window._request_cancel_job(identifier)
    window._remove_job(identifier)
    assert cancelled == []
    assert identifier in window.downloads.jobs
    window._render_history()
    window.history_page.table.topLevelItem(0).setSelected(True)
    assert not window.history_page.delete_button.isEnabled()
    assert not window.history_page.retry_button.isEnabled()
    window._remove_history({identifier})
    assert window.history.get(identifier) is not None
    window.history.clear(window._active_ids())
    assert window.history.get(identifier) is not None
    window._on_job_failed(identifier, "test cleanup")
    assert window.settings_page.folder_edit.isEnabled()


def test_cancellation_confirmation_cannot_be_stacked(window, monkeypatch):
    identifier, job = enqueue(window, monkeypatch)
    window._request_cancel_job(identifier)
    dialog = window._confirmation
    assert dialog is not None
    for _ in range(10):
        window._request_cancel_job(identifier)
        assert window._confirmation is dialog
    assert not job.cancelling
    dialog.button(QMessageBox.StandardButton.No).click()
    assert window._confirmation is None
    assert not job.cancelling
    window._request_cancel_job(identifier)
    window._confirmation.button(QMessageBox.StandardButton.Yes).click()
    assert job.cancelling
    window._on_job_cancelled(identifier)
    assert job.finished


def test_history_retry_confirms_and_gets_fresh_source_and_voice(window, tmp_path, monkeypatch):
    existing = tmp_path / "Episode.mp4"
    existing.write_bytes(b"finished video")
    entry = HistoryEntry(
        "old",
        "Old episode",
        "Episode",
        SOURCE,
        480,
        1,
        status="finished",
        translation="Voice B",
        path=str(existing),
    )
    window.history.put(entry)
    window._copy_history_link(entry.id)
    assert QApplication.clipboard().text() == SOURCE.split('"')[1]
    calls = []
    monkeypatch.setattr(window.resolver, "resolve", lambda *args: calls.append(args))
    monkeypatch.setattr(window.downloads.pool, "start", lambda task: None)
    window._retry_history(entry.id)
    assert window._confirmation is not None
    assert calls == []
    assert window.downloads.jobs == {}
    # The explicit download-again action allows one new copy.
    dialog = window._confirmation
    next(
        button
        for button in dialog.buttons()
        if dialog.buttonRole(button) == QMessageBox.ButtonRole.ActionRole
    ).click()
    assert calls[-1][1] == SOURCE
    voice_a = Translation("Voice A", "video", "42", "a" * 16)
    voice_b = Translation("Voice B", "video", "43", "b" * 16)
    resolved = replace(video(), translations=(voice_a, voice_b), translation=voice_a)
    window._on_resolved(window._request_id, resolved)
    assert calls[-1][2] == voice_b
    assert window.downloads.jobs == {}
    window._on_resolved(window._request_id, replace(resolved, translation=voice_b))
    identifier, job = next(iter(window.downloads.jobs.items()))
    assert job.url == "https://cdn.example/fresh-480"
    assert job.title == "Episode"
    saved = window.history.get(identifier)
    assert saved.source_input == SOURCE.split('"')[1]
    assert saved.translation == "Voice B"
    assert saved.quality == 480
    assert existing.read_bytes() == b"finished video"


def test_history_retry_finds_duplicate_in_its_own_series_folder(window, monkeypatch):
    for series in ("Other series", "Current series"):
        folder = window.settings.download_dir / series
        folder.mkdir(parents=True)
        (folder / "Episode.mp4").write_bytes(b"video")
    other = window.settings.download_dir / "Other series" / "Episode.mp4"
    window.history.put(HistoryEntry("other", "Episode", "Episode", SOURCE, 480, 2, path=str(other)))
    window.history.put(
        HistoryEntry("retry", "Episode", "Episode", SOURCE, 480, 1, series="Current series")
    )
    confirmed = []
    monkeypatch.setattr(
        window, "_confirm_existing", lambda title, path, retry: confirmed.append(path)
    )

    window._retry_history("retry")

    assert confirmed == [str(window.settings.download_dir / "Current series" / "Episode.mp4")]


def test_deleted_video_disables_actions_everywhere_and_preserves_history(
    window, monkeypatch, qtbot
):
    identifier, job = enqueue(window, monkeypatch)
    path = window.settings.download_dir / "Episode.mp4"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"finished video")
    window._on_job_finished(identifier, str(path))
    qtbot.waitUntil(lambda: window.library_page.table.topLevelItemCount() == 1, timeout=3000)
    window.history_page.table.topLevelItem(0).setSelected(True)
    assert window.history_page.play_button.isEnabled()
    path.unlink()
    opened = []
    monkeypatch.setattr("kodikdown.gui.main_window.open_path", lambda path: opened.append(path))
    window._open_file(str(path))
    assert opened == []
    window._request_media_refresh()
    qtbot.waitUntil(
        lambda: (
            window.library_page.table.topLevelItemCount() == 0
            and job.row.property("state") == "missing"
        ),
        timeout=3000,
    )
    assert not window.history_page.play_button.isEnabled()
    assert job.row.open_button.isHidden()
    assert window.history.get(identifier) is not None
    assert window.history_page.table.topLevelItemCount() == 1


def test_library_delete_is_confirmed_and_updates_history(window, monkeypatch, qtbot):
    identifier, job = enqueue(window, monkeypatch)
    path = window.settings.download_dir / "Episode.mp4"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"finished video")
    window._on_job_finished(identifier, str(path))
    qtbot.waitUntil(lambda: window.library_page.table.topLevelItemCount() == 1, timeout=3000)
    window.library_page.table.topLevelItem(0).setSelected(True)
    window.library_page.delete_button.click()
    assert window._confirmation is not None
    assert path.exists()
    window._confirmation.button(QMessageBox.StandardButton.Yes).click()
    qtbot.waitUntil(lambda: not path.exists(), timeout=3000)
    qtbot.waitUntil(lambda: job.row.property("state") == "missing", timeout=3000)
    assert window.history.get(identifier) is not None


def test_active_and_intermediate_outputs_never_enter_library(tmp_path, qapp):
    target = unique_target(tmp_path, "Episode")
    files = [target.with_suffix(".mp4"), Path(str(target) + ".f137.mp4")]
    for path in files:
        path.write_bytes(b"still being written")
    results = []
    unrelated = tmp_path / "Unrelated.mp4"
    unrelated.write_bytes(b"outside the library")
    task = MediaScan(1, (), (*map(str, files), str(unrelated)))
    task.signals.ready.connect(lambda *args: results.append(args))
    try:
        task.run()
        assert results[0][1] == ()
        assert results[0][2][str(unrelated)]
        assert not any(results[0][2][str(file)] for file in files)
    finally:
        release_target(target)


def test_only_finished_download_rows_can_be_selected(window, monkeypatch):
    identifier, _job = enqueue(window, monkeypatch)
    window._toggle_download_selection(identifier)
    assert window._selected_jobs == set()
    window._on_job_cancelled(identifier)
    window._toggle_download_selection(identifier)
    assert window._selected_jobs == {identifier}
    window._remove_selected_downloads()
    assert window._confirmation is not None
    window._confirmation.button(QMessageBox.StandardButton.Yes).click()
    assert identifier not in window.downloads.jobs
    assert window.history.get(identifier) is not None


def test_history_persists_original_input_and_recovers_interrupted_jobs(tmp_path):
    store = HistoryStore(tmp_path / "history.json")
    entry = HistoryEntry("job", "Episode", "Episode", SOURCE, 720, 123, status="downloading")
    store.put(entry)
    store.flush()
    store.close()
    restored = HistoryStore(store.path)
    try:
        assert restored.get("job").source_input == SOURCE
        assert restored.get("job").status == "interrupted"
    finally:
        restored.close()


def test_paused_download_can_be_restored_and_resumed(window, monkeypatch, qtbot):
    identifier, job = enqueue(window, monkeypatch)
    monkeypatch.setattr(window.downloads.pool, "tryTake", lambda _: True)
    window._pause_job(identifier)
    assert job.status == "paused"
    assert not window._transfers_busy()
    window.history.flush()
    window._quit_requested = True
    assert window.close()

    restored = MainWindow(window.store, window.settings)
    qtbot.addWidget(restored)
    try:
        pending = restored.downloads.jobs[identifier]
        assert pending.status == "paused"
        assert pending.directory == job.directory
        starts = []
        monkeypatch.setattr(restored.downloads.pool, "start", starts.append)
        restored._resume_all()
        assert starts == [pending.task]
        assert restored.history.get(identifier).status == "queued"
        assert pending.task.job_id == identifier
    finally:
        for pending in restored.downloads.jobs.values():
            pending.finished = True
        restored._quit_requested = True
        restored.close()


def test_favorite_remembers_quality_and_selects_only_missing_episodes(window, monkeypatch):
    url = "https://yani.tv/catalog/item/sample"
    choice = Choice("Kodik", "Studio", (Episode("1", SOURCE), Episode("2", SOURCE)))
    series = Series(url, "Sample", (choice,))
    window.series_picker.set_series(series, 480, True)
    window._save_favorite()
    (favorite,) = Favorites(window.store.path.parent).entries()
    assert (favorite.player, favorite.voice, favorite.quality) == ("Kodik", "Studio", 480)

    saved = window.store.path.parent / "episode.mp4"
    saved.write_bytes(b"downloaded video")
    window.library.put(
        HistoryEntry(
            "one",
            "Episode",
            "Episode",
            url,
            480,
            10,
            path=str(saved),
            retry_input=EpisodeRequest("1", "Kodik", "Studio").link(url),
        )
    )
    monkeypatch.setattr(window.resolver, "resolve", lambda *_: None)
    window._open_favorite(favorite)
    window._on_catalog_ready(window._request_id, series)
    picker = window.series_picker
    assert picker.quality.currentData() == 480
    assert [episode.number for episode in picker.selected(choice)] == ["2"]


def test_history_failed_atomic_write_keeps_previous_file(tmp_path, monkeypatch):
    store = HistoryStore(tmp_path / "history.json")
    first = HistoryEntry("first", "One", "One", SOURCE, 720, 1, status="finished")
    store.put(first)
    store.flush()
    previous = store.path.read_bytes()

    def fail(*args):
        raise OSError("disk full")

    monkeypatch.setattr("kodikdown.gui.media_store.os.replace", fail)
    store.put(replace(first, title="Changed"))
    with pytest.raises(OSError):
        store.flush()
    store.close()
    assert store.path.read_bytes() == previous
    assert not list(tmp_path.glob("*.tmp"))


def test_history_retries_failed_changes_on_next_save(tmp_path, monkeypatch):
    store = HistoryStore(tmp_path / "history.json")
    old = HistoryEntry("old", "Old", "Old", SOURCE, 720, 1)
    first = HistoryEntry("first", "One", "One", SOURCE, 720, 2)
    second = HistoryEntry("second", "Two", "Two", SOURCE, 480, 3)
    try:
        store.put(old)
        store.flush()

        def fail(*args):
            raise OSError("disk full")

        with monkeypatch.context() as patch:
            patch.setattr("kodikdown.gui.media_store.os.replace", fail)
            store.remove({old.id}, set())
            store.put(first)
            with pytest.raises(OSError):
                store.flush()

        store.put(second)
        store.flush()
        restored = HistoryStore(store.path)
        try:
            assert [entry.id for entry in restored.entries] == [second.id, first.id]
        finally:
            restored.close()
    finally:
        store.close()


def test_media_search_matches_series_and_voice_and_drops_hidden_selection(window):
    entries = (
        HistoryEntry(
            "a", "Series 01", "Series 01", SOURCE, 720, 1, series="Космос", translation="Studio A"
        ),
        HistoryEntry(
            "b", "Series 02", "Series 02", SOURCE, 480, 2, series="Космос", translation="Studio B"
        ),
    )
    window.history_page.set_history(entries, {}, set())
    window.library_page.set_files(
        tuple(MediaFile(e.id, e.title, 16, e.created, e.series, e.translation) for e in entries)
    )

    for page in (window.history_page, window.library_page):
        group = page.table.topLevelItem(0)
        assert not group.isExpanded()
        group.child(0).setSelected(True)
        page.search.setText(f"{entries[0].series.upper()} studio B")
        group = page.table.topLevelItem(0)
        assert group.isExpanded()
        assert group.childCount() == 1
        assert group.child(0).text(0) == "Series 02"
        assert not page.selected_ids()
        assert not page.delete_button.isEnabled()
        page.search.setText("пусто")
        assert page.empty.text() == t("media_no_matches")
        page.search.clear()
        assert not page.table.topLevelItem(0).isExpanded()


def test_separate_windows_keep_each_others_history(tmp_path):
    path = tmp_path / "history.json"
    first = HistoryStore(path)
    second = HistoryStore(path)
    try:
        first.put(HistoryEntry("first", "One", "One", SOURCE, 720, 1))
        second.put(HistoryEntry("second", "Two", "Two", SOURCE, 480, 2))
        first.flush()
        second.flush()
        first.remove({"first"}, set())
        first.flush()
        restored = HistoryStore(path)
        try:
            assert [entry.id for entry in restored.entries] == ["second"]
        finally:
            restored.close()
    finally:
        first.close()
        second.close()


def test_stepper_changes_once_and_other_settings_revert_during_cooldown(window):
    window.open_settings()
    page = window.settings_page
    page.plus_button.click()
    assert window.settings.concurrent_downloads == 3
    page.minus_button.click()
    page.confirm_delete_check.click()
    assert window.settings.concurrent_downloads == 3
    assert page.concurrent_spin.value() == 3
    assert page.confirm_delete_check.isChecked()
    assert window.store.load().confirm_delete is True


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_concurrency_value_has_room_to_render(window, qtbot, theme):
    window._apply_settings(window.settings.updated(theme=theme), force=True)
    window.show()
    window.open_settings()
    qtbot.wait(20)
    editor = window.settings_page.concurrent_spin.findChild(QLineEdit)
    assert editor.text() == "2"
    assert editor.width() >= editor.fontMetrics().horizontalAdvance("2") + 4
    assert editor.height() >= editor.fontMetrics().height()


def test_fallback_from_assembly_restores_cancellation(window, monkeypatch):
    identifier, job = enqueue(window, monkeypatch)
    window._on_progress(identifier, ProgressSnapshot(stage="processing"))
    assert job.status == "assembling"
    window._on_progress(identifier, ProgressSnapshot(quality=480, stage="downloading"))
    assert job.status == "downloading"
    assert not job.row.cancel_button.isHidden()
    assert window.history.get(identifier).quality == 480
    window._cancel_job(identifier)
    assert job.cancelling


def test_clipboard_cannot_replace_pending_retry(window, monkeypatch):
    window.settings = window.settings.updated(auto_paste=True)
    QApplication.clipboard().setText(SOURCE)
    window._retry_entry = HistoryEntry("retry", "Episode", "Episode", SOURCE, 480, 1)
    window.url_edit.clear()
    window._auto_paste()
    assert window.url_edit.text() == ""
    window._retry_entry = None
    window._set_resolving(True)
    window._auto_paste()
    assert window.url_edit.text() == ""
    window._set_resolving(False)


def test_close_during_assembly_keeps_the_job_running(window, monkeypatch):
    identifier, job = enqueue(window, monkeypatch)
    window.show()
    window._on_progress(identifier, ProgressSnapshot(stage="processing"))
    monkeypatch.setattr(window.tray, "ensure_visible", lambda: True)
    assert not window.close()
    assert not job.finished
    assert not job.cancelling
    assert not window.isVisible()
    window.restore_window()
    assert not window.request_quit()
    assert window.isVisible()


def test_clearing_history_keeps_existing_session_download_available(window, monkeypatch, qtbot):
    identifier, job = enqueue(window, monkeypatch)
    path = window.settings.download_dir / "Episode.mp4"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"finished video")
    window._on_job_finished(identifier, str(path))
    qtbot.waitUntil(lambda: not window.media.scanning, timeout=3000)
    window.settings = window.settings.updated(confirm_delete=False)
    window._remove_history({identifier})
    assert window.history.get(identifier) is None
    window._request_media_refresh()
    qtbot.waitUntil(lambda: not window.media.scanning, timeout=3000)
    assert path.exists()
    assert not job.row.open_button.isHidden()
    assert window.media.availability[str(path)]
    path.unlink()
    window._request_media_refresh()
    qtbot.waitUntil(lambda: not window.media.scanning, timeout=3000)
    assert job.row.open_button.isHidden()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX named-home expansion")
def test_unknown_user_download_directory_rolls_back_without_exception(window):
    previous = window.settings
    window.open_settings()
    window.settings_page.folder_edit.setText("~kodikdown_no_such_user_qa/videos")
    window.settings_page._folder_edited()
    assert window.settings == previous
    assert window.settings_page.folder_edit.text() == str(previous.download_dir)
    assert window.save_indicator.state == "idle"
    assert len(window._toasts) == 1


def test_periodic_refresh_does_not_starve_a_slow_scan(window, monkeypatch, qtbot):
    qtbot.waitUntil(lambda: not window.media.scanning, timeout=3000)
    tasks = []
    monkeypatch.setattr(window.media.pool, "start", tasks.append)
    monkeypatch.setattr(window, "isVisible", lambda: True)
    monkeypatch.setattr(window, "isActiveWindow", lambda: True)
    window._request_media_refresh()
    task = tasks[0]
    for _ in range(4):
        window._poll_media()
    assert window.media._generation == task.generation
    window.media._on_scanned(task.generation, (), {})
    assert not window.media.scanning


def test_started_download_changes_label_and_late_start_does_not_reset_assembly(window, monkeypatch):
    from kodikdown.i18n import t

    identifier, job = enqueue(window, monkeypatch)
    window._on_job_started(identifier)
    assert job.row.detail.text() == t("history_downloading")
    window._on_progress(identifier, ProgressSnapshot(stage="processing"))
    window._on_job_started(identifier)
    assert job.status == "assembling"
    assert job.row.detail.text() == t("stage_processing")


@pytest.mark.parametrize("language", ["ru", "en"])
def test_exit_confirmation_uses_app_language_and_rejects_duplicate_exit(window, language):
    from kodikdown.i18n import current_language, set_language, t

    previous = current_language()
    set_language(language)
    observed = []

    def close_dialog():
        dialog = window._confirmation
        observed.extend(
            [
                dialog.button(QMessageBox.StandardButton.Yes).text(),
                dialog.button(QMessageBox.StandardButton.No).text(),
                window.request_quit(),
            ]
        )
        dialog.done(QMessageBox.StandardButton.No)

    QTimer.singleShot(0, close_dialog)
    try:
        assert not window._confirm_quit(1)
        assert observed == [t("tray_quit"), t("cancel"), False]
        assert window._confirmation is None
    finally:
        set_language(previous)
