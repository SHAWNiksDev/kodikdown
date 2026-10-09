"""Opening files and folders, with the fallbacks a frozen build needs."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

logger = logging.getLogger(__name__)


def _child_env() -> dict[str, str]:
    """Environment for launched helpers, with PyInstaller's lib path undone.

    The one-file bootloader puts its bundled libraries on LD_LIBRARY_PATH,
    which makes system programs like xdg-open fail with symbol lookup errors,
    so restore whatever was there before it started.
    """
    env = os.environ.copy()
    original = env.pop("LD_LIBRARY_PATH_ORIG", None)
    if original is not None:
        env["LD_LIBRARY_PATH"] = original
    else:
        env.pop("LD_LIBRARY_PATH", None)
    return env


def _spawn(command: list[str]) -> bool:
    try:
        subprocess.Popen(
            command,
            env=_child_env(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return False
    return True


def open_path(path: Path) -> bool:
    """Open a file (or folder) with the desktop's default application."""
    if not path.exists():
        return False
    if QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
        return True
    if sys.platform == "win32":
        return _spawn(["cmd", "/c", "start", "", str(path)])
    if sys.platform == "darwin":
        return _spawn(["open", str(path)])
    return _spawn(["xdg-open", str(path)]) or _spawn(["gio", "open", str(path)])


def open_directory(path: Path) -> bool:
    if not path.is_dir():
        return False
    if QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
        return True
    if sys.platform == "win32":
        return _spawn(["explorer", str(path)])
    if sys.platform == "darwin":
        return _spawn(["open", str(path)])
    return _spawn(["xdg-open", str(path)]) or _spawn(["gio", "open", str(path)])


def reveal_path(path: Path) -> bool:
    """Show a finished file in the system file manager."""
    if not path.exists():
        return False
    if sys.platform == "win32":
        return _spawn(["explorer", f"/select,{path}"])
    if sys.platform == "darwin":
        return _spawn(["open", "-R", str(path)])
    return open_directory(path.parent)
