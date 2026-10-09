"""Thread bridges: one asyncio loop for lookups, a pool for downloads."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
from collections.abc import Coroutine
from concurrent.futures import Future
from typing import Any

from PySide6.QtCore import QObject, QRunnable, Signal

from kodikdown.downloader import DownloadCancelled, Downloader, DownloadFailed
from kodikdown.kodik.client import KodikClient
from kodikdown.kodik.errors import (
    HostUnavailableError,
    InvalidUrlError,
    NoStreamsError,
    PageStructureError,
    RequestFailedError,
)
from kodikdown.kodik.models import ResolvedVideo, Translation

logger = logging.getLogger(__name__)


class ResolverWorker(QObject):
    """Owns an asyncio loop in a helper thread and runs lookups on it.

    httpx is async, and keeping one loop — and one client — alive lets the
    discovered endpoint cache survive between lookups.
    """

    resolved = Signal(int, object)
    failed = Signal(int, str, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._client = KodikClient()
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._current: asyncio.Task[Any] | None = None
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._run_loop, name="kodikdown-async", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5)

    # -- loop plumbing -----------------------------------------------------
    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._ready.set()
        with contextlib.suppress(RuntimeError):
            self._loop.run_forever()

    def _submit(self, coroutine: Coroutine[Any, Any, Any]) -> Future[Any]:
        async def runner() -> Any:
            with self._lock:
                self._current = asyncio.current_task()
            try:
                return await coroutine
            finally:
                with self._lock:
                    self._current = None

        return asyncio.run_coroutine_threadsafe(runner(), self._loop)

    # -- public API --------------------------------------------------------
    def resolve(self, request_id: int, url: str, translation: Translation | None) -> None:
        self.cancel()
        future = self._submit(self._client.resolve(url, translation))
        future.add_done_callback(lambda done: self._deliver(request_id, done))

    def cancel(self) -> None:
        with self._lock:
            task = self._current
        if task is not None and not task.done():
            self._loop.call_soon_threadsafe(task.cancel)

    def shutdown(self) -> None:
        self.cancel()
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=3)

    def _deliver(self, request_id: int, future: Future[Any]) -> None:
        try:
            resolved: ResolvedVideo = future.result()
        except asyncio.CancelledError:
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
            self.resolved.emit(request_id, resolved)


class DownloadSignals(QObject):
    progress = Signal(str, object)
    finished = Signal(str, str)
    failed = Signal(str, str)
    cancelled = Signal(str)


class DownloadTask(QRunnable):
    """Runs one blocking yt-dlp transfer inside the Qt thread pool."""

    def __init__(
        self,
        job_id: str,
        downloader: Downloader,
        url: str,
        title: str,
        referer: str,
    ) -> None:
        super().__init__()
        self.job_id = job_id
        self.signals = DownloadSignals()
        self._downloader = downloader
        self._url = url
        self._title = title
        self._referer = referer
        self.setAutoDelete(False)

    def run(self) -> None:
        try:
            path = self._downloader.download_blocking(self._url, self._title, self._referer)
        except DownloadCancelled:
            self.signals.cancelled.emit(self.job_id)
        except DownloadFailed as exc:
            self.signals.failed.emit(self.job_id, str(exc))
        except Exception as exc:
            logger.exception("download %s failed", self.job_id)
            self.signals.failed.emit(self.job_id, str(exc))
        else:
            self.signals.finished.emit(self.job_id, str(path))

    def cancel(self) -> None:
        self._downloader.cancel()
