from __future__ import annotations

import base64
import functools
import http.server
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

import pytest
import respx

from kodikdown.config import ConfigStore, Settings
from kodikdown.downloader import Downloader, ProgressSnapshot
from kodikdown.gui.main_window import MainWindow
from kodikdown.kodik.client import KodikClient
from kodikdown.kodik.decoder import caesar
from kodikdown.kodik.models import ResolvedVideo, StreamVariant, referer_for

HASH = "060cab655974d46835b3f4405807acc2"
PAGE_URL = f"https://mock.local/video/91873/{HASH}/720p"
JS_URL = "https://mock.local/assets/js/app.player_single"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def encrypt(url: str) -> str:
    """The player's obfuscation, applied in reverse."""
    return caesar(base64.b64encode(url.encode()).decode(), -18)


@pytest.fixture(scope="module")
def media_server(tmp_path_factory: pytest.TempPathFactory) -> object:
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
            "testsrc=duration=2:size=160x120:rate=10",
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
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{port}/stream.m3u8"
    server.shutdown()


@pytest.fixture(scope="module")
def slow_media_server(tmp_path_factory: pytest.TempPathFactory) -> object:
    """A local HLS server whose fragments take long enough to stay quiet."""
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")

    root = tmp_path_factory.mktemp("slow-hls")
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
            "testsrc=duration=12:size=320x240:rate=15",
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

    class Throttled(http.server.SimpleHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path.endswith(".ts"):
                time.sleep(2.0)
            super().do_GET()

        def log_message(self, *args: object) -> None:
            pass

    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(Throttled, directory=str(root))
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/stream.m3u8"
    server.shutdown()


def _page_html(manifest_url: str) -> str:
    return (
        "<!doctype html><html><head><title>Kodik Player</title>"
        "<script>"
        'var urlParams = \'{"d":"kodikplayer.com","d_sign":"a:1",'
        '"pd":"kodikplayer.com","pd_sign":"b:1","ref":"","ref_sign":"c:1"}\';'
        '</script><script src="/assets/js/app.player_single.test.js"></script>'
        "<script>var vInfo = {};"
        "vInfo.type = 'video';"
        f"vInfo.hash = '{HASH}';"
        "vInfo.id = '91873';</script></head><body>"
        f'<option data-id="869" data-translation-type="subtitles" data-media-id="91873"'
        f' data-media-hash="{HASH}" data-media-type="video" data-title="Субтитры"'
        ' selected="selected">Субтитры</option></body></html>'
    )


@respx.mock
def test_lookup_then_download_end_to_end(media_server: object, tmp_path: Path) -> None:
    manifest_url = str(media_server)
    respx.get(PAGE_URL).respond(200, text=_page_html(manifest_url))
    respx.get(url__startswith=JS_URL).respond(
        200, text='$.ajax({type:"POST",url:atob("L2Z0b3I="),dataType:"json"});'
    )
    respx.post("https://mock.local/ftor").respond(
        200,
        json={
            "default": 720,
            "links": {
                "720": [{"src": encrypt(manifest_url), "type": "application/x-mpegURL"}],
                "360": [{"src": encrypt(manifest_url), "type": "application/x-mpegURL"}],
            },
        },
    )

    import asyncio

    async def lookup() -> ResolvedVideo:
        async with KodikClient(hosts=("mock.local",)) as client:
            return await client.resolve(PAGE_URL)

    resolved = asyncio.run(lookup())
    assert [variant.quality for variant in resolved.variants] == [720, 360]
    assert resolved.default_quality == 720
    assert resolved.translation is not None
    assert resolved.translation.is_subtitles

    variant = resolved.pick(720)
    downloader = Downloader(output_dir=tmp_path / "downloads")
    produced = downloader.download_blocking(
        variant.url, resolved.title or "video", referer_for(variant.url)
    )

    assert produced.exists()
    assert produced.stat().st_size > 0
    assert produced.name == "kodik-91873.mp4"


@pytest.fixture()
def window(qtbot, tmp_path: Path):
    store = ConfigStore(tmp_path / "settings.json")
    settings = Settings(download_dir=tmp_path / "downloads")
    window = MainWindow(store, settings)
    qtbot.addWidget(window)
    yield window
    window.resolver.shutdown()


def _sample_video() -> ResolvedVideo:
    return ResolvedVideo(
        title="Test video",
        variants=(
            StreamVariant(720, "https://cdn/720.m3u8", direct_mp4="https://cdn/720.mp4"),
            StreamVariant(480, "https://cdn/480.m3u8"),
            StreamVariant(360, "https://cdn/360.m3u8"),
        ),
        default_quality=480,
    )


def test_window_starts_with_an_empty_state(window: MainWindow) -> None:
    assert window.url_edit.text() == ""
    assert window.result_card.isHidden()
    assert not window.downloads_empty.isHidden()
    assert window.resolve_bar.isHidden()


def test_theme_toggle_switches_modes(window: MainWindow) -> None:
    start = window._palette.mode
    window._toggle_theme()

    assert window._palette.mode != start
    assert window.store.load().theme == window._palette.mode
    assert not window.theme_button.icon().isNull()


def test_paste_reads_the_clipboard(window: MainWindow) -> None:
    from PySide6.QtWidgets import QApplication

    QApplication.clipboard().setText("https://kodikplayer.com/video/1/abcdef0123456789/720p")
    window._paste()

    assert window.url_edit.text().startswith("https://kodikplayer.com")


def test_resolve_button_becomes_cancel_while_busy(window: MainWindow) -> None:
    window._start_resolve(PAGE_URL, None)

    assert window._resolving is True
    assert not window.resolve_bar.isHidden()
    window._set_resolving(False)
    assert window.resolve_bar.isHidden()


def test_failed_lookup_shows_the_reason(window: MainWindow) -> None:
    window._start_resolve(PAGE_URL, None)
    window._on_resolve_failed(window._request_id, "invalid_url", "")

    assert window._resolving is False
    assert window.result_card.isHidden()
    assert window.status_label.property("state") == "error"


def test_stale_lookup_reply_is_ignored(window: MainWindow) -> None:
    window._start_resolve(PAGE_URL, None)
    window._on_resolved(window._request_id - 1, _sample_video())

    assert window._resolved is None
    assert window.result_card.isHidden()


def test_result_card_lists_qualities_and_tracks_selection(window: MainWindow) -> None:
    window._on_resolved(window._request_id, _sample_video())

    assert not window.result_card.isHidden()
    labels = [button.text() for button in window.quality_group.buttons()]
    assert labels == ["720p · best", "480p", "360p"]
    assert window._quality == 720
    assert not window.mp4_check.isHidden()

    window._select_quality(480)
    assert window._selected_variant().quality == 480
    # Only the 720p entry has a plain mp4 behind it.
    assert window.mp4_check.isHidden()

    window._select_quality(720)
    assert not window.mp4_check.isHidden()
    assert window.name_edit.text() == "Test video"


def test_voice_over_switch_reuses_the_same_link(window: MainWindow) -> None:
    from kodikdown.kodik.models import Translation

    translations = (
        Translation("AniLibria.TV", "video", "1", "a" * 32, translation_id="1"),
        Translation("Re:anime", "video", "2", "b" * 32, translation_id="2"),
    )
    video = _sample_video()
    window._on_resolved(
        window._request_id,
        ResolvedVideo(
            title=video.title,
            variants=video.variants,
            translations=translations,
            translation=translations[0],
        ),
    )
    window.url_edit.setText(PAGE_URL)
    window._url_in_use = PAGE_URL
    window._resolved_url = PAGE_URL

    assert not window.translation_row.isHidden()
    window.translation_combo.setCurrentIndex(1)

    assert window._resolving is True
    assert window._translation_for(PAGE_URL) == translations[1]
    window.resolver.cancel()
    window._set_resolving(False)


def test_download_row_follows_its_signals(window: MainWindow, monkeypatch) -> None:
    monkeypatch.setattr(window.pool, "start", lambda task: None)
    window._on_resolved(window._request_id, _sample_video())
    window.url_edit.setText(PAGE_URL)
    window._url_in_use = PAGE_URL
    window._resolved_url = PAGE_URL

    window._on_download()
    job_id, job = next(iter(window._jobs.items()))
    assert job.row.title_label.text() == "Test video"
    assert window.downloads_empty.isHidden()

    window._on_download()
    assert len(window._jobs) == 1  # the same stream is not queued twice

    window._on_job_finished(job_id, "/tmp/Test video.mp4")
    assert job.finished is True
    assert job.row.property("state") == "done"
    assert window._active_urls == set()

    window._clear_finished()
    assert window._jobs == {}
    assert not window.downloads_empty.isHidden()


def test_download_progress_reaches_the_row(qtbot, window: MainWindow, media_server: object) -> None:
    """The regression that mattered: transfer ran, the row never moved."""
    window._on_resolved(
        window._request_id,
        ResolvedVideo(title="Clip", variants=(StreamVariant(360, str(media_server)),)),
    )
    window.url_edit.setText(PAGE_URL)
    window._url_in_use = PAGE_URL
    window._resolved_url = PAGE_URL

    window._on_download()
    _job_id, job = next(iter(window._jobs.items()))
    snapshots: list[ProgressSnapshot] = []
    job.task.signals.progress.connect(lambda _jid, snapshot: snapshots.append(snapshot))

    qtbot.waitUntil(lambda: job.finished, timeout=120_000)

    assert snapshots, "no progress ever reached the window"
    assert any(snapshot.downloaded > 0 for snapshot in snapshots)
    assert job.row.property("state") == "done"
    assert window.downloads_empty.isHidden()
    assert window._active_urls == set()


def test_progress_keeps_moving_while_fragments_are_slow(
    qtbot, window: MainWindow, slow_media_server: object
) -> None:
    """yt-dlp is silent between fragments; the row must not freeze meanwhile."""
    window._on_resolved(
        window._request_id,
        ResolvedVideo(title="Slow", variants=(StreamVariant(360, str(slow_media_server)),)),
    )
    window.url_edit.setText(PAGE_URL)
    window._url_in_use = PAGE_URL
    window._resolved_url = PAGE_URL

    window._on_download()
    _job_id, job = next(iter(window._jobs.items()))
    snapshots: list[ProgressSnapshot] = []
    job.task.signals.progress.connect(lambda _jid, snapshot: snapshots.append(snapshot))

    qtbot.waitUntil(lambda: job.finished, timeout=180_000)

    monitored = [snapshot for snapshot in snapshots if snapshot.source == "monitor"]
    assert monitored, "the disk monitor never reported anything"
    assert monitored[0].downloaded > 0
    assert job.row.property("state") == "done"


def test_download_task_always_wires_a_progress_listener(tmp_path: Path) -> None:
    from kodikdown.gui.workers import DownloadTask

    task = DownloadTask("job", "https://cdn/x.m3u8", "clip", "https://cdn/", tmp_path)

    assert task._downloader._listener is not None


def test_cancelling_a_queued_download_is_immediate(qtbot, window: MainWindow) -> None:
    import threading

    from PySide6.QtCore import QRunnable

    class Blocker(QRunnable):
        def __init__(self, release: threading.Event) -> None:
            super().__init__()
            self._release = release

        def run(self) -> None:
            self._release.wait(30)

    release = threading.Event()
    window.pool.setMaxThreadCount(1)
    window.pool.start(Blocker(release))
    qtbot.waitUntil(lambda: window.pool.activeThreadCount() == 1, timeout=10_000)

    window._on_resolved(
        window._request_id,
        ResolvedVideo(title="Clip", variants=(StreamVariant(360, "https://cdn/360.m3u8"),)),
    )
    window.url_edit.setText(PAGE_URL)
    window._url_in_use = PAGE_URL
    window._resolved_url = PAGE_URL
    window._on_download()

    job_id, job = next(iter(window._jobs.items()))
    assert job.started is False

    window._cancel_job(job_id)

    assert job.finished is True
    assert job.started is False
    release.set()


def test_settings_dialog_returns_updated_values(window: MainWindow, tmp_path: Path) -> None:
    from kodikdown.gui.settings_dialog import SettingsDialog

    dialog = SettingsDialog(window.settings, window.store, window)
    dialog.folder_edit.setText(str(tmp_path / "other"))
    dialog.concurrent_spin.setValue(4)
    dialog.mp4_check.setChecked(True)
    dialog._save()

    updated = dialog.settings()
    assert updated.download_dir == tmp_path / "other"
    assert updated.concurrent_downloads == 4
    assert updated.prefer_mp4 is True
    assert updated.language == window.settings.language


def test_retranslate_switches_the_interface_language(window: MainWindow) -> None:
    from kodikdown.i18n import set_language

    set_language("ru")
    window.retranslate()
    assert window.find_button.text() == "Найти видео"
    assert window.download_button.text() == "Скачать"

    set_language("en")
    window.retranslate()
    assert window.find_button.text() == "Find video"
