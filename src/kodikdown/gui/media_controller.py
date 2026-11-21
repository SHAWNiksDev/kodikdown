from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QThreadPool, Signal

from kodikdown.downloader import is_pending_output
from kodikdown.gui.media_store import DeleteFiles, HistoryStore, MediaFile, MediaScan


class MediaController(QObject):
    changed = Signal()
    deleted = Signal(object, str)
    save_failed = Signal(str)

    def __init__(self, settings_path: Path, parent: QObject) -> None:
        super().__init__(parent)
        self.history = HistoryStore(settings_path.with_name("history.json"), self.save_failed.emit)
        self.library = HistoryStore(settings_path.with_name("library.json"), self.save_failed.emit)
        if not self.library.path.exists():
            self.library.put_many(
                entry for entry in self.history.entries if entry.status == "finished" and entry.path
            )
        parent.destroyed.connect(self.history.close)
        parent.destroyed.connect(self.library.close)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.files: tuple[MediaFile, ...] = ()
        self.availability: dict[str, bool] = {}
        self._scan: MediaScan | None = None
        self._generation = 0
        self._download_paths: tuple[str, ...] = ()
        self._closed = False

    @property
    def scanning(self) -> bool:
        return self._scan is not None

    def refresh(self, download_paths: tuple[str, ...]) -> None:
        if self._closed:
            return
        self._download_paths = download_paths
        self._generation += 1
        if self._scan is None:
            self._start_scan()

    def _start_scan(self) -> None:
        entries = self.library.entries
        paths = dict.fromkeys(
            (*self._download_paths, *(entry.path for entry in (*self.history.entries, *entries)))
        )
        self._scan = MediaScan(self._generation, entries, tuple(paths))
        self._scan.signals.ready.connect(self._on_scanned)
        self.pool.start(self._scan)

    def _on_scanned(
        self, generation: int, files: tuple[MediaFile, ...], available: dict[str, bool]
    ) -> None:
        self._scan = None
        if self._closed:
            return
        if generation != self._generation:
            self._start_scan()
            return
        self.files = files
        self.availability = available
        self.changed.emit()

    def delete(self, paths: set[str]) -> bool:
        if any(is_pending_output(Path(path)) for path in paths):
            return False
        task = DeleteFiles(paths)
        task.signals.done.connect(self._on_deleted)
        self.pool.start(task)
        return True

    def _on_deleted(self, paths: set[str], error: str) -> None:
        if self._closed:
            return
        self.library.remove(
            {entry.id for entry in self.library.entries if entry.path in paths}, set()
        )
        self.availability.update(dict.fromkeys(paths, False))
        self.refresh(self._download_paths)
        self.deleted.emit(paths, error)

    def close(self) -> None:
        self._closed = True
        self.history.close()
        self.library.close()
        self.pool.clear()
