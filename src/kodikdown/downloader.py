from __future__ import annotations

import asyncio
import contextlib
import gc
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from glob import escape as glob_escape
from pathlib import Path

import yt_dlp

from kodikdown.net import USER_AGENT

_PROGRESS_INTERVAL = 0.12
# Cold Kodik CDN nodes regularly need more than one attempt for the manifest,
# and a plain socket read can stall for a while before it starts answering.
_TRANSFER_ATTEMPTS = 3
_RETRY_DELAY = 1.5
_TRANSIENT_MARKERS = (
    "timed out",
    "timeout",
    "temporary failure",
    "connection reset",
    "connection aborted",
    "connection refused",
    "unable to download",
    "http error 5",
    "http error 429",
    "read error",
    "incomplete read",
    "remote end closed",
)


@dataclass(frozen=True)
class ProgressSnapshot:
    downloaded: int = 0
    total: int | None = None
    speed: float | None = None
    eta: float | None = None
    fragments: bool = False
    stage: str = "downloading"


ProgressListener = Callable[[ProgressSnapshot], None]

_ILLEGAL_FS_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_MEDIA_SUFFIX_RE = re.compile(r"\.(mp4|mkv|webm|avi|mov|m4v|flv|wmv|ts)$", re.IGNORECASE)

# yt-dlp treats % as the start of an output-template field, so it cannot appear
# in a file name that is fed back into outtmpl.
_TEMPLATE_CHARS = re.compile(r"%")

# yt-dlp writes the unfinished file as *.part, keeps its queue state in
# *.ytdl and stores HLS fragments as *.part-Frag<n> (sometimes with another
# .part on top while the fragment itself is still being written).
_PARTIAL_SUFFIXES = (".part", ".ytdl", ".frag")
_PARTIAL_MARKER = ".part-Frag"
_REMOVAL_ATTEMPTS = 6

# Windows does not allow these names even with a fine extension.
_RESERVED_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}


def safe_filename(name: str, fallback: str = "video") -> str:
    cleaned = _ILLEGAL_FS_CHARS.sub("_", name).strip(" .")
    cleaned = _TEMPLATE_CHARS.sub("_", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)[:120]
    cleaned = _MEDIA_SUFFIX_RE.sub("", cleaned).strip(" .")
    if not cleaned or set(cleaned) == {"_"}:
        return fallback
    base = cleaned.split(".", 1)[0].strip().lower()
    if base in _RESERVED_NAMES:
        cleaned = f"_{cleaned}"
    return cleaned


_RESERVED_TARGETS: set[str] = set()
_RESERVED_LOCK = threading.Lock()


def unique_target(directory: Path, stem: str) -> Path:
    """`clip` -> `clip (2)` when a finished file with that name already exists.

    Names already promised to another running transfer are skipped as well,
    otherwise two simultaneous downloads could write into the same file.
    """
    with _RESERVED_LOCK:
        candidate = directory / stem
        index = 2
        while str(candidate) in _RESERVED_TARGETS or _existing_media(candidate):
            candidate = directory / f"{stem} ({index})"
            index += 1
            if index > 100:
                raise FileExistsError(f"no free file name left for {stem!r}")
        _RESERVED_TARGETS.add(str(candidate))
        return candidate


def release_target(target: Path) -> None:
    with _RESERVED_LOCK:
        _RESERVED_TARGETS.discard(str(target))


def _existing_media(target_base: Path) -> bool:
    if not target_base.parent.exists():
        return False
    pattern = f"{glob_escape(target_base.name)}.*"
    return any(
        path
        for path in target_base.parent.glob(pattern)
        if path.suffix.lower() not in _PARTIAL_SUFFIXES and _PARTIAL_MARKER not in path.name
    )


class DownloadCancelled(Exception):
    """Raised when the user asked to stop the transfer."""


class DownloadFailed(Exception):
    """yt-dlp could not fetch or assemble the stream."""


class _CollectingLogger:
    """Keeps the last yt-dlp error line so failures can be shown verbatim."""

    def __init__(self) -> None:
        self.last_error = ""

    def debug(self, message: str) -> None:
        pass

    def info(self, message: str) -> None:
        pass

    def warning(self, message: str) -> None:
        pass

    def error(self, message: str) -> None:
        text = str(message).strip()
        if text.startswith("ERROR:"):
            text = text.removeprefix("ERROR:").strip()
        if text:
            self.last_error = text


class Downloader:
    """Thin async wrapper around yt-dlp for HLS manifests and direct files."""

    def __init__(
        self,
        output_dir: Path,
        listener: ProgressListener | None = None,
        cancel_event: threading.Event | None = None,
        *,
        concurrent_fragments: int = 8,
        socket_timeout: float = 30.0,
        retries: int = 10,
        filename: str | None = None,
    ) -> None:
        self.output_dir = Path(output_dir)
        self._listener = listener
        self._cancel_event = cancel_event or threading.Event()
        self._concurrent_fragments = max(1, concurrent_fragments)
        self._socket_timeout = max(5.0, socket_timeout)
        self._retries = max(0, retries)
        self._filename = filename
        self._last_emit = 0.0
        self._last_snapshot: ProgressSnapshot | None = None
        self._logger = _CollectingLogger()

    # -- control -----------------------------------------------------------
    def cancel(self) -> None:
        self._cancel_event.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel_event.is_set()

    async def download(self, url: str, title: str, referer: str) -> Path:
        return await asyncio.to_thread(self.download_blocking, url, title, referer)

    # -- the actual work ---------------------------------------------------
    def download_blocking(self, url: str, title: str, referer: str) -> Path:
        if self.cancelled:
            raise DownloadCancelled
        self.output_dir.mkdir(parents=True, exist_ok=True)
        if not self.output_dir.is_dir():
            raise DownloadFailed(f"{self.output_dir} is not a folder")

        stem = safe_filename(self._filename or title)
        target_base = unique_target(self.output_dir, stem)
        try:
            self._transfer_with_retries(target_base, url, referer)
        except DownloadCancelled:
            self._cleanup_cancelled(target_base)
            raise
        finally:
            release_target(target_base)

        if self.cancelled:
            self._cleanup_cancelled(target_base)
            raise DownloadCancelled

        produced = self._pick_result(target_base)
        if produced is None:
            self._cleanup_cancelled(target_base)
            detail = self._logger.last_error or "no file was written"
            raise DownloadFailed(f"download finished without a file: {detail}")
        return produced

    def _transfer_with_retries(self, target_base: Path, url: str, referer: str) -> None:
        """Retry a transfer that died on a network hiccup.

        Partial files are deliberately kept between attempts: yt-dlp resumes
        the fragments it already has, so the retry is cheap.
        """
        for attempt in range(_TRANSFER_ATTEMPTS):
            try:
                self._transfer(target_base, url, referer)
                return
            except DownloadFailed as exc:
                last = attempt + 1 == _TRANSFER_ATTEMPTS
                if last or self.cancelled or not _is_transient(str(exc)):
                    raise
                time.sleep(_RETRY_DELAY * (attempt + 1))

    def _transfer(self, target_base: Path, url: str, referer: str) -> None:
        try:
            options = self._options(target_base, referer)
            with yt_dlp.YoutubeDL(options) as ydl:
                ydl.download([url])
        except yt_dlp.utils.DownloadCancelled as exc:
            self._cancel_event.set()
            raise DownloadCancelled from exc
        except yt_dlp.utils.DownloadError as exc:
            if self.cancelled:
                raise DownloadCancelled from exc
            raise DownloadFailed(self._failure_message(exc)) from exc
        except OSError as exc:
            raise DownloadFailed(f"could not write to {self.output_dir}: {exc}") from exc

    def _pick_result(self, target_base: Path) -> Path | None:
        parent = target_base.parent
        pattern = f"{glob_escape(target_base.name)}.*"
        produced = [
            path
            for path in parent.glob(pattern)
            if path.suffix.lower() not in _PARTIAL_SUFFIXES and _PARTIAL_MARKER not in path.name
        ]
        if not produced:
            return None
        produced.sort(key=_mtime)
        return produced[-1].resolve()

    def _cleanup_cancelled(self, target_base: Path) -> None:
        """Drop the partial files left behind by a cancelled transfer.

        A cancelled yt-dlp run keeps some fragment workers alive for a moment,
        and on Windows an open handle blocks deletion, so give the filesystem a
        few tries before giving up. The explicit collect breaks the reference
        cycles those workers are parked in.
        """
        gc.collect()
        for attempt in range(_REMOVAL_ATTEMPTS):
            if not self._remove_partials(target_base):
                return
            time.sleep(0.15 * (attempt + 1))

    def _failure_message(self, exc: Exception) -> str:
        message = self._logger.last_error or str(exc)
        message = re.sub(r"^ERROR:\s*", "", message.strip())
        message = re.sub(r"\s+", " ", message)
        return message[:400] if message else "yt-dlp failed"

    # -- yt-dlp plumbing ---------------------------------------------------
    def _options(self, target_base: Path, referer: str) -> dict[str, object]:
        return {
            "format": "best",
            "outtmpl": f"{target_base}.%(ext)s",
            "noplaylist": True,
            "concurrent_fragment_downloads": self._concurrent_fragments,
            "retries": self._retries,
            "fragment_retries": self._retries,
            "extractor_retries": 4,
            "file_access_retries": 3,
            # Short timeout so a stalled server (or a cancel during a stall)
            # fails fast instead of hanging.
            "socket_timeout": self._socket_timeout,
            "http_chunk_size": 10 * 1024 * 1024,
            "hls_prefer_native": True,
            "continuedl": True,
            "overwrites": False,
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "cachedir": False,
            "logger": self._logger,
            "http_headers": {"Referer": referer, "User-Agent": USER_AGENT},
            "progress_hooks": [self._hook],
            "postprocessor_hooks": [self._pp_hook],
        }

    def _remove_partials(self, target_base: Path) -> bool:
        """Delete leftovers; returns True when something is still locked."""
        parent = target_base.parent
        if not parent.exists():
            return False
        pattern = f"{glob_escape(target_base.name)}.*"
        blocked = False
        for path in parent.glob(pattern):
            if path.suffix not in _PARTIAL_SUFFIXES and _PARTIAL_MARKER not in path.name:
                continue
            try:
                path.unlink()
            except OSError:
                blocked = True
        return blocked

    def _hook(self, status: dict[str, object]) -> None:
        if self.cancelled:
            raise yt_dlp.utils.DownloadCancelled()
        if self._listener is None:
            return
        state = status.get("status")
        if state == "finished":
            self._emit(self._with_stage("finished"), force=True)
            return
        if state != "downloading":
            return

        downloaded = status.get("downloaded_bytes")
        total = status.get("total_bytes") or status.get("total_bytes_estimate")
        # HLS downloads sometimes report only fragment counters.
        fragments = False
        if downloaded is None:
            index = status.get("fragment_index")
            count = status.get("fragment_count")
            if isinstance(index, (int, float)) and isinstance(count, (int, float)) and count:
                downloaded, total = int(index), int(count)
                fragments = True

        self._emit(
            ProgressSnapshot(
                downloaded=int(downloaded) if isinstance(downloaded, (int, float)) else 0,
                total=int(total) if isinstance(total, (int, float)) else None,
                speed=_as_float(status.get("speed")),
                eta=_as_float(status.get("eta")),
                fragments=fragments,
            )
        )

    def _pp_hook(self, status: dict[str, object]) -> None:
        # Postprocessors (ffmpeg fixup/merge) report rarely, but when they do,
        # a pending cancel should still stop the job, and the UI should show
        # that the transfer moved on to assembling.
        if self.cancelled:
            raise yt_dlp.utils.DownloadCancelled()
        if self._listener is not None and status.get("status") == "started":
            self._emit(self._with_stage("processing"), force=True)

    def _with_stage(self, stage: str) -> ProgressSnapshot:
        """A terminal snapshot that keeps whatever the transfer reported before."""
        previous = self._last_snapshot or ProgressSnapshot()
        return ProgressSnapshot(
            downloaded=previous.downloaded,
            total=previous.total,
            speed=previous.speed,
            eta=previous.eta,
            fragments=previous.fragments,
            stage=stage,
        )

    def _emit(self, snapshot: ProgressSnapshot, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_emit < _PROGRESS_INTERVAL:
            return
        self._last_emit = now
        self._last_snapshot = snapshot
        if self._listener is not None:
            with contextlib.suppress(Exception):
                self._listener(snapshot)


def _is_transient(message: str) -> bool:
    lowered = message.lower()
    return any(marker in lowered for marker in _TRANSIENT_MARKERS)


def _mtime(path: Path) -> float:
    with contextlib.suppress(OSError):
        return path.stat().st_mtime
    return 0.0


def _as_int(value: object) -> int:
    return int(value) if isinstance(value, (int, float)) else 0


def _as_float(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None
