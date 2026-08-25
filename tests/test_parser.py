from __future__ import annotations

import pytest

from kodikdown.kodik.errors import InvalidUrlError, PageStructureError
from kodikdown.kodik.models import EmbedInfo
from kodikdown.kodik.parser import (
    extract_embed,
    extract_endpoint,
    extract_payload,
    extract_player_js_path,
    extract_title,
)

HASH = "060cab655974d46835b3f4405807acc2"


def test_extract_embed_plain_url() -> None:
    info = extract_embed(f"https://kodik.info/video/91873/{HASH}/720p")
    assert info == EmbedInfo("kodik.info", "video", "91873", HASH, 720)
    assert info.page_url == f"https://kodik.info/video/91873/{HASH}/720p"


def test_extract_embed_without_quality_keeps_bare_url() -> None:
    info = extract_embed(f"//kodik.cc/serial/42/{HASH}")
    assert info.domain == "kodik.cc"
    assert info.media_type == "serial"
    assert info.quality is None
    assert info.page_url == f"https://kodik.cc/serial/42/{HASH}"


def test_extract_embed_from_iframe_tag() -> None:
    tag = f'<iframe src="//kodik.info/video/91873/{HASH}?i=0" width="610" height="370"></iframe>'
    info = extract_embed(tag)
    assert info.video_id == "91873"
    assert info.content_hash == HASH


def test_extract_embed_season_type() -> None:
    info = extract_embed(f"https://urumain.com/season/7711/{HASH}/480p")
    assert info.media_type == "season"


def test_extract_embed_rejects_junk() -> None:
    with pytest.raises(InvalidUrlError):
        extract_embed("https://youtube.com/watch?v=abc")
    with pytest.raises(InvalidUrlError):
        extract_embed("")


def test_extract_payload_from_live_page(player_page_html: str) -> None:
    payload = extract_payload(player_page_html)
    assert payload is not None
    assert payload.media_type == "video"
    assert payload.video_id == "91873"
    assert payload.as_form()["bad_user"] == "True"


def test_extract_payload_returns_none_when_absent() -> None:
    assert extract_payload("<html><body>nothing here</body></html>") is None


def test_extract_player_js_path(player_page_html: str) -> None:
    path = extract_player_js_path(player_page_html)
    assert path.startswith("assets/js/app.player_single")
    assert path.endswith(".js")


def test_extract_endpoint_from_bundle(player_js_snippet: str) -> None:
    assert extract_endpoint(player_js_snippet) == "/ftor"


def test_extract_endpoint_raises_on_unrelated_script() -> None:
    with pytest.raises(PageStructureError):
        extract_endpoint("console.log('hello'); $.ajax({type:'POST'});")


def test_extract_title_ignores_generic_names() -> None:
    assert extract_title("<title>Kodik Player</title>") is None
    assert extract_title("<title>Ван-Пис 1024 серия</title>") == "Ван-Пис 1024 серия"
