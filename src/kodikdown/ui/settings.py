from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select

from kodikdown.config import Settings
from kodikdown.i18n import t


def _child_env() -> dict[str, str]:
    """Environment for launched helpers, with PyInstaller's lib path undone.

    The one-file bootloader puts its bundled libraries on LD_LIBRARY_PATH,
    which makes system programs like sh and xdg-open fail with symbol
    lookup errors, so restore whatever was there before it started.
    """
    env = os.environ.copy()
    original = env.pop("LD_LIBRARY_PATH_ORIG", None)
    if original is not None:
        env["LD_LIBRARY_PATH"] = original
    else:
        env.pop("LD_LIBRARY_PATH", None)
    return env


def open_in_file_manager(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined]
        return

    if sys.platform == "darwin":
        commands = [["open", str(path)]]
    else:
        commands = [
            ["gio", "open", str(path)],
            ["xdg-open", str(path)],
            ["kde-open5", str(path)],
            ["kde-open", str(path)],
            ["nautilus", str(path)],
        ]

    failures: list[str] = []
    for command in commands:
        try:
            process = subprocess.Popen(
                command,
                env=_child_env(),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            continue
        try:
            returncode = process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            return  # still running, so the opener did start something
        if returncode == 0:
            return
        failures.append(f"{command[0]} exited with {returncode}")

    raise OSError("; ".join(failures) or "no file manager found")


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
                yield Button(t("open_folder"), id="open-btn")
                yield Button(t("back"), id="back-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-btn":
            self._save()
        elif event.button.id == "open-btn":
            self._open_download_dir()
        else:
            self.dismiss(None)

    def _selected_dir(self) -> Path:
        raw_dir = self.query_one("#dir-input", Input).value.strip()
        return Path(raw_dir).expanduser() if raw_dir else self._current.download_dir

    def _save(self) -> None:
        target_dir = self._selected_dir()
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.notify(t("folder_not_created", detail=str(exc)), severity="error")
            return

        language = self.query_one("#language-select", Select).value
        self.dismiss(
            Settings(
                download_dir=target_dir,
                language=language if isinstance(language, str) else "auto",
            )
        )

    def _open_download_dir(self) -> None:
        target_dir = self._selected_dir()
        if not target_dir.is_dir():
            self.notify(t("folder_missing"), severity="warning")
            return
        try:
            open_in_file_manager(target_dir)
        except OSError as exc:
            self.notify(t("folder_open_failed", detail=str(exc)), severity="error")
