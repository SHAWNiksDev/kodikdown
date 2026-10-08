from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from textual.widgets import Button, Input, Label, Select

from kodikdown.config import ConfigStore, Settings
from kodikdown.i18n import set_language
from kodikdown.kodik.models import ResolvedVideo, StreamVariant, Translation
from kodikdown.ui.app import KodikDownApp
from kodikdown.ui.settings import SettingsScreen, _child_env, open_in_file_manager


@pytest.fixture(autouse=True)
def _restore_language() -> None:
    yield
    set_language("en")


async def test_paste_button_inserts_clipboard_at_cursor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("pyperclip.paste", lambda: "https://kodik.info/x")
    app = KodikDownApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        field = app.query_one("#url-input", Input)
        field.value = "ab"
        field.cursor_position = 1
        await pilot.click("#paste-btn")
        await pilot.pause()
        assert field.value == "ahttps://kodik.info/xb"


async def test_paste_button_keeps_value_when_clipboard_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("pyperclip.paste", lambda: "   ")
    app = KodikDownApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        field = app.query_one("#url-input", Input)
        field.value = "keep me"
        await pilot.click("#paste-btn")
        await pilot.pause()
        assert field.value == "keep me"


async def test_paste_button_survives_clipboard_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom() -> str:
        raise RuntimeError("no clipboard backend")

    monkeypatch.setattr("pyperclip.paste", boom)
    app = KodikDownApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.click("#paste-btn")
        await pilot.pause()


async def test_result_shows_translation_select() -> None:
    translations = (
        Translation("AniLibria.TV", "video", "102509", "a" * 32),
        Translation("Reanimedia", "video", "54982", "b" * 32),
    )
    resolved = ResolvedVideo(
        title="Test",
        variants=(StreamVariant(720, "https://cdn.example/720.m3u8"),),
        translations=translations,
        translation=translations[0],
    )

    app = KodikDownApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        app._show_result(resolved)
        await pilot.pause()

        select = app.query_one("#translation-select", Select)
        assert select.value == translations[0].key
        assert app.query_one("#quality-set") is not None


async def test_result_has_no_translation_select_without_choices() -> None:
    resolved = ResolvedVideo(
        title="Test",
        variants=(StreamVariant(720, "https://cdn.example/720.m3u8"),),
    )

    app = KodikDownApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        app._show_result(resolved)
        await pilot.pause()

        assert not app.query("#translation-select")


async def test_app_starts_in_saved_language(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path / "settings.json")
    store.save(Settings(download_dir=tmp_path, language="ru"))

    app = KodikDownApp(store=store)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.query_one("#resolve-btn", Button).label == "Найти видео"


async def test_settings_screen_applies_language_live(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path / "settings.json")
    store.save(Settings(download_dir=tmp_path, language="auto"))
    app = KodikDownApp(store=store)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.action_open_settings()
        await pilot.pause()

        screen = app.screen
        assert isinstance(screen, SettingsScreen)
        screen.query_one("#language-select", Select).value = "ru"
        await pilot.pause()
        screen.query_one("#save-btn", Button).press()
        await pilot.pause()

        assert app.settings.language == "ru"
        assert app.query_one("#paste-btn", Button).label == "Вставить"
        title = app.query_one("#downloads-title", Label)
        assert str(title.render()) == "Загрузки"

    assert store.load().language == "ru"


async def test_settings_rejects_file_as_download_dir(tmp_path: Path) -> None:
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("i am a file", encoding="utf-8")
    store = ConfigStore(tmp_path / "settings.json")
    app = KodikDownApp(store=store)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.action_open_settings()
        await pilot.pause()

        screen = app.screen
        assert isinstance(screen, SettingsScreen)
        screen.query_one("#dir-input", Input).value = str(blocker)
        screen.query_one("#save-btn", Button).press()
        await pilot.pause()

        assert isinstance(app.screen, SettingsScreen)
    assert not store.path.exists()


async def test_settings_opens_download_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[Path] = []
    monkeypatch.setattr("kodikdown.ui.settings.open_in_file_manager", opened.append)

    store = ConfigStore(tmp_path / "settings.json")
    store.save(Settings(download_dir=tmp_path, language="auto"))
    app = KodikDownApp(store=store)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.action_open_settings()
        await pilot.pause()
        app.screen.query_one("#open-btn", Button).press()
        await pilot.pause()

    assert opened == [tmp_path]


def test_child_env_restores_pre_pyinstaller_library_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LD_LIBRARY_PATH", "/tmp/_MEI123456")
    monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", "/usr/local/lib")

    assert _child_env()["LD_LIBRARY_PATH"] == "/usr/local/lib"


def test_child_env_drops_bundled_library_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LD_LIBRARY_PATH", "/tmp/_MEI123456")
    monkeypatch.delenv("LD_LIBRARY_PATH_ORIG", raising=False)

    assert "LD_LIBRARY_PATH" not in _child_env()


class _FakeProcess:
    def __init__(self, returncode: int) -> None:
        self.returncode = returncode

    def wait(self, timeout: float | None = None) -> int:
        return self.returncode


def test_open_in_file_manager_starts_clean_helper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("LD_LIBRARY_PATH", "/tmp/_MEI123456")
    monkeypatch.delenv("LD_LIBRARY_PATH_ORIG", raising=False)
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_popen(command: list[str], **kwargs: object) -> _FakeProcess:
        calls.append((command, kwargs))
        return _FakeProcess(0)

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    open_in_file_manager(tmp_path)

    command, kwargs = calls[0]
    assert command[0] == "gio"
    assert "LD_LIBRARY_PATH" not in kwargs["env"]  # type: ignore[operator]
    assert kwargs["stdout"] == subprocess.DEVNULL


def test_open_in_file_manager_tries_next_helper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    launched: list[str] = []
    codes = iter([3, 0])

    def fake_popen(command: list[str], **kwargs: object) -> _FakeProcess:
        launched.append(command[0])
        return _FakeProcess(next(codes))

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    open_in_file_manager(tmp_path)

    assert launched == ["gio", "xdg-open"]


def test_open_in_file_manager_reports_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: _FakeProcess(127))

    with pytest.raises(OSError):
        open_in_file_manager(tmp_path)
