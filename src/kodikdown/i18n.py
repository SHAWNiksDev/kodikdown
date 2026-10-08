from __future__ import annotations

import locale
import os
from typing import Any

Translations = dict[str, str]

_CATALOG: dict[str, Translations] = {
    "en": {
        "app_title": "KodikDown",
        "url_placeholder": "Kodik player link or <iframe …>",
        "resolve": "Find video",
        "paste": "Paste",
        "paste_empty": "Clipboard is empty",
        "paste_failed": "Could not read the clipboard",
        "resolving": "Looking up the video…",
        "invalid_url": "Does not look like a Kodik player link",
        "network_error": "Network or server problem: {detail}",
        "page_changed": "Player changed — could not parse the page",
        "no_streams": "No streams found",
        "quality": "Quality",
        "translation": "Voice-over",
        "download": "Download",
        "downloads_section": "Downloads",
        "downloads_empty": "Finished and active downloads will appear here",
        "cancel": "Cancel",
        "cancelling": "Cancelling…",
        "cancelled": "Download cancelled",
        "saved_to": "Done: {path}",
        "failed": "Download failed: {detail}",
        "unexpected_error": "Something went wrong: {detail}",
        "already_downloading": "Already downloading this video",
        "settings_title": "Settings",
        "download_dir": "Download folder",
        "language": "Language",
        "language_auto": "System default",
        "open_folder": "Open folder",
        "folder_missing": "Folder does not exist",
        "folder_not_created": "Could not create the folder: {detail}",
        "folder_open_failed": "Could not open the folder: {detail}",
        "save": "Save",
        "back": "Back",
        "quit": "Quit",
        "settings_saved": "Settings saved",
        "title_unknown": "Untitled",
        "cli_invalid_url": "Could not recognize the player link.",
        "cli_download_done": "Saved to {path}",
        "cli_quality_fallback": "Wanted {wanted}p, using {picked}p. Available: {list}",
        "cli_qualities": "{title}: {list}",
        "cli_translation_unknown": "No voice-over matches {name}. Available: {list}",
        "cli_translation_missing": "This video has no selectable voice-overs.",
    },
    "ru": {
        "app_title": "KodikDown",
        "url_placeholder": "Ссылка на плеер Kodik или <iframe …>",
        "resolve": "Найти видео",
        "paste": "Вставить",
        "paste_empty": "Буфер обмена пуст",
        "paste_failed": "Не удалось прочитать буфер обмена",
        "resolving": "Ищу видео…",
        "invalid_url": "Не похоже на ссылку плеера Kodik",
        "network_error": "Проблема с сетью или сервером: {detail}",
        "page_changed": "Плеер изменился — не удалось разобрать страницу",
        "no_streams": "Ссылки на видео не найдены",
        "quality": "Качество",
        "translation": "Озвучка",
        "download": "Скачать",
        "downloads_section": "Загрузки",
        "downloads_empty": "Здесь появятся активные и завершённые загрузки",
        "cancel": "Отмена",
        "cancelling": "Отменяю…",
        "cancelled": "Загрузка отменена",
        "saved_to": "Готово: {path}",
        "failed": "Ошибка загрузки: {detail}",
        "unexpected_error": "Что-то пошло не так: {detail}",
        "already_downloading": "Это видео уже скачивается",
        "settings_title": "Настройки",
        "download_dir": "Папка загрузок",
        "language": "Язык",
        "language_auto": "Как в системе",
        "open_folder": "Открыть папку",
        "folder_missing": "Папка не существует",
        "folder_not_created": "Не удалось создать папку: {detail}",
        "folder_open_failed": "Не удалось открыть папку: {detail}",
        "save": "Сохранить",
        "back": "Назад",
        "quit": "Выход",
        "settings_saved": "Настройки сохранены",
        "title_unknown": "Без названия",
        "cli_invalid_url": "Не удалось распознать ссылку плеера.",
        "cli_download_done": "Сохранено в {path}",
        "cli_quality_fallback": "Запрошено {wanted}p, скачиваю {picked}p. Доступно: {list}",
        "cli_qualities": "{title}: {list}",
        "cli_translation_unknown": "Озвучка «{name}» не найдена. Доступно: {list}",
        "cli_translation_missing": "У этого видео нет выбора озвучек.",
    },
}

DEFAULT_LANGUAGE = "en"
_current_language = DEFAULT_LANGUAGE


def detect_language() -> str:
    """Best guess at the user's preferred language."""
    for variable in ("LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(variable, "")
        if value.lower().startswith("ru"):
            return "ru"
    try:
        code, _ = locale.getlocale()
    except (TypeError, ValueError):
        code = None
    if code and code.lower().startswith("ru"):
        return "ru"
    return DEFAULT_LANGUAGE


def resolve_language(preference: str) -> str:
    return preference if preference in _CATALOG else detect_language()


def set_language(preference: str) -> str:
    global _current_language
    _current_language = resolve_language(preference)
    return _current_language


def current_language() -> str:
    return _current_language


def t(key: str, **kwargs: Any) -> str:
    catalog = _CATALOG.get(_current_language, _CATALOG[DEFAULT_LANGUAGE])
    template = catalog.get(key) or _CATALOG[DEFAULT_LANGUAGE].get(key, key)
    return template.format(**kwargs) if kwargs else template
