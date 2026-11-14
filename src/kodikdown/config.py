from __future__ import annotations

import contextlib
import json
import os
import tempfile
from dataclasses import dataclass, field, replace
from pathlib import Path

from platformdirs import user_config_dir

LANGUAGE_CHOICES = ("auto", "en", "ru")
THEME_CHOICES = ("auto", "light", "dark")
MIN_CONCURRENT_DOWNLOADS = 1
MAX_CONCURRENT_DOWNLOADS = 5


def default_download_dir() -> Path:
    downloads = Path.home() / "Downloads"
    base = downloads if downloads.is_dir() else Path.home()
    return base / "KodikDown"


@dataclass(frozen=True)
class Settings:
    download_dir: Path = field(default_factory=default_download_dir)
    language: str = "auto"
    theme: str = "auto"
    concurrent_downloads: int = 2
    prefer_mp4: bool = False
    default_quality: str = "ask"
    auto_paste: bool = False
    confirm_cancel_download: bool = True
    confirm_delete: bool = True
    animations: bool = True

    def updated(
        self,
        *,
        download_dir: Path | None = None,
        language: str | None = None,
        theme: str | None = None,
        concurrent_downloads: int | None = None,
        prefer_mp4: bool | None = None,
        default_quality: str | None = None,
        auto_paste: bool | None = None,
        confirm_cancel_download: bool | None = None,
        confirm_delete: bool | None = None,
        animations: bool | None = None,
    ) -> Settings:
        return replace(
            self,
            download_dir=self.download_dir if download_dir is None else download_dir,
            language=self.language if language is None else language,
            theme=self.theme if theme is None else theme,
            concurrent_downloads=(
                self.concurrent_downloads if concurrent_downloads is None else concurrent_downloads
            ),
            prefer_mp4=self.prefer_mp4 if prefer_mp4 is None else prefer_mp4,
            default_quality=self.default_quality if default_quality is None else default_quality,
            auto_paste=self.auto_paste if auto_paste is None else auto_paste,
            confirm_cancel_download=(
                self.confirm_cancel_download
                if confirm_cancel_download is None
                else confirm_cancel_download
            ),
            confirm_delete=self.confirm_delete if confirm_delete is None else confirm_delete,
            animations=self.animations if animations is None else animations,
        )


class ConfigStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (Path(user_config_dir("kodikdown", appauthor=False)) / "settings.json")

    def load(self) -> Settings:
        try:
            stored: dict[str, object] = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            stored = {}
        if not isinstance(stored, dict):
            stored = {}

        raw_directory = stored.get("download_dir")
        download_dir = default_download_dir()
        if isinstance(raw_directory, str) and raw_directory.strip():
            try:
                if "\x00" in raw_directory:
                    raise ValueError("Download directory contains a null character")
                download_dir = Path(raw_directory).expanduser()
            except (OSError, RuntimeError, ValueError):
                # A stale ~user or malformed path must not stop app startup or
                # discard the remaining valid preferences.
                pass

        language = _choice(stored.get("language"), LANGUAGE_CHOICES, "auto")
        theme = _choice(stored.get("theme"), THEME_CHOICES, "auto")
        concurrent = _int_in_range(
            stored.get("concurrent_downloads"),
            MIN_CONCURRENT_DOWNLOADS,
            MAX_CONCURRENT_DOWNLOADS,
            default=2,
        )
        return Settings(
            download_dir=download_dir,
            language=language,
            theme=theme,
            concurrent_downloads=concurrent,
            prefer_mp4=stored.get("prefer_mp4") is True,
            default_quality=_choice(
                stored.get("default_quality"), ("ask", "1080", "720", "480", "360"), "ask"
            ),
            auto_paste=stored.get("auto_paste") is True,
            confirm_cancel_download=stored.get("confirm_cancel_download", True) is not False,
            confirm_delete=stored.get("confirm_delete", True) is not False,
            animations=stored.get("animations", True) is not False,
        )

    def save(self, settings: Settings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {
                "download_dir": str(settings.download_dir),
                "language": settings.language,
                "theme": settings.theme,
                "concurrent_downloads": settings.concurrent_downloads,
                "prefer_mp4": settings.prefer_mp4,
                "default_quality": settings.default_quality,
                "auto_paste": settings.auto_paste,
                "confirm_cancel_download": settings.confirm_cancel_download,
                "confirm_delete": settings.confirm_delete,
                "animations": settings.animations,
            },
            indent=2,
            ensure_ascii=False,
        )
        # Write next to the target and replace, so a crash mid-write cannot
        # leave a half-saved settings file behind.
        handle, temp_name = tempfile.mkstemp(
            dir=self.path.parent, prefix=f".{self.path.name}.", suffix=".tmp"
        )
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                stream.write(payload)
            os.replace(temp_name, self.path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(temp_name)
            raise


def _choice(value: object, choices: tuple[str, ...], default: str) -> str:
    return value if isinstance(value, str) and value in choices else default


def _int_in_range(value: object, low: int, high: int, *, default: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return max(low, min(high, value))
