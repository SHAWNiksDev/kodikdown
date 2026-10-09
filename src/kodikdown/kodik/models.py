from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlparse

# kodik.info and kodik.biz were lost to domain squatters; the player lives on
# kodikplayer.com now. The rest are long-lived mirrors. Any of them serves the
# same embed paths, so a link with a dead host can still be resolved.
DEFAULT_HOSTS: tuple[str, ...] = (
    "kodikplayer.com",
    "kodik.info",
    "kodik.biz",
    "kodik.cc",
    "aniqit.com",
)

_HLS_MANIFEST_SUFFIX = ":hls:manifest.m3u8"


def referer_for(stream_url: str) -> str:
    """Referer header the CDN expects for a resolved manifest URL."""
    host = urlparse(stream_url).hostname or ""
    if not host:
        tail = stream_url.split("//", 1)[-1]
        host = tail.split("/", 1)[0]
    return f"https://{host}/" if host else "https://kodikplayer.com/"


def direct_mp4_url(stream_url: str) -> str | None:
    """The plain mp4 behind an HLS manifest link, when the CDN serves one."""
    if stream_url.endswith(_HLS_MANIFEST_SUFFIX):
        return stream_url[: -len(_HLS_MANIFEST_SUFFIX)]
    return None


@dataclass(frozen=True)
class EmbedInfo:
    """Parts of a player embed URL: host plus the type/id/hash triple."""

    domain: str
    media_type: str
    video_id: str
    content_hash: str
    quality: int | None = None
    query: str = ""

    @property
    def path(self) -> str:
        base = f"/{self.media_type}/{self.video_id}/{self.content_hash}"
        return f"{base}/{self.quality}p" if self.quality else base

    def url_on(self, host: str) -> str:
        suffix = f"?{self.query}" if self.query else ""
        return f"https://{host}{self.path}{suffix}"

    @property
    def page_url(self) -> str:
        return self.url_on(self.domain)

    @property
    def fallback_title(self) -> str:
        return f"kodik-{self.video_id}"


@dataclass(frozen=True)
class PlayerPayload:
    """Form fields identifying one video track of the player."""

    media_type: str
    video_id: str
    content_hash: str

    def as_form(self) -> dict[str, str]:
        return {
            "type": self.media_type,
            "id": self.video_id,
            "hash": self.content_hash,
            "bad_user": "true",
            "cdn_is_working": "true",
        }


@dataclass(frozen=True)
class Translation:
    """A voice-over or subtitle track the player can serve."""

    title: str
    media_type: str
    media_id: str
    content_hash: str
    translation_id: str = ""
    kind: str = "voice"
    selected: bool = False

    @property
    def key(self) -> str:
        return f"{self.media_type}:{self.media_id}:{self.content_hash}"

    @property
    def is_subtitles(self) -> bool:
        return self.kind == "subtitles"

    def as_payload(self) -> PlayerPayload:
        return PlayerPayload(self.media_type, self.media_id, self.content_hash)


@dataclass(frozen=True)
class PlayerPage:
    """Everything worth keeping from one fetch of the embed page."""

    payload: PlayerPayload
    player_js_path: str
    title: str | None = None
    url_params: dict[str, str] = field(default_factory=dict)
    translations: tuple[Translation, ...] = ()
    current_translation: Translation | None = None

    def signed_form(self, payload: PlayerPayload) -> dict[str, str]:
        """Form body for the video-info endpoint, signatures included.

        The signatures are minted per page view and bound to the domain the
        player was opened from, so they have to travel back verbatim. ``ref``
        arrives percent-encoded and must be decoded — the signature is computed
        over the decoded value, and an empty one makes the server answer 500.
        """
        from urllib.parse import unquote

        fields = payload.as_form()
        for name in ("d", "d_sign", "pd", "pd_sign"):
            value = self.url_params.get(name)
            if value:
                fields[name] = value
        ref = unquote(self.url_params.get("ref", "")).strip()
        if ref:
            fields["ref"] = ref
            ref_sign = self.url_params.get("ref_sign")
            if ref_sign:
                fields["ref_sign"] = ref_sign
        return fields


@dataclass(frozen=True)
class StreamVariant:
    """One selectable quality: an HLS manifest and/or a direct file."""

    quality: int
    url: str
    kind: str = "hls"
    direct_mp4: str | None = None

    @property
    def label(self) -> str:
        return f"{self.quality}p"


@dataclass(frozen=True)
class ResolvedVideo:
    """Everything the UI needs after a successful lookup."""

    title: str | None
    variants: tuple[StreamVariant, ...]
    translations: tuple[Translation, ...] = ()
    translation: Translation | None = None
    default_quality: int | None = None
    warnings: tuple[str, ...] = ()

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
        if quality is None:
            return self.best
        exact = [v for v in self.variants if v.quality == quality]
        if exact:
            return exact[0]
        lower = [v for v in self.variants if v.quality < quality]
        if lower:
            return lower[0]
        # Asked for less than we have (e.g. 200p when only 360p+ exists):
        # give the smallest file instead of the biggest one.
        return self.variants[-1]
