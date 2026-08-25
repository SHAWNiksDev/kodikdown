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

from kodikdown.downloader import Downloader, ProgressSnapshot, safe_filename


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
