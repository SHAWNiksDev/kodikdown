from __future__ import annotations

import httpx
import pytest
import respx

from kodikdown.kodik.client import KodikClient, build_variants
from kodikdown.kodik.errors import (
    HostUnavailableError,
    InvalidUrlError,
    NoStreamsError,
    PageStructureError,
    RequestFailedError,
)

HASH = "060cab655974d46835b3f4405807acc2"
PAGE_URL = f"https://mock.local/video/91873/{HASH}/720p"
SERIAL_HASH = "932d5da818729ec5ccc9be7968ee3717"
SERIAL_URL = f"https://mock.local/seria/1304528/{SERIAL_HASH}/720p"
JS_URL = "https://mock.local/assets/js/app.player_single"


def _mock_page(player_page_html: str, path: str = PAGE_URL) -> respx.Route:
    return respx.get(path).respond(200, text=player_page_html)


def _mock_js(player_js_snippet: str, path: str = JS_URL) -> respx.Route:
    return respx.get(url__startswith=path).respond(200, text=player_js_snippet)


def _client() -> KodikClient:
    # Pin the host list so a failure cannot silently fall through to a mirror.
    return KodikClient(hosts=("mock.local",))


@respx.mock
async def test_resolve_happy_path(
    player_page_html: str,
    player_js_snippet: str,
    video_info_json: dict[str, object],
) -> None:
    _mock_page(player_page_html)
    _mock_js(player_js_snippet)
    post = respx.post("https://mock.local/ftor").respond(200, json=video_info_json)

    async with _client() as client:
        resolved = await client.resolve(PAGE_URL)

    assert [variant.quality for variant in resolved.variants] == [720, 480, 360]
    assert all(variant.url.startswith("https://") for variant in resolved.variants)
    assert resolved.variants[0].direct_mp4 is not None
    assert resolved.title == "kodik-91873"
    assert resolved.default_quality == 360
    assert len(resolved.translations) == 9
    assert resolved.translation is not None
    assert resolved.translation.title == "Субтитры"

    form = post.calls.last.request.content.decode()
    assert "bad_user=true" in form
    assert f"hash={HASH}" in form
    # An empty ref must not be sent: the signature would not match it.
    assert "ref=" not in form


@respx.mock
async def test_post_carries_signed_url_params(
    serial_page_html: str,
    player_js_snippet: str,
    video_info_json: dict[str, object],
) -> None:
    _mock_page(serial_page_html, SERIAL_URL)
    _mock_js(player_js_snippet, "https://mock.local/assets/js/app.player_single.deadbeef.js")
    post = respx.post("https://mock.local/ftor").respond(200, json=video_info_json)

    async with _client() as client:
        await client.resolve(SERIAL_URL)

    form = post.calls.last.request.content.decode()
    assert "d=animego.org" in form
    assert "d_sign=aa%3A1" in form
    assert "pd_sign=bb%3A1" in form
    assert "ref=https%3A%2F%2Fanimego.org%2F" in form
    assert "ref_sign=cc%3A1" in form
    assert "translations" not in form


@respx.mock
async def test_stale_signatures_are_replaced_by_a_fresh_page(
    player_page_html: str,
    player_js_snippet: str,
    video_info_json: dict[str, object],
) -> None:
    page = _mock_page(player_page_html)
    _mock_js(player_js_snippet)
    respx.post("https://mock.local/ftor").side_effect = [
        httpx.Response(500, text="Internal Server Error"),
        httpx.Response(200, json=video_info_json),
    ]

    async with _client() as client:
        resolved = await client.resolve(PAGE_URL)

    assert resolved.variants
    assert page.call_count == 2


@respx.mock
async def test_non_json_reply_is_retried(
    player_page_html: str,
    player_js_snippet: str,
    video_info_json: dict[str, object],
) -> None:
    _mock_page(player_page_html)
    _mock_js(player_js_snippet)
    respx.post("https://mock.local/ftor").side_effect = [
        httpx.Response(200, text="<html>gateway error</html>"),
        httpx.Response(200, json=video_info_json),
    ]

    async with _client() as client:
        assert (await client.resolve(PAGE_URL)).variants


@respx.mock
async def test_error_payload_from_the_player_is_surfaced(
    player_page_html: str,
    player_js_snippet: str,
) -> None:
    _mock_page(player_page_html)
    _mock_js(player_js_snippet)
    respx.post("https://mock.local/ftor").respond(200, json={"error": "video is not available"})
    respx.get("https://mock.local/ftor").respond(200, json={"error": "video is not available"})

    async with _client() as client:
        with pytest.raises(RequestFailedError, match="video is not available"):
            await client.resolve(PAGE_URL)


@respx.mock
async def test_get_fallback_when_post_never_succeeds(
    player_page_html: str,
    player_js_snippet: str,
    video_info_json: dict[str, object],
) -> None:
    _mock_page(player_page_html)
    _mock_js(player_js_snippet)
    respx.post("https://mock.local/ftor").respond(403)
    respx.get("https://mock.local/ftor").respond(200, json=video_info_json)

    async with _client() as client:
        resolved = await client.resolve(PAGE_URL)

    assert resolved.variants
    assert respx.get("https://mock.local/ftor").call_count == 1


@respx.mock
async def test_resolve_raises_when_links_are_empty(
    player_page_html: str,
    player_js_snippet: str,
) -> None:
    _mock_page(player_page_html)
    _mock_js(player_js_snippet)
    respx.post("https://mock.local/ftor").respond(200, json={"links": {}})
    respx.get("https://mock.local/ftor").respond(200, json={"links": {}})

    async with _client() as client:
        with pytest.raises(NoStreamsError):
            await client.resolve(PAGE_URL)


@respx.mock
async def test_translation_switch_posts_the_new_media_id(
    serial_page_html: str,
    player_js_snippet: str,
    video_info_json: dict[str, object],
) -> None:
    _mock_page(serial_page_html, SERIAL_URL)
    _mock_js(player_js_snippet, "https://mock.local/assets/js/app.player_single.deadbeef.js")
    post = respx.post("https://mock.local/ftor").respond(200, json=video_info_json)

    async with _client() as client:
        first = await client.resolve(SERIAL_URL)
        anilibria = next(item for item in first.translations if item.title == "AniLibria.TV")
        switched = await client.resolve(SERIAL_URL, anilibria)

    assert switched.translation == anilibria
    form = post.calls.last.request.content.decode()
    assert "id=102509" in form
    assert "hash=e5af7227ae1de504d41f753c59c7b4ba" in form


@respx.mock
async def test_dead_host_falls_back_to_a_mirror(
    serial_page_html: str,
    player_js_snippet: str,
    video_info_json: dict[str, object],
) -> None:
    embed_url = f"https://kodik.info/seria/1304528/{SERIAL_HASH}/720p"
    respx.get(embed_url).mock(side_effect=httpx.ConnectError("nodename nor servname provided"))
    _mock_page(serial_page_html, f"https://kodikplayer.com/seria/1304528/{SERIAL_HASH}/720p")
    _mock_js(player_js_snippet, "https://kodikplayer.com/assets/js/app.player_single")
    respx.post("https://kodikplayer.com/ftor").respond(200, json=video_info_json)

    async with KodikClient() as client:
        resolved = await client.resolve(embed_url)

    assert resolved.variants


@respx.mock
async def test_all_hosts_dead_raises_host_unavailable(
    player_page_html: str,
) -> None:
    url = f"https://mock.local/video/91873/{HASH}/720p"
    respx.get(url).mock(side_effect=httpx.ConnectError("no dns"))

    async with _client() as client:
        with pytest.raises(HostUnavailableError):
            await client.resolve(url)


@respx.mock
async def test_broken_page_is_not_retried_on_other_hosts() -> None:
    url = f"https://mock.local/video/91873/{HASH}/720p"
    page = respx.get(url).respond(200, text="<html>hello</html>")

    async with KodikClient() as client:
        with pytest.raises(PageStructureError):
            await client.resolve(url)

    assert page.call_count == 1


@respx.mock
async def test_proxied_streams_produce_a_warning(
    player_page_html: str,
    player_js_snippet: str,
    video_info_json: dict[str, object],
) -> None:
    _mock_page(player_page_html)
    _mock_js(player_js_snippet)
    respx.post("https://mock.local/ftor").respond(200, json=video_info_json)

    async with _client() as client:
        resolved = await client.resolve(PAGE_URL)

    assert resolved.warnings == ("proxy",)


async def test_resolve_rejects_non_embed_input() -> None:
    async with _client() as client:
        with pytest.raises(InvalidUrlError):
            await client.resolve("not a link at all")


def test_build_variants_skips_malformed_entries() -> None:
    data = {
        "links": {
            "720": [{"src": "@@@@"}, {"broken": True}],
            "oops": [{"src": "zzz"}],
            "360": "not-a-list",
        }
    }
    assert build_variants(data) == ()


def test_build_variants_prefers_hls_entry(video_info_json: dict[str, object]) -> None:
    links = video_info_json["links"]
    assert isinstance(links, dict)
    hls = links["720"][0]  # type: ignore[index]
    variants = build_variants(
        {
            "links": {
                "720": [
                    {"src": "https://cdn.example/720.mp4", "type": "video/mp4"},
                    hls,
                ]
            }
        }
    )

    assert len(variants) == 1
    assert variants[0].kind == "hls"


def test_build_variants_dedupes_same_quality(video_info_json: dict[str, object]) -> None:
    links = video_info_json["links"]
    assert isinstance(links, dict)
    entry = links["720"][0]  # type: ignore[index]
    variants = build_variants({"links": {"720": [entry, entry], "360": [entry]}})

    assert [variant.quality for variant in variants] == [720, 360]
