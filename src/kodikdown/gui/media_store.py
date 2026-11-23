"""Persistent download history and background storage checks for the desktop UI."""

from __future__ import annotations

import contextlib
import json
import math
import os
import tempfile
import time
from collections.abc import Callable, Iterable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import TypedDict, Unpack

from PySide6.QtCore import QObject, QRunnable, Signal

from kodikdown.downloader import is_pending_output
from kodikdown.output_locks import release, try_reserve


@dataclass(frozen=True)
class HistoryEntry:
    id: str
    title: str
    file_name: str
    source_input: str
    quality: int
    created: float
    status: str = "queued"
    translation: str = ""
    prefer_mp4: bool = False
    path: str = ""
    error: str = ""
    file_size: int = 0
    retry_input: str = ""
    series: str = ""

    @classmethod
    def from_json(cls, raw: object) -> HistoryEntry | None:
        if not isinstance(raw, dict):
            return None
        required = ("id", "title", "file_name", "source_input")
        if any(not isinstance(raw.get(key), str) for key in required):
            return None
        if type(raw.get("quality")) is not int or type(raw.get("created")) not in (int, float):
            return None
        allowed = {name: value for name, value in raw.items() if name in cls.__dataclass_fields__}
        if any(
            not isinstance(allowed.get(key, ""), str)
            for key in ("status", "translation", "path", "error", "retry_input", "series")
        ):
            return None
        if not 0 <= raw["created"] <= 253402300799 or not math.isfinite(raw["created"]):
            return None
        if type(allowed.get("prefer_mp4", False)) is not bool:
            allowed["prefer_mp4"] = False
        if type(allowed.get("file_size", 0)) is not int or allowed.get("file_size", 0) < 0:
            allowed["file_size"] = 0
        return cls(**allowed)


def _read_history(path: Path) -> dict[str, HistoryEntry]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}
    if not isinstance(raw, list):
        return {}
    return {entry.id: entry for item in raw if (entry := HistoryEntry.from_json(item))}


class HistoryChanges(TypedDict, total=False):
    status: str
    path: str
    quality: int
    error: str
    file_size: int


class HistoryStore:
    def __init__(self, path: Path, on_error: Callable[[str], None] | None = None) -> None:
        self.path = path
        self._on_error = on_error
        self._writer = ThreadPoolExecutor(max_workers=1, thread_name_prefix="kodikdown-history")
        self._pending: Future[None] | None = None
        self._closed = False
        try:
            self._entries = _read_history(path)
        except OSError:
            self._entries = {}
        for identifier, entry in self._entries.items():
            if entry.status in ("queued", "downloading", "assembling"):
                self._entries[identifier] = replace(entry, status="interrupted", error="")

    @property
    def entries(self) -> tuple[HistoryEntry, ...]:
        return tuple(sorted(self._entries.values(), key=lambda entry: entry.created, reverse=True))

    def get(self, identifier: str) -> HistoryEntry | None:
        return self._entries.get(identifier)

    def put(self, entry: HistoryEntry) -> None:
        self.put_many((entry,))

    def put_many(self, entries: Iterable[HistoryEntry]) -> None:
        updates = {entry.id: entry for entry in entries}
        self._entries.update(updates)
        self._save(updates, set())

    def update(self, identifier: str, **changes: Unpack[HistoryChanges]) -> None:
        old = self.get(identifier)
        if old is not None:
            updated = replace(old, **changes)
            if updated != old:
                self.put(updated)

    def remove(self, identifiers: set[str], protected: set[str]) -> None:
        removed = identifiers - protected
        for identifier in removed:
            self._entries.pop(identifier, None)
        self._save({}, removed)

    def clear(self, protected: set[str]) -> None:
        self.remove(set(self._entries), protected)

    def _save(self, updates: dict[str, HistoryEntry], removed: set[str]) -> None:
        if self._closed or not (updates or removed):
            return
        self._pending = self._writer.submit(self._write, updates, removed)
        self._pending.add_done_callback(self._written)

    def _write(self, updates: dict[str, HistoryEntry], removed: set[str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + 5
        while not try_reserve(self.path):
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Could not lock {self.path}")
            time.sleep(0.05)
        try:
            entries = _read_history(self.path)
            entries.update(updates)
            for identifier in removed:
                entries.pop(identifier, None)
            ordered = sorted(entries.values(), key=lambda entry: entry.created, reverse=True)
            self._replace_file(json.dumps([asdict(entry) for entry in ordered], ensure_ascii=False))
        finally:
            release(self.path)

    def _replace_file(self, payload: str) -> None:
        descriptor, temporary = tempfile.mkstemp(
            dir=self.path.parent, prefix=".history-", suffix=".tmp"
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(payload)
            os.replace(temporary, self.path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(temporary)
            raise

    def _written(self, future: Future[None]) -> None:
        error = future.exception()
        if error is not None and self._on_error is not None and not self._closed:
            with contextlib.suppress(RuntimeError):
                self._on_error(str(error))

    def flush(self) -> None:
        if self._pending is not None:
            self._pending.result(timeout=10)

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._writer.shutdown(wait=True)


@dataclass(frozen=True)
class MediaFile:
    path: str
    title: str
    size: int
    modified: float
    series: str = ""


def readable_file(raw: str) -> bool:
    if not raw:
        return False
    try:
        path = Path(raw)
        return (
            path.is_file()
            and path.stat().st_size > 0
            and os.access(path, os.R_OK)
            and not is_pending_output(path)
        )
    except (OSError, ValueError):
        return False


class ScanSignals(QObject):
    ready = Signal(int, object, object)


class DeleteSignals(QObject):
    done = Signal(object, str)


class DeleteFiles(QRunnable):
    def __init__(self, paths: set[str]) -> None:
        super().__init__()
        self.paths = paths
        self.signals = DeleteSignals()

    def run(self) -> None:
        deleted: set[str] = set()
        errors: list[str] = []
        for raw in self.paths:
            try:
                path = Path(raw)
                if is_pending_output(path):
                    continue
                path.unlink(missing_ok=True)
                deleted.add(raw)
            except OSError as exc:
                errors.append(str(exc))
        with contextlib.suppress(RuntimeError):
            self.signals.done.emit(deleted, "; ".join(errors))


class MediaScan(QRunnable):
    def __init__(
        self, generation: int, entries: tuple[HistoryEntry, ...], paths: tuple[str, ...]
    ) -> None:
        super().__init__()
        self.generation = generation
        self.entries = entries
        self.paths = paths
        self.signals = ScanSignals()

    def run(self) -> None:
        files: list[MediaFile] = []
        availability = {path: readable_file(path) for path in self.paths if path}
        seen: set[str] = set()
        for entry in self.entries:
            if entry.path in seen or not availability.get(entry.path, False):
                continue
            try:
                stat = Path(entry.path).stat()
            except OSError:
                continue
            seen.add(entry.path)
            files.append(
                MediaFile(entry.path, entry.title, stat.st_size, stat.st_mtime, entry.series)
            )
        with contextlib.suppress(RuntimeError):
            self.signals.ready.emit(
                self.generation,
                tuple(sorted(files, key=lambda item: item.modified, reverse=True)),
                availability,
            )
