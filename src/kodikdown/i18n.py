from __future__ import annotations

import locale
import os
from typing import Any

Translations = dict[str, str]

_CATALOG: dict[str, Translations] = {
    "en": {
        "app_title": "KodikDown",
        "url_placeholder": "Paste a Kodik player link or the whole <iframe> tag",
        "paste": "Paste",
        "resolve": "Find video",
        "paste_empty": "Clipboard is empty",
        "paste_failed": "Could not read the clipboard",
        "resolving": "Looking up the video…",
        "invalid_url": "That does not look like a Kodik player link",
        "network_error": "Network or server problem: {detail}",
        "page_changed": "The player page changed — could not read it",
        "no_streams": "The player returned no streams for this video",
        "hint": (
            "Any mirror works: kodikplayer.com, kodik.info, … "
            "Links with ?episode= and ?season= keep their episode."
        ),
        "title_unknown": "Untitled",
        "file_name": "File name",
        "quality": "Quality",
        "best_badge": "best",
        "translation": "Voice-over",
        "download": "Download",
        "download_mp4": "Download as MP4",
        "warning_proxy": (
            "The CDN rate-limited this connection and served a proxy link — it works, but slower."
        ),
        "downloads_section": "Downloads",
        "downloads_empty": "Active and finished downloads appear here",
        "cancel": "Cancel",
        "cancelling": "Cancelling…",
        "cancelled": "Download cancelled",
        "saved_to": "Saved to {path}",
        "open_file": "Open",
        "open_folder": "Open folder",
        "remove": "Remove",
        "clear_finished": "Clear finished",
        "failed": "Download failed: {detail}",
        "unexpected_error": "Something went wrong: {detail}",
        "already_downloading": "This video is already downloading",
        "queued": "Waiting for a free slot…",
        "starting": "Starting…",
        "link_required": "Paste a player link first",
        "stage_processing": "Assembling…",
        "stage_finished": "Finishing…",
        "eta": "left {time}",
        "settings_title": "Settings",
        "download_dir": "Download folder",
        "browse": "Browse…",
        "language": "Language",
        "language_auto": "System default",
        "theme": "Theme",
        "theme_auto": "Match system",
        "theme_light": "Light",
        "theme_dark": "Dark",
        "toggle_theme": "Switch theme",
        "concurrent_downloads": "Simultaneous downloads",
        "prefer_mp4": "Prefer plain MP4 files",
        "prefer_mp4_hint": "Skips HLS assembling when the CDN offers a direct file.",
        "save": "Save",
        "close": "Close",
        "settings_saved": "Settings saved",
        "quit_with_downloads": "There are {count} unfinished downloads. Quit and cancel them?",
        "folder_missing": "Folder does not exist",
        "folder_not_created": "Could not create the folder: {detail}",
        "folder_open_failed": "Could not open the folder: {detail}",
        "file_missing": "The file is gone",
        "settings_path": "Settings file: {path}",
        "cli_invalid_url": "Could not recognize the player link.",
        "cli_download_done": "Saved to {path}",
        "cli_quality_fallback": "Wanted {wanted}p, using {picked}p. Available: {list}",
        "cli_qualities": "{title}: {list}",
        "cli_translations": "Voice-overs of {title}:",
        "cli_translation_unknown": "No voice-over matches {name}. Available: {list}",
        "cli_translation_missing": "This video has no selectable voice-overs.",
        "cli_cancelled": "Cancelled",
        "cli_print_url": "{url}",
    },
    "ru": {
        "app_title": "KodikDown",
        "url_placeholder": "Вставьте ссылку на плеер Kodik или тег <iframe> целиком",
        "paste": "Вставить",
        "resolve": "Найти видео",
        "paste_empty": "Буфер обмена пуст",
        "paste_failed": "Не удалось прочитать буфер обмена",
        "resolving": "Ищу видео…",
        "invalid_url": "Не похоже на ссылку плеера Kodik",
        "network_error": "Проблема с сетью или сервером: {detail}",
        "page_changed": "Страница плеера изменилась — не удалось её разобрать",
        "no_streams": "Плеер не отдал ссылки на видео",
        "hint": (
            "Подходит любое зеркало: kodikplayer.com, kodik.info, … "
            "Параметры ?episode= и ?season= сохраняются."
        ),
        "title_unknown": "Без названия",
        "file_name": "Имя файла",
        "quality": "Качество",
        "best_badge": "лучшее",
        "translation": "Озвучка",
        "download": "Скачать",
        "download_mp4": "Скачать как MP4",
        "warning_proxy": (
            "CDN ограничил скорость и выдал прокси-ссылку — она работает, но медленнее."
        ),
        "downloads_section": "Загрузки",
        "downloads_empty": "Здесь появятся активные и завершённые загрузки",
        "cancel": "Отмена",
        "cancelling": "Отменяю…",
        "cancelled": "Загрузка отменена",
        "saved_to": "Сохранено в {path}",
        "open_file": "Открыть",
        "open_folder": "Открыть папку",
        "remove": "Убрать",
        "clear_finished": "Очистить завершённые",
        "failed": "Ошибка загрузки: {detail}",
        "unexpected_error": "Что-то пошло не так: {detail}",
        "already_downloading": "Это видео уже скачивается",
        "queued": "Ожидает свободного слота…",
        "starting": "Начинаю…",
        "link_required": "Сначала вставьте ссылку на плеер",
        "stage_processing": "Собираю файл…",
        "stage_finished": "Завершаю…",
        "eta": "осталось {time}",
        "settings_title": "Настройки",
        "download_dir": "Папка загрузок",
        "browse": "Выбрать…",
        "language": "Язык",
        "language_auto": "Как в системе",
        "theme": "Тема",
        "theme_auto": "Как в системе",
        "theme_light": "Светлая",
        "theme_dark": "Тёмная",
        "toggle_theme": "Переключить тему",
        "concurrent_downloads": "Одновременных загрузок",
        "prefer_mp4": "Скачивать обычные MP4",
        "prefer_mp4_hint": "Без сборки HLS, если CDN отдаёт готовый файл.",
        "save": "Сохранить",
        "close": "Закрыть",
        "settings_saved": "Настройки сохранены",
        "quit_with_downloads": "Осталось незавершённых загрузок: {count}. Выйти и отменить их?",
        "folder_missing": "Папка не существует",
        "folder_not_created": "Не удалось создать папку: {detail}",
        "folder_open_failed": "Не удалось открыть папку: {detail}",
        "file_missing": "Файл не найден",
        "settings_path": "Файл настроек: {path}",
        "cli_invalid_url": "Не удалось распознать ссылку плеера.",
        "cli_download_done": "Сохранено в {path}",
        "cli_quality_fallback": "Запрошено {wanted}p, скачиваю {picked}p. Доступно: {list}",
        "cli_qualities": "{title}: {list}",
        "cli_translations": "Озвучки {title}:",
        "cli_translation_unknown": "Озвучка «{name}» не найдена. Доступно: {list}",
        "cli_translation_missing": "У этого видео нет выбора озвучек.",
        "cli_cancelled": "Отменено",
        "cli_print_url": "{url}",
    },
}

# Language names are intentionally in their own language.
LANGUAGE_NAMES = {"en": "English", "ru": "Русский"}

DEFAULT_LANGUAGE = "en"
_current_language = DEFAULT_LANGUAGE


def detect_language() -> str:
    """Best guess at the user's preferred language."""
    for variable in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
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
