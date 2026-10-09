from __future__ import annotations

import asyncio
import contextlib
from typing import Any

import httpx

from kodikdown.kodik.decoder import (
    KNOWN_SHIFT,
    decode_stream_url,
    normalise_url,
    stream_kind,
)
from kodikdown.kodik.errors import (
    HostUnavailableError,
    NoStreamsError,
    PageStructureError,
    RequestFailedError,
)
from kodikdown.kodik.models import (
    DEFAULT_HOSTS,
    EmbedInfo,
    PlayerPage,
    PlayerPayload,
    ResolvedVideo,
    StreamVariant,
    Translation,
)
from kodikdown.kodik.parser import extract_embed, extract_endpoint, parse_player_page
from kodikdown.net import DEFAULT_TIMEOUT, build_client

# Statuses worth one more try: rate limiting and the transient gateway errors
# Kodik returns when its own backend hiccups.
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
# Links served from this path mean the request was proxied because our IP hit
# the player's rate limit; they usually work, but at a lower speed.
_PROXY_MARKER = "/s/m/"
_TOTAL_TIMEOUT = 90.0
_POST_ATTEMPTS = 3


def _source_rank(entry: dict[str, Any]) -> int:
    """Lower is better: HLS plays everywhere, plain mp4 is a fine fallback."""
    kind = str(entry.get("type", "")).lower()
    if "mpegurl" in kind or "m3u8" in kind:
        return 0
    if "dash" in kind or "mpd" in kind:
        return 1
    if "mp4" in kind or "video" in kind:
        return 2
    return 3


def build_variants(data: dict[str, Any]) -> tuple[StreamVariant, ...]:
    links = data.get("links")
    if not isinstance(links, dict):
        return ()

    variants: list[StreamVariant] = []
    for key, entries in links.items():
        if not isinstance(key, str) or not key.isdigit() or not isinstance(entries, list):
            continue
        quality = int(key)

        best: StreamVariant | None = None
        best_rank = 4
        for entry in entries:
            if not isinstance(entry, dict) or not entry.get("src"):
                continue
            decoded = decode_stream_url(str(entry["src"]), KNOWN_SHIFT)
            if decoded is None:
                continue
            rank = _source_rank(entry)
            if rank >= best_rank:
                continue
            url, _shift = decoded
            url = normalise_url(url)
            kind, direct_mp4 = stream_kind(url)
            best = StreamVariant(
                quality=quality,
                url=url,
                kind=kind,
                direct_mp4=normalise_url(direct_mp4) if direct_mp4 else None,
            )
            best_rank = rank

        if best is not None:
            variants.append(best)

    variants.sort(key=lambda variant: variant.quality, reverse=True)
    unique: list[StreamVariant] = []
    seen: set[int] = set()
    for variant in variants:
        if variant.quality not in seen:
            seen.add(variant.quality)
            unique.append(variant)
    return tuple(unique)


class KodikClient:
    """Resolves embed URLs into direct stream links without a browser."""

    def __init__(
        self,
        http: httpx.AsyncClient | None = None,
        hosts: tuple[str, ...] = DEFAULT_HOSTS,
        timeout: httpx.Timeout | None = None,
    ) -> None:
        self._http = http or build_client(timeout=timeout or DEFAULT_TIMEOUT)
        self._owns_http = http is None
        self._hosts = hosts
        self._endpoint_cache: dict[str, str] = {}
        self._preferred_host: str | None = None

    async def __aenter__(self) -> KodikClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()

    async def close(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    # -- public API --------------------------------------------------------
    async def resolve(
        self,
        raw_url: str,
        translation: Translation | None = None,
    ) -> ResolvedVideo:
        embed = extract_embed(raw_url)
        last_error: Exception | None = None
        for host in self._candidate_hosts(embed.domain):
            try:
                async with asyncio.timeout(_TOTAL_TIMEOUT):
                    resolved = await self._resolve_on(host, embed, translation)
            except (HostUnavailableError, NoStreamsError) as exc:
                last_error = exc
                continue
            self._preferred_host = host
            return resolved

        if last_error is not None:
            raise last_error
        raise RequestFailedError("could not reach any Kodik mirror")

    # -- one host ----------------------------------------------------------
    async def _resolve_on(
        self,
        host: str,
        embed: EmbedInfo,
        translation: Translation | None,
    ) -> ResolvedVideo:
        page = await self._load_page(host, embed)
        payload = translation.as_payload() if translation else page.payload
        data = await self._fetch_links(host, embed, page, payload)

        variants = build_variants(data)
        if not variants:
            raise NoStreamsError("the player returned no playable streams")

        warnings: list[str] = []
        if any(_PROXY_MARKER in variant.url for variant in variants):
            warnings.append("proxy")

        return ResolvedVideo(
            title=page.title or embed.fallback_title,
            variants=variants,
            translations=page.translations,
            translation=translation or page.current_translation,
            default_quality=_as_quality(data.get("default")),
            warnings=tuple(warnings),
        )

    async def _load_page(self, host: str, embed: EmbedInfo) -> PlayerPage:
        url = embed.url_on(host)
        text = await self._get_text(url, referer=f"https://{host}/")
        return parse_player_page(text, embed)

    async def _fetch_links(
        self,
        host: str,
        embed: EmbedInfo,
        page: PlayerPage,
        payload: PlayerPayload,
    ) -> dict[str, Any]:
        """Ask the video-info endpoint, refreshing the signed page if needed.

        Signatures are minted per page view and go stale quickly, so every
        rejected reply is answered by fetching the page again rather than by
        replaying the same request.
        """
        last_body: str = ""
        error = ""
        for attempt in range(_POST_ATTEMPTS):
            endpoint = await self._endpoint_for(host, page)
            body, error = await self._post_links(host, embed, page, payload, endpoint)
            if body is not None:
                return body
            last_body = error
            if attempt + 1 < _POST_ATTEMPTS:
                page = await self._load_page(host, embed)
                await asyncio.sleep(0.4 * (attempt + 1))

        # Last resort: the endpoint also answers plain GETs for old embeds.
        endpoint = await self._endpoint_for(host, page)
        body, error = await self._get_links(host, endpoint, payload)
        if body is not None:
            return body

        detail = error or last_body or "no response"
        raise RequestFailedError(f"video-info request failed: {detail}")

    async def _post_links(
        self,
        host: str,
        embed: EmbedInfo,
        page: PlayerPage,
        payload: PlayerPayload,
        endpoint: str,
    ) -> tuple[dict[str, Any] | None, str]:
        url = f"https://{host}{endpoint}"
        headers = {
            "Referer": embed.url_on(host),
            "Origin": f"https://{host}",
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*; q=0.01",
        }
        try:
            response = await self._http.post(url, data=page.signed_form(payload), headers=headers)
        except httpx.HTTPError as exc:
            return None, f"POST {endpoint} failed: {_transport_reason(exc)}"
        return _parse_reply(response, "POST")

    async def _get_links(
        self,
        host: str,
        endpoint: str,
        payload: PlayerPayload,
    ) -> tuple[dict[str, Any] | None, str]:
        url = f"https://{host}{endpoint}"
        headers = {"Referer": f"https://{host}/", "X-Requested-With": "XMLHttpRequest"}
        try:
            response = await self._http.get(url, params=payload.as_form(), headers=headers)
        except httpx.HTTPError as exc:
            return None, f"GET {endpoint} failed: {_transport_reason(exc)}"
        return _parse_reply(response, "GET")

    async def _endpoint_for(self, host: str, page: PlayerPage) -> str:
        cached = self._endpoint_cache.get(host)
        if not page.player_js_path:
            if cached:
                return cached
            raise PageStructureError("page does not link the player script")

        player_js = await self._get_text(
            f"https://{host}/{page.player_js_path}", referer=f"https://{host}/"
        )
        endpoint = extract_endpoint(player_js)
        self._endpoint_cache[host] = endpoint
        return endpoint

    # -- transport ---------------------------------------------------------
    def _candidate_hosts(self, requested: str) -> list[str]:
        hosts: list[str] = []
        for host in (self._preferred_host, requested, *self._hosts):
            if host and host not in hosts:
                hosts.append(host)
        return hosts

    async def _get_text(self, url: str, referer: str | None = None) -> str:
        response = await self._request("GET", url, headers={"Referer": referer or url})
        if response.status_code in _RETRY_STATUSES:
            await asyncio.sleep(0.5)
            response = await self._request("GET", url, headers={"Referer": referer or url})
        if response.status_code >= 400:
            raise RequestFailedError(f"HTTP {response.status_code} for {url}")
        return response.text

    async def _request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        data: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        attempts: int = 2,
    ) -> httpx.Response:
        last: httpx.HTTPError | None = None
        for attempt in range(attempts):
            try:
                return await self._http.request(
                    method, url, headers=headers, data=data, params=params
                )
            except httpx.HTTPError as exc:
                last = exc
                if attempt + 1 < attempts:
                    await asyncio.sleep(0.5 * (attempt + 1))
        raise HostUnavailableError(f"{method} {url} failed: {_transport_reason(last)}") from last


def _parse_reply(response: httpx.Response, method: str) -> tuple[dict[str, Any] | None, str]:
    if response.status_code >= 400:
        return None, f"{method} returned HTTP {response.status_code}"
    content_type = response.headers.get("content-type", "")
    if "json" not in content_type.lower():
        return None, f"{method} returned {content_type or 'an unknown content type'}"
    try:
        body: Any = response.json()
    except ValueError:
        return None, f"{method} reply is not valid JSON"
    if not isinstance(body, dict):
        return None, f"unexpected video-info reply: {str(body)[:120]!r}"
    if body.get("error"):
        return None, str(body["error"])
    return body, ""


def _transport_reason(exc: httpx.HTTPError | None) -> str:
    if exc is None:
        return "unknown error"
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
        return f"connection failed ({exc})"
    if isinstance(exc, (httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout)):
        return "server stopped responding"
    return str(exc) or exc.__class__.__name__


def _as_quality(value: Any) -> int | None:
    with contextlib.suppress(TypeError, ValueError):
        return int(value)
    return None
