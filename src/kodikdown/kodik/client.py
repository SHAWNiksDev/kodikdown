from __future__ import annotations

from typing import Any

import httpx

from kodikdown.kodik.decoder import align_quality, decode_stream_url
from kodikdown.kodik.errors import NoStreamsError, PageStructureError, RequestFailedError
from kodikdown.kodik.models import PlayerPayload, ResolvedVideo, StreamVariant
from kodikdown.kodik.parser import (
    extract_embed,
    extract_endpoint,
    extract_payload,
    extract_player_js_path,
    extract_title,
)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
}


def build_variants(data: dict[str, Any]) -> tuple[StreamVariant, ...]:
    links = data.get("links")
    if not isinstance(links, dict):
        return ()

    variants: list[StreamVariant] = []
    for key, entries in links.items():
        if not isinstance(key, str) or not key.isdigit() or not isinstance(entries, list):
            continue
        quality = int(key)
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            url = decode_stream_url(str(entry.get("src", "")))
            if url:
                variants.append(StreamVariant(quality=quality, url=align_quality(url, quality)))

    variants.sort(key=lambda v: v.quality, reverse=True)
    unique: list[StreamVariant] = []
    for variant in variants:
        if variant.url not in {existing.url for existing in unique}:
            unique.append(variant)
    return tuple(unique)


class KodikClient:
    """Resolves embed URLs into direct stream links without a browser."""

    def __init__(self, http: httpx.AsyncClient | None = None) -> None:
        self._http = http or httpx.AsyncClient(
            headers=DEFAULT_HEADERS,
            timeout=httpx.Timeout(15.0),
            follow_redirects=True,
        )
        self._owns_http = http is None
        self._endpoint_cache: dict[str, str] = {}

    async def __aenter__(self) -> KodikClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()

    async def close(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def resolve(self, raw_url: str) -> ResolvedVideo:
        embed = extract_embed(raw_url)
        html = await self._get_text(embed.page_url)
        payload = extract_payload(html) or PlayerPayload(
            embed.media_type, embed.video_id, embed.content_hash
        )
        title = extract_title(html) or f"kodik-{embed.video_id}"

        data = await self._fetch_links(embed.domain, payload, html)
        variants = build_variants(data)
        if not variants:
            raise NoStreamsError("server response contained no playable streams")
        return ResolvedVideo(title=title, variants=variants)

    async def _fetch_links(
        self,
        domain: str,
        payload: PlayerPayload,
        html: str,
    ) -> dict[str, Any]:
        last_error: Exception | None = None
        for _ in range(2):
            endpoint = await self._endpoint_for(domain, payload, html)
            try:
                response = await self._http.post(
                    f"https://{domain}{endpoint}",
                    data=payload.as_form(),
                    headers={"Referer": f"https://{domain}/", "X-Requested-With": "XMLHttpRequest"},
                )
                response.raise_for_status()
                body = response.json()
            except httpx.HTTPError as exc:
                last_error = exc
                self._endpoint_cache.pop(domain, None)
                continue

            if isinstance(body, dict):
                return body
            raise PageStructureError(f"unexpected video-info reply: {str(body)[:120]!r}")
        raise RequestFailedError(f"video-info request failed: {last_error}") from last_error

    async def _endpoint_for(self, domain: str, payload: PlayerPayload, html: str) -> str:
        cached = self._endpoint_cache.get(domain)
        if cached:
            return cached
        js_path = extract_player_js_path(html)
        player_js = await self._get_text(
            f"https://{domain}/{js_path}", referer=f"https://{domain}/"
        )
        self._endpoint_cache[domain] = extract_endpoint(player_js)
        return self._endpoint_cache[domain]

    async def _get_text(self, url: str, referer: str | None = None) -> str:
        try:
            response = await self._http.get(url, headers={"Referer": referer or url})
            response.raise_for_status()
            return response.text
        except httpx.HTTPStatusError as exc:
            raise RequestFailedError(f"HTTP {exc.response.status_code} for {url}") from exc
        except httpx.HTTPError as exc:
            raise RequestFailedError(f"request to {url} failed: {exc}") from exc
