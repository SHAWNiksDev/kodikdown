from pathlib import Path

from PyInstaller.utils.hooks.qt import add_qt6_dependencies

hiddenimports, binaries, datas = add_qt6_dependencies(__file__)

# Keep the portal, Qt file picker and system input methods on desktop.
binaries = [
    (source, destination)
    for source, destination in binaries
    if Path(source).stem.removeprefix("lib") not in {"qgtk3", "qpdf", "qtvirtualkeyboardplugin"}
]
