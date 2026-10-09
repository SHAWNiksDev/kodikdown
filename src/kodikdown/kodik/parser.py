from __future__ import annotations

import base64
import binascii
import html
import json
import re
from urllib.parse import urlparse

from kodikdown.kodik.errors import InvalidUrlError, PageStructureError
from kodikdown.kodik.models import EmbedInfo, PlayerPage, PlayerPayload, Translation

_EMBED_RE = re.compile(
    r"/(?P<type>[a-z][a-z-]*)/(?P<id>\d+)/(?P<hash>[0-9a-z]{16,})"
    r"(?:/(?P<quality>\d{3,4})p?)?",
    re.IGNORECASE,
)
_IFRAME_SRC_RE = re.compile(r"""<iframe[^>]*?\bsrc\s*=\s*["'](?P<src>[^"']+)["']""", re.IGNORECASE)
_QUERY_TAIL_RE = re.compile(r"^\?(?P<query>[^\"'\s>]*)")

_URL_PARAMS_RE = re.compile(
    r"""urlParams\s*=\s*(?P<quote>["'])(?P<json>\{.*?\})(?P=quote)""",
    re.DOTALL,
)
_SIGNED_VAR_RE = re.compile(
    r"""\bvar\s+(?P<name>domain|d_sign|pd|pd_sign|ref|ref_sign)\s*=\s*["'](?P<value>[^"']*)["']"""
)
_VAR_TO_PARAM = {
    "domain": "d",
    "d_sign": "d_sign",
    "pd": "pd",
    "pd_sign": "pd_sign",
    "ref": "ref",
    "ref_sign": "ref_sign",
}

_VINFO_RE = re.compile(r"\.\s*(?P<field>type|hash|id)\s*=\s*'(?P<value>[^']*)'\s*;")
_VINFO_DOUBLE_RE = re.compile(r'\.\s*(?P<field>type|hash|id)\s*=\s*"(?P<value>[^"]*)"\s*;')
_TRANSLATION_ID_RE = re.compile(r"\btranslationId\s*=\s*(?P<id>\d+)")
_TRANSLATION_TITLE_RE = re.compile(r"""\btranslationTitle\s*=\s*["'](?P<title>[^"']*)["']""")

_PLAYER_JS_PATTERNS = (
    # Current bundle name, e.g. assets/js/app.player_single.<sha256>.js
    re.compile(
        r"""<script\s[^>]*?src=["'](?:https?://[^/"']+)?/(?P<path>assets/js/app\.player_single[^"']+?\.js)["']""",
        re.IGNORECASE,
    ),
    # The fallback bundle some pages list in playerLink.
    re.compile(
        r"""["'](?:https?://[^/"']+)?/(?P<path>assets/js/app\.player[^"']*?\.js)["']""",
        re.IGNORECASE,
    ),
    # Just in case they rename it one day.
    re.compile(
        r"""<script\s[^>]*?src=["'](?:https?://[^/"']+)?/(?P<path>assets/js/[^"']*player[^"']*?\.js)["']""",
        re.IGNORECASE,
    ),
)
# The endpoint address sits in `$.ajax({type:"POST", url:atob("L2Z0b3I="), ...})`.
_AJAX_ATOB_RE = re.compile(r"""url\s*:\s*atob\(\s*["'](?P<encoded>[A-Za-z0-9+/=]{4,})["']""")
_ATOB_RE = re.compile(r"""atob\(\s*["'](?P<encoded>[A-Za-z0-9+/=]{4,})["']""")
_KNOWN_ENDPOINT_RE = re.compile(r"""["'](?P<path>/(?:ftor|gvi|kor|vtt|[a-z]{2,8}))["']""")

_TITLE_RE = re.compile(r"<title>(?P<title>.*?)</title>", re.IGNORECASE | re.DOTALL)
_OG_TITLE_RE = re.compile(
    r"""<meta\s[^>]*property=["']og:title["'][^>]*content=["'](?P<title>[^"']+)["']""",
    re.IGNORECASE,
)
_GENERIC_TITLE_RE = re.compile(r"^(kodik|kodik\s*player|player)$", re.IGNORECASE)

_OPTION_TAG_RE = re.compile(r"<option\b(?P<attrs>[^>]*)>", re.IGNORECASE | re.DOTALL)
_OPTION_ATTR_RE = re.compile(
    r"""(?P<name>[a-z][a-z-]*)\s*=\s*["'](?P<value>[^"']*)["']""", re.IGNORECASE
)


def extract_embed(raw: str) -> EmbedInfo:
    """Accept a bare embed URL, a protocol-relative one or a whole iframe tag."""
    text = html.unescape(raw.strip())
    iframe = _IFRAME_SRC_RE.search(text)
    if iframe:
        text = iframe.group("src").strip()

    if text.startswith("//"):
        text = f"https:{text}"
    if not text.startswith("http"):
        text = f"https://{text.lstrip('/')}"

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
        query=_query_after(text, match.end()),
    )


def _host_of(url: str) -> str:
    parsed = urlparse(url if "://" in url else f"https://{url.lstrip('/')}")
    if parsed.hostname:
        return parsed.hostname.lower()
    return url.split("//", 1)[-1].split("/", 1)[0].split("?", 1)[0].lower()


def _query_after(url: str, position: int) -> str:
    """Keep `?episode=…&season=…` — it decides which episode the page shows."""
    tail = url[position:]
    match = _QUERY_TAIL_RE.match(tail)
    return match.group("query") if match else ""


def extract_payload(page_html: str) -> PlayerPayload | None:
    fields: dict[str, str] = {}
    for pattern in (_VINFO_RE, _VINFO_DOUBLE_RE):
        for match in pattern.finditer(page_html):
            fields.setdefault(match.group("field"), match.group("value").strip())
    try:
        return PlayerPayload(fields["type"], fields["id"], fields["hash"])
    except KeyError:
        return None


def extract_url_params(page_html: str) -> dict[str, str]:
    """Signed request parameters, from the JSON blob or the loose globals."""
    match = _URL_PARAMS_RE.search(page_html)
    if match:
        try:
            parsed = json.loads(match.group("json"))
        except ValueError:
            parsed = None
        if isinstance(parsed, dict):
            return {str(key): str(value) for key, value in parsed.items() if value is not None}

    params: dict[str, str] = {}
    for var in _SIGNED_VAR_RE.finditer(page_html):
        params.setdefault(_VAR_TO_PARAM[var.group("name")], var.group("value"))
    return params


def extract_translations(page_html: str) -> tuple[Translation, ...]:
    """Voice-overs and subtitles offered by the player page, in page order."""
    translations: list[Translation] = []
    seen: set[tuple[str, str, str]] = set()
    for option in _OPTION_TAG_RE.finditer(page_html):
        attrs = {
            match.group("name").lower(): html.unescape(match.group("value")).strip()
            for match in _OPTION_ATTR_RE.finditer(option.group("attrs"))
        }
        media_type = attrs.get("data-media-type", "")
        media_id = attrs.get("data-media-id", "")
        content_hash = attrs.get("data-media-hash", "").lower()
        if not media_type or not media_id or not content_hash:
            continue
        identity = (media_type, media_id, content_hash)
        if identity in seen:
            continue
        seen.add(identity)
        translations.append(
            Translation(
                title=attrs.get("data-title") or media_id,
                media_type=media_type,
                media_id=media_id,
                content_hash=content_hash,
                translation_id=attrs.get("data-id", ""),
                kind=attrs.get("data-translation-type", "voice"),
                selected="selected" in option.group("attrs").lower(),
            )
        )
    return tuple(translations)


def extract_current_translation(
    page_html: str,
    translations: tuple[Translation, ...],
    payload: PlayerPayload | None = None,
) -> Translation | None:
    """Which voice-over the page was opened with."""
    if not translations:
        return None

    for translation in translations:
        if translation.selected:
            return translation

    id_match = _TRANSLATION_ID_RE.search(page_html)
    if id_match:
        wanted = id_match.group("id")
        for translation in translations:
            if translation.translation_id == wanted:
                return translation

    title_match = _TRANSLATION_TITLE_RE.search(page_html)
    if title_match:
        wanted = html.unescape(title_match.group("title")).strip().casefold()
        for translation in translations:
            if translation.title.strip().casefold() == wanted:
                return translation

    if payload is not None:
        for translation in translations:
            if (
                translation.media_id == payload.video_id
                and translation.content_hash == payload.content_hash
            ):
                return translation
    return translations[0]


def extract_player_js_path(page_html: str) -> str:
    path = find_player_js_path(page_html)
    if path is None:
        raise PageStructureError("player script tag not found on page")
    return path


def find_player_js_path(page_html: str) -> str | None:
    for pattern in _PLAYER_JS_PATTERNS:
        match = pattern.search(page_html)
        if match:
            return match.group("path")
    return None


def extract_endpoint(player_js: str) -> str:
    """The video-info endpoint lives in the player bundle behind atob()."""
    ajax = _AJAX_ATOB_RE.search(player_js)
    if ajax:
        decoded = _decode_endpoint(ajax.group("encoded"))
        if decoded:
            return decoded

    found: list[str] = []
    for match in _ATOB_RE.finditer(player_js):
        decoded = _decode_endpoint(match.group("encoded"))
        if decoded:
            found.append(decoded)
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


def _decode_endpoint(encoded: str) -> str | None:
    try:
        endpoint = base64.b64decode(encoded + "=" * (-len(encoded) % 4)).decode("utf-8")
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return None
    if endpoint.startswith("/") and len(endpoint) < 64 and " " not in endpoint:
        return endpoint
    return None


def extract_title(page_html: str) -> str | None:
    match = _TITLE_RE.search(page_html)
    title = match.group("title") if match else ""
    if not title:
        og = _OG_TITLE_RE.search(page_html)
        title = og.group("title") if og else ""
    title = html.unescape(re.sub(r"\s+", " ", title)).strip()
    if not title or _GENERIC_TITLE_RE.match(title):
        return None
    return title


def parse_player_page(page_html: str, embed: EmbedInfo) -> PlayerPage:
    """Turn one fetch of the embed page into the pieces the client needs."""
    payload = extract_payload(page_html)
    url_params = extract_url_params(page_html)
    if payload is None and not url_params:
        raise PageStructureError("page carries no Kodik player data")

    resolved_payload = payload or PlayerPayload(
        embed.media_type, embed.video_id, embed.content_hash
    )
    translations = extract_translations(page_html)
    return PlayerPage(
        payload=resolved_payload,
        player_js_path=find_player_js_path(page_html) or "",
        title=extract_title(page_html),
        url_params=url_params,
        translations=translations,
        current_translation=extract_current_translation(page_html, translations, resolved_payload),
    )
