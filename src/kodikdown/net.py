from __future__ import annotations

import httpx

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
)

DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
}

# The player answers slowly on cold CDN nodes, but a stalled socket should never
# hold the UI for longer than half a minute.
DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=25.0, write=25.0, pool=10.0)

LIMITS = httpx.Limits(max_connections=16, max_keepalive_connections=8, keepalive_expiry=30.0)


def build_client(
    *,
    timeout: httpx.Timeout | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers={**DEFAULT_HEADERS, **(headers or {})},
        timeout=timeout or DEFAULT_TIMEOUT,
        limits=LIMITS,
        follow_redirects=True,
    )
