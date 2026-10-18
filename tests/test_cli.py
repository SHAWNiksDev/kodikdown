from __future__ import annotations

import pytest
import respx
from typer.testing import CliRunner

from kodikdown.cli import app

PAGE_URL = "https://mock.local/video/91873/060cab655974d46835b3f4405807acc2/720p"


def _mock_resolve(
    player_page_html: str, player_js_snippet: str, video_info_json: dict[str, object]
) -> None:
    respx.get(PAGE_URL).respond(200, text=player_page_html)
    respx.get(url__startswith="https://mock.local/assets/js/app.player_single").respond(
        200, text=player_js_snippet
    )
    respx.post("https://mock.local/ftor").respond(200, json=video_info_json)


@respx.mock
def test_download_list_qualities(
    player_page_html: str, player_js_snippet: str, video_info_json: dict[str, object]
) -> None:
    _mock_resolve(player_page_html, player_js_snippet, video_info_json)
    result = CliRunner().invoke(app, ["download", PAGE_URL, "--list-qualities"])
    assert result.exit_code == 0
    assert "720p" in result.output


@respx.mock
def test_download_print_url(
    player_page_html: str, player_js_snippet: str, video_info_json: dict[str, object]
) -> None:
    _mock_resolve(player_page_html, player_js_snippet, video_info_json)
    result = CliRunner().invoke(app, ["download", PAGE_URL, "--print-url"])
    assert result.exit_code == 0
    # Warnings go to stderr, so the URL is the last line of the captured text.
    assert result.output.strip().splitlines()[-1].startswith("https://")


@respx.mock
def test_download_reports_proxy_warning(
    player_page_html: str, player_js_snippet: str, video_info_json: dict[str, object]
) -> None:
    _mock_resolve(player_page_html, player_js_snippet, video_info_json)
    result = CliRunner().invoke(app, ["download", PAGE_URL, "--print-url"])
    assert result.exit_code == 0
    assert "cdn" in result.output.lower()


@respx.mock
def test_list_translations(
    player_page_html: str, player_js_snippet: str, video_info_json: dict[str, object]
) -> None:
    _mock_resolve(player_page_html, player_js_snippet, video_info_json)
    result = CliRunner().invoke(app, ["download", PAGE_URL, "--list-translations"])

    assert result.exit_code == 0
    assert "1. AniLibria.TV" in result.output
    assert "9. Субтитры" in result.output


@respx.mock
def test_translation_option_switches_lookup(
    player_page_html: str, player_js_snippet: str, video_info_json: dict[str, object]
) -> None:
    _mock_resolve(player_page_html, player_js_snippet, video_info_json)
    result = CliRunner().invoke(
        app, ["download", PAGE_URL, "--translation", "AniLibria", "--print-url"]
    )

    assert result.exit_code == 0
    assert result.output.strip().splitlines()[-1].startswith("https://")
    post_request = respx.post("https://mock.local/ftor").calls.last.request
    assert b"id=102509" in post_request.content


@respx.mock
def test_translation_option_accepts_number(
    player_page_html: str, player_js_snippet: str, video_info_json: dict[str, object]
) -> None:
    _mock_resolve(player_page_html, player_js_snippet, video_info_json)
    result = CliRunner().invoke(app, ["download", PAGE_URL, "--translation", "1", "--print-url"])

    assert result.exit_code == 0
    post_request = respx.post("https://mock.local/ftor").calls.last.request
    assert b"id=102509" in post_request.content


@respx.mock
def test_unknown_translation_exits_with_error(
    player_page_html: str, player_js_snippet: str, video_info_json: dict[str, object]
) -> None:
    _mock_resolve(player_page_html, player_js_snippet, video_info_json)
    result = CliRunner().invoke(app, ["download", PAGE_URL, "--translation", "nope"])

    assert result.exit_code == 6
    assert "nope" in result.output
    assert "AniLibria.TV" in result.output


@respx.mock
def test_invalid_url_exits_with_code_two() -> None:
    result = CliRunner().invoke(app, ["download", "https://example.com/nope"])

    assert result.exit_code == 2


@respx.mock
def test_all_mirrors_down_exits_with_network_code() -> None:
    import httpx

    for host in (
        "mock.local",
        "kodikplayer.com",
        "kodik.info",
        "kodik.biz",
        "kodik.cc",
        "aniqit.com",
    ):
        respx.get(f"https://{host}/video/91873/060cab655974d46835b3f4405807acc2/720p").mock(
            side_effect=httpx.ConnectError("no dns")
        )

    result = CliRunner().invoke(app, ["download", PAGE_URL, "--print-url"])

    assert result.exit_code == 4


def test_cli_format_helpers() -> None:
    from kodikdown.cli import _format_duration, _format_size, _format_speed

    assert _format_size(0) == "0 B"
    assert _format_size(500) == "500 B"
    assert _format_size(1024 * 1024 * 5) == "5.0 MB"
    assert _format_speed(1024 * 1024 * 2) == "2.0 MB/s"
    assert _format_duration(65) == "1:05"
    assert _format_duration(3665) == "1:01:05"


def test_gui_command_invokes_launch_gui(monkeypatch) -> None:
    launched = False

    def fake_launch() -> None:
        nonlocal launched
        launched = True

    monkeypatch.setattr("kodikdown.cli.launch_gui", fake_launch)
    CliRunner().invoke(app, ["gui", PAGE_URL])
    assert launched is True


def test_main_url_argument_routes_to_gui(monkeypatch) -> None:
    import sys

    from kodikdown.cli import main

    launched = False

    def fake_launch() -> None:
        nonlocal launched
        launched = True

    monkeypatch.setattr("kodikdown.cli.launch_gui", fake_launch)
    monkeypatch.setattr(sys, "argv", ["kodikdown", PAGE_URL])
    main()
    assert launched is True


def test_main_cli_binary_no_args_shows_help(monkeypatch) -> None:
    import sys

    from kodikdown.cli import main

    monkeypatch.setattr(sys, "argv", ["kodikdown-cli"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0


@respx.mock
def test_main_cli_binary_url_routes_to_download(
    player_page_html: str,
    player_js_snippet: str,
    video_info_json: dict[str, object],
    monkeypatch,
) -> None:
    import sys

    from kodikdown.cli import main

    _mock_resolve(player_page_html, player_js_snippet, video_info_json)
    monkeypatch.setattr(sys, "argv", ["kodikdown-cli", PAGE_URL, "--list-qualities"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0


@respx.mock
def test_download_print_url_with_mp4(
    player_page_html: str, player_js_snippet: str, video_info_json: dict[str, object]
) -> None:
    _mock_resolve(player_page_html, player_js_snippet, video_info_json)
    result = CliRunner().invoke(app, ["download", PAGE_URL, "--print-url", "--mp4"])
    assert result.exit_code == 0
    url = result.output.strip().splitlines()[-1]
    assert url.startswith("https://")
    assert not url.endswith(":hls:manifest.m3u8")
    assert url.endswith(".mp4")


def test_gui_command_passes_url(monkeypatch) -> None:
    passed_url = None

    def fake_launch(url: str | None = None) -> None:
        nonlocal passed_url
        passed_url = url

    monkeypatch.setattr("kodikdown.cli.launch_gui", fake_launch)
    CliRunner().invoke(app, ["gui", PAGE_URL])
    assert passed_url == PAGE_URL


@respx.mock
def test_download_with_custom_filename(
    player_page_html: str,
    player_js_snippet: str,
    video_info_json: dict[str, object],
    tmp_path,
    monkeypatch,
) -> None:
    _mock_resolve(player_page_html, player_js_snippet, video_info_json)
    download_called = False

    def fake_download(self, url, title, referer):
        nonlocal download_called
        download_called = True
        assert self._filename == "My_Custom_Episode"
        res = tmp_path / "My_Custom_Episode.mp4"
        res.write_bytes(b"data")
        return res

    monkeypatch.setattr("kodikdown.downloader.Downloader.download_blocking", fake_download)
    result = CliRunner().invoke(
        app, ["download", PAGE_URL, "--filename", "My_Custom_Episode", "-o", str(tmp_path)]
    )
    assert result.exit_code == 0
    assert download_called is True
