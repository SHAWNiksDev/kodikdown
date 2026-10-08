from __future__ import annotations

from pathlib import Path

import pytest
from textual.widgets import Button, Input, Label, Select

from kodikdown.config import ConfigStore, Settings
from kodikdown.i18n import set_language
from kodikdown.kodik.models import ResolvedVideo, StreamVariant, Translation
from kodikdown.ui.app import KodikDownApp
from kodikdown.ui.settings import SettingsScreen


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
