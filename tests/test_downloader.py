from __future__ import annotations

import functools
import http.server
import multiprocessing
import shutil
import socket
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
import yt_dlp

from kodikdown.downloader import (
    DownloadCancelled,
    Downloader,
    DownloadFailed,
    DownloadSource,
    ProgressSnapshot,
    _bytes_on_disk,
    _is_transient,
    is_pending_output,
    release_target,
    safe_filename,
    unique_target,
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
    assert safe_filename("界" * 120) == "界" * 66
    assert safe_filename("clip\udcff.mp4") == "clip"


def test_safe_filename_avoids_windows_reserved_names() -> None:
    assert safe_filename("CON") != "CON"
    assert safe_filename("nul.mp4") != "nul.mp4"
    assert safe_filename("LPT².txt") == "_LPT².txt"


def test_safe_filename_drops_media_extension() -> None:
    assert safe_filename("Show.S01E01.mkv") == "Show.S01E01"
    assert safe_filename("clip.MP4") == "clip"


def test_safe_filename_removes_output_template_characters() -> None:
    # yt-dlp would try to expand "%(ext)s" and fail on an unknown field.
    cleaned = safe_filename("100% (1)s.mp4")
    assert "%" not in cleaned
    assert cleaned.startswith("100_")


def test_unique_target_avoids_overwriting(tmp_path: Path) -> None:
    (tmp_path / "clip.mp4").write_bytes(b"old")

    assert unique_target(tmp_path, "clip").name == "clip (2)"
    (tmp_path / "clip (2).mp4").write_bytes(b"older")
    assert unique_target(tmp_path, "clip").name == "clip (3)"
    assert unique_target(tmp_path, "fresh").name == "fresh"


def test_unique_target_reserves_names_for_parallel_jobs(tmp_path: Path) -> None:
    first = unique_target(tmp_path, "clip")
    second = unique_target(tmp_path, "clip")
    third = unique_target(tmp_path, "clip")

    assert [first.name, second.name, third.name] == ["clip", "clip (2)", "clip (3)"]

    release_target(second)
    assert unique_target(tmp_path, "clip").name == "clip (2)"

    release_target(first)
    release_target(third)


def test_unique_target_avoids_resuming_unknown_partial_files(tmp_path: Path) -> None:
    (tmp_path / "clip.mp4.part").write_bytes(b"half")
    (tmp_path / "clip.mp4.part-Frag3").write_bytes(b"frag")

    assert unique_target(tmp_path, "clip").name == "clip (2)"


def _reserve_in_process(directory, ready, proceed, paths, cancel):
    target = unique_target(directory, "clip")
    partial = target.with_suffix(".mp4.part")
    try:
        ready.wait(timeout=10)
        partial.write_bytes(b"cancelled" if cancel else b"keep")
        paths.put(target.name)
        if not proceed.wait(timeout=10):
            raise TimeoutError("parent did not release workers")
        if cancel:
            Downloader(directory)._remove_partials(target)
    finally:
        release_target(target)


def test_processes_reserve_separate_partial_files(tmp_path: Path) -> None:
    context = multiprocessing.get_context("spawn")
    ready = context.Barrier(2)
    proceed = context.Event()
    paths = context.Queue()
    processes = [
        context.Process(target=_reserve_in_process, args=(tmp_path, ready, proceed, paths, cancel))
        for cancel in (True, False)
    ]
    for process in processes:
        process.start()
    try:
        names = {paths.get(timeout=15), paths.get(timeout=15)}
        assert names == {"clip", "clip (2)"}
        assert all(is_pending_output(tmp_path / f"{name}.mp4") for name in names)
    finally:
        proceed.set()
        for process in processes:
            process.join(10)
            if process.is_alive():
                process.kill()
                process.join()
        paths.close()
    assert all(process.exitcode == 0 for process in processes)
    assert [path.read_bytes() for path in tmp_path.glob("*.part")] == [b"keep"]
    assert [path.name for path in tmp_path.glob(".kodikdown*.lock")] == [".kodikdown.lock"]


def _hold_reservation(directory, ready):
    target = unique_target(directory, "clip")
    ready.send(target.name)
    time.sleep(60)


def test_killed_process_releases_its_reservation(tmp_path: Path) -> None:
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_hold_reservation, args=(tmp_path, sender))
    process.start()
    sender.close()
    output = tmp_path / "clip.mp4"
    try:
        assert receiver.poll(15)
        assert receiver.recv() == "clip"
        assert is_pending_output(output)
        other = unique_target(tmp_path, "clip")
        assert other.name == "clip (2)"
        release_target(other)
    finally:
        if process.is_alive():
            process.kill()
        process.join(10)
        receiver.close()
    assert process.exitcode is not None
    assert not is_pending_output(output)
    target = unique_target(tmp_path, "clip")
    try:
        assert target.name == "clip"
        assert [path.name for path in tmp_path.iterdir()] == [".kodikdown.lock"]
    finally:
        release_target(target)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows file attributes")
@pytest.mark.parametrize("existing", [False, True])
def test_reservation_file_is_hidden_on_windows(tmp_path: Path, existing: bool) -> None:
    anchor = tmp_path / ".kodikdown.lock"
    if existing:
        anchor.touch()
    target = unique_target(tmp_path, "clip")
    try:
        assert anchor.stat().st_file_attributes & stat.FILE_ATTRIBUTE_HIDDEN
    finally:
        release_target(target)


@pytest.mark.parametrize("stem", ["episode", "episode[1]"])
def test_parallel_dotted_titles_keep_their_own_files(tmp_path: Path, stem: str) -> None:
    first = unique_target(tmp_path, stem)
    second = unique_target(tmp_path, f"{stem}.2")
    try:
        downloader = Downloader(tmp_path)
        other_video = tmp_path / f"{second.name}.mp4"
        other_partial = tmp_path / f"{second.name}.mp4.part-Frag3.part"
        other_video.write_bytes(b"other video")
        other_partial.write_bytes(b"other fragment")
        assert downloader._pick_result(first) is None
        assert _bytes_on_disk(first) == 0

        own_video = tmp_path / f"{first.name}.mp4"
        own_partial = tmp_path / f"{first.name}.mp4.part"
        own_video.write_bytes(b"own")
        own_partial.write_bytes(b"half")
        assert downloader._pick_result(first) == own_video.resolve()
        assert _bytes_on_disk(first) == 7
        assert not downloader._remove_partials(first)
        assert not own_partial.exists()
        assert own_video.read_bytes() == b"own"
        assert other_video.read_bytes() == b"other video"
        assert other_partial.read_bytes() == b"other fragment"
    finally:
        release_target(first)
        release_target(second)


def test_download_options_send_browser_identity(tmp_path: Path) -> None:
    downloader = Downloader(output_dir=tmp_path)
    options = downloader._options(tmp_path / "clip", "https://cdn.example/")
    headers = options["http_headers"]
    assert isinstance(headers, dict)
    assert headers["Referer"] == "https://cdn.example/"
    assert str(headers["User-Agent"]).startswith("Mozilla/5.0")
    assert options["socket_timeout"] == 15.0
    assert options["retries"] == 10
    assert options["noplaylist"] is True
    assert options["cachedir"] is False


def test_hook_understands_fragment_counters(tmp_path: Path) -> None:
    snapshots: list[ProgressSnapshot] = []
    downloader = Downloader(output_dir=tmp_path, listener=snapshots.append)
    downloader._hook({"status": "downloading", "fragment_index": 3, "fragment_count": 10})
    assert snapshots == [ProgressSnapshot(downloaded=3, total=10, fragments=True)]


def test_hook_understands_fragment_counters_when_downloaded_bytes_present(tmp_path: Path) -> None:
    snapshots: list[ProgressSnapshot] = []
    downloader = Downloader(output_dir=tmp_path, listener=snapshots.append)
    downloader._hook(
        {
            "status": "downloading",
            "downloaded_bytes": 1024,
            "total_bytes": None,
            "fragment_index": 5,
            "fragment_count": 20,
        }
    )
    assert snapshots == [ProgressSnapshot(downloaded=5, total=20, fragments=True)]


def test_pick_result_ignores_subdirectories(tmp_path: Path) -> None:
    subfolder = tmp_path / "clip.backup"
    subfolder.mkdir()
    (tmp_path / "clip.mp4").write_bytes(b"video data")
    downloader = Downloader(output_dir=tmp_path)
    result = downloader._pick_result(tmp_path / "clip")
    assert result is not None
    assert result.name == "clip.mp4"
    assert result.is_file()


def test_hook_reports_speed_and_eta(tmp_path: Path) -> None:
    snapshots: list[ProgressSnapshot] = []
    downloader = Downloader(output_dir=tmp_path, listener=snapshots.append)
    downloader._hook(
        {
            "status": "downloading",
            "downloaded_bytes": 512,
            "total_bytes": 1024,
            "speed": 256.0,
            "eta": 2.0,
        }
    )
    assert snapshots == [ProgressSnapshot(downloaded=512, total=1024, speed=256.0, eta=2.0)]


def test_hook_announces_the_end_of_a_transfer(tmp_path: Path) -> None:
    snapshots: list[ProgressSnapshot] = []
    downloader = Downloader(output_dir=tmp_path, listener=snapshots.append)
    downloader._hook({"status": "finished"})
    assert [snapshot.stage for snapshot in snapshots] == ["finished"]


def test_hook_keeps_last_known_sizes_on_finish(tmp_path: Path) -> None:
    snapshots: list[ProgressSnapshot] = []
    downloader = Downloader(output_dir=tmp_path, listener=snapshots.append)
    downloader._hook(
        {"status": "downloading", "downloaded_bytes": 900, "total_bytes": 1000, "speed": 10.0}
    )
    downloader._hook({"status": "finished"})

    assert snapshots[-1].stage == "finished"
    assert snapshots[-1].downloaded == 900
    assert snapshots[-1].total == 1000


def test_progress_is_throttled(tmp_path: Path) -> None:
    snapshots: list[ProgressSnapshot] = []
    downloader = Downloader(output_dir=tmp_path, listener=snapshots.append)
    for index in range(50):
        downloader._hook({"status": "downloading", "downloaded_bytes": index, "total_bytes": 100})
    assert 0 < len(snapshots) < 50


def test_pp_hook_reports_processing(tmp_path: Path) -> None:
    snapshots: list[ProgressSnapshot] = []
    downloader = Downloader(output_dir=tmp_path, listener=snapshots.append)
    downloader._pp_hook({"status": "started"})

    assert snapshots == [ProgressSnapshot(stage="processing")]


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


def test_remove_partials_keeps_finished_files(tmp_path: Path) -> None:
    finished = tmp_path / "movie.mp4"
    finished.write_bytes(b"done")
    decoy = tmp_path / "movie.Part.2.mp4"
    decoy.write_bytes(b"also done")
    for name in (
        "movie.mp4.part",
        "movie.mp4.ytdl",
        "movie.mp4.part-Frag3",
        "movie.mp4.part-Frag4.part",
        "movie.frag",
    ):
        (tmp_path / name).write_bytes(b"junk")

    blocked = Downloader(output_dir=tmp_path)._remove_partials(tmp_path / "movie")

    assert blocked is False
    assert sorted(p.name for p in tmp_path.iterdir()) == ["movie.Part.2.mp4", "movie.mp4"]


def test_monitor_reports_bytes_while_ytdlp_is_quiet(tmp_path: Path) -> None:
    snapshots: list[ProgressSnapshot] = []
    downloader = Downloader(output_dir=tmp_path, listener=snapshots.append)
    target = tmp_path / "clip"

    downloader._start_monitor(target)
    try:
        (tmp_path / "clip.mp4.part").write_bytes(b"x" * 4096)
        (tmp_path / "clip.mp4.part-Frag3").write_bytes(b"y" * 2048)
        deadline = time.monotonic() + 5
        while not snapshots and time.monotonic() < deadline:
            time.sleep(0.1)
    finally:
        downloader._stop_monitor()

    assert snapshots, "the monitor never reported the partial files"
    assert snapshots[0].downloaded == 6144
    assert snapshots[0].stage == "downloading"


def test_monitor_stays_quiet_right_after_a_real_snapshot(tmp_path: Path) -> None:
    snapshots: list[ProgressSnapshot] = []
    downloader = Downloader(output_dir=tmp_path, listener=snapshots.append)
    (tmp_path / "clip.mp4.part").write_bytes(b"x" * 1024)

    downloader._start_monitor(tmp_path / "clip")
    try:
        downloader._hook({"status": "downloading", "downloaded_bytes": 10, "total_bytes": 100})
        time.sleep(0.8)
    finally:
        downloader._stop_monitor()

    assert [snapshot.downloaded for snapshot in snapshots] == [10]


def test_failed_postprocessing_does_not_publish_a_video(tmp_path: Path, monkeypatch) -> None:
    def transfer(self, target, url, referer):
        target.with_suffix(".mp4").write_bytes(b"unfinished video")
        raise DownloadFailed("postprocessing failed")

    monkeypatch.setattr(Downloader, "_transfer", transfer)
    downloader = Downloader(tmp_path)

    with pytest.raises(DownloadFailed, match="postprocessing failed"):
        downloader.download_blocking("https://cdn/video.m3u8", "clip", "https://cdn/")

    assert not (tmp_path / "clip.mp4").exists()
    assert not list(tmp_path.glob(".kodikdown-*"))


def test_cancel_cleans_up_outside_the_exception_handler(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Windows keeps *.part files open while a traceback still holds them."""
    contexts: list[object] = []

    def failing_transfer(self: Downloader, target_base: Path, url: str, referer: str) -> None:
        raise DownloadCancelled

    def spy_cleanup(self: Downloader, target_base: Path) -> None:
        contexts.append(sys.exc_info())

    monkeypatch.setattr(Downloader, "_transfer_with_retries", failing_transfer)
    monkeypatch.setattr(Downloader, "_cleanup_cancelled", spy_cleanup)
    downloader = Downloader(output_dir=tmp_path)

    with pytest.raises(DownloadCancelled):
        downloader.download_blocking("https://cdn/x.m3u8", "clip", "https://cdn/")

    assert contexts, "the partial files were never cleaned up"
    assert contexts[0] == (None, None, None), "cleanup ran with the traceback still alive"


def test_download_blocking_respects_pre_set_cancel(tmp_path: Path) -> None:
    event = threading.Event()
    event.set()
    downloader = Downloader(output_dir=tmp_path, cancel_event=event)
    with pytest.raises(DownloadCancelled):
        downloader.download_blocking("http://127.0.0.1/video.m3u8", "clip", "http://127.0.0.1/")


def test_download_blocking_creates_output_dir(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "videos"
    downloader = Downloader(output_dir=target)
    with pytest.raises(DownloadFailed):
        downloader.download_blocking("http://127.0.0.1:1/none.m3u8", "clip", "http://127.0.0.1/")
    assert target.is_dir()


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _make_hls(root: Path, *, duration: int = 1, gop: int | None = None) -> None:
    clip = root / "clip.mp4"
    command = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=duration={duration}:size=128x96:rate=10",
        "-pix_fmt",
        "yuv420p",
    ]
    if gop is not None:
        command += ["-c:v", "libx264", "-g", str(gop)]
    command.append(str(clip))
    subprocess.run(command, check=True)
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


@pytest.fixture(scope="module")
def hls_server(tmp_path_factory: pytest.TempPathFactory) -> object:
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")

    root = tmp_path_factory.mktemp("hls")
    _make_hls(root)

    port = _free_port()
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{port}/stream.m3u8"
    server.shutdown()


def test_download_blocking_saves_file(hls_server: object, tmp_path: Path) -> None:
    downloader = Downloader(output_dir=tmp_path)
    produced = downloader.download_blocking(str(hls_server), "My Test / Video", "http://127.0.0.1/")

    assert produced.exists()
    assert produced.stat().st_size > 0
    assert produced.name == "My Test _ Video.mp4"


def test_download_blocking_keeps_an_existing_file(hls_server: object, tmp_path: Path) -> None:
    existing = tmp_path / "tracked.mp4"
    existing.write_bytes(b"previous")

    downloader = Downloader(output_dir=tmp_path)
    produced = downloader.download_blocking(str(hls_server), "tracked", "http://127.0.0.1/")

    assert produced.name == "tracked (2).mp4"
    assert existing.read_bytes() == b"previous"


def test_download_blocking_uses_the_requested_filename(hls_server: object, tmp_path: Path) -> None:
    downloader = Downloader(output_dir=tmp_path, filename="Custom Name")
    produced = downloader.download_blocking(str(hls_server), "ignored", "http://127.0.0.1/")

    assert produced.name == "Custom Name.mp4"


def test_slow_mp4_reports_progress_and_can_cancel_before_end_of_file(tmp_path: Path) -> None:
    progress = threading.Event()
    waited_for_eof = threading.Event()
    payload = b"video bytes" * 8192

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            try:
                self.wfile.write(payload[:2048])
                self.wfile.flush()
                if not progress.wait(3):
                    waited_for_eof.set()
                self.wfile.write(payload[2048:])
            except OSError:
                pass

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    def on_progress(snapshot):
        if snapshot.downloaded:
            progress.set()
            downloader.cancel()

    downloader = Downloader(output_dir=tmp_path, listener=on_progress)
    try:
        with pytest.raises(DownloadCancelled):
            downloader.download_blocking(
                f"http://127.0.0.1:{server.server_port}/slow.mp4", "slow", "http://127.0.0.1/"
            )
        assert progress.is_set()
        assert not waited_for_eof.is_set()
        assert {path.name for path in tmp_path.iterdir()} == {".kodikdown.lock"}
    finally:
        progress.set()
        server.shutdown()
        server.server_close()


def test_download_blocking_handles_bracketed_title(hls_server: object, tmp_path: Path) -> None:
    downloader = Downloader(output_dir=tmp_path)
    produced = downloader.download_blocking(
        str(hls_server), "[SubsPlease] Clip - 01", "http://127.0.0.1/"
    )

    assert produced.name == "[SubsPlease] Clip - 01.mp4"
    assert produced.exists()


def test_progress_listener_receives_updates(hls_server: object, tmp_path: Path) -> None:
    snapshots: list[ProgressSnapshot] = []
    downloader = Downloader(output_dir=tmp_path, listener=snapshots.append)
    downloader.download_blocking(str(hls_server), "tracked", "http://127.0.0.1/")

    assert any(snapshot.downloaded > 0 for snapshot in snapshots)
    assert {"finished"} <= {snapshot.stage for snapshot in snapshots}


def test_transient_errors_are_retried(tmp_path: Path, monkeypatch) -> None:
    attempts: list[int] = []

    def flaky(self: Downloader, target_base: Path, url: str, referer: str) -> None:
        attempts.append(1)
        if len(attempts) == 1:
            raise DownloadFailed("Failed to download m3u8 information: timed out")
        target_base.with_suffix(".mp4").write_bytes(b"done")

    monkeypatch.setattr(Downloader, "_transfer", flaky)
    monkeypatch.setattr("kodikdown.downloader.time.sleep", lambda _seconds: None)
    downloader = Downloader(output_dir=tmp_path)

    produced = downloader.download_blocking("https://cdn/x.m3u8", "clip", "https://cdn/")

    assert len(attempts) == 2
    assert produced.name == "clip.mp4"


def test_permanent_errors_are_not_retried(tmp_path: Path, monkeypatch) -> None:
    attempts: list[int] = []

    def broken(self: Downloader, target_base: Path, url: str, referer: str) -> None:
        attempts.append(1)
        raise DownloadFailed("HTTP Error 404: Not Found")

    monkeypatch.setattr(Downloader, "_transfer", broken)
    downloader = Downloader(output_dir=tmp_path)

    with pytest.raises(DownloadFailed):
        downloader.download_blocking("https://cdn/x.m3u8", "clip", "https://cdn/")

    assert attempts == [1]


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Failed to download m3u8 information: timed out", True),
        ("HTTP Error 503: Service Unavailable", True),
        ("HTTP Error 404: Not Found", False),
        ("Unsupported URL: https://x", False),
    ],
)
def test_transient_classifier(message: str, expected: bool) -> None:
    assert _is_transient(message) is expected


def test_download_blocking_reports_unreachable_host(tmp_path: Path) -> None:
    downloader = Downloader(output_dir=tmp_path)
    with pytest.raises(DownloadFailed):
        downloader.download_blocking("http://127.0.0.1:1/missing.m3u8", "clip", "http://127.0.0.1/")


def test_cancel_interrupts_slow_download(tmp_path: Path) -> None:
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")

    root = tmp_path / "slow"
    root.mkdir()
    _make_hls(root, duration=8, gop=10)

    class Slow(http.server.SimpleHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path.endswith(".ts"):
                time.sleep(0.5)
            super().do_GET()

        def log_message(self, *args: object) -> None:
            pass

    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(Slow, directory=str(root))
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
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

        leftovers = [
            path.name
            for path in (tmp_path / "out").iterdir()
            if path.name.startswith("cancelled-video")
        ]
        assert leftovers == []
    finally:
        server.shutdown()


def test_transfer_with_retries_uses_supplied_fallback_on_404(tmp_path: Path, monkeypatch) -> None:
    attempts: list[str] = []

    def mock_transfer(self: Downloader, target_base: Path, url: str, referer: str) -> None:
        attempts.append(url)
        if "720.mp4" in url:
            raise DownloadFailed("HTTP Error 404: Not Found")
        # 480 succeeds
        target_base.with_suffix(".mp4").write_bytes(b"fallback content")

    monkeypatch.setattr(Downloader, "_transfer", mock_transfer)
    downloader = Downloader(
        output_dir=tmp_path,
        fallback_sources=(DownloadSource("https://cdn/video/480.mp4:hls:manifest.m3u8", 480),),
    )
    produced = downloader.download_blocking(
        "https://cdn/video/720.mp4:hls:manifest.m3u8", "clip", "https://cdn/"
    )

    assert len(attempts) == 2
    assert "720.mp4" in attempts[0]
    assert "480.mp4" in attempts[1]
    assert produced.name == "clip.mp4"
    assert produced.read_bytes() == b"fallback content"


def test_transfer_with_retries_fails_if_all_fallbacks_404(tmp_path: Path, monkeypatch) -> None:
    attempts: list[str] = []

    def mock_transfer(self: Downloader, target_base: Path, url: str, referer: str) -> None:
        attempts.append(url)
        raise DownloadFailed("HTTP Error 404: Not Found")

    monkeypatch.setattr(Downloader, "_transfer", mock_transfer)
    downloader = Downloader(
        output_dir=tmp_path,
        fallback_sources=(DownloadSource("https://cdn/video/480.mp4:hls:manifest.m3u8", 480),),
    )

    with pytest.raises(DownloadFailed, match="HTTP Error 404"):
        downloader.download_blocking(
            "https://cdn/video/720.mp4:hls:manifest.m3u8", "clip", "https://cdn/"
        )

    assert len(attempts) == 2
    assert "720.mp4" in attempts[0]
    assert "480.mp4" in attempts[1]


def test_missing_hls_segment_never_reports_success(tmp_path: Path) -> None:
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    root = tmp_path / "server"
    root.mkdir()
    _make_hls(root, duration=3, gop=10)
    fragments = sorted(root.glob("stream*.ts"))
    assert len(fragments) == 3
    fragments[1].unlink()
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        downloader = Downloader(output_dir=tmp_path / "out", retries=0)
        url = f"http://127.0.0.1:{server.server_port}/stream.m3u8"
        with pytest.raises(DownloadFailed):
            downloader.download_blocking(url, "incomplete", "http://127.0.0.1/")
        assert not list((tmp_path / "out").glob("*.mp4"))
    finally:
        server.shutdown()
        server.server_close()


def test_does_not_invent_fallback_urls(tmp_path: Path, monkeypatch) -> None:
    attempts = []

    def transfer(self, target, url, referer):
        attempts.append(url)
        raise DownloadFailed("HTTP Error 404")

    monkeypatch.setattr(Downloader, "_transfer", transfer)
    url = "https://cdn/720.mp4:hls:manifest.m3u8?signature=keep"
    with pytest.raises(DownloadFailed):
        Downloader(tmp_path).download_blocking(url, "clip", "https://cdn/")
    assert attempts == [url]


def test_fallback_uses_360p_and_clears_previous_fragments(tmp_path: Path, monkeypatch) -> None:
    attempts = []
    snapshots = []

    def transfer(self, target, url, referer):
        attempts.append(url)
        if "360" in url:
            assert not target.with_suffix(".mp4.part").exists()
            target.with_suffix(".mp4").write_bytes(b"complete")
        else:
            target.with_suffix(".mp4.part").write_bytes(b"wrong resolution")
            raise DownloadFailed("HTTP Error 403")

    monkeypatch.setattr(Downloader, "_transfer", transfer)
    downloader = Downloader(
        tmp_path,
        listener=snapshots.append,
        fallback_sources=(
            DownloadSource("https://cdn/480.mp4", 480),
            DownloadSource("https://cdn/360.mp4", 360),
        ),
    )
    assert (
        downloader.download_blocking("https://cdn/720.mp4", "clip", "https://cdn/").read_bytes()
        == b"complete"
    )
    assert len(attempts) == 3
    assert [s.quality for s in snapshots] == [480, 360]


def test_safe_filename_limits_multibyte_names() -> None:
    name = safe_filename("動画" * 100)
    assert name
    assert len(name.encode("utf-8")) <= 200
