from __future__ import annotations

import pytest
import respx

from kodikdown.sources import MediaClient, Series


async def test_direct_video_decodes_title_without_changing_the_stream_url() -> None:
    url = "https://cdn.example/Episode%202.MP4?token=a%2Bb"
    async with MediaClient() as client:
        video = await client.resolve_player(url)

    assert video.title == "Episode 2"
    assert video.best.url == url


@pytest.mark.parametrize("prefix", ("anime/releases", "anime/releases/release", "release"))
@respx.mock
async def test_aniliberty_accepts_current_and_older_release_links(prefix: str) -> None:
    respx.get("https://aniliberty.top/api/v1/anime/releases/sample-series").respond(
        json={
            "name": {"main": "Sample Series"},
            "episodes": [
                {
                    "id": "fdc390c0-b5a9-4143-8695-9f1f77533b85",
                    "ordinal": 1,
                    "hls_720": "https://cdn.example/episode.m3u8",
                }
            ],
        }
    )
    async with MediaClient() as client:
        catalog = await client.lookup(
            f"https://www.aniliberty.top/{prefix}/sample-series", include_poster=False
        )
    assert isinstance(catalog, Series)
    assert catalog.title == "Sample Series"
    assert catalog.choices[0].episodes[0].number == "1"


@pytest.mark.parametrize(
    "player_tag",
    [
        '<video id="hls-video" data-stream-src="{url}"></video>',
        '<source id="vsource" src="{url}">',
    ],
)
@respx.mock
async def test_anidub_resolves_playlist_from_both_player_layouts(player_tag: str) -> None:
    page = "https://anidub.life/42-example.html"
    host = "https://player26.ladonyvesna2005.info"
    embed = f"{host}/index.php?playlist"
    first, second = "a" * 32, "b" * 32
    manifest = f"{host}/vid.php?v=%2Fs9%2F{second}&lang=ru"
    respx.get(page).respond(text=f'<title>Example</title><iframe src="{embed}"></iframe>')
    respx.get(embed).respond(
        text=(
            '<select id="episode-select">'
            f'<option value="/s9/{first}">1</option><option value="/s9/{second}">2</option>'
            "</select>" + player_tag.format(url=f"vid.php?v=%2Fs9%2F{first}&amp;lang=ru")
        )
    )
    stream = respx.get(manifest).respond(
        text="#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1000,RESOLUTION=1280x720\nchunk.m3u8\n"
    )

    async with MediaClient() as client:
        series = await client.lookup(page, include_poster=False)
        assert isinstance(series, Series)
        (choice,) = series.choices
        assert [episode.number for episode in choice.episodes] == ["1", "2"]
        video = await client.resolve_episode(series.title, choice, choice.episodes[1])

    assert video.best.quality == 720
    assert video.best.url == f"{host}/chunk.m3u8"
    assert stream.calls.last.request.headers["referer"] == embed
