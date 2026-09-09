from __future__ import annotations

import json
from pathlib import Path

from kodikdown.config import ConfigStore, Settings, default_download_dir


def test_roundtrip_save_and_load(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path / "settings.json")
    original = Settings(download_dir=tmp_path / "videos")

    store.save(original)
    loaded = store.load()

    assert loaded == original
    assert store.path.exists()


def test_load_returns_defaults_when_file_missing(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path / "absent.json")
    loaded = store.load()

    assert loaded.download_dir == default_download_dir()


def test_load_survives_corrupted_file(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{not json", encoding="utf-8")
    assert ConfigStore(path).load().download_dir == default_download_dir()


def test_load_ignores_unknown_keys(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps({"quality": "bogus", "download_dir": "/tmp/ok", "unknown": 123}),
        encoding="utf-8",
    )
    loaded = ConfigStore(path).load()

    assert loaded.download_dir == Path("/tmp/ok")


def test_updated_returns_new_instance(tmp_path: Path) -> None:
    base = Settings(download_dir=tmp_path / "videos")
    changed = base.updated(download_dir=tmp_path / "other")
    assert base.download_dir == tmp_path / "videos"
    assert changed.download_dir == tmp_path / "other"


def test_load_falls_back_on_bad_type(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"download_dir": 12345}), encoding="utf-8")
    assert ConfigStore(path).load().download_dir == default_download_dir()
