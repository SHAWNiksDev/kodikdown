from __future__ import annotations

import contextlib
import threading

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Button, Label, ProgressBar

from kodikdown.downloader import ProgressSnapshot
from kodikdown.i18n import t


def format_speed(speed: float | None) -> str:
    if not speed:
        return ""
    units = ["B/s", "KB/s", "MB/s", "GB/s"]
    value = float(speed)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}"
        value /= 1024
    return ""


class DownloadCard(Widget):
    """One active download: name, progress bar, speed and a cancel button."""

    class Finished(Message):
        def __init__(self, card: DownloadCard, path: str) -> None:
            super().__init__()
            self.card = card
            self.path = path

    class Cancelled(Message):
        def __init__(self, card: DownloadCard) -> None:
            super().__init__()
            self.card = card

    class Failed(Message):
        def __init__(self, card: DownloadCard, detail: str) -> None:
            super().__init__()
            self.card = card
            self.detail = detail

    def __init__(self, title: str, quality: int, url: str = "") -> None:
        super().__init__(classes="download-card")
        label = title.strip()
        if len(label) > 42:
            label = label[:41].rstrip() + "…"
        self.entry_title = f"{quality}p · {label}"
        self.url = url
        self.cancel_event = threading.Event()
        self._bar: ProgressBar | None = None
        self._speed_label: Label | None = None
        self._cancel_button: Button | None = None

    def compose(self) -> ComposeResult:
        with Horizontal(classes="card-body"):
            with Vertical(classes="card-info"):
                yield Label(self.entry_title, classes="card-title")
                yield ProgressBar(show_eta=False, classes="card-progress")
                yield Label("", classes="card-speed")
            yield Button(t("cancel"), variant="error", classes="card-cancel", id="card-cancel")

    def push_progress(self, snapshot: ProgressSnapshot) -> None:
        try:
            if self._bar is None:
                self._bar = self.query_one(".card-progress", ProgressBar)
            if snapshot.total:
                self._bar.update(total=snapshot.total, progress=snapshot.downloaded)
            else:
                self._bar.update(progress=snapshot.downloaded)
            if self._speed_label is None:
                self._speed_label = self.query_one(".card-speed", Label)
            self._speed_label.update(format_speed(snapshot.speed))
        except Exception:
            # Card was already closed or not mounted yet.
            return

    def mark_done(self, path: str) -> None:
        self._finish_with(t("saved_to", path=path))
        self.post_message(self.Finished(self, path))

    def mark_cancelled(self) -> None:
        self._finish_with(t("cancelled"))
        self.post_message(self.Cancelled(self))

    def mark_failed(self, detail: str) -> None:
        self._finish_with(t("failed", detail=detail))
        self.post_message(self.Failed(self, detail))

    def _finish_with(self, message: str) -> None:
        self.cancel_event.set()
        for child in list(self.children):
            child.remove()
        self.add_class("card-done")
        with contextlib.suppress(Exception):
            self.mount(Label(message, classes="card-status"))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if self.cancel_event.is_set():
            return
        self.cancel_event.set()
        btn = self.query_one("#card-cancel", Button)
        btn.disabled = True
        btn.label = t("cancelling")
