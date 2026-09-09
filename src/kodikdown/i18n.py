from __future__ import annotations

from typing import Any

Translations = dict[str, str]

_CATALOG: Translations = {
    "app_title": "KodikDown",
    "url_placeholder": "Kodik player link or <iframe …>",
    "resolve": "Find video",
    "resolving": "Looking up the video…",
    "invalid_url": "Does not look like a Kodik player link",
    "network_error": "Network or server problem: {detail}",
    "page_changed": "Player changed — could not parse the page",
    "no_streams": "No streams found",
    "quality": "Quality",
    "download": "Download",
    "downloads_section": "Downloads",
    "downloads_empty": "Finished and active downloads will appear here",
    "cancel": "Cancel",
    "cancelling": "Cancelling…",
    "cancelled": "Download cancelled",
    "saved_to": "Done: {path}",
    "failed": "Download failed: {detail}",
    "already_downloading": "Already downloading this video",
    "settings_title": "Settings",
    "download_dir": "Download folder",
    "save": "Save",
    "back": "Back",
    "quit": "Quit",
    "settings_saved": "Settings saved",
    "title_unknown": "Untitled",
    "cli_invalid_url": "Could not recognize the player link.",
    "cli_download_done": "Saved to {path}",
    "cli_quality_unavailable": "Available qualities: {list}",
    "cli_quality_fallback": "Wanted {wanted}p, using {picked}p. Available: {list}",
    "cli_qualities": "{title}: {list}",
}


def t(key: str, **kwargs: Any) -> str:
    template = _CATALOG.get(key, key)
    return template.format(**kwargs) if kwargs else template
