from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QThreadPool, Signal

from kodikdown.downloader import DownloadSource, safe_filename
from kodikdown.gui.theme import Palette
from kodikdown.gui.widgets import DownloadRow
from kodikdown.gui.workers import DownloadTask, EpisodeDownload


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
    status: str = "queued"
    percent: int | None = None


class DownloadQueue(QObject):
    started = Signal(str)
    progress = Signal(str, object)
    finished = Signal(str, str)
    failed = Signal(str, str)
    cancelled = Signal(str)

    def __init__(self, concurrency: int, parent: QObject) -> None:
        super().__init__(parent)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(concurrency)
        self.jobs: dict[str, DownloadJob] = {}
        self.active_urls: set[str] = set()

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
        episode: EpisodeDownload | None,
    ) -> DownloadJob:
        job_id = uuid.uuid4().hex
        row = DownloadRow(job_id, title, quality, palette)
        task = DownloadTask(
            job_id,
            url,
            title,
            referer,
            directory,
            concurrent_fragments=4,
            fallback_sources=fallback_sources,
            episode=episode,
        )
        task.signals.started.connect(self.started)
        task.signals.progress.connect(self.progress)
        task.signals.finished.connect(self.finished)
        task.signals.failed.connect(self.failed)
        task.signals.cancelled.connect(self.cancelled)

        job = DownloadJob(task, row, url, title, directory)
        self.jobs[job_id] = job
        self.active_urls.add(url)
        return job

    def cancel(self, job: DownloadJob) -> None:
        job.cancelling = True
        job.task.cancel()
        if self.pool.tryTake(job.task):
            self.cancelled.emit(job.task.job_id)
        else:
            job.row.mark_cancelling()

    def settle(self, job: DownloadJob) -> None:
        self.active_urls.discard(job.url)
