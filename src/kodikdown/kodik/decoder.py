from __future__ import annotations

import base64
import binascii
import re

_SHIFT_BOUND = 26
# The rotation the player currently uses; verified live in September 2026 and
# tried first so the usual case costs one base64 decode instead of 26.
KNOWN_SHIFT = 18
_URL_PREFIXES = ("https://", "http://", "//")
_HOST_RE = re.compile(r"^(?://|https?://)(?P<host>[^/?#\s]+)")
_HLS_SUFFIX_RE = re.compile(r":hls:manifest\.m3u8$")
_DASH_SUFFIX_RE = re.compile(r":dash:manifest\.mpd$")


def caesar(text: str, shift: int) -> str:
    """Rotate latin letters forward, exactly like the player's JS does."""
    out: list[str] = []
    for char in text:
        if "a" <= char <= "z" or "A" <= char <= "Z":
            base = ord("a") if char.islower() else ord("A")
            out.append(chr(base + (ord(char) - base + shift) % _SHIFT_BOUND))
        else:
            out.append(char)
    return "".join(out)


def _looks_like_url(value: str) -> bool:
    if not value.startswith(_URL_PREFIXES) or " " in value:
        return False
    match = _HOST_RE.match(value)
    if match is None:
        return False
    host = match.group("host").partition(":")[0]
    return "." in host or host == "localhost"


def decode_stream_url(encoded: str, known_shift: int | None = None) -> tuple[str, int] | None:
    """Recover a direct manifest URL from the obfuscated ``src`` field.

    Returns the URL together with the shift that produced it, or ``None`` when
    the value is not an encrypted URL at all.
    """
    text = "".join(encoded.split())
    if not text:
        return None
    if _looks_like_url(text):
        return text, 0
    if len(text) < 8:
        return None

    shifts = [known_shift] if known_shift is not None else []
    shifts.extend(shift for shift in range(_SHIFT_BOUND) if shift != known_shift)
    for shift in shifts:
        rotated = caesar(text, shift)
        rotated += "=" * (-len(rotated) % 4)
        try:
            decoded = base64.b64decode(rotated, validate=False).decode("utf-8")
        except (binascii.Error, ValueError, UnicodeDecodeError):
            continue
        if _looks_like_url(decoded):
            return decoded, shift
    return None


def normalise_url(url: str) -> str:
    return url if url.startswith("http") else f"https:{url}"


def stream_kind(url: str) -> tuple[str, str | None]:
    """Classify a decoded link, plus the plain mp4 hiding behind an HLS one."""
    hls = _HLS_SUFFIX_RE.search(url)
    if hls:
        return "hls", url[: hls.start()]
    if _DASH_SUFFIX_RE.search(url):
        return "dash", None
    lowered = url.split("?", 1)[0].lower()
    if lowered.endswith(".m3u8"):
        return "hls", None
    if lowered.endswith(".mpd"):
        return "dash", None
    if lowered.endswith(".mp4"):
        return "mp4", url
    return "hls", None
