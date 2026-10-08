from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select

from kodikdown.config import Settings
from kodikdown.i18n import t


class SettingsScreen(ModalScreen["Settings | None"]):
    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self._current = settings

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="settings-body"):
            yield Label(t("settings_title"), classes="settings-header")
            yield Label(t("download_dir"), classes="field-label")
            yield Input(value=str(self._current.download_dir), id="dir-input")
            yield Label(t("language"), classes="field-label")
            yield Select(
                (
                    (t("language_auto"), "auto"),
                    ("English", "en"),
                    ("Русский", "ru"),
                ),
                value=self._current.language,
                allow_blank=False,
                id="language-select",
            )
            with Horizontal(classes="settings-actions"):
                yield Button(t("save"), variant="primary", id="save-btn")
                yield Button(t("back"), id="back-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-btn":
            raw_dir = self.query_one("#dir-input", Input).value.strip()
            target_dir = Path(raw_dir).expanduser() if raw_dir else self._current.download_dir
            language = self.query_one("#language-select", Select).value
            self.dismiss(
                Settings(
                    download_dir=target_dir,
                    language=language if isinstance(language, str) else "auto",
                )
            )
        else:
            self.dismiss(None)
