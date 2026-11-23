from __future__ import annotations

import pytest
import respx

from kodikdown.sources import MediaClient, Series


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
