from __future__ import annotations

import contextlib
import json
import os
import tempfile
from dataclasses import dataclass, field, replace
from pathlib import Path

from platformdirs import user_config_dir


def default_download_dir() -> Path:
    downloads = Path.home() / "Downloads"
    base = downloads if downloads.is_dir() else Path.home()
    return base / "KodikDown"


@dataclass(frozen=True)
class Settings:
    download_dir: Path = field(default_factory=default_download_dir)

    def updated(
        self,
        *,
        download_dir: Path | None = None,
    ) -> Settings:
        return replace(
            self,
            download_dir=self.download_dir if download_dir is None else download_dir,
        )


class ConfigStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (Path(user_config_dir("kodikdown", appauthor=False)) / "settings.json")

    def load(self) -> Settings:
        try:
            stored: dict[str, object] = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            stored = {}

        raw_directory = stored.get("download_dir")
        if isinstance(raw_directory, str) and raw_directory.strip():
            return Settings(download_dir=Path(raw_directory).expanduser())
        return Settings(download_dir=default_download_dir())

    def save(self, settings: Settings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {"download_dir": str(settings.download_dir)}, indent=2, ensure_ascii=False
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
