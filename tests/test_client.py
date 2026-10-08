from __future__ import annotations

import httpx
import pytest
import respx

from kodikdown.kodik.client import KodikClient, build_variants
from kodikdown.kodik.errors import InvalidUrlError, NoStreamsError, RequestFailedError

PAGE_URL = "https://mock.local/video/91873/060cab655974d46835b3f4405807acc2/720p"


def _routes(
    player_page_html: str,
    player_js_snippet: str,
    video_info_json: dict[str, object],
) -> None:
    respx.get(PAGE_URL).respond(200, text=player_page_html)
    respx.get(url__startswith="https://mock.local/assets/js/app.player_single").respond(
        200, text=player_js_snippet
    )
    respx.post("https://mock.local/ftor").respond(200, json=video_info_json)


@respx.mock
async def test_resolve_happy_path(
    player_page_html: str,
    player_js_snippet: str,
    video_info_json: dict[str, object],
) -> None:
    _routes(player_page_html, player_js_snippet, video_info_json)

    async with KodikClient() as client:
        resolved = await client.resolve(PAGE_URL)

    qualities = [variant.quality for variant in resolved.variants]
    assert qualities == [720, 480, 360]
    assert all(variant.url.startswith("https://") for variant in resolved.variants)
    assert resolved.title == "kodik-91873"

    post_request = respx.post("https://mock.local/ftor").calls.last.request
    assert b"bad_user=True" in post_request.content


@respx.mock
async def test_endpoint_refreshed_after_server_failure(
    player_page_html: str,
    player_js_snippet: str,
    video_info_json: dict[str, object],
) -> None:
    _routes(player_page_html, player_js_snippet, video_info_json)
    respx.post("https://mock.local/ftor").side_effect = [
        httpx.Response(500),
        httpx.Response(200, json=video_info_json),
    ]

    async with KodikClient() as client:
        resolved = await client.resolve(PAGE_URL)

    assert len(respx.post("https://mock.local/ftor").calls) == 2
    assert resolved.variants


@respx.mock
async def test_resolve_recovers_from_non_json_reply(
    player_page_html: str,
    player_js_snippet: str,
    video_info_json: dict[str, object],
) -> None:
    _routes(player_page_html, player_js_snippet, video_info_json)
    respx.post("https://mock.local/ftor").side_effect = [
        httpx.Response(200, text="<html>gateway error</html>"),
        httpx.Response(200, json=video_info_json),
    ]

    async with KodikClient() as client:
        resolved = await client.resolve(PAGE_URL)

    assert len(respx.post("https://mock.local/ftor").calls) == 2
    assert resolved.variants


@respx.mock
async def test_resolve_raises_after_two_non_json_replies(
    player_page_html: str,
    player_js_snippet: str,
) -> None:
    respx.get(PAGE_URL).respond(200, text=player_page_html)
    respx.get(url__startswith="https://mock.local/assets/js/app.player_single").respond(
        200, text=player_js_snippet
    )
    respx.post("https://mock.local/ftor").respond(200, text="still not json")

    async with KodikClient() as client:
        with pytest.raises(RequestFailedError):
            await client.resolve(PAGE_URL)


@respx.mock
async def test_resolve_reuses_page_and_endpoint(
    player_page_html: str,
    player_js_snippet: str,
    video_info_json: dict[str, object],
) -> None:
    page_route = respx.get(PAGE_URL).respond(200, text=player_page_html)
    js_route = respx.get(url__startswith="https://mock.local/assets/js/app.player_single").respond(
        200, text=player_js_snippet
    )
    post_route = respx.post("https://mock.local/ftor").respond(200, json=video_info_json)

    async with KodikClient() as client:
        first = await client.resolve(PAGE_URL)
        second = await client.resolve(PAGE_URL)

    assert first.variants == second.variants
    assert page_route.call_count == 1
    assert js_route.call_count == 1
    assert post_route.call_count == 1


@respx.mock
async def test_resolve_marks_current_translation(
    player_page_html: str,
    player_js_snippet: str,
    video_info_json: dict[str, object],
) -> None:
    _routes(player_page_html, player_js_snippet, video_info_json)

    async with KodikClient() as client:
        resolved = await client.resolve(PAGE_URL)

    assert resolved.translation is not None
    assert resolved.translation.title == "Субтитры"
    assert len(resolved.translations) == 9


@respx.mock
async def test_resolve_switches_translation(
    player_page_html: str,
    player_js_snippet: str,
    video_info_json: dict[str, object],
) -> None:
    _routes(player_page_html, player_js_snippet, video_info_json)

    async with KodikClient() as client:
        first = await client.resolve(PAGE_URL)
        anilibria = next(item for item in first.translations if item.title == "AniLibria.TV")
        switched = await client.resolve(PAGE_URL, anilibria)

    assert switched.translation == anilibria
    post_request = respx.post("https://mock.local/ftor").calls.last.request
    assert b"id=102509" in post_request.content
    assert b"hash=e5af7227ae1de504d41f753c59c7b4ba" in post_request.content


@respx.mock
async def test_resolve_raises_when_no_streams(
    player_page_html: str,
    player_js_snippet: str,
) -> None:
    respx.get(PAGE_URL).respond(200, text=player_page_html)
    respx.get(url__startswith="https://mock.local/assets/js/app.player_single").respond(
        200, text=player_js_snippet
    )
    respx.post("https://mock.local/ftor").respond(200, json={"links": {}})

    async with KodikClient() as client:
        with pytest.raises(NoStreamsError):
            await client.resolve(PAGE_URL)


async def test_resolve_rejects_non_embed_input() -> None:
    async with KodikClient() as client:
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


def test_build_variants_dedupes_same_quality(video_info_json: dict[str, object]) -> None:
    links = video_info_json["links"]
    assert isinstance(links, dict)
    entry = links["720"][0]  # type: ignore[index]
    variants = build_variants({"links": {"720": [entry, entry], "360": [entry]}})

    assert [variant.quality for variant in variants] == [720, 360]
