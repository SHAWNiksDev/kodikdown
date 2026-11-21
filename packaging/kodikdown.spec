"""PyInstaller recipe for the KodikDown desktop build.

Build from the repository root:

    pyinstaller packaging/kodikdown.spec --noconfirm
"""

import os
import sys
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent  # noqa: F821 - injected by PyInstaller
NAME = os.environ.get("KODIKDOWN_BUILD_NAME", "kodikdown").strip() or "kodikdown"

EXCLUDED_QT = [
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DExtras",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.Qt3DRender",
    "PySide6.QtBluetooth",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtDesigner",
    "PySide6.QtGraphs",
    "PySide6.QtHelp",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtNfc",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtPositioning",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQuickControls2",
    "PySide6.QtQuickWidgets",
    "PySide6.QtRemoteObjects",
    "PySide6.QtScxml",
    "PySide6.QtSensors",
    "PySide6.QtSerialBus",
    "PySide6.QtSerialPort",
    "PySide6.QtSpatialAudio",
    "PySide6.QtSql",
    "PySide6.QtStateMachine",
    "PySide6.QtTest",
    "PySide6.QtTextToSpeech",
    "PySide6.QtWebChannel",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebSockets",
]

EXCLUDES = [
    *EXCLUDED_QT,
    "IPython",
    "PIL",
    "matplotlib",
    "mypy",
    "numpy",
    "pydantic.mypy",
    "pydantic.v1.mypy",
    "pydoc",
    "pytest",
    "setuptools",
    "sqlite3",
    "tkinter",
]

a = Analysis(  # noqa: F821 - injected by PyInstaller
    [str(ROOT / "src" / "kodikdown" / "gui" / "__main__.py")],
    pathex=[str(ROOT / "src")],
    datas=[
        (str(ROOT / "src/kodikdown/gui/brands/*.png"), "kodikdown/gui/brands"),
    ],
    hookspath=[str(ROOT / "packaging" / "hooks")],
    excludes=EXCLUDES,
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
    console=False,
    icon=str(ROOT / "docs" / "app.ico") if sys.platform == "win32" else None,
)
