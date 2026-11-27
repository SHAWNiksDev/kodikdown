"""`python -m kodikdown.gui` — the window without going through the CLI."""

from __future__ import annotations

import sys

from kodikdown import __version__

if __name__ == "__main__":
    if sys.argv[1:] in (["--version"], ["-V"]):
        if sys.stdout is not None:
            print(f"kodikdown {__version__}")
        raise SystemExit(0)

    if len(sys.argv) == 3 and sys.argv[1] == "--check-playback":
        from pathlib import Path

        from kodikdown.gui.player import check_playback

        raise SystemExit(check_playback(Path(sys.argv[2])))

    from kodikdown.gui.app import run

    raise SystemExit(run())
