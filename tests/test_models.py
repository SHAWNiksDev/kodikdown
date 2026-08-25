from __future__ import annotations

import pytest

from kodikdown.kodik.models import EmbedInfo, ResolvedVideo, StreamVariant

HASH = "a" * 32


@pytest.fixture()
def resolved() -> ResolvedVideo:
    variants = (
        StreamVariant(720, "https://cdn/720.m3u8"),
        StreamVariant(480, "https://cdn/480.m3u8"),
        StreamVariant(360, "https://cdn/360.m3u8"),
    )
    return ResolvedVideo(title="Test", variants=variants)


def test_best_is_highest_quality(resolved: ResolvedVideo) -> None:
    assert resolved.best.quality == 720


def test_pick_exact_match(resolved: ResolvedVideo) -> None:
    assert resolved.pick(480).url.endswith("480.m3u8")


def test_pick_falls_back_to_closest_lower(resolved: ResolvedVideo) -> None:
    assert resolved.pick(600).quality == 480


def test_pick_without_preference_returns_best(resolved: ResolvedVideo) -> None:
    assert resolved.pick(None).quality == 720


def test_embed_page_url_appends_quality_only_when_known() -> None:
    bare = EmbedInfo("kodik.info", "video", "91873", HASH)
    with_quality = EmbedInfo("kodik.info", "video", "91873", HASH, 720)
    assert f"/{HASH}" in bare.page_url
    assert with_quality.page_url.endswith(f"/{HASH}/720p")
