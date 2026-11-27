"""Find episodes on supported sites and pass their streams to the downloader."""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, replace
from decimal import Decimal
from html.parser import HTMLParser
from itertools import pairwise
from typing import Any
from urllib.parse import parse_qs, unquote, urlencode, urljoin, urlsplit, urlunsplit

import httpx
from anime_dl_core import CvhPlayer, extract_async, supports
from anime_dl_core.errors import AnimeDlCoreError, NetworkError, ServiceError

from kodikdown.kodik.client import KodikClient
from kodikdown.kodik.errors import (
    InvalidUrlError,
    NoStreamsError,
    PageStructureError,
    RequestFailedError,
)
from kodikdown.kodik.models import ResolvedVideo, StreamVariant, Translation
from kodikdown.kodik.parser import extract_title
from kodikdown.net import build_client

YUMMY_API = "https://api.yani.tv"
LIBRIA_ORIGIN = "https://aniliberty.top/"
LIBRIA_API = urljoin(LIBRIA_ORIGIN, "api/v1")
GO_HEADERS = {"X-Requested-With": "XMLHttpRequest"}
YUMMY_HOSTS = {"yani.tv", "yummyani.me", "yummy-anime.ru"}
GO_HOSTS = {"animego.org", "animego.me"}
LIBRIA_HOSTS = {"aniliberty.top", "anilibria.top", "anilibria.app"}
DUB_HOSTS = {"anidub.com", "anidub.life", "anidub.digital", "anidub.pro"}
WEB_PLAYERS = {"aniboom", "cvh", "sibnet", "animedia", "vk"}
NUMBER = re.compile(r"\d{1,6}(?:\.\d{1,4})?")
URL = re.compile(r"""(?:https?:)?//[^\s"'<>\])]+""", re.IGNORECASE)
CVH_STATS_ID = re.compile(r"^United video id:[ \t]*([0-9]{1,24})[ \t]*\r?$", re.I | re.M)
CVH_FRAME = re.compile(r"^URL:[ \t]*https://player\.cdnvideohub\.com/", re.I | re.M)


@dataclass(frozen=True)
class Episode:
    number: str
    url: str
    source: str = "player"
    referer: str | None = None


@dataclass(frozen=True)
class Choice:
    player: str
    voice: str
    episodes: tuple[Episode, ...]


@dataclass(frozen=True)
class Series:
    url: str
    title: str
    choices: tuple[Choice, ...]
    unavailable: tuple[str, ...] = ()
    description: str = ""
    poster_url: str = ""
    poster: bytes = b""


@dataclass(frozen=True)
class EpisodeRequest:
    number: str
    player: str
    voice: str

    def link(self, series_url: str) -> str:
        fragment = urlencode(
            {"kd_episode": self.number, "player": self.player, "voice": self.voice}
        )
        return urlunsplit(urlsplit(series_url)._replace(fragment=fragment))

    @classmethod
    def from_url(cls, url: str) -> EpisodeRequest | None:
        fields = parse_qs(urlsplit(web_url(url)).fragment, keep_blank_values=True)
        if fields.get("kd_episode") and fields.get("player"):
            return cls(fields["kd_episode"][0], fields["player"][0], fields.get("voice", [""])[0])
        return None


def web_url(raw: str) -> str:
    raw = html.unescape(raw.strip())
    video = CVH_STATS_ID.search(raw)
    if video and CVH_FRAME.search(raw):
        return f"https://plapi.cdnvideohub.com/api/v1/player/sv/video/{video[1]}"
    iframe = re.search(r"""<iframe\b[^>]*?\bsrc\s*=\s*(["'])(.*?)\1""", raw, re.I)
    match = URL.search(iframe[2] if iframe else raw)
    url = match[0] if match else raw
    if url.startswith("//"):
        url = "https:" + url
    elif not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    try:
        parsed = urlsplit(url)
        if not parsed.hostname or parsed.username or parsed.password:
            return ""
    except ValueError:
        return ""
    return url


def public_source(raw: str) -> str:
    url = web_url(raw)
    if EpisodeRequest.from_url(url) is not None:
        return urlunsplit(urlsplit(url)._replace(fragment=""))
    return url


def _site(url: str) -> tuple[str, str] | None:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    path = parsed.path.rstrip("/")
    for domain in YUMMY_HOSTS:
        if host == domain or host.endswith("." + domain):
            match = re.fullmatch(r"/(?:catalog/item/|anime/)([\w-]+)", path)
            if match:
                return "yummy", match[1]
    if host.removeprefix("www.") in GO_HOSTS:
        match = re.fullmatch(r"/anime/([\w-]+)-(\d+)", path)
        if match:
            return "go", match[2]
    if host.removeprefix("www.") in LIBRIA_HOSTS:
        match = re.fullmatch(r"/(?:anime/releases/(?:release/)?|release/)([\w-]+)(?:\.html)?", path)
        if match:
            return "libria", match[1]
    if re.fullmatch(r"/(?:[\w-]+/)*\d+-[\w-]+\.html", path) and any(
        host == domain or host.endswith("." + domain) for domain in DUB_HOSTS
    ):
        return "dub", ""
    return None


def _player_kind(url: str) -> str | None:
    parsed = urlsplit(url)
    path = parsed.path.casefold()
    if path.endswith((".mp4", ".m3u8", ".mpd")):
        return path.rsplit(".", 1)[1]
    if path.endswith("/iframecvh.html") and _is_yummy_host(parsed.hostname or ""):
        return "cvh"
    kind = supports(url)
    return kind if kind in WEB_PLAYERS or kind == "kodik" else None


def _is_yummy_host(host: str) -> bool:
    return any(host == domain or host.endswith("." + domain) for domain in YUMMY_HOSTS)


def recognized_link(raw: str) -> bool:
    url = web_url(raw)
    return bool(url and (_site(url) or _player_kind(url)))


def _episode_number(value: Any) -> str | None:
    number = str(value)
    if NUMBER.fullmatch(number):
        return str(Decimal(number)).rstrip("0").rstrip(".") if "." in number else str(int(number))
    return None


def _choices(options: dict[tuple[str, str], dict[str, Episode]]) -> tuple[Choice, ...]:
    return tuple(
        Choice(
            player, voice, tuple(sorted(entries.values(), key=lambda item: Decimal(item.number)))
        )
        for (player, voice), entries in options.items()
    )


class GoPlayerPage(HTMLParser):
    def __init__(self, document: str, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.episodes: dict[str, Episode] = {}
        self.links: dict[tuple[str, str], str] = {}
        self.pages: list[int] = []
        self.feed(document)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_map = dict(attrs)
        if pages := attrs_map.get("data-anime-player-episodes-pages-value"):
            metadata = json.loads(pages)
            self.pages = [entry["page"] for entry in metadata if 0 < entry["page"] <= 100]
        number = _episode_number(attrs_map.get("data-episode-number"))
        identifier = attrs_map.get("data-episode") or ""
        if number is not None and identifier.isascii() and identifier.isdecimal():
            url = urljoin(self.base_url, f"/player/videos/{identifier}")
            self.episodes[number] = Episode(number, url, source="go")

        embed = attrs_map.get("data-player")
        player = attrs_map.get("data-provider-title")
        voice = attrs_map.get("data-translation-title")
        if tag == "button" and embed and player and voice:
            key = player.strip(), voice.removesuffix(" (ошибка)").strip()
            self.links.setdefault(key, urljoin(self.base_url, embed))


class PageDetails(HTMLParser):
    def __init__(self, document: str) -> None:
        super().__init__()
        self.values: dict[str, str] = {}
        self.feed(document)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "meta":
            fields = dict(attrs)
            key = fields.get("property") or fields.get("name")
            content = fields.get("content")
            if key and content:
                self.values.setdefault(key, content)

    def series(
        self,
        url: str,
        fallback: str,
        choices: tuple[Choice, ...],
        unavailable: tuple[str, ...] = (),
    ) -> Series:
        title = self.values.get("og:title") or fallback
        description = self.values.get("og:description") or self.values.get("description", "")
        poster = self.values.get("og:image", "")
        return Series(
            url,
            title,
            choices,
            unavailable,
            description=description,
            poster_url=urljoin(url, poster) if poster else "",
        )


class DubPlayerPage(HTMLParser):
    def __init__(self, document: str) -> None:
        super().__init__(convert_charrefs=True)
        self.frames: list[str] = []
        self.episode_paths: list[str] = []
        self.manifest: str | None = None
        self._inside_playlist = False
        self.feed(document)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        fields = dict(attrs)
        if tag == "iframe" and (src := fields.get("src")):
            self.frames.append(src)
        elif tag == "select":
            self._inside_playlist = fields.get("id") == "episode-select"
        elif tag == "option" and self._inside_playlist:
            if (value := fields.get("value")) and re.fullmatch(r"/s\d+/[\da-f]{24,64}", value):
                self.episode_paths.append(value)
        elif tag == "video" and fields.get("id") == "hls-video":
            self.manifest = fields.get("data-stream-src") or self.manifest
        elif tag == "source" and fields.get("id") == "vsource" and self.manifest is None:
            self.manifest = fields.get("src")

    def handle_endtag(self, tag: str) -> None:
        if tag == "select":
            self._inside_playlist = False


class MediaClient:
    def __init__(self, http: httpx.AsyncClient | None = None) -> None:
        self.http = http if http is not None else build_client()
        self.owns_http = http is None
        self.kodik = KodikClient(http=self.http)

    async def __aenter__(self) -> MediaClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()

    async def close(self) -> None:
        if self.owns_http:
            await self.http.aclose()

    async def _get(self, url: str, *, headers: dict[str, str] | None = None) -> httpx.Response:
        try:
            response = await self.http.get(url, headers=headers)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            host = exc.request.url.host
            raise RequestFailedError(f"{host}: HTTP {exc.response.status_code}") from exc
        except httpx.RequestError as exc:
            raise RequestFailedError(exc.request.url.host) from exc
        return response

    async def _json(self, url: str, *, headers: dict[str, str] | None = None) -> Any:
        response = await self._get(url, headers=headers)
        try:
            return response.json()
        except ValueError as exc:
            raise PageStructureError(response.url.host) from exc

    async def lookup(
        self, raw: str, translation: Translation | None = None, *, include_poster: bool = True
    ) -> Series | ResolvedVideo:
        url = web_url(raw)
        site = _site(url)
        if site is None:
            return await self.resolve_player(raw, translation)
        series = await self.catalog(url, *site)
        request = EpisodeRequest.from_url(url)
        if request is None:
            if include_poster and series.poster_url:
                series = replace(series, poster=await self._poster(series.poster_url))
            return series
        for choice in series.choices:
            if (choice.player, choice.voice) == (request.player, request.voice):
                for episode in choice.episodes:
                    if episode.number == request.number:
                        return await self.resolve_episode(series.title, choice, episode)
        raise NoStreamsError()

    async def _poster(self, url: str) -> bytes:
        if not url.startswith("https://"):
            return b""
        try:
            async with self.http.stream("GET", url, timeout=4) as response:
                kind = response.headers.get("content-type", "")
                if not response.is_success or not kind.startswith("image/"):
                    return b""
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > 512_000:
                        return b""
                return bytes(body)
        except httpx.HTTPError:
            return b""

    async def catalog(self, url: str, site: str, slug: str) -> Series:
        clean_url = urlunsplit(urlsplit(url)._replace(fragment=""))
        try:
            if site == "yummy":
                series = await self._yummy(clean_url, slug)
            elif site == "go":
                series = await self._animego(clean_url, slug)
            elif site == "dub":
                series = await self._anidub(clean_url)
            else:
                series = await self._libria(clean_url, slug)
        except (KeyError, TypeError, AttributeError, ValueError) as exc:
            raise PageStructureError() from exc
        if not series.choices:
            raise NoStreamsError()
        return series

    async def _yummy(self, url: str, slug: str) -> Series:
        info = (await self._json(f"{YUMMY_API}/anime/{slug}"))["response"]
        entries = (await self._json(f"{YUMMY_API}/anime/{int(info['anime_id'])}/videos"))[
            "response"
        ]
        options: dict[tuple[str, str], dict[str, Episode]] = {}
        unavailable: set[str] = set()
        for entry in entries:
            data = entry.get("data") or {}
            player = str(data.get("player") or "").removeprefix("Плеер ").strip()
            voice = str(data.get("dubbing") or "").removeprefix("Озвучка ").strip()
            number = _episode_number(entry.get("number"))
            embed = entry.get("iframe_url")
            if not player or not isinstance(embed, str) or number is None:
                continue
            link = urljoin(url, embed)
            if not _player_kind(link):
                unavailable.add(player)
                continue
            options.setdefault((player, voice), {}).setdefault(number, Episode(number, link))
        poster = (info.get("poster") or {}).get("medium", "")
        return Series(
            url,
            info["title"],
            _choices(options),
            tuple(sorted(unavailable)),
            description=info.get("description") or "",
            poster_url=urljoin(url, poster) if poster else "",
        )

    async def _go_player(self, url: str) -> GoPlayerPage:
        response = await self._json(url, headers=GO_HEADERS)
        try:
            return GoPlayerPage(response["data"]["content"], url)
        except (KeyError, TypeError) as exc:
            raise PageStructureError() from exc

    async def _animego(self, url: str, identifier: str) -> Series:
        response = await self._get(url)
        base = str(response.url)
        page_url = urljoin(base, f"/player/{identifier}")
        page = await self._go_player(page_url)
        for number in sorted(set(page.pages)):
            extra = await self._go_player(f"{page_url}/episodes?page={number}")
            page.episodes.update(extra.episodes)
        title = extract_title(response.text) or urlsplit(url).path.rsplit("/", 1)[-1]
        options: dict[tuple[str, str], dict[str, Episode]] = {}
        unavailable: set[str] = set()
        first = min(page.episodes, key=Decimal, default="1")
        for key, embed in page.links.items():
            if _player_kind(embed):
                options[key] = page.episodes | {first: Episode(first, embed)}
            else:
                unavailable.add(key[0])
        return PageDetails(response.text).series(
            base, title, _choices(options), tuple(sorted(unavailable))
        )

    async def _anidub(self, url: str) -> Series:
        page = await self._get(url)
        title_url = str(page.url)
        title = extract_title(page.text) or urlsplit(url).path.rsplit("/", 1)[-1]
        for embed in DubPlayerPage(page.text).frames:
            player_url = urljoin(title_url, embed)
            host = urlsplit(player_url).hostname or ""
            if not re.fullmatch(r"player\d+\.ladonyvesna2005\.info", host):
                continue
            response = await self._get(player_url, headers={"Referer": title_url})
            player = DubPlayerPage(response.text)
            if not player.manifest:
                continue
            referer = str(response.url)
            manifest = urlsplit(urljoin(referer, player.manifest))
            params = parse_qs(manifest.query, keep_blank_values=True)
            paths = player.episode_paths or params.get("v", [])
            if (
                not paths
                or not manifest.path.endswith("/vid.php")
                or not re.fullmatch(r"player\d+\.ladonyvesna2005\.info", manifest.hostname or "")
            ):
                continue
            episodes = []
            for number, path in enumerate(paths, start=1):
                query = urlencode(params | {"v": [path]}, doseq=True)
                stream = urlunsplit(manifest._replace(query=query))
                episodes.append(Episode(str(number), stream, "dub", referer))
            return PageDetails(page.text).series(
                title_url, title, (Choice("AniDUB", "AniDUB", tuple(episodes)),)
            )
        raise NoStreamsError()

    async def _libria(self, url: str, slug: str) -> Series:
        release = await self._json(f"{LIBRIA_API}/anime/releases/{slug}")
        title = release["name"].get("main") or release["alias"]
        episodes: dict[str, Episode] = {}
        for entry in release["episodes"]:
            number = _episode_number(entry.get("ordinal"))
            episode_id = str(entry.get("id", ""))
            if (
                number is not None
                and re.fullmatch(r"[\da-f-]{36}", episode_id, re.I)
                and _libria_variants(entry)
            ):
                episode_url = f"{LIBRIA_API}/anime/releases/episodes/{episode_id}"
                episodes[number] = Episode(number, episode_url, source="libria")
        poster = (release.get("poster") or {}).get("src", "")
        return Series(
            url,
            title,
            _choices({("AniLiberty", "AniLiberty"): episodes}) if episodes else (),
            description=release.get("description") or "",
            poster_url=urljoin(LIBRIA_ORIGIN, poster) if poster else "",
        )

    async def resolve_episode(self, title: str, choice: Choice, episode: Episode) -> ResolvedVideo:
        url = episode.url
        if episode.source == "libria":
            variants = _libria_variants(await self._json(url))
            if not variants:
                raise NoStreamsError()
            return ResolvedVideo(title, variants)
        if episode.source == "dub":
            return await self._hls(title, url, episode.referer)
        if episode.source == "go":
            page = await self._go_player(url)
            url = page.links.get((choice.player, choice.voice), "")
            if not url:
                raise NoStreamsError()
        return await self.resolve_player(url)

    async def _hls(self, title: str, url: str, referer: str | None) -> ResolvedVideo:
        response = await self._get(url, headers={"Referer": referer} if referer else None)
        if not response.text.startswith("#EXTM3U"):
            raise NoStreamsError()
        variants: dict[int, StreamVariant] = {}
        lines = [line.strip() for line in response.text.splitlines() if line.strip()]
        for line, stream in pairwise(lines):
            if not line.startswith("#EXT-X-STREAM-INF:") or stream.startswith("#"):
                continue
            match = re.search(r"\bRESOLUTION=\d+x(\d+)", line)
            if match and "AUDIO=" not in line:
                quality = int(match[1])
                link = urljoin(str(response.url), stream)
                variants[quality] = StreamVariant(quality, link, referer=referer)
        if not variants:
            return ResolvedVideo(title, (StreamVariant(0, url, referer=referer),))
        return ResolvedVideo(title, tuple(variants[key] for key in sorted(variants, reverse=True)))

    async def resolve_player(
        self, raw: str, translation: Translation | None = None
    ) -> ResolvedVideo:
        url = web_url(raw)
        kind = _player_kind(url) if url else None
        if kind in {"mp4", "m3u8", "mpd"}:
            path = urlsplit(url).path
            name = unquote(path.rsplit("/", 1)[-1].rsplit(".", 1)[0])
            return ResolvedVideo(name or None, (StreamVariant(0, url, kind),))
        if kind not in WEB_PLAYERS:
            return await self.kodik.resolve(raw, translation)

        try:
            parsed = urlsplit(url)
            if kind == "cvh" and parsed.path.casefold().endswith("/iframecvh.html"):
                params = parse_qs(parsed.query)
                identifier = params.get("anime_id", [""])[0]
                number = params.get("episode", ["1"])[0]
                voice = params.get("dubbing", [""])[0].removeprefix("Озвучка ")
                if not identifier.isascii() or not identifier.isdecimal() or not number.isdecimal():
                    raise InvalidUrlError()
                async with CvhPlayer(timeout=12, pub="745") as player:
                    result = await player.aextract(
                        identifier, episode=int(number), studio=voice or None
                    )
                    if voice and _voice_key(result.translation or "") != _voice_key(voice):
                        raise NoStreamsError()
            else:
                result = await extract_async(url, timeout=12)
        except NetworkError as exc:
            raise RequestFailedError(parsed.hostname or kind) from exc
        except ServiceError as exc:
            detail = f": HTTP {exc.status}" if exc.status else ""
            raise RequestFailedError((parsed.hostname or kind) + detail) from exc
        except AnimeDlCoreError as exc:
            raise NoStreamsError() from exc
        variants = _stream_variants(result.streams)
        if not variants:
            raise NoStreamsError()
        return ResolvedVideo(result.title, variants)


def _voice_key(name: str) -> str:
    return "".join(character for character in name.casefold() if character.isalnum())


def _libria_variants(entry: Any) -> tuple[StreamVariant, ...]:
    if not isinstance(entry, dict):
        raise PageStructureError()
    return tuple(
        StreamVariant(height, link, referer=LIBRIA_ORIGIN)
        for height in (1080, 720, 480)
        if isinstance(link := entry.get(f"hls_{height}"), str) and link.startswith("https://")
    )


def _stream_variants(streams: Any) -> tuple[StreamVariant, ...]:
    by_quality: dict[int, dict[str, Any]] = {}
    for stream in streams:
        if not stream.audio_url and stream.url.startswith(("https://", "http://")):
            by_quality.setdefault(stream.quality or 0, {}).setdefault(str(stream.kind), stream)
    if any(by_quality):
        by_quality.pop(0, None)
    variants = []
    for quality, formats in sorted(by_quality.items(), reverse=True):
        mp4 = formats.get("mp4")
        stream = formats.get("hls") or mp4 or formats.get("dash")
        if stream is None:
            continue
        variants.append(
            StreamVariant(
                quality,
                stream.url,
                str(stream.kind),
                mp4.url if mp4 is not None and mp4 is not stream else None,
                stream.headers.get("Referer"),
                mp4.headers.get("Referer") if mp4 is not None else None,
            )
        )
    return tuple(variants)
