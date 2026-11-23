#!/usr/bin/env bash
set -euo pipefail

export QT_QPA_PLATFORM=xcb
"$1" &
app=$!
trap 'kill "$app" 2>/dev/null || true; wait "$app" 2>/dev/null || true' EXIT

for ((attempt = 0; attempt < 30; attempt++)); do
    if ! kill -0 "$app" 2>/dev/null; then
        printf '%s\n' "GUI exited before opening: $1" >&2
        exit 1
    fi
    if xdotool search --onlyvisible --name '^KodikDown$' >/dev/null; then
        exit 0
    fi
    sleep 1
done

printf '%s\n' "KodikDown window did not appear: $1" >&2
exit 1
