from __future__ import annotations

import pytest
from textual.widgets import Input

from kodikdown.ui.app import KodikDownApp


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
