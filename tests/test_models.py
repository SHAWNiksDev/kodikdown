from __future__ import annotations

import pytest

from kodikdown.kodik.models import (
    EmbedInfo,
    ResolvedVideo,
    StreamVariant,
    Translation,
    referer_for,
)

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


def test_pick_below_all_returns_smallest(resolved: ResolvedVideo) -> None:
    assert resolved.pick(200).quality == 360


def test_find_translation_matches_exact_and_partial() -> None:
    translations = (
        Translation("AniLibria.TV", "video", "102509", "a" * 32),
        Translation("Reanimedia", "video", "54982", "b" * 32),
    )
    video = ResolvedVideo(title="Test", variants=(), translations=translations)

    assert video.find_translation("anilibria.tv") == translations[0]
    assert video.find_translation("rean") == translations[1]
    assert video.find_translation("missing") is None
    assert video.find_translation("") is None


def test_translation_key_is_stable() -> None:
    assert Translation("x", "video", "1", "hash").key == "video:1:hash"


def test_referer_for_uses_manifest_host() -> None:
    assert (
        referer_for("https://cdn.example.com/a/720.mp4:hls:manifest.m3u8")
        == "https://cdn.example.com/"
    )
    assert referer_for("//cdn.example.com/x.m3u8") == "https://cdn.example.com/"


def test_embed_page_url_appends_quality_only_when_known() -> None:
    bare = EmbedInfo("kodik.info", "video", "91873", HASH)
    with_quality = EmbedInfo("kodik.info", "video", "91873", HASH, 720)
    assert f"/{HASH}" in bare.page_url
    assert with_quality.page_url.endswith(f"/{HASH}/720p")
