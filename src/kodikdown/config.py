from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, replace
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
        return Settings(
            download_dir=Path(str(raw_directory)) if raw_directory else default_download_dir(),
        )

    def save(self, settings: Settings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(settings)
        payload["download_dir"] = str(settings.download_dir)
        self.path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
