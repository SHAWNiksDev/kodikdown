"""Thread bridges: one asyncio loop for lookups, a pool for downloads."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
from collections.abc import Coroutine
from concurrent.futures import CancelledError, Future
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QRunnable, Signal, SignalInstance

from kodikdown.downloader import (
    DownloadCancelled,
    Downloader,
    DownloadFailed,
    DownloadSource,
    ProgressSnapshot,
    fallback_sources_for,
)
from kodikdown.i18n import t
from kodikdown.kodik.errors import (
    HostUnavailableError,
    InvalidUrlError,
    NoStreamsError,
    PageStructureError,
    RequestFailedError,
)
from kodikdown.kodik.models import ResolvedVideo, Translation
from kodikdown.sources import Choice, Episode, MediaClient, Series

logger = logging.getLogger(__name__)


class ResolverWorker(QObject):
    """Owns an asyncio loop in a helper thread and runs lookups on it.

    httpx is async, and keeping one loop — and one client — alive lets the
    discovered endpoint cache survive between lookups.
    """

    resolved = Signal(int, object)
    catalog_ready = Signal(int, object)
    failed = Signal(int, str, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._client = MediaClient()
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._future: Future[Any] | None = None
        self._is_shut_down = False
        self._thread = threading.Thread(target=self._run_loop, name="kodikdown-async", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5)

    # -- loop plumbing -----------------------------------------------------
    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._ready.set()
        try:
            self._loop.run_forever()
        finally:
            pending = asyncio.all_tasks(self._loop)
            for task in pending:
                task.cancel()
            if pending:
                self._loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            self._loop.run_until_complete(self._loop.shutdown_asyncgens())
            self._loop.close()

    def _submit(self, coroutine: Coroutine[Any, Any, Any]) -> Future[Any]:
        return asyncio.run_coroutine_threadsafe(coroutine, self._loop)

    # -- public API --------------------------------------------------------
    def resolve(self, request_id: int, url: str, translation: Translation | None) -> None:
        self.cancel()
        if self._is_shut_down:
            return
        future = self._submit(self._client.lookup(url, translation))
        self._future = future
        future.add_done_callback(lambda done: self._deliver(request_id, done))

    def cancel(self) -> None:
        if self._future is not None:
            self._future.cancel()

    def shutdown(self) -> None:
        if self._is_shut_down:
            return
        self._is_shut_down = True
        self.cancel()
        if self._loop.is_running():
            with contextlib.suppress(Exception):
                future = asyncio.run_coroutine_threadsafe(self._client.close(), self._loop)
                future.result(timeout=2)
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=3)

    def _deliver(self, request_id: int, future: Future[Any]) -> None:
        if self._is_shut_down:
            return
        with contextlib.suppress(RuntimeError):
            try:
                resolved: ResolvedVideo | Series = future.result()
            except (asyncio.CancelledError, CancelledError):
                return
            except InvalidUrlError:
                self.failed.emit(request_id, "invalid_url", "")
            except NoStreamsError as exc:
                self.failed.emit(request_id, "no_streams", str(exc))
            except PageStructureError as exc:
                self.failed.emit(request_id, "page_changed", str(exc))
            except HostUnavailableError as exc:
                self.failed.emit(request_id, "network", str(exc))
            except RequestFailedError as exc:
                self.failed.emit(request_id, "network", str(exc))
            except Exception as exc:
                logger.exception("resolve failed")
                self.failed.emit(request_id, "unexpected", str(exc))
            else:
                if isinstance(resolved, Series):
                    self.catalog_ready.emit(request_id, resolved)
                else:
                    self.resolved.emit(request_id, resolved)


class DownloadSignals(QObject):
    started = Signal(str)
    progress = Signal(str, object)
    finished = Signal(str, str)
    failed = Signal(str, str)
    cancelled = Signal(str)


@dataclass(frozen=True)
class EpisodeDownload:
    title: str
    choice: Choice
    episode: Episode
    quality: int | None
    prefer_mp4: bool

    async def resolve(self) -> ResolvedVideo:
        async with MediaClient() as client:
            return await client.resolve_episode(self.title, self.choice, self.episode)


class DownloadTask(QRunnable):
    """Runs one blocking yt-dlp transfer inside the Qt thread pool.

    The task owns its downloader, so the progress listener cannot be left
    unwired: every snapshot leaves as a signal.
    """

    def __init__(
        self,
        job_id: str,
        url: str,
        title: str,
        referer: str,
        output_dir: Path,
        *,
        concurrent_fragments: int = 8,
        socket_timeout: float = 15.0,
        signals: DownloadSignals | None = None,
        fallback_sources: tuple[DownloadSource, ...] = (),
        episode: EpisodeDownload | None = None,
    ) -> None:
        super().__init__()
        self.job_id = job_id
        self.url = url
        self.signals = signals or DownloadSignals()
        self._output_dir = output_dir
        self._fragments = max(1, min(8, concurrent_fragments))
        self._socket_timeout = socket_timeout
        self._cancel_event = threading.Event()
        self._episode = episode
        self._lookup_error = t("episode_unavailable")
        self._downloader = self._make_downloader(fallback_sources)
        self._title = title
        self._referer = referer
        self.setAutoDelete(False)

    def _make_downloader(self, fallbacks: tuple[DownloadSource, ...]) -> Downloader:
        return Downloader(
            output_dir=self._output_dir,
            listener=self._emit_progress,
            cancel_event=self._cancel_event,
            concurrent_fragments=self._fragments,
            socket_timeout=self._socket_timeout,
            fallback_sources=fallbacks,
        )

    async def _resolve_episode(self, episode: EpisodeDownload) -> ResolvedVideo:
        lookup = asyncio.create_task(episode.resolve())
        try:
            while not self._cancel_event.is_set():
                done, _ = await asyncio.wait((lookup,), timeout=0.1)
                if done:
                    return lookup.result()
            raise DownloadCancelled
        finally:
            if not lookup.done():
                lookup.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await lookup

    def run(self) -> None:
        self._emit(self.signals.started, self.job_id)
        try:
            url = self.url
            referer = self._referer
            if self._episode is not None:
                resolved = asyncio.run(self._resolve_episode(self._episode))
                variant = resolved.pick(self._episode.quality)
                prefer_mp4 = self._episode.prefer_mp4
                url = variant.download_url(prefer_mp4)
                referer = variant.download_referer(prefer_mp4)
                self._emit_progress(ProgressSnapshot(quality=variant.quality))
                self._downloader = self._make_downloader(
                    fallback_sources_for(resolved, variant.quality, prefer_mp4)
                )
            path = self._downloader.download_blocking(url, self._title, referer)
        except (DownloadCancelled, KeyboardInterrupt):
            self._emit(self.signals.cancelled, self.job_id)
        except DownloadFailed as exc:
            self._emit(self.signals.failed, self.job_id, str(exc))
        except (NoStreamsError, PageStructureError, RequestFailedError, InvalidUrlError) as exc:
            self._emit(self.signals.failed, self.job_id, str(exc) or self._lookup_error)
        except Exception as exc:
            logger.exception("download %s failed", self.job_id)
            self._emit(self.signals.failed, self.job_id, str(exc))
        else:
            self._emit(self.signals.finished, self.job_id, str(path))

    @staticmethod
    def _emit(signal: SignalInstance, *args: object) -> None:
        # The window can be gone while the last fragments are still winding down.
        with contextlib.suppress(RuntimeError):
            signal.emit(*args)

    def cancel(self) -> None:
        self._cancel_event.set()

    def _emit_progress(self, snapshot: ProgressSnapshot) -> None:
        self._emit(self.signals.progress, self.job_id, snapshot)
