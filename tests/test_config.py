from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from kodikdown.config import ConfigStore, Settings, default_download_dir


def test_roundtrip_save_and_load(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path / "settings.json")
    original = Settings(
        download_dir=tmp_path / "videos",
        language="ru",
        theme="dark",
        concurrent_downloads=3,
        prefer_mp4=True,
    )

    store.save(original)
    loaded = store.load()

    assert loaded == original
    assert store.path.exists()


def test_load_returns_defaults_when_file_missing(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path / "absent.json")
    loaded = store.load()

    assert loaded.download_dir == default_download_dir()
    assert loaded.theme == "auto"
    assert loaded.concurrent_downloads == 2


def test_load_survives_corrupted_file(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{not json", encoding="utf-8")
    assert ConfigStore(path).load().download_dir == default_download_dir()


def test_load_survives_non_object_json(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
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
    changed = base.updated(download_dir=tmp_path / "other", language="ru")
    assert base.download_dir == tmp_path / "videos"
    assert base.language == "auto"
    assert changed.download_dir == tmp_path / "other"
    assert changed.language == "ru"


def test_language_and_theme_roundtrip(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path / "settings.json")
    store.save(Settings(download_dir=tmp_path / "videos", language="ru", theme="light"))

    loaded = store.load()
    assert loaded.language == "ru"
    assert loaded.theme == "light"


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        ({"language": "klingon"}, "auto"),
        ({"theme": "neon"}, "auto"),
        ({"language": 5, "theme": ["dark"]}, "auto"),
    ],
)
def test_load_falls_back_on_bad_choices(
    tmp_path: Path, stored: dict[str, object], expected: str
) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"download_dir": "/tmp/ok", **stored}), "utf-8")
    loaded = ConfigStore(path).load()

    assert loaded.language == expected
    assert loaded.theme == expected


@pytest.mark.parametrize(
    ("stored", "expected"),
    [(0, 1), (99, 5), ("many", 2), (True, 2), (None, 2), (4, 4)],
)
def test_concurrent_downloads_is_clamped(tmp_path: Path, stored: object, expected: int) -> None:
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps({"download_dir": "/tmp/ok", "concurrent_downloads": stored}), "utf-8"
    )
    assert ConfigStore(path).load().concurrent_downloads == expected


def test_load_falls_back_on_bad_type(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"download_dir": 12345}), encoding="utf-8")
    assert ConfigStore(path).load().download_dir == default_download_dir()


@pytest.mark.parametrize(
    "directory",
    [
        pytest.param(
            "~kodikdown_no_such_user_qa/videos",
            marks=pytest.mark.skipif(os.name == "nt", reason="POSIX named-home expansion"),
        ),
        "bad\x00path",
    ],
)
def test_unusable_saved_directory_keeps_other_preferences(tmp_path, directory):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"download_dir": directory, "language": "ru", "theme": "dark"}))
    loaded = ConfigStore(path).load()
    assert loaded.download_dir == default_download_dir()
    assert loaded.language == "ru"
    assert loaded.theme == "dark"


def test_save_leaves_no_temp_files_behind(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path / "settings.json")
    store.save(Settings(download_dir=tmp_path / "videos"))

    assert sorted(p.name for p in tmp_path.iterdir()) == ["settings.json"]


def test_failed_replace_keeps_previous_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = ConfigStore(tmp_path / "settings.json")
    store.save(Settings(download_dir=tmp_path / "first"))

    def broken_replace(source: object, target: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", broken_replace)
    with pytest.raises(OSError):
        store.save(Settings(download_dir=tmp_path / "second"))

    assert store.load().download_dir == tmp_path / "first"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["settings.json"]


def test_non_utf8_settings_use_defaults(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_bytes(b"\xff\xfe")
    assert ConfigStore(path).load() == Settings()


def test_desktop_preferences_roundtrip_and_partial_updates(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path / "settings.json")
    settings = Settings(
        download_dir=tmp_path,
        default_quality="480",
        auto_paste=True,
        confirm_cancel_download=False,
        confirm_delete=False,
        animations=False,
    )
    store.save(settings)
    assert store.load() == settings
    changed = settings.updated(theme="dark", language="ru")
    assert changed.default_quality == "480"
    assert changed.auto_paste is True
    assert changed.animations is False
    assert changed.confirm_cancel_download is False
    assert changed.confirm_delete is False


def test_old_settings_gain_safe_desktop_defaults(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text('{"theme":"dark","default_quality":"broken"}', encoding="utf-8")
    settings = ConfigStore(path).load()
    assert settings.theme == "dark"
    assert settings.default_quality == "ask"
    assert settings.confirm_cancel_download is True
    assert settings.confirm_delete is True
    assert settings.animations is True
