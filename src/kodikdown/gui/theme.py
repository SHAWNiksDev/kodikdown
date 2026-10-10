"""Light and dark palettes plus the stylesheet built from them."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication

MODE_AUTO = "auto"
MODE_LIGHT = "light"
MODE_DARK = "dark"


@dataclass(frozen=True)
class Palette:
    mode: str
    background: str
    surface: str
    surface_alt: str
    border: str
    border_strong: str
    text: str
    text_muted: str
    accent: str
    accent_hover: str
    accent_soft: str
    success: str
    danger: str
    warning: str
    shadow: str

    @property
    def is_dark(self) -> bool:
        return self.mode == MODE_DARK


LIGHT = Palette(
    mode=MODE_LIGHT,
    background="#f4f5f7",
    surface="#ffffff",
    surface_alt="#eceef2",
    border="#dfe3e9",
    border_strong="#c8ced8",
    text="#171a1f",
    text_muted="#6a7280",
    accent="#2f6fed",
    accent_hover="#2a63d4",
    accent_soft="#e6edfd",
    success="#1a8f52",
    danger="#cf3f45",
    warning="#9a6b12",
    shadow="rgba(15, 23, 42, 0.10)",
)

DARK = Palette(
    mode=MODE_DARK,
    background="#15171c",
    surface="#1d2027",
    surface_alt="#24272f",
    border="#2d323c",
    border_strong="#3b414d",
    text="#e7e9ee",
    text_muted="#98a1af",
    accent="#5b8dfa",
    accent_hover="#6f9cff",
    accent_soft="#22304d",
    success="#37c07d",
    danger="#ef6b70",
    warning="#dcb256",
    shadow="rgba(0, 0, 0, 0.45)",
)


def system_mode() -> str:
    """Best-effort answer to "does the desktop prefer dark?"."""
    scheme = _qt_color_scheme()
    if scheme is not None:
        return scheme
    if sys.platform == "win32":
        return _windows_mode()
    return _linux_mode()


def _qt_color_scheme() -> str | None:
    application = QGuiApplication.instance()
    if application is None:
        return None
    try:
        scheme = application.styleHints().colorScheme()  # type: ignore[attr-defined]
    except AttributeError:  # very old Qt
        return None
    if scheme == Qt.ColorScheme.Dark:
        return MODE_DARK
    if scheme == Qt.ColorScheme.Light:
        return MODE_LIGHT
    return None


def _windows_mode() -> str:
    try:
        import winreg
    except ImportError:
        return MODE_LIGHT
    try:
        with winreg.OpenKey(  # type: ignore[attr-defined]
            winreg.HKEY_CURRENT_USER,  # type: ignore[attr-defined]
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")  # type: ignore[attr-defined]
    except OSError:
        return MODE_LIGHT
    return MODE_LIGHT if value else MODE_DARK


def _linux_mode() -> str:
    try:
        result = subprocess.run(
            ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return MODE_LIGHT
    output = result.stdout.strip().lower()
    if "dark" in output:
        return MODE_DARK
    return MODE_LIGHT


def palette_for(mode: str) -> Palette:
    if mode == MODE_AUTO:
        mode = system_mode()
    return DARK if mode == MODE_DARK else LIGHT


def stylesheet(palette: Palette) -> str:
    return f"""
    * {{
        font-family: "Segoe UI", "Inter", "Noto Sans", "DejaVu Sans", sans-serif;
        font-size: 13px;
        outline: none;
    }}
    QWidget {{
        color: {palette.text};
        background: transparent;
    }}
    #window, QMainWindow, QDialog {{
        background: {palette.background};
    }}
    #header {{
        background: {palette.surface};
        border-bottom: 1px solid {palette.border};
    }}
    #brand {{ font-size: 15px; font-weight: 600; }}
    #brand-sub {{ color: {palette.text_muted}; font-size: 11px; }}
    #card, #panel {{
        background: {palette.surface};
        border: 1px solid {palette.border};
        border-radius: 12px;
    }}
    #panel-title {{ font-size: 14px; font-weight: 600; }}
    #muted, #hint, #status {{ color: {palette.text_muted}; }}
    #status[state="error"] {{ color: {palette.danger}; }}
    #status[state="success"] {{ color: {palette.success}; }}
    QLineEdit, QComboBox, QSpinBox {{
        background: {palette.surface};
        border: 1px solid {palette.border};
        border-radius: 8px;
        padding: 7px 10px;
        selection-background-color: {palette.accent};
        selection-color: #ffffff;
    }}
    QLineEdit:hover, QComboBox:hover, QSpinBox:hover {{ border-color: {palette.border_strong}; }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border-color: {palette.accent}; }}
    QLineEdit:disabled, QComboBox:disabled {{ color: {palette.text_muted}; }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QComboBox QAbstractItemView {{
        background: {palette.surface};
        border: 1px solid {palette.border};
        border-radius: 8px;
        padding: 4px;
        selection-background-color: {palette.accent_soft};
        selection-color: {palette.text};
        outline: none;
    }}
    QPushButton {{
        background: {palette.surface};
        border: 1px solid {palette.border};
        border-radius: 8px;
        padding: 7px 14px;
    }}
    QPushButton:hover {{ background: {palette.surface_alt}; border-color: {palette.border_strong}; }}
    QPushButton:pressed {{ background: {palette.surface_alt}; }}
    QPushButton:disabled {{ color: {palette.text_muted}; border-color: {palette.border}; }}
    QPushButton#primary {{
        background: {palette.accent};
        border: 1px solid {palette.accent};
        color: #ffffff;
        font-weight: 600;
    }}
    QPushButton#primary:hover {{ background: {palette.accent_hover}; border-color: {palette.accent_hover}; }}
    QPushButton#primary:disabled {{
        background: {palette.accent_soft};
        border-color: {palette.accent_soft};
        color: {palette.text_muted};
    }}
    QPushButton#ghost {{ border-color: transparent; background: transparent; }}
    QPushButton#ghost:hover {{ background: {palette.surface_alt}; }}
    QPushButton#icon {{ border-color: transparent; background: transparent; padding: 6px; }}
    QPushButton#icon:hover {{ background: {palette.surface_alt}; }}
    QPushButton#link {{
        border: none; background: transparent;
        color: {palette.accent}; padding: 2px 4px;
    }}
    QPushButton#link:hover {{ color: {palette.accent_hover}; }}
    QPushButton#quality {{
        border-radius: 14px; padding: 5px 14px;
        background: {palette.surface_alt};
        border: 1px solid transparent;
    }}
    QPushButton#quality:hover {{ border-color: {palette.border_strong}; }}
    QPushButton#quality:checked {{
        background: {palette.accent_soft};
        border: 1px solid {palette.accent};
        color: {palette.accent};
        font-weight: 600;
    }}
    QScrollArea {{ border: none; background: transparent; }}
    QScrollBar:vertical {{
        background: transparent; width: 10px; margin: 2px;
    }}
    QScrollBar::handle:vertical {{
        background: {palette.border_strong}; border-radius: 5px; min-height: 32px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {palette.text_muted}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    #download-row {{
        background: {palette.surface};
        border: 1px solid {palette.border};
        border-radius: 10px;
    }}
    #download-row[state="done"] {{ border-color: {palette.success}; }}
    #download-row[state="failed"] {{ border-color: {palette.danger}; }}
    #row-title {{ font-weight: 600; }}
    #row-detail {{ color: {palette.text_muted}; }}
    #row-detail[state="error"] {{ color: {palette.danger}; }}
    #row-detail[state="success"] {{ color: {palette.success}; }}
    #badge {{
        background: {palette.surface_alt};
        border-radius: 6px;
        padding: 2px 7px;
        color: {palette.text_muted};
        font-size: 11px;
        font-weight: 600;
    }}
    #warning {{
        background: {palette.surface_alt};
        border: 1px solid {palette.border};
        border-radius: 8px;
        color: {palette.warning};
        padding: 7px 10px;
    }}
    QCheckBox::indicator {{
        width: 16px; height: 16px;
        border: 1px solid {palette.border_strong};
        border-radius: 4px;
        background: {palette.surface};
    }}
    QCheckBox::indicator:checked {{
        background: {palette.accent};
        border-color: {palette.accent};
    }}
    QToolTip {{
        background: {palette.surface};
        color: {palette.text};
        border: 1px solid {palette.border};
        padding: 4px 6px;
        border-radius: 6px;
    }}
    QLabel#section {{ color: {palette.text_muted}; font-weight: 600; font-size: 11px; }}
    QFrame#separator {{ background: {palette.border}; max-height: 1px; border: none; }}
    #toast {{
        background: {palette.text};
        color: {palette.surface};
        border-radius: 10px;
        padding: 10px 14px;
    }}
    #toast[severity="error"] {{ background: {palette.danger}; }}
    #toast[severity="success"] {{ background: {palette.success}; }}
    #toast QLabel {{ color: {palette.surface}; background: transparent; }}
    #toast[severity="error"] QLabel, #toast[severity="success"] QLabel {{ color: #ffffff; }}
    """
