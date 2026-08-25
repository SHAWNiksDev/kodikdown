from __future__ import annotations

from dataclasses import dataclass


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
class ResolvedVideo:
    """Everything the UI needs after a successful lookup."""

    title: str | None
    variants: tuple[StreamVariant, ...]

    @property
    def best(self) -> StreamVariant:
        return self.variants[0]

    def pick(self, quality: int | None) -> StreamVariant:
        if quality is not None:
            exact = [v for v in self.variants if v.quality == quality]
            if exact:
                return exact[0]
            lower = [v for v in self.variants if v.quality < quality]
            if lower:
                return lower[0]
        return self.best
