from __future__ import annotations

import base64
import re

_SHIFT_BOUND = 26
_URL_PREFIXES = ("https://", "http://", "//")
_MP4_QUALITY_RE = re.compile(r"(?<!\d)(?P<q>\d{3})\.mp4")


def caesar(text: str, shift: int) -> str:
    chars = []
    for ch in text:
        if "a" <= ch <= "z" or "A" <= ch <= "Z":
            base = ord("a") if ch.islower() else ord("A")
            offset = (ord(ch) - base + _SHIFT_BOUND - shift) % _SHIFT_BOUND
            chars.append(chr(base + offset))
        else:
            chars.append(ch)
    return "".join(chars)


def decode_stream_url(encoded: str) -> str | None:
    """Recover a direct manifest URL from the obfuscated `src` field.

    The player rotates latin letters by an unknown shift and hides the result
    in base64, so we brute-force the shift and keep whatever yields a URL.
    """
    for shift in range(_SHIFT_BOUND):
        padded = caesar(encoded, shift)
        padded += "=" * (-len(padded) % 4)
        try:
            decoded = base64.b64decode(padded).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            continue
        if decoded.startswith(_URL_PREFIXES):
            return decoded if decoded.startswith("http") else f"https:{decoded}"
    return None


def align_quality(url: str, quality: int) -> str:
    """Make sure the requested quality is the one encoded in the path."""
    match = _MP4_QUALITY_RE.search(url)
    if match and match.group("q") != str(quality):
        start, end = match.span("q")
        return f"{url[:start]}{quality}{url[end:]}"
    return url
