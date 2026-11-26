from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QThreadPool, Signal

from kodikdown.downloader import DownloadSource, safe_filename
from kodikdown.gui.theme import Palette
from kodikdown.gui.widgets import DownloadRow
from kodikdown.gui.workers import DownloadTask, EpisodeDownload, SavedDownload
from kodikdown.output_locks import release, try_reserve


@dataclass
class DownloadJob:
    task: DownloadTask
    row: DownloadRow
    url: str
    title: str
    directory: Path
    started: bool = False
    finished: bool = False
    cancelling: bool = False
    pausing: bool = False
    priority: int = 0
    status: str = "queued"
    percent: int | None = None


class DownloadQueue(QObject):
    started = Signal(str)
    progress = Signal(str, object)
    finished = Signal(str, str)
    failed = Signal(str, str)
    cancelled = Signal(str)

    def __init__(self, concurrency: int, lock_directory: Path, parent: QObject) -> None:
        super().__init__(parent)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(concurrency)
        self.jobs: dict[str, DownloadJob] = {}
        self.active_urls: set[str] = set()
        self.lock_directory = lock_directory
        self._owned: set[str] = set()
        self._priority = 0

    def contains(self, url: str, title: str, directory: Path) -> bool:
        filename = safe_filename(title).casefold()
        return url in self.active_urls or any(
            not job.finished
            and job.directory == directory
            and safe_filename(job.title).casefold() == filename
            for job in self.jobs.values()
        )

    def add(
        self,
        url: str,
        title: str,
        directory: Path,
        quality: int,
        palette: Palette,
        referer: str,
        fallback_sources: tuple[DownloadSource, ...],
        episode: EpisodeDownload | SavedDownload | None,
        *,
        job_id: str | None = None,
        priority: int = 0,
    ) -> DownloadJob:
        job_id = job_id or uuid.uuid4().hex
        self.lock_directory.mkdir(parents=True, exist_ok=True)
        if not try_reserve(self.lock_directory / f"download-{job_id}"):
            raise FileExistsError(job_id)
        self._owned.add(job_id)
        row = DownloadRow(job_id, title, quality, palette)
        task = self._task(
            job_id,
            url,
            title,
            referer,
            directory,
            fallback_sources,
            episode,
        )
        job = DownloadJob(task, row, url, title, directory, priority=priority)
        self.jobs[job_id] = job
        self.active_urls.add(url)
        self._priority = max(priority, self._priority)
        return job

    def _task(
        self,
        job_id: str,
        url: str,
        title: str,
        referer: str,
        directory: Path,
        fallback_sources: tuple[DownloadSource, ...],
        episode: EpisodeDownload | SavedDownload | None,
    ) -> DownloadTask:
        task = DownloadTask(
            job_id,
            url,
            title,
            referer,
            directory,
            concurrent_fragments=4,
            fallback_sources=fallback_sources,
            episode=episode,
            resume_id=job_id,
        )
        task.signals.started.connect(self.started)
        task.signals.progress.connect(self.progress)
        task.signals.finished.connect(self.finished)
        task.signals.failed.connect(self.failed)
        task.signals.cancelled.connect(self.cancelled)

        return task

    def start(self, job: DownloadJob) -> None:
        if job.priority:
            self.pool.start(job.task, job.priority)
        else:
            self.pool.start(job.task)

    def restart(self, job: DownloadJob, source: SavedDownload) -> None:
        job.task = self._task(
            job.task.job_id,
            job.url,
            job.title,
            "",
            job.directory,
            (),
            source,
        )
        job.started = job.finished = job.cancelling = job.pausing = False
        job.status = "queued"
        job.percent = None
        self.active_urls.add(job.url)
        self.start(job)

    def prioritize(self, job: DownloadJob) -> bool:
        if job.status != "queued" or not self.pool.tryTake(job.task):
            return False
        self._priority += 1
        job.priority = self._priority
        self.start(job)
        return True

    def cancel(self, job: DownloadJob, *, pause: bool = False) -> None:
        job.cancelling = True
        job.pausing = pause
        job.task.cancel()
        if self.pool.tryTake(job.task):
            self.cancelled.emit(job.task.job_id)
        else:
            job.row.mark_cancelling()

    def settle(self, job: DownloadJob, *, release_lock: bool = True) -> None:
        self.active_urls.discard(job.url)
        if release_lock:
            self.release(job.task.job_id)

    def release(self, job_id: str) -> None:
        if job_id in self._owned:
            release(self.lock_directory / f"download-{job_id}")
            self._owned.discard(job_id)

    def release_all(self) -> None:
        for job_id in tuple(self._owned):
            self.release(job_id)
