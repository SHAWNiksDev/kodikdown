from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QLabel

from kodikdown.gui.icons import app_icon
from test_desktop_pages import enqueue

pytest_plugins = ("test_desktop_pages",)


def test_wheel_preserves_settings_with_and_without_focus(window):
    window.show()
    window.open_settings()
    original = window.settings
    for control in (window.settings_page.concurrent_spin, window.settings_page.quality_combo):
        for focused in (False, True):
            if focused:
                control.setFocus()
            else:
                control.clearFocus()
            event = QWheelEvent(
                QPointF(control.rect().center()),
                QPointF(control.mapToGlobal(control.rect().center())),
                QPoint(),
                QPoint(0, -120),
                Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
                Qt.ScrollPhase.NoScrollPhase,
                False,
            )
            QApplication.sendEvent(control, event)
            assert not event.isAccepted()
            assert window.settings == original
    window.settings_page.plus_button.click()
    assert window.settings.concurrent_downloads == original.concurrent_downloads + 1


def test_settings_saves_share_one_bounded_indicator(window, qtbot):
    window._apply_settings(window.settings.updated(auto_paste=True), force=True)
    assert window.save_indicator.state == "saving"
    assert not window._toasts
    qtbot.waitUntil(lambda: window.save_indicator.state == "saved", timeout=800)
    window._apply_settings(window.settings.updated(auto_paste=False), force=True)
    assert window.save_indicator.state == "saving"
    assert not window._toasts
    qtbot.waitUntil(lambda: window.save_indicator.state == "idle", timeout=1800)
    assert not window.save_indicator.timer.isActive()


def test_failed_save_does_not_show_success(window, monkeypatch):
    def fail(settings):
        raise OSError("disk full")

    monkeypatch.setattr(window.store, "save", fail)
    window._apply_settings(window.settings.updated(auto_paste=True), force=True)
    assert window.save_indicator.state == "idle"
    assert not window.settings.auto_paste
    assert len(window._toasts) == 1


def test_close_hides_but_keeps_download_and_can_restore(window, monkeypatch):
    identifier, job = enqueue(window, monkeypatch)
    cancelled = []
    monkeypatch.setattr(job.task, "cancel", lambda: cancelled.append(True))
    monkeypatch.setattr(window.tray, "ensure_visible", lambda: True)
    window.show()
    window.url_edit.setText("keep my input")
    assert not window.close()
    assert not window.isVisible()
    assert not window._closing
    assert not window.history._closed
    assert not cancelled
    assert window.downloads.jobs[identifier] is job
    window.tray.show_action.trigger()
    assert window.isVisible()
    assert window.url_edit.text() == "keep my input"


def test_missing_tray_keeps_window_reachable_on_taskbar(window, monkeypatch):
    monkeypatch.setattr(window.tray, "ensure_visible", lambda: False)
    window.show()
    assert not window.close()
    assert window.isVisible()
    assert window.isMinimized()
    assert not window._closing
    window.restore_window()
    assert not window.isMinimized()


def test_tray_exit_keeps_confirmation_and_shuts_down_only_after_yes(window, monkeypatch, qtbot):
    _, job = enqueue(window, monkeypatch)
    monkeypatch.setattr(window, "_confirm_quit", lambda count: False)
    window.tray.quit_action.trigger()
    assert not window._closing
    assert not window._quit_requested
    assert not job.cancelling
    cancelled = []
    monkeypatch.setattr(job.task, "cancel", lambda: cancelled.append(True))
    monkeypatch.setattr(window, "_confirm_quit", lambda count: True)
    with qtbot.waitSignal(window.exit_requested):
        window.tray.quit_action.trigger()
    assert cancelled == [True]
    assert window._closing
    assert window.history._closed
    assert not window._media_timer.isActive()
    assert not window.tray.icon.isVisible()


def test_header_logo_and_about(window):
    for size in (16, 28, 64):
        image = app_icon(size=size).pixmap(size, size).toImage()
        assert image.pixelColor(size // 5, size // 2).alpha() == 255
        assert image.pixelColor(size // 2, size // 2).name() == "#ffffff"
    assert not window.settings_page.github_button.icon().isNull()
    assert not any(
        "SHAWNiks" in label.text() for label in window.settings_page.findChildren(QLabel)
    )
