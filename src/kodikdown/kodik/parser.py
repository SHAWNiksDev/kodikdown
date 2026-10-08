from __future__ import annotations

import base64
import html
import re
from urllib.parse import urlparse

from kodikdown.kodik.errors import InvalidUrlError, PageStructureError
from kodikdown.kodik.models import EmbedInfo, PlayerPayload

_EMBED_RE = re.compile(
    r"/(?P<type>[a-z][a-z-]*)/(?P<id>\d+)/(?P<hash>[0-9a-f]{32})(?:/(?P<quality>\d+)p?)?",
    re.IGNORECASE,
)
_IFRAME_SRC_RE = re.compile(r"""<iframe[^>]*?\ssrc=["'](?P<src>[^"']+)["']""", re.IGNORECASE)
_VINFO_RE = re.compile(r"\.\s*(?P<field>type|hash|id)\s*=\s*'(?P<value>[^']*)'\s*;")
_VINFO_DOUBLE_RE = re.compile(r'\.\s*(?P<field>type|hash|id)\s*=\s*"(?P<value>[^"]*)"\s*;')
_PLAYER_JS_PATTERNS = (
    # Current bundle name, e.g. assets/js/app.player_single.abc123.js
    re.compile(
        r"""<script\s[^>]*?src=["'](?:https?://[^/"']+)?/(?P<path>assets/js/app\.player_single[^"']+?\.js)["']""",
        re.IGNORECASE,
    ),
    # Just in case they rename it one day.
    re.compile(
        r"""<script\s[^>]*?src=["'](?:https?://[^/"']+)?/(?P<path>assets/js/[^"']*player[^"']*?\.js)["']""",
        re.IGNORECASE,
    ),
)
_ATOB_RE = re.compile(
    r"""atob\(\s*["'](?P<encoded>[A-Za-z0-9+/=]{8,})["']""",
)
_KNOWN_ENDPOINT_RE = re.compile(r"""["'](?P<path>/(?:ftor|gvi|[a-z]{2,8}))["']""")
_TITLE_RE = re.compile(r"<title>(?P<title>.*?)</title>", re.IGNORECASE | re.DOTALL)
_OG_TITLE_RE = re.compile(
    r"""<meta\s[^>]*property=["']og:title["'][^>]*content=["'](?P<title>[^"']+)["']""",
    re.IGNORECASE,
)
_GENERIC_TITLE_RE = re.compile(r"^(kodik|kodik\s*player)$", re.IGNORECASE)


def extract_embed(raw: str) -> EmbedInfo:
    """Accept a bare embed URL, a protocol-relative one or a whole iframe tag."""
    text = html.unescape(raw.strip())
    iframe = _IFRAME_SRC_RE.search(text)
    if iframe:
        text = iframe.group("src").strip()

    if text.startswith("//"):
        text = f"https:{text}"

    match = _EMBED_RE.search(text)
    if not match:
        raise InvalidUrlError(f"not a kodik embed: {raw[:120]!r}")

    quality = match.group("quality")
    return EmbedInfo(
        domain=_host_of(text),
        media_type=match.group("type").lower(),
        video_id=match.group("id"),
        content_hash=match.group("hash").lower(),
        quality=int(quality) if quality else None,
    )


def _host_of(url: str) -> str:
    parsed = urlparse(url if "://" in url else f"https://{url.lstrip('/')}")
    if parsed.hostname:
        return parsed.hostname.lower()
    # Very old fallback, should not normally trigger.
    return url.split("//", 1)[-1].split("/", 1)[0].split("?", 1)[0].lower()


def extract_payload(html_text: str) -> PlayerPayload | None:
    fields: dict[str, str] = {}
    for pattern in (_VINFO_RE, _VINFO_DOUBLE_RE):
        for match in pattern.finditer(html_text):
            fields.setdefault(match.group("field"), match.group("value").strip())
    try:
        return PlayerPayload(fields["type"], fields["id"], fields["hash"])
    except KeyError:
        return None


def extract_player_js_path(html_text: str) -> str:
    for pattern in _PLAYER_JS_PATTERNS:
        match = pattern.search(html_text)
        if match:
            return match.group("path")
    raise PageStructureError("player script tag not found on page")


def extract_endpoint(player_js: str) -> str:
    """The video-info endpoint lives in the player bundle behind atob()."""
    found: list[str] = []
    for match in _ATOB_RE.finditer(player_js):
        try:
            endpoint = base64.b64decode(match.group("encoded")).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            continue
        if endpoint.startswith("/") and len(endpoint) < 64 and " " not in endpoint:
            found.append(endpoint)
    # API endpoints are short ("/ftor", "/gvi", ...), other atob() strings
    # usually decode to asset paths, so prefer those without a dot.
    for endpoint in found:
        if "." not in endpoint and len(endpoint) <= 16:
            return endpoint
    if found:
        return found[0]
    # Older bundles sometimes inline /ftor or /gvi without atob.
    for match in _KNOWN_ENDPOINT_RE.finditer(player_js):
        return match.group("path")
    raise PageStructureError("video-info endpoint not found in player bundle")


def extract_title(html_text: str) -> str | None:
    match = _TITLE_RE.search(html_text)
    title = match.group("title") if match else ""
    if not title:
        og = _OG_TITLE_RE.search(html_text)
        title = og.group("title") if og else ""
    title = html.unescape(re.sub(r"\s+", " ", title)).strip()
    if not title or _GENERIC_TITLE_RE.match(title):
        return None
    return title
