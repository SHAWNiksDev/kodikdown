from __future__ import annotations

import asyncio
import contextlib
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass
from glob import escape as glob_escape
from pathlib import Path

import yt_dlp

from kodikdown.net import USER_AGENT


@dataclass(frozen=True)
class ProgressSnapshot:
    downloaded: int = 0
    total: int | None = None
    speed: float | None = None
    fragments: bool = False


ProgressListener = Callable[[ProgressSnapshot], None]

_ILLEGAL_FS_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_MEDIA_SUFFIX_RE = re.compile(r"\.(mp4|mkv|webm|avi|mov|m4v|flv|wmv|ts)$", re.IGNORECASE)

# yt-dlp writes the unfinished file as *.part, keeps its queue state in
# *.ytdl and stores HLS fragments as *.part-Frag<n> (sometimes with another
# .part on top while the fragment itself is still being written).
_PARTIAL_SUFFIXES = (".part", ".ytdl", ".frag")
_PARTIAL_MARKER = ".part-Frag"

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
    cleaned = re.sub(r"\s+", " ", cleaned)[:120]
    cleaned = _MEDIA_SUFFIX_RE.sub("", cleaned).strip(" .")
    if not cleaned or set(cleaned) == {"_"}:
        return fallback
    base = cleaned.split(".", 1)[0].strip().lower()
    if base in _RESERVED_NAMES:
        cleaned = f"_{cleaned}"
    return cleaned


class DownloadCancelled(Exception):
    """Raised when the user asked to stop the transfer."""


class DownloadFailed(Exception):
    """yt-dlp could not fetch or assemble the stream."""


class Downloader:
    """Thin async wrapper around yt-dlp for HLS manifests."""

    def __init__(
        self,
        output_dir: Path,
        listener: ProgressListener | None = None,
        cancel_event: threading.Event | None = None,
    ) -> None:
        self.output_dir = Path(output_dir)
        self._listener = listener
        self._cancel_event = cancel_event or threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel_event.is_set()

    async def download(self, url: str, title: str, referer: str) -> Path:
        return await asyncio.to_thread(self.download_blocking, url, title, referer)

    def download_blocking(self, url: str, title: str, referer: str) -> Path:
        if self.cancelled:
            raise DownloadCancelled
        stem = safe_filename(title)
        target_base = self.output_dir / stem
        pattern = f"{glob_escape(target_base.name)}.*"
        before = set(target_base.parent.glob(pattern)) if target_base.parent.exists() else set()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        try:
            options = self._options(target_base, referer)
            with yt_dlp.YoutubeDL(options) as ydl:
                ydl.download([url])
        except yt_dlp.utils.DownloadCancelled as exc:
            self._remove_partials(target_base)
            raise DownloadCancelled from exc
        except yt_dlp.utils.DownloadError as exc:
            raise DownloadFailed(str(exc).replace("ERROR: ", "", 1)) from exc

        after = sorted(
            (
                p
                for p in target_base.parent.glob(pattern)
                if not p.name.endswith((".part", ".ytdl"))
            ),
            key=lambda p: p.stat().st_mtime,
        )
        fresh = [p for p in after if p not in before]
        produced = fresh or after
        if not produced:
            raise FileNotFoundError(f"yt-dlp finished but no file matched {target_base.name}.*")
        return produced[-1].resolve()

    def _options(self, target_base: Path, referer: str) -> dict[str, object]:
        return {
            "format": "best",
            "outtmpl": f"{target_base}.%(ext)s",
            "concurrent_fragment_downloads": 8,
            "retries": 10,
            "fragment_retries": 10,
            # Short timeout so a stalled server (or a cancel during a stall)
            # fails fast instead of hanging.
            "socket_timeout": 10,
            "http_chunk_size": 10 * 1024 * 1024,
            "hls_prefer_native": True,
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "http_headers": {"Referer": referer, "User-Agent": USER_AGENT},
            "progress_hooks": [self._hook],
            "postprocessor_hooks": [self._pp_hook],
        }

    def _remove_partials(self, target_base: Path) -> None:
        parent = target_base.parent
        if not parent.exists():
            return
        pattern = f"{glob_escape(target_base.name)}.*"
        for path in parent.glob(pattern):
            if path.suffix in _PARTIAL_SUFFIXES or _PARTIAL_MARKER in path.name:
                with contextlib.suppress(OSError):
                    path.unlink()

    def _hook(self, status: dict[str, object]) -> None:
        if self.cancelled:
            raise yt_dlp.utils.DownloadCancelled()
        if self._listener is None or status.get("status") != "downloading":
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
        speed = status.get("speed")
        self._listener(
            ProgressSnapshot(
                downloaded=int(downloaded) if isinstance(downloaded, (int, float)) else 0,
                total=int(total) if isinstance(total, (int, float)) else None,
                speed=float(speed) if isinstance(speed, (int, float)) else None,
                fragments=fragments,
            )
        )

    def _pp_hook(self, status: dict[str, object]) -> None:
        # Postprocessors (ffmpeg fixup/merge) report rarely, but when they do,
        # a pending cancel should still stop the job.
        if self.cancelled:
            raise yt_dlp.utils.DownloadCancelled()
