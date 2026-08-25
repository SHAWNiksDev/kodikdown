from __future__ import annotations

import pytest

from kodikdown.kodik.decoder import align_quality, caesar, decode_stream_url

# Real vectors captured from a live player response.
ENCODED_360 = (
    "iPZ0kPU6Tg9eUBUck29aj2ZrHO4cG29bT3UdjA9pANQeG0pVVsf5WExqZhsfEsU1muQgmPHiZ05zGus1"
    "iuQgUPHsEM5aG25El2RPWEpiAM12EDlRU01FAFlHist0EsZHUNxxULJVD0shBNlRms9MH3ZVms0fBCZr"
    "UNtyBBRVms13T2MhVrMhHLJrU2C4GhpuGuYgVLG4UrCgHLHqGrprGuU2VhtuHLUhULQhUhU2VuZuVOC1"
    "VONsHEM2HuC0WEU1WLG6UrIgVrI1ULMeUq8hVrIcjFI0WupakhxbGE5xHuDhlK5bU3C4"
)
DECODED_360 = (
    "https://p13.solodcdn.com/s/m/aHR0cHM6Ly9jbG91ZC5zb2xvZGNkbi5jb20vdXNlcnVwbG9hZHMv"
    "YWI3MWIwYjItZDY0Zi00MWI3LWIzODgtMzM1MDc0YjM2MzMw/"
    "a3613d0c3e8c8fbd2468252d6bb8cbc679fd330233366df4e54adea6fe49c586:2026050102/"
    "360.mp4:hls:manifest.m3u8"
)


def test_caesar_matches_reference_shift() -> None:
    shifted = caesar(ENCODED_360, 8)
    assert shifted.startswith("aHR0cHM6Ly9wMTMuc29sb2RjZG4uY29t")


def test_decode_stream_url_recovers_direct_link() -> None:
    assert decode_stream_url(ENCODED_360) == DECODED_360


def test_decode_stream_url_rejects_garbage() -> None:
    assert decode_stream_url("") is None
    assert decode_stream_url("@@@@") is None


def test_align_quality_forces_requested_tier() -> None:
    upgraded = align_quality(DECODED_360, 720)
    assert "/720.mp4:" in upgraded
    assert align_quality(upgraded, 720) == upgraded


def test_align_quality_leaves_unmatched_urls_alone() -> None:
    plain = "https://cdn.example/path/video.mp4"
    assert align_quality(plain, 1080) == plain


@pytest.mark.parametrize(
    ("quality_key"),
    ["360", "480", "720"],
)
def test_fixture_links_decode_to_https(
    video_info_json: dict[str, object], quality_key: str
) -> None:
    links = video_info_json["links"]
    assert isinstance(links, dict)
    entry = links[quality_key][0]  # type: ignore[index]
    decoded = decode_stream_url(entry["src"])  # type: ignore[index]
    assert decoded is not None
    assert decoded.startswith("https://")
    assert ".mp4" in decoded
