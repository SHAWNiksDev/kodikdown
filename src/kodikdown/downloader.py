from __future__ import annotations

import asyncio
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import yt_dlp


@dataclass(frozen=True)
class ProgressSnapshot:
    downloaded: int = 0
    total: int | None = None
    speed: float | None = None


ProgressListener = Callable[[ProgressSnapshot], None]

_ILLEGAL_FS_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_filename(name: str, fallback: str = "video") -> str:
    cleaned = _ILLEGAL_FS_CHARS.sub("_", name).strip(" .")
    cleaned = re.sub(r"\s+", " ", cleaned)[:120]
    if not cleaned or set(cleaned) == {"_"}:
        return fallback
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
        stem = safe_filename(title)
        target_base = self.output_dir / stem
        options = {
            "format": "best",
            "outtmpl": f"{target_base}.%(ext)s",
            "concurrent_fragment_downloads": 16,
            "retries": 10,
            "fragment_retries": 10,
            "socket_timeout": 10,
            "http_chunk_size": 10 * 1024 * 1024,
            "hls_prefer_native": True,
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "http_headers": {"Referer": referer},
            "progress_hooks": [self._hook],
        }
        self.output_dir.mkdir(parents=True, exist_ok=True)
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                ydl.download([url])
        except yt_dlp.utils.DownloadCancelled as exc:
            raise DownloadCancelled from exc
        except yt_dlp.utils.DownloadError as exc:
            raise DownloadFailed(str(exc).replace("ERROR: ", "", 1)) from exc

        produced = sorted(
            target_base.parent.glob(f"{target_base.name}.*"), key=lambda p: p.stat().st_mtime
        )
        if not produced:
            raise FileNotFoundError(f"yt-dlp finished but no file matched {target_base.name}.*")
        return produced[-1].resolve()

    def _hook(self, status: dict[str, object]) -> None:
        if self.cancelled:
            raise yt_dlp.utils.DownloadCancelled()
        if self._listener is None or status.get("status") != "downloading":
            return
        downloaded = status.get("downloaded_bytes")
        total = status.get("total_bytes") or status.get("total_bytes_estimate")
        speed = status.get("speed")
        self._listener(
            ProgressSnapshot(
                downloaded=int(downloaded) if isinstance(downloaded, (int, float)) else 0,
                total=int(total) if isinstance(total, (int, float)) else None,
                speed=float(speed) if isinstance(speed, (int, float)) else None,
            )
        )
