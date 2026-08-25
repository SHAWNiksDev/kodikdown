from __future__ import annotations

from kodikdown.i18n import _CATALOG, t


def test_t_formats_placeholders() -> None:
    result = t("saved_to", path="/tmp/movie.mp4")
    assert "/tmp/movie.mp4" in result


def test_t_unknown_key_returns_key() -> None:
    assert t("nonexistent_key") == "nonexistent_key"


def test_catalog_covers_cli_and_ui_messages() -> None:
    for key in ("resolve", "download", "settings_title", "cli_download_done", "cancel"):
        assert key in _CATALOG
