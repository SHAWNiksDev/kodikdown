from __future__ import annotations

import pytest

from kodikdown.kodik.decoder import (
    KNOWN_SHIFT,
    caesar,
    decode_stream_url,
    normalise_url,
    stream_kind,
)

# Real vector captured from a live player response.
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


def test_caesar_rotates_forward() -> None:
    assert caesar("abcXYZ", 18) == "stuPQR"
    assert caesar(caesar("Helsinki", 18), 8) == "Helsinki"


def test_caesar_keeps_punctuation() -> None:
    assert caesar("a-b_c.1", 18) == "s-t_u.1"


def test_caesar_matches_reference_shift() -> None:
    assert caesar(ENCODED_360, KNOWN_SHIFT).startswith("aHR0cHM6Ly9wMTMuc29sb2RjZG4uY29t")


def test_decode_stream_url_recovers_direct_link() -> None:
    assert decode_stream_url(ENCODED_360) == (DECODED_360, KNOWN_SHIFT)


def test_decode_stream_url_honours_known_shift() -> None:
    assert decode_stream_url(ENCODED_360, 3) == (DECODED_360, KNOWN_SHIFT)


def test_decode_stream_url_accepts_plain_urls() -> None:
    plain = "https://cdn.example.com/video/720.mp4:hls:manifest.m3u8"
    assert decode_stream_url(plain) == (plain, 0)


def test_decode_stream_url_rejects_garbage() -> None:
    assert decode_stream_url("") is None
    assert decode_stream_url("@@@@") is None
    assert decode_stream_url("bm90IGEgdXJs") is None


@pytest.mark.parametrize("quality_key", ["360", "480", "720"])
def test_fixture_links_decode_to_https(
    video_info_json: dict[str, object], quality_key: str
) -> None:
    links = video_info_json["links"]
    assert isinstance(links, dict)
    entry = links[quality_key][0]  # type: ignore[index]
    decoded = decode_stream_url(entry["src"])  # type: ignore[index]
    assert decoded is not None
    url, _shift = decoded
    assert ".mp4" in url
    assert f"/{quality_key}.mp4:" in url


def test_stream_kind_splits_direct_mp4_from_hls() -> None:
    kind, direct = stream_kind("https://cdn/720.mp4:hls:manifest.m3u8")
    assert kind == "hls"
    assert direct == "https://cdn/720.mp4"


def test_stream_kind_recognises_plain_media() -> None:
    assert stream_kind("https://cdn/x.m3u8") == ("hls", None)
    assert stream_kind("https://cdn/x.mp4") == ("mp4", "https://cdn/x.mp4")
    assert stream_kind("https://cdn/x.mpd") == ("dash", None)


def test_normalise_url_adds_scheme() -> None:
    assert normalise_url("//cdn.example/x.m3u8") == "https://cdn.example/x.m3u8"
    assert normalise_url("https://cdn.example/x.m3u8") == "https://cdn.example/x.m3u8"
