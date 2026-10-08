from __future__ import annotations

import pytest

from kodikdown.i18n import _CATALOG, current_language, detect_language, set_language, t


@pytest.fixture(autouse=True)
def _restore_language() -> None:
    set_language("en")
    yield
    set_language("en")


def test_t_formats_placeholders() -> None:
    result = t("saved_to", path="/tmp/movie.mp4")
    assert "/tmp/movie.mp4" in result


def test_t_unknown_key_returns_key() -> None:
    assert t("nonexistent_key") == "nonexistent_key"


def test_catalog_keys_match_between_languages() -> None:
    assert _CATALOG["en"].keys() == _CATALOG["ru"].keys()


def test_catalog_covers_cli_and_ui_messages() -> None:
    for key in (
        "resolve",
        "download",
        "settings_title",
        "cli_download_done",
        "cli_quality_fallback",
        "cli_qualities",
        "cli_translation_unknown",
        "cancel",
        "language",
    ):
        assert key in _CATALOG["en"]
        assert key in _CATALOG["ru"]


def test_set_language_switches_catalog() -> None:
    assert set_language("ru") == "ru"
    assert t("download") == "Скачать"
    assert set_language("en") == "en"
    assert t("download") == "Download"


def test_auto_language_uses_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANG", "ru_RU.UTF-8")
    monkeypatch.delenv("LC_ALL", raising=False)
    monkeypatch.delenv("LC_MESSAGES", raising=False)

    assert detect_language() == "ru"
    assert set_language("auto") == "ru"
    assert current_language() == "ru"


def test_unknown_language_falls_back_to_detection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    monkeypatch.delenv("LC_ALL", raising=False)
    monkeypatch.delenv("LC_MESSAGES", raising=False)

    assert set_language("klingon") == "en"
    assert t("download") == "Download"
