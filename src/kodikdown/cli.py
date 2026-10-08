from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Annotated

import httpx
import typer

from kodikdown import __version__
from kodikdown.config import ConfigStore, Settings
from kodikdown.downloader import DownloadCancelled, Downloader, DownloadFailed
from kodikdown.i18n import set_language, t
from kodikdown.kodik.client import KodikClient
from kodikdown.kodik.errors import (
    InvalidUrlError,
    NoStreamsError,
    PageStructureError,
    RequestFailedError,
    TranslationNotFoundError,
)
from kodikdown.kodik.models import ResolvedVideo, Translation, referer_for
from kodikdown.ui.app import launch_tui

app = typer.Typer(
    add_completion=False,
    invoke_without_command=True,
    help="Download videos from Kodik players.",
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"kodikdown {__version__}")
        raise typer.Exit


@app.callback()
def callback(
    ctx: typer.Context,
    version: Annotated[
        bool | None,
        typer.Option("--version", "-V", callback=_version_callback, is_eager=True),
    ] = None,
) -> None:
    if ctx.invoked_subcommand is None:
        launch_tui()


@app.command()
def download(
    url: Annotated[str, typer.Argument(help="Kodik player link or iframe tag")],
    quality: Annotated[int | None, typer.Option("--quality", "-q", min=1)] = None,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", file_okay=False, dir_okay=True),
    ] = None,
    list_qualities: Annotated[
        bool, typer.Option("--list-qualities", "-l", help="Show qualities and exit.")
    ] = False,
    list_translations: Annotated[
        bool, typer.Option("--list-translations", help="Show voice-overs and exit.")
    ] = False,
    translation: Annotated[
        str | None, typer.Option("--translation", "-t", help="Voice-over name or number.")
    ] = None,
    print_url: Annotated[
        bool, typer.Option("--print-url", help="Print the direct manifest URL and exit.")
    ] = False,
) -> None:
    """Resolve one link and save the video without opening the interface."""
    settings: Settings = ConfigStore().load()
    set_language(settings.language)
    target_dir = (output or settings.download_dir).expanduser()
    try:
        resolved = asyncio.run(_resolve(url, translation))
    except InvalidUrlError:
        typer.secho(t("cli_invalid_url"), fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from None
    except TranslationNotFoundError as exc:
        message = (
            t("cli_translation_unknown", name=exc.name, list=exc.available)
            if exc.available
            else t("cli_translation_missing")
        )
        typer.secho(message, fg=typer.colors.RED, err=True)
        raise typer.Exit(6) from None
    except (NoStreamsError, PageStructureError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(3) from None
    except (RequestFailedError, httpx.HTTPError) as exc:
        typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(4) from None

    if list_qualities:
        available = ", ".join(f"{v.quality}p" for v in resolved.variants)
        typer.echo(t("cli_qualities", title=resolved.title or "video", list=available))
        return

    if list_translations:
        if not resolved.translations:
            typer.echo(t("cli_translation_missing"))
        for index, item in enumerate(resolved.translations, start=1):
            typer.echo(f"{index}. {item.title}")
        return

    variant = resolved.pick(quality)
    if print_url:
        typer.echo(variant.url)
        return

    if quality is not None and variant.quality != quality:
        available = ", ".join(f"{v.quality}p" for v in resolved.variants)
        typer.echo(
            t("cli_quality_fallback", wanted=quality, picked=variant.quality, list=available)
        )

    title = resolved.title or "kodik-video"
    downloader = Downloader(output_dir=target_dir)

    try:
        path = downloader.download_blocking(variant.url, title, referer_for(variant.url))
    except (KeyboardInterrupt, DownloadCancelled):
        downloader.cancel()
        typer.secho("cancelled", fg=typer.colors.YELLOW, err=True)
        raise typer.Exit(130) from None
    except DownloadFailed as exc:
        typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(5) from None

    typer.secho(t("cli_download_done", path=path), fg=typer.colors.GREEN)


async def _resolve(url: str, translation: str | None = None) -> ResolvedVideo:
    async with KodikClient() as client:
        resolved = await client.resolve(url)
        if translation is None:
            return resolved
        chosen = _find_translation(resolved, translation)
        if chosen is None:
            names = ", ".join(item.title for item in resolved.translations)
            raise TranslationNotFoundError(translation, names)
        if chosen == resolved.translation:
            return resolved
        return await client.resolve(url, chosen)


def _find_translation(resolved: ResolvedVideo, query: str) -> Translation | None:
    text = query.strip()
    if text.isdigit():
        index = int(text) - 1
        if 0 <= index < len(resolved.translations):
            return resolved.translations[index]
    return resolved.find_translation(text)


def main() -> None:
    if sys.platform == "win32":
        _enable_windows_console_utf8()
    app()


def _enable_windows_console_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8", errors="replace")


if __name__ == "__main__":
    main()
