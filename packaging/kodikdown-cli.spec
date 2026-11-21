"""PyInstaller recipe for the scriptable command-line build.

Build from the repository root:

    pyinstaller packaging/kodikdown-cli.spec --noconfirm
"""

import os
import sys
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent  # noqa: F821 - injected by PyInstaller
NAME = os.environ.get("KODIKDOWN_BUILD_NAME", "kodikdown-cli").strip() or "kodikdown-cli"

a = Analysis(  # noqa: F821 - injected by PyInstaller
    [str(ROOT / "src" / "kodikdown" / "cli.py")],
    pathex=[str(ROOT / "src")],
    hookspath=[str(ROOT / "packaging" / "hooks")],
    excludes=[
        "PySide6",
        "kodikdown.gui",
        "mypy",
        "pydantic.mypy",
        "pydantic.v1.mypy",
        "pydoc",
        "pytest",
        "setuptools",
        "shiboken6",
        "sqlite3",
        "tkinter",
    ],
)
pyz = PYZ(a.pure)  # noqa: F821 - injected by PyInstaller

exe = EXE(  # noqa: F821 - injected by PyInstaller
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name=NAME,
    strip=sys.platform == "linux",
    upx=False,
)
