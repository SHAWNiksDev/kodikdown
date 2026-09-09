from __future__ import annotations

import functools
import re
from typing import ClassVar

import httpx
import pyperclip
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Footer, Header, Input, Label, RadioButton, RadioSet, Static

from kodikdown import __version__
from kodikdown.config import ConfigStore, Settings
from kodikdown.downloader import DownloadCancelled, Downloader
from kodikdown.i18n import t
from kodikdown.kodik.client import KodikClient
from kodikdown.kodik.errors import (
    InvalidUrlError,
    KodikError,
    NoStreamsError,
    PageStructureError,
    RequestFailedError,
)
from kodikdown.kodik.models import ResolvedVideo, referer_for
from kodikdown.ui.settings import SettingsScreen
from kodikdown.ui.widgets import DownloadCard

_QUALITY_NUM_RE = re.compile(r"(\d+)")


class KodikDownApp(App[None]):
    TITLE = "KodikDown"
    SUB_TITLE = f"v{__version__}"
    ENABLE_COMMAND_PALETTE = False

    CSS = """
    Screen {
        background: $boost;
        scrollbar-color: $surface-lighten-1;
        scrollbar-background: $boost;
    }
    #main-scroll { height: 1fr; padding: 1 2 0 2; }
    .url-row { height: auto; margin-bottom: 1; }
    #url-input {
        width: 1fr; margin-right: 1;
        border: round $panel; background: $surface;
    }
    #url-input:focus { border: round $accent; }
    .url-row Button { min-width: 14; }
    #paste-btn { min-width: 10; }
    /* The default tall button borders (eighth blocks) look like dotted
       lines in the stock Windows console font, so use solid ones. */
    Button, Button:hover, Button:focus, Button:disabled {
        border: solid $panel !important;
    }
    Button.-primary, Button.-primary:hover, Button.-primary:focus {
        border: solid $primary !important;
    }
    Button.-success, Button.-success:hover, Button.-success:focus {
        border: solid $success !important;
    }
    Button.-error, Button.-error:hover, Button.-error:focus {
        border: solid $error !important;
    }
    #status {
        height: auto; margin-bottom: 1; padding: 0 1;
        color: $text-muted; width: 1fr;
    }
    #status.error { color: $error; }
    #status.success { color: $success; }
    .section-title { color: $text-muted; text-style: bold; }
    #result { display: none; height: auto; margin-bottom: 1; overflow: hidden; }
    #result.populated {
        display: block;
        border: round $panel; background: $surface; padding: 1 2;
    }
    #result > .title-line {
        text-style: bold; margin-bottom: 1;
        width: 1fr; overflow: hidden; text_overflow: ellipsis;
    }
    #quality-set { height: auto; margin-bottom: 1; }
    #download-btn { min-width: 16; }
    #downloads { height: auto; }
    #downloads-empty { color: $text-disabled; padding: 0 1 1 1; }
    .download-card {
        height: auto;
        background: $surface;
        border: round $panel;
        border-left: heavy $accent;
        padding: 0 1;
        margin-bottom: 1;
        overflow: hidden;
    }
    .download-card.card-done { border-left: heavy $success; }
    .card-body { height: auto; align-vertical: middle; }
    .card-info { width: 1fr; height: auto; margin-right: 1; overflow: hidden; }
    .card-title {
        text-style: bold; width: 1fr;
        overflow: hidden; text_overflow: ellipsis;
    }
    .card-progress { width: 1fr; }
    .card-speed { color: $text-muted; }
    .card-cancel { max-width: 12; }
    .card-cancel:disabled { opacity: 0.6; }
    .card-status { color: $success; width: 1fr; overflow: hidden; text_overflow: ellipsis; }
    SettingsScreen {
        align: center middle;
        background: $background;
    }
    #settings-body {
        width: 64;
        border: thick $panel; background: $surface; padding: 1 2;
    }
    .settings-header { text-style: bold; color: $accent; margin-bottom: 1; }
    .field-label { color: $text-muted; margin-top: 1; }
    .settings-actions { height: auto; margin-top: 1; }
    .settings-actions Button { margin-right: 1; min-width: 14; }
    """

    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
        ("ctrl+q", "quit", "Quit"),
        ("ctrl+s", "open_settings", "Settings"),
    ]

    def __init__(self, store: ConfigStore | None = None) -> None:
        super().__init__()
        self.store = store or ConfigStore()
        self.settings: Settings = self.store.load()
        self._resolved: ResolvedVideo | None = None
        self._chosen_quality: int | None = None
        self._active_urls: set[str] = set()

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with VerticalScroll(id="main-scroll"):
            with Horizontal(classes="url-row"):
                yield Input(placeholder=t("url_placeholder"), id="url-input")
                yield Button(t("paste"), id="paste-btn")
                yield Button(t("resolve"), variant="primary", id="resolve-btn")
                yield Button(t("settings_title"), id="settings-btn")
            yield Static("", id="status")
            yield VerticalScroll(id="result")
            yield Label(t("downloads_section"), classes="section-title")
            yield Static(t("downloads_empty"), id="downloads-empty")
            with Vertical(id="downloads"):
                pass
        yield Footer()

    def action_open_settings(self) -> None:
        self.push_screen(SettingsScreen(self.settings), self._apply_settings)

    def _apply_settings(self, updated: Settings | None) -> None:
        if updated is None:
            return
        self.settings = updated
        self.store.save(updated)
        self.notify(t("settings_saved"))

    def _set_status(
        self, key: str, *, error: bool = False, success: bool = False, **kwargs: object
    ) -> None:
        status = self.query_one("#status", Static)
        status.remove_class("error")
        status.remove_class("success")
        if error:
            status.add_class("error")
        elif success:
            status.add_class("success")
        status.update(t(key, **kwargs))

    @on(Button.Pressed, "#settings-btn")
    def _settings_button(self) -> None:
        self.action_open_settings()

    @on(Button.Pressed, "#paste-btn")
    def _paste_clicked(self) -> None:
        try:
            text = (pyperclip.paste() or "").strip()
        except Exception:
            self.notify(t("paste_failed"), severity="error")
            return
        if not text:
            self.notify(t("paste_empty"), severity="warning")
            return
        field = self.query_one("#url-input", Input)
        pos = min(field.cursor_position, len(field.value))
        field.value = field.value[:pos] + text + field.value[pos:]
        field.cursor_position = pos + len(text)
        field.focus()

    @on(Button.Pressed, "#resolve-btn")
    def _resolve_clicked(self) -> None:
        self._begin_resolve()

    @on(Input.Submitted, "#url-input")
    def _url_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self._begin_resolve()

    def _begin_resolve(self) -> None:
        raw = self.query_one("#url-input", Input).value.strip()
        if not raw:
            return
        self._set_status("resolving")
        self._clear_result()
        self._resolve_worker(raw)

    @work(exclusive=True, group="resolve")
    async def _resolve_worker(self, raw: str) -> None:
        try:
            async with KodikClient() as client:
                resolved = await client.resolve(raw)
        except InvalidUrlError:
            self._set_status("invalid_url", error=True)
        except NoStreamsError:
            self._set_status("no_streams", error=True)
        except PageStructureError:
            self._set_status("page_changed", error=True)
        except RequestFailedError as exc:
            self._set_status("network_error", error=True, detail=str(exc))
        except httpx.HTTPError as exc:
            self._set_status("network_error", error=True, detail=str(exc.__cause__ or exc))
        except KodikError as exc:
            self._set_status("failed", error=True, detail=str(exc))
        else:
            self._show_result(resolved)

    def _show_result(self, resolved: ResolvedVideo) -> None:
        self._resolved = resolved
        self._chosen_quality = resolved.variants[0].quality

        container = self.query_one("#result", VerticalScroll)
        options = [
            RadioButton(f"{variant.quality}p", value=(i == 0))
            for i, variant in enumerate(resolved.variants)
        ]
        title = resolved.title or t("title_unknown")
        if len(title) > 62:
            title = title[:61].rstrip() + "…"
        container.mount_all(
            [
                Label(title, classes="title-line"),
                RadioSet(*options, id="quality-set"),
                Button(t("download"), variant="success", id="download-btn"),
            ]
        )
        container.add_class("populated")
        container.scroll_visible()

    def _clear_result(self) -> None:
        self._resolved = None
        self._chosen_quality = None
        container = self.query_one("#result", VerticalScroll)
        container.remove_class("populated")
        container.remove_children()

    @on(RadioSet.Changed, "#quality-set")
    def _quality_selected(self, event: RadioSet.Changed) -> None:
        found = _QUALITY_NUM_RE.search(str(event.pressed.label))
        if found:
            self._chosen_quality = int(found.group(1))

    @on(Button.Pressed, "#download-btn")
    def _start_download(self) -> None:
        if self._resolved is None:
            return
        variant = self._resolved.pick(self._chosen_quality)
        title = self._resolved.title or t("title_unknown")

        if variant.url in self._active_urls:
            self.notify(t("already_downloading"), severity="warning")
            return

        self._active_urls.add(variant.url)
        self.query_one("#downloads-empty", Static).display = False
        card = DownloadCard(title, variant.quality, url=variant.url)
        self.query_one("#downloads", Vertical).mount(card)

        downloader = Downloader(
            output_dir=self.settings.download_dir,
            listener=functools.partial(self.call_from_thread, card.push_progress),
            cancel_event=card.cancel_event,
        )
        self._run_download(downloader, card, variant.url, title, referer_for(variant.url))

    @work(thread=True, exclusive=False, group="downloads")
    def _run_download(
        self,
        downloader: Downloader,
        card: DownloadCard,
        url: str,
        title: str,
        referer: str,
    ) -> None:
        try:
            path = downloader.download_blocking(url, title, referer)
        except DownloadCancelled:
            self.call_from_thread(card.mark_cancelled)
        except Exception as exc:
            self.call_from_thread(card.mark_failed, str(exc))
        else:
            self.call_from_thread(card.mark_done, str(path))

    @on(DownloadCard.Finished)
    def _download_finished(self, event: DownloadCard.Finished) -> None:
        event.stop()
        self._retire_card(event.card)
        self.notify(t("saved_to", path=event.path), timeout=8)

    @on(DownloadCard.Cancelled)
    def _download_cancelled(self, event: DownloadCard.Cancelled) -> None:
        event.stop()
        self._retire_card(event.card)
        self.notify(t("cancelled"))

    @on(DownloadCard.Failed)
    def _download_failed(self, event: DownloadCard.Failed) -> None:
        event.stop()
        self._retire_card(event.card)
        self._set_status("failed", error=True, detail=event.detail)

    def _retire_card(self, card: DownloadCard) -> None:
        url = getattr(card, "url", None)
        if isinstance(url, str):
            self._active_urls.discard(url)

        def cleanup() -> None:
            card.remove()
            if not self.query("#downloads > .download-card"):
                self.query_one("#downloads-empty", Static).display = True

        card.set_timer(4.0, cleanup)


def launch_tui(store: ConfigStore | None = None) -> None:
    KodikDownApp(store).run()
