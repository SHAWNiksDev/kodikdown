# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

[3.0.0]: https://github.com/SHAWNiksDev/kodikdown/compare/v2.2.2...v3.0.0
[2.2.2]: https://github.com/SHAWNiksDev/kodikdown/compare/v2.2.1...v2.2.2
[2.2.1]: https://github.com/SHAWNiksDev/kodikdown/compare/v2.2.0...v2.2.1
[2.2.0]: https://github.com/SHAWNiksDev/kodikdown/compare/v2.1.1...v2.2.0
[2.1.1]: https://github.com/SHAWNiksDev/kodikdown/compare/v2.1.0...v2.1.1
[2.1.0]: https://github.com/SHAWNiksDev/kodikdown/compare/v2.0.0...v2.1.0
[2.0.0]: https://github.com/SHAWNiksDev/kodikdown/releases/tag/v2.0.0
