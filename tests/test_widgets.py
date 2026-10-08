from __future__ import annotations

import pytest

from kodikdown.downloader import ProgressSnapshot
from kodikdown.i18n import set_language
from kodikdown.ui.widgets import DownloadCard, format_eta, format_size, format_speed


@pytest.fixture(autouse=True)
def _english() -> None:
    set_language("en")
    yield
    set_language("en")


def test_format_size_scales_units() -> None:
    assert format_size(None) == ""
    assert format_size(0) == ""
    assert format_size(512) == "512 B"
    assert format_size(1536) == "1.5 KB"
    assert format_size(5 * 1024**2) == "5.0 MB"


def test_format_speed_scales_units() -> None:
    assert format_speed(None) == ""
    assert format_speed(1024) == "1.0 KB/s"


def test_format_eta_stays_readable() -> None:
    assert format_eta(None) == ""
    assert format_eta(0) == ""
    assert format_eta(65) == "1:05"
    assert format_eta(3661) == "1:01:01"
    assert format_eta(25 * 3600) == ""


def test_progress_details_for_bytes() -> None:
    snapshot = ProgressSnapshot(downloaded=50, total=100, speed=10.0)
    details = DownloadCard._progress_details(snapshot)
    assert "50 B / 100 B" in details
    assert "10.0 B/s" in details
    assert "ETA" in details


def test_progress_details_for_fragments() -> None:
    snapshot = ProgressSnapshot(downloaded=3, total=10, fragments=True)
    assert DownloadCard._progress_details(snapshot) == "3/10"


def test_progress_details_before_first_byte() -> None:
    snapshot = ProgressSnapshot(downloaded=0, total=100)
    assert DownloadCard._progress_details(snapshot).startswith("0 B / 100 B")
