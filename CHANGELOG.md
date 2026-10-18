# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.5.0] - 2026-10-18

### English

#### Added
- Native Android app (Kotlin / Material 3) with background downloading via Foreground Service and Partial WakeLock
- Android Video Library tab for browsing, playing, and sharing downloaded episodes directly via system MediaStore
- Download History tab tracking all initiated downloads, statuses, and file sizes with duplicate prevention dialogs
- Automatic quality fallback: dynamically switches to 480p/360p if requested 720p manifests return HTTP 404/403 from the CDN
- 1 MB socket buffer and parallel fragment downloads for maximum streaming throughput
- CLI `--filename` (`-n`) flag and direct URL argument handling for instant GUI lookup
- Hotkeys in desktop GUI (`Ctrl+S` for settings, `Ctrl+Q` to quit)

#### Changed
- Optimized Android RecyclerView animations to eliminate live download card flicker
- Android library cards now inspect actual video track dimensions via MediaStore for accurate resolution badges
- Parser now strips markdown syntax and surrounding text from messy copied URLs and iframes
- Updated build and CI workflows to package and publish the Android APK

#### Fixed
- Fixed clipboard paste issues on Android when handling plain-text intents
- Fixed download card status persisting on "Finishing…" instead of displaying "Downloaded"
- Prevented accidental duplicate downloads with an interactive confirmation prompt
- Fixed Scoped Storage permission issues when launching external video players
- Auto-creation of missing download directories in desktop settings

---

### Русский

#### Добавлено
- Нативное Android-приложение (Kotlin, Material 3) с фоновой загрузкой через Foreground Service и Partial WakeLock
- Вкладка «Библиотека» на Android для просмотра, воспроизведения и шеринга скачанных серий через системный MediaStore
- Вкладка «История» со всеми прошлыми загрузками, фильтрацией статусов и предупреждением при повторном скачивании
- Автоматический фоллбэк качества: при ошибках 404/403 на 720p загрузчик на лету переключается на рабочие 480p/360p
- Увеличенный буфер сокетов (1 МБ) и многопоточная загрузка чанков для максимальной скорости
- Аргумент `--filename` (`-n`) в CLI и запуск GUI с прямой ссылкой в параметрах
- Горячие клавиши в десктопной версии: `Ctrl+S` (настройки) и `Ctrl+Q` (выход)

#### Изменено
- Отключена лишняя анимация RecyclerView в Android, устранив наложение текста при обновлении прогресса
- Определение реального разрешения видео в «Библиотеке» через MediaStore Video Heights вместо статических данных
- Парсер ссылок теперь надежно очищает скопированный текст от Markdown-разметки и лишних символов
- GitHub Actions и релизный скрипт обновлены для автоматической публикации Android APK

#### Исправлено
- Исправлена работа кнопки «Вставить» из системного буфера обмена на Android
- Исправлено зависание бейджа со статусом «Завершаю…» после успешной сборки файла (теперь корректно «Скачано»)
- Устранена ошибка повторного скачивания одного и того же видео без предупреждения
- Исправлено открытие видео во внешних плеерах через FileProvider / Scoped Storage
- Автоматическое создание целевой папки загрузок в десктопной версии при сохранении настроек

## [3.0.1] - 2026-10-11

### English

#### Added
- Smooth crossfade animation when toggling themes
- Spinning micro-interaction on theme and settings buttons
- Modernized progress bar with gradient fill and glowing wave effect in busy mode
- Visual status indicators (check, warning, close) with fade-in animation on download rows
- Icons on action buttons (paste, resolve, download, open folder, clear, settings dialog)
- Branded app icon in the window header
- Live download progress indicator in CLI

#### Fixed
- Mirror fallback now catches HTTP 403, 404, 500 and timeout errors instead of failing when primary mirrors reject connections
- Parser preserves query parameters when links contain a trailing slash before `?` (`/?episode=...`)
- Modern JavaScript variables (`const`, `let`, `window.`) and object literal payloads in Kodik player scripts
- CLI no longer crashes when launched directly with a URL (`kodikdown <url>`)
- Isolated yt-dlp output directory from file templates, avoiding output path corruption
- Cancel button now breaks retry backoff immediately
- Eliminated 60 FPS idle CPU drain from hidden progress bar timers
- Reset custom file name when resolving a new video
- Cleaned up unawaited coroutine warnings on exit

---

### Русский

#### Добавлено
- Плавная кроссфейд-анимация при переключении темы оформления
- Анимация вращения кнопок темы и настроек при нажатии
- Обновленный прогресс-бар: градиентная полоса и эффект световой волны в режиме ожидания
- Иконки статуса (успех, ошибка, отмена) с плавной анимацией в списке загрузок
- Иконки для кнопок («Вставить», «Найти», «Скачать», «Открыть папку», диалог настроек)
- Фирменный значок приложения в шапке окна
- Интерактивный прогресс-бар загрузки в консольном режиме

#### Исправлено
- Полноценный фоллбэк на резервные зеркала при HTTP 403, 404, 500 и таймаутах
- Парсер больше не теряет параметры серии в ссылках со слэшем (`/?episode=...`)
- Поддержка современных объявлений JS (`const`, `let`, `window.`) и объектов в скриптах плеера Kodik
- CLI больше не падает при прямом запуске со ссылкой (`kodikdown <url>`)
- Папка загрузки изолирована от шаблона имени файла yt-dlp во избежание сбоев путей
- Мгновенная отмена скачивания даже во время паузы между повторными попытками
- Устранена фоновая нагрузка на процессор (60 FPS) от скрытых таймеров прогресс-бара
- Сброс кастомного названия при открытии нового видео
- Исправлены предупреждения о незакрытых корутинах при выходе

## [3.0.0] - 2026-10-10

The terminal interface is gone: KodikDown is a desktop application now, and the
player lookup was reworked for the signed API Kodik uses today.

### Added

- Desktop window (PySide6/Qt) for Windows and Linux: link field with paste,
  editable file name, voice-over and quality pickers, and a download list with
  live progress, per-transfer cancel, *Open* and *Open folder*
- Light and dark themes that follow the system by default and switch from the
  header or the settings dialog
- Progress that keeps moving between HLS fragments by watching the partial
  files on disk, plus honest "starting" and "waiting for a free slot" states
- Optional direct MP4 download when the CDN serves the whole file
- Several downloads at once, with the limit configurable in settings
- `kodikdown-cli` console script and a `--mp4` flag next to the existing CLI
- PyInstaller recipes for the desktop app and the CLI, built for both platforms
  on `v*` tags
- Offline end-to-end test: a mocked player page followed by a real HLS download
  from a local server, and window tests that run headless

### Changed

- Lookups are signed now: the page's `urlParams` (referer, domain and their
  signatures) travel back with the video id, and the page is fetched again
  between attempts instead of replaying expired signatures
- Links from dead mirrors are retried against the working Kodik hosts, since
  `kodik.info` and `kodik.biz` no longer resolve
- The endpoint address is read from the `$.ajax({url: atob(...)})` call in the
  player bundle
- Transfers survive stalls: transient timeouts and 5xx replies are retried,
  sockets get 30 seconds, finished files are never overwritten and parallel
  downloads reserve their file names
- Cancelling closes the row immediately and drops jobs the pool had not
  started yet
- Download folder, language, theme, concurrency and the MP4 preference live in
  the settings file
- Requirements: Python 3.11+ with PySide6 instead of Textual and pyperclip

### Fixed

- Toast messages rendered as empty pills — Qt style sheets do not inherit text
  colour into child widgets
- A running download no longer sits on "waiting for a free slot": the progress
  listener was never attached to the downloader
- A cancelled transfer no longer leaves `<name>.part` behind on Windows
- File names containing `%` no longer break yt-dlp's output template
- An empty link field now says so instead of complaining about the clipboard
- Delayed callbacks can no longer touch widgets that are already gone

### Removed

- The Textual TUI and the clipboard dependency, superseded by the desktop app

## [2.2.2] - 2026-10-08

### Fixed

- Release yt-dlp's file handle before deleting the partial files of a
  cancelled download

## [2.2.1] - 2026-10-08

### Fixed

- Open the download folder from a one-file build
- Clean up partial files after a cancelled download

## [2.2.0] - 2026-10-08

### Added

- Voice-over picker for every video
- English and Russian interface, detected from the system
- Richer download progress and folder tools in the interface

### Fixed

- Reuse the player client and survive non-JSON API replies
- Accept HTML-escaped iframe embeds
- Escape file globs and clean up download names
- Save settings atomically
- Require a quality above zero in the CLI

## [2.1.1] - 2026-09-09

### Fixed

- Paste button and solid button borders on Windows

## [2.1.0] - 2026-09-09

### Added

- `--list-qualities`, `--list-translations` and `--print-url` CLI flags

### Changed

- Faster cancel and a tougher player page parser
- CI installs ffmpeg from the OS packages

## [2.0.0] - 2026-08-25

### Changed

- Rewritten to talk to the Kodik API directly, with a terminal interface
  instead of a headless Chromium

[3.5.0]: https://github.com/SHAWNiksDev/kodikdown/compare/v3.0.1...v3.5.0
[3.0.1]: https://github.com/SHAWNiksDev/kodikdown/compare/v3.0.0...v3.0.1
[3.0.0]: https://github.com/SHAWNiksDev/kodikdown/compare/v2.2.2...v3.0.0
[2.2.2]: https://github.com/SHAWNiksDev/kodikdown/compare/v2.2.1...v2.2.2
[2.2.1]: https://github.com/SHAWNiksDev/kodikdown/compare/v2.2.0...v2.2.1
[2.2.0]: https://github.com/SHAWNiksDev/kodikdown/compare/v2.1.1...v2.2.0
[2.1.1]: https://github.com/SHAWNiksDev/kodikdown/compare/v2.1.0...v2.1.1
[2.1.0]: https://github.com/SHAWNiksDev/kodikdown/compare/v2.0.0...v2.1.0
[2.0.0]: https://github.com/SHAWNiksDev/kodikdown/releases/tag/v2.0.0
