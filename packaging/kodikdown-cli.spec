# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller recipe for the scriptable command-line build.

Build from the repository root:

    pyinstaller packaging/kodikdown-cli.spec --noconfirm
"""

import os
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent  # noqa: F821 - injected by PyInstaller
NAME = os.environ.get("KODIKDOWN_BUILD_NAME", "kodikdown-cli").strip() or "kodikdown-cli"

a = Analysis(  # noqa: F821 - injected by PyInstaller
    [str(ROOT / "src" / "kodikdown" / "cli.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=[],
    hiddenimports=["kodikdown.cli"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821 - injected by PyInstaller

exe = EXE(  # noqa: F821 - injected by PyInstaller
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=True,
)
