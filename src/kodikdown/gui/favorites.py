from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from PySide6.QtCore import QSettings


@dataclass(frozen=True)
class Favorite:
    url: str
    title: str
    player: str
    voice: str
    quality: int
    group: bool
    prefer_mp4: bool


class Favorites:
    def __init__(self, directory: Path) -> None:
        self._settings = QSettings(str(directory / "favorites.ini"), QSettings.Format.IniFormat)

    def entries(self) -> list[Favorite]:
        self._settings.sync()
        found = []
        for key in self._settings.allKeys():
            try:
                item = Favorite(**json.loads(str(self._settings.value(key, "", str))))
                if item.url.startswith(("https://", "http://")) and item.quality > 0:
                    found.append(item)
            except (ValueError, AttributeError, TypeError):
                continue
        return sorted(found, key=lambda item: item.title.casefold())

    def save(self, favorite: Favorite) -> None:
        self._settings.setValue(
            _key(favorite.url), json.dumps(asdict(favorite), ensure_ascii=False)
        )
        self._sync()

    def remove(self, favorite: Favorite) -> None:
        self._settings.remove(_key(favorite.url))
        self._sync()

    def _sync(self) -> None:
        self._settings.sync()
        if self._settings.status() != QSettings.Status.NoError:
            raise OSError(self._settings.fileName())


def _key(url: str) -> str:
    return url.encode().hex()
