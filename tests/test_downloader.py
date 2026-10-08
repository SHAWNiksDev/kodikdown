from __future__ import annotations

import functools
import http.server
import shutil
import socket
import subprocess
import threading
from pathlib import Path

import pytest
import yt_dlp

from kodikdown.downloader import (
    DownloadCancelled,
    Downloader,
    ProgressSnapshot,
    safe_filename,
)


def test_safe_filename_strips_illegal_chars() -> None:
    assert safe_filename('a<b>c:"d|e?f*g') == "a_b_c__d_e_f_g"


def test_safe_filename_trims_and_collapses_spaces() -> None:
    assert safe_filename("  .my  video.  ") == "my video"


def test_safe_filename_falls_back_when_empty() -> None:
    assert safe_filename(" . ??? ") == "video"
    assert safe_filename("", fallback="clip") == "clip"
    assert safe_filename("___", fallback="clip") == "clip"


def test_safe_filename_caps_length() -> None:
    assert len(safe_filename("x" * 500)) == 120


def test_safe_filename_avoids_windows_reserved_names() -> None:
    assert safe_filename("CON") != "CON"
    assert safe_filename("nul.mp4") != "nul.mp4"


def test_safe_filename_drops_media_extension() -> None:
    assert safe_filename("Show.S01E01.mkv") == "Show.S01E01"
    assert safe_filename("clip.MP4") == "clip"


def test_download_options_send_browser_identity(tmp_path: Path) -> None:
    downloader = Downloader(output_dir=tmp_path)
    options = downloader._options(tmp_path / "clip", "https://cdn.example/")
    headers = options["http_headers"]
    assert isinstance(headers, dict)
    assert headers["Referer"] == "https://cdn.example/"
    assert str(headers["User-Agent"]).startswith("Mozilla/5.0")


def test_hook_understands_fragment_counters(tmp_path: Path) -> None:
    snapshots: list[ProgressSnapshot] = []
    downloader = Downloader(output_dir=tmp_path, listener=snapshots.append)
    downloader._hook({"status": "downloading", "fragment_index": 3, "fragment_count": 10})
    assert snapshots == [ProgressSnapshot(downloaded=3, total=10, speed=None, fragments=True)]


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="module")
def hls_server(tmp_path_factory: pytest.TempPathFactory) -> object:
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")

    root = tmp_path_factory.mktemp("hls")
    clip = root / "clip.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=1:size=128x96:rate=10",
            "-pix_fmt",
            "yuv420p",
            str(clip),
        ],
        check=True,
    )
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(clip),
            "-c",
            "copy",
            "-hls_time",
            "1",
            "-hls_list_size",
            "0",
            str(root / "stream.m3u8"),
        ],
        check=True,
        cwd=root,
    )

    port = _free_port()
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}/stream.m3u8"
    server.shutdown()


def test_download_blocking_saves_file(
    hls_server: object,
    tmp_path: Path,
) -> None:
    url = hls_server  # type: ignore[assignment]
    downloader = Downloader(output_dir=tmp_path)
    produced = downloader.download_blocking(url, "My Test / Video", "http://127.0.0.1/")

    assert produced.exists()
    assert produced.stat().st_size > 0
    assert produced.name == "My Test _ Video.mp4"


def test_download_blocking_handles_bracketed_title(
    hls_server: object,
    tmp_path: Path,
) -> None:
    downloader = Downloader(output_dir=tmp_path)
    produced = downloader.download_blocking(
        hls_server,
        "[SubsPlease] Clip - 01",
        "http://127.0.0.1/",  # type: ignore[arg-type]
    )

    assert produced.name == "[SubsPlease] Clip - 01.mp4"
    assert produced.exists()


def test_progress_listener_receives_updates(
    hls_server: object,
    tmp_path: Path,
) -> None:
    snapshots: list[ProgressSnapshot] = []
    downloader = Downloader(
        output_dir=tmp_path,
        listener=snapshots.append,
    )
    downloader.download_blocking(hls_server, "tracked", "http://127.0.0.1/")  # type: ignore[arg-type]
    assert any(snap.downloaded > 0 for snap in snapshots)


def test_hook_reports_progress_to_listener(tmp_path: Path) -> None:
    snapshots: list[ProgressSnapshot] = []
    downloader = Downloader(output_dir=tmp_path, listener=snapshots.append)
    downloader._hook(
        {"status": "downloading", "downloaded_bytes": 512, "total_bytes": 1024, "speed": 256.0}
    )
    assert snapshots == [ProgressSnapshot(downloaded=512, total=1024, speed=256.0)]


def test_hook_skips_finished_events(tmp_path: Path) -> None:
    snapshots: list[ProgressSnapshot] = []
    downloader = Downloader(output_dir=tmp_path, listener=snapshots.append)
    downloader._hook({"status": "finished"})
    assert snapshots == []


def test_hook_raises_once_cancelled(tmp_path: Path) -> None:
    event = threading.Event()
    event.set()
    downloader = Downloader(output_dir=tmp_path, cancel_event=event)
    with pytest.raises(yt_dlp.utils.DownloadCancelled):
        downloader._hook({"status": "downloading"})


def test_pp_hook_raises_once_cancelled(tmp_path: Path) -> None:
    event = threading.Event()
    event.set()
    downloader = Downloader(output_dir=tmp_path, cancel_event=event)
    with pytest.raises(yt_dlp.utils.DownloadCancelled):
        downloader._pp_hook({"status": "started"})


def test_pp_hook_ignores_normal_status(tmp_path: Path) -> None:
    downloader = Downloader(output_dir=tmp_path)
    assert downloader._pp_hook({"status": "finished"}) is None


def test_download_blocking_respects_pre_set_cancel(tmp_path: Path) -> None:
    event = threading.Event()
    event.set()
    downloader = Downloader(output_dir=tmp_path, cancel_event=event)
    with pytest.raises(DownloadCancelled):
        downloader.download_blocking("http://127.0.0.1/video.m3u8", "clip", "http://127.0.0.1/")


def test_cancel_interrupts_slow_download(tmp_path: Path) -> None:
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")

    root = tmp_path / "slow"
    root.mkdir()
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=8:size=128x96:rate=10",
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "libx264",
            "-g",
            "10",
            str(root / "clip.mp4"),
        ],
        check=True,
    )
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(root / "clip.mp4"),
            "-c",
            "copy",
            "-hls_time",
            "1",
            "-hls_list_size",
            "0",
            str(root / "stream.m3u8"),
        ],
        check=True,
        cwd=root,
    )

    class Slow(http.server.SimpleHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path.endswith(".ts"):
                threading.Event().wait(0.5)
            super().do_GET()

        def log_message(self, *args: object) -> None:
            pass

    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(Slow, directory=str(root))
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/stream.m3u8"
        cancel_event = threading.Event()

        def stop_on_first_progress(snapshot: ProgressSnapshot) -> None:
            if snapshot.downloaded > 0:
                cancel_event.set()

        downloader = Downloader(
            output_dir=tmp_path / "out",
            listener=stop_on_first_progress,
            cancel_event=cancel_event,
        )
        with pytest.raises(DownloadCancelled):
            downloader.download_blocking(url, "cancelled-video", "http://127.0.0.1/")
    finally:
        server.shutdown()
