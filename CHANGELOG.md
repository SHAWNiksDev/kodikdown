# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [4.7.0] - 2026-11-26

### Русский

- На ПК и Android очередь сохраняется между запусками. Загрузки можно поставить на паузу, поднять в очереди и повторить после ошибки. Если источник позволяет проверить частичный файл, загрузка продолжится с сохранённого места.
- Избранное запоминает плеер, озвучку и качество. При открытии сериала выделяются серии, которых ещё нет в библиотеке или очереди.
- Скачанные видео открываются во встроенном плеере с перемоткой, настройкой скорости, полноэкранным режимом и сохранением позиции. Есть кнопка для внешнего плеера.
- В библиотеке и истории на ПК появился поиск по названию, сериалу и озвучке.
- CLI учитывает сохранённое качество и предпочтение MP4. Для отдельных загрузок добавлен флаг `--no-mp4`.
- После изменения ссылки в окне загрузки скрывается предыдущий результат. На Android незавершённый поиск по старой ссылке отменяется.
- Если запись истории на ПК временно не удалась, изменения будут записаны при следующем сохранении.
- Android отклоняет HLS-плейлисты из одних ключевых кадров и плейлисты с несовместимой разметкой сегментов.

### English

- The desktop and Android queues survive restarts. Pause, prioritize and retry downloads, and resume partial files when the source can be verified.
- Favorites remember the player, voice-over and quality. Opening a favorite selects episodes that are missing from the library and queue.
- Watch downloaded videos in the built-in player with seeking, playback speed, full screen and a saved playback position. An external player is also available.
- Search the desktop library and history by title, series, or voice-over.
- The CLI uses saved quality and MP4 preferences and accepts `--no-mp4` for individual downloads.
- Editing a link hides the previous result. On Android, it also cancels a lookup for the old link.
- Desktop history retries unsaved changes the next time it saves.
- Android rejects keyframe-only HLS playlists and unsupported segment layouts.

## [4.6.0] - 2026-11-23

### Русский

- Android сохраняет прямые ссылки HLS с одним расширением `.mp4`.
- Android скрывает клавиатуру перед переключением на другую вкладку.
- AniDUB снова отдаёт списки серий на ПК и Android после обновления плеера.
- Для Linux x86_64 доступен AppImage. В нём уже есть Python и Qt, а для обработки HLS и DASH используется системный FFmpeg.
- CLI показывает серии по ссылке на страницу аниме. Укажите `--list-episodes`, затем выберите серию через `--episode` и при необходимости плеер с озвучкой через `--source`.
- На ПК файл появляется в папке загрузок после успешной обработки. Ошибка или отмена больше не оставляет там видео с готовым именем. Загрузки из двух окон сохраняются в одной истории без перезаписи чужих записей.
- Если прямой MP4 недоступен, ПК пробует HLS в том же качестве. Android проверяет идентификатор файла при возобновлении MP4 и выбирает в HLS разрешение ближе к запрошенному.
- APK подписан тем же ключом, что и 4.5.0. Обновление поверх официальной сборки сохраняет настройки и историю.
- Сборки для ПК занимают меньше места. Windows скрывает служебный файл блокировки в папке загрузок.
- ПК резервирует имена файлов между процессами. ОС освобождает блокировки после завершения процесса. Повтор из истории ищет дубликат в папке нужного сериала.
- Android корректно скачивает HLS с относительными ссылками после редиректов и передаёт `Referer` при прямой загрузке MP4. Отмена дожидается закрытия сетевых операций перед удалением временных файлов.
- Исправлены гонка при создании кэша, обработка имён с многобайтовыми символами и восстановление строк после отмены свайпа. Библиотека обновляет доступность файлов реже и точечно.
- Подписанный APK содержит SHA деревьев Android и общих иконок. CI сверяет их с исходниками в теге перед публикацией.

### English

- Android uses a single `.mp4` extension when saving direct HLS links.
- Android dismisses the keyboard before switching away from the download tab.
- Desktop and Android read episode lists from the updated AniDUB player.
- Linux x86_64 now has an AppImage with Python and Qt included. It uses system FFmpeg for HLS and DASH processing.
- The CLI accepts anime pages. Run `--list-episodes`, then use `--episode` and optionally `--source` to choose an episode, player and voice-over.
- Desktop downloads move to the destination after processing succeeds. Separate windows can add entries to the same history without overwriting each other's changes.
- Desktop can try HLS at the same quality when direct MP4 is unavailable. Android checks file identity before resuming an MP4 and selects an HLS variant closer to the requested resolution.
- The Android APK uses the 4.5.0 signing key, so updating the official app keeps history and settings.
- Desktop builds are smaller. Windows hides the download lock file in File Explorer.
- Desktop reserves output names across processes. The OS releases the locks when a process exits. History retries look for duplicates in the episode's own series folder.
- Android resolves relative HLS links after redirects and sends the `Referer` for direct MP4 downloads. Cancellation waits for network readers to close before removing partial files.
- Fixed a cache directory race, multibyte filenames and row restoration after cancelled swipe actions. File availability checks run less often and refresh the affected rows.
- The locally signed APK embeds the Android and shared icon tree hashes. CI checks them against the release tag before publishing.

## [4.5.0] - 2026-11-19

### Скачивание по ссылке на аниме

- Вставьте страницу **YummyAnime** (включая старый сайт), **AnimeGO**, **AniLiberty** или **AniDUB**. KodikDown покажет доступные плееры, озвучки и серии. Для источников, которые отдают постер и описание, их можно открыть или свернуть.
- Кроме **Kodik**, можно вставлять ссылки на **CVH** и **AniBoom**. На Windows и Linux добавлены **Sibnet**, **Animedia** и **VK Видео**. Статистику CVH можно вставить целиком, если она содержит ID видео.
- Выбирайте одну серию, несколько или весь список. Настройка **В папку сериала** сохраняет их вместе.

### Библиотека, история и фоновые загрузки

- Библиотека показывает файлы, скачанные через KodikDown. В библиотеке и истории удобно искать серии по папке.
- **Скопировать исходную ссылку** возвращает адрес страницы или плеера. Для вставленного iframe копируется адрес из `src`.
- На ПК прогресс виден в меню трея. На Android фоновые загрузки идут с тихим уведомлением, а в настройках отображается версия установленного приложения.
- Если источник не сообщает разрешение, Android показывает качество **Исходное**.

### Установка и инструкции

В выпуск входят **Android 7.0+**, **Windows x64** и **Linux x64**. Для Windows и Linux доступны приложение с интерфейсом и консольная сборка.

> **Android.** У APK новая подпись. Перед установкой 4.5.0 удалите прежнюю версию. История и настройки сбросятся, видео в общей папке останутся.

[Инструкция со скриншотами](https://github.com/SHAWNiksDev/kodikdown/blob/main/docs/guide-ru.md) · [English guide](https://github.com/SHAWNiksDev/kodikdown/blob/main/docs/guide-en.md)

<details>
<summary>English release notes</summary>

- Paste a page from YummyAnime (including the old site), AnimeGO, AniLiberty or AniDUB to pick a player, voice-over, quality and episodes. Posters and descriptions appear when the source provides them.
- Alongside Kodik, KodikDown accepts CVH and AniBoom player links. Desktop also supports Sibnet, Animedia and VK Video. You can paste CVH statistics containing the video ID.
- Queue individual episodes or a full series and save them in a single folder. The library lists KodikDown downloads. History copies the original page or player URL, including the `src` of a pasted iframe.
- Monitor downloads in the desktop tray or a silent Android notification. Android Settings shows the installed version.
- Android shows **Original** when the source doesn't report a resolution.
- Builds are available for Android 7.0+, Windows x64 and Linux x64. Windows and Linux include GUI and CLI builds.

**Android.** This APK has a new signing key. Uninstall the previous version before installing 4.5.0. This clears app settings and history. Videos in shared storage stay on your device.

</details>

## [4.0.0] - 2026-11-14

### Русский

- На ПК появились вкладки «Библиотека», «История» и «Настройки» в одном окне. Приложение сворачивается в трей и продолжает скачивание.
- Настройки на Android и ПК применяются сразу. Вместо повторяющихся сообщений — небольшой значок сохранения. Смена темы и языка стала плавнее, частые нажатия защищены от повторной обработки.
- Добавлены подтверждения отмены и удаления. Активные загрузки и сборка файла защищены от удаления свайпом или выделением.
- История хранит исходную ссылку. Повторная загрузка заново получает поток, сохраняет озвучку и качество и спрашивает подтверждение, если файл уже существует.
- Библиотека и кнопки открытия учитывают удаление файлов. Исправлены статусы и прогресс, уведомления Android и индикация небольших MP4 на ПК.
- Исправлена сборка HLS в MP4 на Android: звук AAC, временные метки видео и обработка больших фрагментов. Загрузчик повторяет запросы после обрывов, не выдаёт неполный файл за готовый и ограничивает использование памяти.
- Исправлены поле ссылки, переключатели в тёмной теме, значки, выделение задач и разметка для планшетов и крупного шрифта.
- Обновлены README и скриншоты. Добавлены проверки загрузок, интерфейса и восстановления после ошибок.

**Android:** из-за новой подписи удалите старую тестовую версию и установите этот APK. Настройки и история сбросятся; скачанные в общую папку видео останутся. Следующие релизы обновляются поверх.

Готовые сборки этого выпуска — Android, Windows x64 и Linux x64. Для Windows и Linux доступны приложение с интерфейсом и консольная версия.

### English

- Desktop Downloads, Library, History and Settings now share one window, with background downloading in the system tray.
- Settings save immediately on both platforms. A small corner indicator replaces repeated success messages; theme and language changes are smoother and repeated actions are guarded.
- Added cancellation and deletion confirmations, protection for active/assembling tasks, original-link history and fresh stream resolution for retries.
- Fixed missing-file detection, download statuses and progress, Android notifications and delayed progress on small desktop MP4 downloads.
- Fixed Android HLS remuxing, raw AAC audio, video timestamps and large-fragment memory use, plus retry and incomplete-file handling.
- Improved narrow/tablet layouts, URL fields, dark-theme controls, icons and task selection. Updated documentation, screenshots and regression tests.

**Android:** uninstall the previous test build once before installing this APK because the signing certificate changed. Settings and history reset; shared downloaded videos remain. Future releases keep the same release key.

This release includes Android, Windows x64 and Linux x64 binaries. Windows and Linux each include a desktop app and a command-line tool.

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

[4.7.0]: https://github.com/SHAWNiksDev/kodikdown/compare/v4.6.0...v4.7.0
[4.6.0]: https://github.com/SHAWNiksDev/kodikdown/compare/v4.5.0...v4.6.0
[4.5.0]: https://github.com/SHAWNiksDev/kodikdown/compare/v4.0.0...v4.5.0
[4.0.0]: https://github.com/SHAWNiksDev/kodikdown/compare/v3.5.0...v4.0.0
[3.5.0]: https://github.com/SHAWNiksDev/kodikdown/compare/v3.0.1...v3.5.0
[3.0.1]: https://github.com/SHAWNiksDev/kodikdown/compare/v3.0.0...v3.0.1
[3.0.0]: https://github.com/SHAWNiksDev/kodikdown/compare/v2.2.2...v3.0.0
[2.2.2]: https://github.com/SHAWNiksDev/kodikdown/compare/v2.2.1...v2.2.2
[2.2.1]: https://github.com/SHAWNiksDev/kodikdown/compare/v2.2.0...v2.2.1
[2.2.0]: https://github.com/SHAWNiksDev/kodikdown/compare/v2.1.1...v2.2.0
[2.1.1]: https://github.com/SHAWNiksDev/kodikdown/compare/v2.1.0...v2.1.1
[2.1.0]: https://github.com/SHAWNiksDev/kodikdown/compare/v2.0.0...v2.1.0
[2.0.0]: https://github.com/SHAWNiksDev/kodikdown/releases/tag/v2.0.0
