from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


def referer_for(stream_url: str) -> str:
    """Referer header yt-dlp should send for a resolved manifest URL."""
    host = urlparse(stream_url).hostname or ""
    if not host:
        # Fallback for protocol-relative or odd URLs.
        tail = stream_url.split("//", 1)[-1]
        host = tail.split("/", 1)[0]
    return f"https://{host}/" if host else "https://kodik.info/"


@dataclass(frozen=True)
class EmbedInfo:
    """Parts of a player embed URL: host plus the type/id/hash triple."""

    domain: str
    media_type: str
    video_id: str
    content_hash: str
    quality: int | None = None

    @property
    def page_url(self) -> str:
        base = f"https://{self.domain}/{self.media_type}/{self.video_id}/{self.content_hash}"
        return f"{base}/{self.quality}p" if self.quality else base


@dataclass(frozen=True)
class PlayerPayload:
    """Form fields expected by the player's video-info endpoint."""

    media_type: str
    video_id: str
    content_hash: str

    def as_form(self) -> dict[str, str]:
        return {
            "type": self.media_type,
            "id": self.video_id,
            "hash": self.content_hash,
            "bad_user": "True",
            "info": "{}",
            "cdn_is_working": "True",
        }


@dataclass(frozen=True)
class StreamVariant:
    """A direct HLS manifest for one quality level."""

    quality: int
    url: str


@dataclass(frozen=True)
class Translation:
    """A voice-over or subtitle track the player can serve."""

    title: str
    media_type: str
    media_id: str
    content_hash: str

    @property
    def key(self) -> str:
        return f"{self.media_type}:{self.media_id}:{self.content_hash}"


@dataclass(frozen=True)
class ResolvedVideo:
    """Everything the UI needs after a successful lookup."""

    title: str | None
    variants: tuple[StreamVariant, ...]
    translations: tuple[Translation, ...] = ()
    translation: Translation | None = None

    def find_translation(self, query: str) -> Translation | None:
        wanted = query.strip().casefold()
        if not wanted:
            return None
        for translation in self.translations:
            if translation.title.casefold() == wanted:
                return translation
        for translation in self.translations:
            if wanted in translation.title.casefold():
                return translation
        return None

    @property
    def best(self) -> StreamVariant:
        if not self.variants:
            raise IndexError("no variants available")
        return self.variants[0]

    def pick(self, quality: int | None) -> StreamVariant:
        if not self.variants:
            raise IndexError("no variants available")
        if quality is not None:
            exact = [v for v in self.variants if v.quality == quality]
            if exact:
                return exact[0]
            lower = [v for v in self.variants if v.quality < quality]
            if lower:
                return lower[0]
            # Asked for less than we have (e.g. 200p when only 360p+ exists):
            # give the smallest file instead of the biggest one.
            return self.variants[-1]
        return self.best
