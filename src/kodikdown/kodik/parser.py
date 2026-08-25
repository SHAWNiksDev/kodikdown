from __future__ import annotations

import base64
import re

from kodikdown.kodik.errors import InvalidUrlError, PageStructureError
from kodikdown.kodik.models import EmbedInfo, PlayerPayload

_EMBED_RE = re.compile(
    r"/(?P<type>[a-z][a-z-]*)/(?P<id>\d+)/(?P<hash>[0-9a-f]{32})(?:/(?P<quality>\d+)p?)?",
    re.IGNORECASE,
)
_IFRAME_SRC_RE = re.compile(r"""<iframe[^>]*?\ssrc=["'](?P<src>[^"']+)["']""", re.IGNORECASE)
_VINFO_RE = re.compile(r"\.\s*(?P<field>type|hash|id)\s*=\s*'(?P<value>[^']*)'\s*;")
_PLAYER_JS_RE = re.compile(
    r"""<script\s[^>]*?src=["'](?:https?://[^/"']+)?/(?P<path>assets/js/app\.player_single[^"']+?\.js)["']""",
    re.IGNORECASE,
)
_ENDPOINT_RE = re.compile(
    r"""\$\.ajax\(\s*\{[^}]*?url\s*:\s*atob\(\s*["'](?P<encoded>[A-Za-z0-9+/=]+)["']""",
    re.DOTALL,
)
_TITLE_RE = re.compile(r"<title>(?P<title>.*?)</title>", re.IGNORECASE | re.DOTALL)
_GENERIC_TITLE_RE = re.compile(r"^(kodik|kodik\s*player)$", re.IGNORECASE)


def extract_embed(raw: str) -> EmbedInfo:
    """Accept a bare embed URL, a protocol-relative one or a whole iframe tag."""
    text = raw.strip()
    iframe = _IFRAME_SRC_RE.search(text)
    if iframe:
        text = iframe.group("src")

    if text.startswith("//"):
        text = f"https:{text}"

    match = _EMBED_RE.search(text)
    if not match:
        raise InvalidUrlError(f"not a kodik embed: {raw[:120]!r}")

    quality = match.group("quality")
    return EmbedInfo(
        domain=text.split("//", 1)[-1].split("/", 1)[0].lower(),
        media_type=match.group("type").lower(),
        video_id=match.group("id"),
        content_hash=match.group("hash").lower(),
        quality=int(quality) if quality else None,
    )


def extract_payload(html: str) -> PlayerPayload | None:
    fields: dict[str, str] = {}
    for match in _VINFO_RE.finditer(html):
        fields[match.group("field")] = match.group("value").strip()
    try:
        return PlayerPayload(fields["type"], fields["id"], fields["hash"])
    except KeyError:
        return None


def extract_player_js_path(html: str) -> str:
    match = _PLAYER_JS_RE.search(html)
    if not match:
        raise PageStructureError("player script tag not found on page")
    return match.group("path")


def extract_endpoint(player_js: str) -> str:
    """The video-info endpoint lives in the player bundle behind atob()."""
    match = _ENDPOINT_RE.search(player_js)
    if not match:
        raise PageStructureError("video-info endpoint not found in player bundle")
    endpoint = base64.b64decode(match.group("encoded")).decode("utf-8", errors="strict")
    if not endpoint.startswith("/"):
        raise PageStructureError(f"unexpected video-info endpoint: {endpoint!r}")
    return endpoint


def extract_title(html: str) -> str | None:
    match = _TITLE_RE.search(html)
    if not match:
        return None
    title = re.sub(r"\s+", " ", match.group("title")).strip()
    if not title or _GENERIC_TITLE_RE.match(title):
        return None
    return title
