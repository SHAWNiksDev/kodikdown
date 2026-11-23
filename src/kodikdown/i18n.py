from __future__ import annotations

import locale
import os
from typing import Any

Translations = dict[str, str]

_CATALOG: dict[str, Translations] = {
    "en": {
        "app_title": "KodikDown",
        "url_placeholder": "Paste an anime page or player link",
        "player": "Player",
        "group_series": "Save in a series folder",
        "show_details": "Show description",
        "hide_details": "Hide description",
        "tray_progress": "Downloads in progress ({count})",
        "episodes": "Episodes",
        "episode_number": "Episode {number}",
        "episode_unavailable": "Could not find this episode in the selected player and voice-over",
        "quality_auto": "Original",
        "select_all_episodes": "Select all",
        "clear_episodes": "Clear selection",
        "download_episodes": "Download ({count})",
        "episodes_queued": "Added to queue: {count}.",
        "episodes_skipped": "Already queued or on disk: {count}.",
        "unsupported_players": "Download unavailable from {names}",
        "paste": "Paste",
        "resolve": "Find video",
        "paste_empty": "Clipboard is empty",
        "paste_failed": "Could not read the clipboard",
        "resolving": "Looking up the video…",
        "invalid_url": "This site or player is not supported yet",
        "network_error": "Network or server problem: {detail}",
        "page_changed": "The player page changed — could not read it",
        "no_streams": "The player returned no streams for this video",
        "hint": "Paste an anime page from YummyAnime, AnimeGO, AniLiberty or AniDUB.",
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
        "cli_anime_page": "Use --list-episodes to see the choices, then pass --episode.",
        "cli_unknown_source": "Source {source} is unavailable. See --list-episodes.",
        "cli_unknown_episode": "Episode {episode} is unavailable. See --list-episodes.",
        "cli_needs_anime_page": "Episode options require a supported anime page.",
        "cli_series_translation": "Use --source to select a voice-over from --list-episodes.",
        "cli_download_done": "Saved to {path}",
        "cli_quality_fallback": "Wanted {wanted}p, using {picked}p. Available: {list}",
        "cli_stream_fallback": "Using {quality}p after the previous stream failed.",
        "cli_qualities": "{title}: {list}",
        "cli_translations": "Voice-overs of {title}:",
        "cli_translation_unknown": "No voice-over matches {name}. Available: {list}",
        "cli_translation_missing": "This video has no selectable voice-overs.",
        "cli_cancelled": "Cancelled",
        "cli_print_url": "{url}",
    },
    "ru": {
        "app_title": "KodikDown",
        "url_placeholder": "Вставьте ссылку на аниме или плеер",
        "player": "Плеер",
        "group_series": "В папку сериала",
        "show_details": "Показать описание",
        "hide_details": "Скрыть описание",
        "tray_progress": "Загрузок в очереди ({count})",
        "episodes": "Серии",
        "episode_number": "Серия {number}",
        "episode_unavailable": "Не удалось найти серию с выбранным плеером и озвучкой",
        "quality_auto": "Исходное",
        "select_all_episodes": "Выбрать все",
        "clear_episodes": "Снять выбор",
        "download_episodes": "Скачать ({count})",
        "episodes_queued": "Добавлено в очередь: {count}.",
        "episodes_skipped": "Уже в очереди или на диске: {count}.",
        "unsupported_players": "Скачивание недоступно для {names}",
        "paste": "Вставить",
        "resolve": "Найти видео",
        "paste_empty": "Буфер обмена пуст",
        "paste_failed": "Не удалось прочитать буфер обмена",
        "resolving": "Ищу видео…",
        "invalid_url": "Этот сайт или плеер пока не поддерживается",
        "network_error": "Проблема с сетью или сервером: {detail}",
        "page_changed": "Страница плеера изменилась — не удалось её разобрать",
        "no_streams": "Плеер не отдал ссылки на видео",
        "hint": "Вставьте ссылку на аниме с YummyAnime, AnimeGO, AniLiberty или AniDUB.",
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
        "cli_anime_page": "Список серий — --list-episodes, выбор серии — --episode.",
        "cli_unknown_source": "Источника {source} нет в списке --list-episodes.",
        "cli_unknown_episode": "Серии {episode} нет в выбранном источнике. См. --list-episodes.",
        "cli_needs_anime_page": "Для выбора серий нужна ссылка на страницу аниме.",
        "cli_series_translation": "Для выбора озвучки укажите --source из списка --list-episodes.",
        "cli_download_done": "Сохранено в {path}",
        "cli_quality_fallback": "Запрошено {wanted}p, скачиваю {picked}p. Доступно: {list}",
        "cli_stream_fallback": "Используется {quality}p после ошибки предыдущего потока.",
        "cli_qualities": "{title}: {list}",
        "cli_translations": "Озвучки {title}:",
        "cli_translation_unknown": "Озвучка «{name}» не найдена. Доступно: {list}",
        "cli_translation_missing": "У этого видео нет выбора озвучек.",
        "cli_cancelled": "Отменено",
        "cli_print_url": "{url}",
    },
}


# Shared desktop pages use the same labels and behavior as the Android app.
_CATALOG["en"].update(
    {
        "tab_downloads": "Downloads",
        "tab_library": "Library",
        "tab_history": "History",
        "tab_settings": "Settings",
        "clear_link": "Clear link",
        "settings_saving": "Saving settings…",
        "tray_show": "Open KodikDown",
        "tray_quit": "Quit",
        "settings_appearance": "Appearance",
        "settings_downloads": "Downloads",
        "settings_controls": "Controls",
        "settings_storage": "History and data",
        "about_section": "About",
        "animations": "Animate appearance changes",
        "default_quality": "Default quality",
        "quality_ask": "Choose when looking up a video",
        "auto_paste": "Automatically paste a player link from the clipboard",
        "confirm_cancel_download": "Ask before cancelling a download",
        "confirm_delete": "Ask before deleting videos or records",
        "settings_transfer_locked": (
            "Download settings are locked while looking up, downloading or assembling a video."
        ),
        "settings_saved": "Settings applied",
        "settings_save_failed": "Could not save settings: {detail}",
        "reset_folder": "Default",
        "reset_defaults": "Reset settings",
        "reset_defaults_confirm": "Reset all settings to their defaults?",
        "clear_history": "Clear history",
        "clear_history_confirm": "Clear history? Active downloads and video files will be kept.",
        "history_empty": (
            "Your downloads will appear here. History is kept after you close the app."
        ),
        "library_empty": "No videos in the selected download folder yet.",
        "video_count": "Videos: {count}",
        "history_queued": "Queued",
        "history_downloading": "Downloading",
        "history_assembling": "Assembling",
        "history_finished": "Downloaded",
        "history_failed": "Failed",
        "history_cancelled": "Cancelled",
        "history_interrupted": "Interrupted",
        "available": "Available",
        "status": "Status",
        "file_size": "Size",
        "date": "Date",
        "play": "Watch",
        "download_again": "Download again",
        "copy_link": "Copy original link",
        "link_copied": "Original link copied",
        "original_link_missing": "The original player link is not available for this record.",
        "refresh": "Refresh",
        "delete_file": "Delete video",
        "delete_selected_confirm": "Delete the selected items ({count})? This cannot be undone.",
        "remove_history_confirm": (
            "Remove the selected history records ({count})? Video files will be kept."
        ),
        "delete_failed": "Could not delete video: {detail}",
        "file_deleted": "Video deleted",
        "stop_download": "Stop download",
        "cancel_download_confirm": "Stop downloading “{title}”? Temporary files will be removed.",
        "assembly_protected": "Please wait until the video has finished assembling.",
        "already_downloaded_title": "This video already exists",
        "already_downloaded_message": "“{title}” already exists. Download another copy?",
        "translation_unavailable": (
            "The original voice-over is no longer available. Find "
            "the video again to choose another one."
        ),
        "history_save_failed": "Could not save download history: {detail}",
    }
)
_CATALOG["ru"].update(
    {
        "tab_downloads": "Загрузки",
        "tab_library": "Библиотека",
        "tab_history": "История",
        "tab_settings": "Настройки",
        "clear_link": "Очистить ссылку",
        "settings_saving": "Сохранение настроек…",
        "tray_show": "Открыть KodikDown",
        "tray_quit": "Выйти",
        "settings_appearance": "Внешний вид",
        "settings_downloads": "Загрузка видео",
        "settings_controls": "Управление",
        "settings_storage": "История и данные",
        "about_section": "О приложении",
        "animations": "Анимация смены оформления",
        "default_quality": "Качество по умолчанию",
        "quality_ask": "Выбирать при поиске видео",
        "auto_paste": "Автоматически вставлять ссылку из буфера обмена",
        "confirm_cancel_download": "Спрашивать перед отменой загрузки",
        "confirm_delete": "Подтверждать удаление видео и записей",
        "settings_transfer_locked": (
            "Настройки загрузки недоступны во время поиска, скачивания и сборки видео."
        ),
        "settings_saved": "Настройки применены",
        "settings_save_failed": "Не удалось сохранить настройки: {detail}",
        "reset_folder": "По умолчанию",
        "reset_defaults": "Сбросить настройки",
        "reset_defaults_confirm": "Сбросить все настройки до стандартных значений?",
        "clear_history": "Очистить историю",
        "clear_history_confirm": "Очистить историю? Активные загрузки и файлы видео сохранятся.",
        "history_empty": (
            "Здесь появятся ваши загрузки. История сохраняется после закрытия приложения."
        ),
        "library_empty": "В выбранной папке загрузок пока нет видео.",
        "video_count": "Видео: {count}",
        "history_queued": "В очереди",
        "history_downloading": "Загрузка",
        "history_assembling": "Сборка файла",
        "history_finished": "Скачано",
        "history_failed": "Ошибка",
        "history_cancelled": "Отменено",
        "history_interrupted": "Прервано",
        "available": "Доступно",
        "status": "Состояние",
        "file_size": "Размер",
        "date": "Дата",
        "play": "Смотреть",
        "download_again": "Скачать заново",
        "copy_link": "Скопировать исходную ссылку",
        "link_copied": "Исходная ссылка скопирована",
        "original_link_missing": "Для этой записи исходная ссылка на плеер не сохранилась.",
        "refresh": "Обновить",
        "delete_file": "Удалить видео",
        "delete_selected_confirm": (
            "Удалить выбранные элементы ({count})? Отменить это действие нельзя."
        ),
        "remove_history_confirm": (
            "Убрать выбранные записи из истории ({count})? Видео останутся на диске."
        ),
        "delete_failed": "Не удалось удалить видео: {detail}",
        "file_deleted": "Видео удалено",
        "stop_download": "Остановить загрузку",
        "cancel_download_confirm": (
            "Остановить скачивание «{title}»? Временные файлы будут удалены."
        ),
        "assembly_protected": "Дождитесь окончания сборки видео.",
        "already_downloaded_title": "Это видео уже скачано",
        "already_downloaded_message": "Файл «{title}» уже есть. Скачать ещё одну копию?",
        "translation_unavailable": (
            "Эта озвучка больше недоступна. Найдите видео заново и выберите другую."
        ),
        "history_save_failed": "Не удалось сохранить историю: {detail}",
    }
)

_CATALOG["en"].update(
    {
        "select_download_hint": "Ctrl+click to select finished downloads; right-click for actions.",
        "remove_selected": "Remove selected ({count})",
        "remove_downloads_confirm": (
            "Remove the selected download records ({count})? Video files will be kept."
        ),
    }
)
_CATALOG["ru"].update(
    {
        "select_download_hint": (
            "Ctrl+щелчок — выделить завершённые загрузки; действия — правой кнопкой."
        ),
        "remove_selected": "Убрать выбранные ({count})",
        "remove_downloads_confirm": (
            "Убрать записи выбранных загрузок ({count})? Видео останутся на диске."
        ),
    }
)

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
