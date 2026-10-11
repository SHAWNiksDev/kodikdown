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
    background="#f8fafc",
    surface="#ffffff",
    surface_alt="#f1f5f9",
    border="#e2e8f0",
    border_strong="#cbd5e1",
    text="#0f172a",
    text_muted="#64748b",
    accent="#2563eb",
    accent_hover="#1d4ed8",
    accent_soft="#eff6ff",
    success="#16a34a",
    danger="#dc2626",
    warning="#d97706",
    shadow="rgba(15, 23, 42, 0.08)",
)

DARK = Palette(
    mode=MODE_DARK,
    background="#0f1117",
    surface="#181b22",
    surface_alt="#212631",
    border="#2b3240",
    border_strong="#3d4659",
    text="#f1f5f9",
    text_muted="#94a3b8",
    accent="#3b82f6",
    accent_hover="#60a5fa",
    accent_soft="#1e293b",
    success="#22c55e",
    danger="#ef4444",
    warning="#f59e0b",
    shadow="rgba(0, 0, 0, 0.50)",
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
    style_hints = getattr(application, "styleHints", None)
    if style_hints is None:
        return None
    scheme = getattr(style_hints(), "colorScheme", lambda: None)()
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
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Inter", "Roboto", "Noto Sans", sans-serif;
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
    #brand {{
        font-size: 15px;
        font-weight: 700;
        letter-spacing: -0.2px;
    }}
    #brand-sub {{
        color: {palette.text_muted};
        font-size: 10px;
        font-weight: 600;
        background: {palette.surface_alt};
        border-radius: 4px;
        padding: 1px 5px;
    }}
    #card, #panel {{
        background: {palette.surface};
        border: 1px solid {palette.border};
        border-radius: 12px;
    }}
    #panel-title {{
        font-size: 14px;
        font-weight: 600;
        line-height: 1.3;
    }}
    #muted, #hint, #status {{
        color: {palette.text_muted};
    }}
    #status {{
        padding: 2px 0px;
    }}
    #status[state="error"] {{
        color: {palette.danger};
        font-weight: 500;
    }}
    #status[state="success"] {{
        color: {palette.success};
        font-weight: 500;
    }}
    QLineEdit, QComboBox, QSpinBox {{
        background: {palette.surface};
        border: 1px solid {palette.border};
        border-radius: 8px;
        padding: 8px 12px;
        selection-background-color: {palette.accent};
        selection-color: #ffffff;
    }}
    QLineEdit:hover, QComboBox:hover, QSpinBox:hover {{
        border-color: {palette.border_strong};
    }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{
        border-color: {palette.accent};
    }}
    QLineEdit:disabled, QComboBox:disabled {{
        color: {palette.text_muted};
        background: {palette.surface_alt};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 24px;
    }}
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
        font-weight: 500;
    }}
    QPushButton:hover {{
        background: {palette.surface_alt};
        border-color: {palette.border_strong};
    }}
    QPushButton:pressed {{
        background: {palette.border};
    }}
    QPushButton:disabled {{
        color: {palette.text_muted};
        border-color: {palette.border};
        background: {palette.surface_alt};
    }}
    QPushButton#primary {{
        background: {palette.accent};
        border: 1px solid {palette.accent};
        color: #ffffff;
        font-weight: 600;
    }}
    QPushButton#primary:hover {{
        background: {palette.accent_hover};
        border-color: {palette.accent_hover};
    }}
    QPushButton#primary:pressed {{
        background: {palette.accent};
    }}
    QPushButton#primary:disabled {{
        background: {palette.accent_soft};
        border-color: {palette.accent_soft};
        color: {palette.text_muted};
    }}
    QPushButton#ghost {{
        border-color: transparent;
        background: transparent;
    }}
    QPushButton#ghost:hover {{
        background: {palette.surface_alt};
    }}
    QPushButton#icon {{
        border-color: transparent;
        background: transparent;
        border-radius: 8px;
        padding: 6px;
    }}
    QPushButton#icon:hover {{
        background: {palette.surface_alt};
        border-color: {palette.border};
    }}
    QPushButton#link {{
        border: none;
        background: transparent;
        color: {palette.accent};
        padding: 2px 6px;
        font-weight: 500;
    }}
    QPushButton#link:hover {{
        color: {palette.accent_hover};
        text-decoration: underline;
    }}
    QPushButton#quality {{
        border-radius: 13px;
        padding: 5px 14px;
        background: {palette.surface_alt};
        border: 1px solid {palette.border};
        font-size: 12px;
        font-weight: 500;
    }}
    QPushButton#quality:hover {{
        border-color: {palette.accent};
        background: {palette.surface};
    }}
    QPushButton#quality:checked {{
        background: {palette.accent};
        border: 1px solid {palette.accent};
        color: #ffffff;
        font-weight: 600;
    }}
    QScrollArea {{
        border: none;
        background: transparent;
    }}
    QScrollBar:vertical {{
        background: transparent;
        width: 8px;
        margin: 2px;
    }}
    QScrollBar::handle:vertical {{
        background: {palette.border_strong};
        border-radius: 4px;
        min-height: 32px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {palette.text_muted};
    }}
    QScrollBar::add-line, QScrollBar::sub-line {{
        height: 0;
        width: 0;
    }}
    QScrollBar::add-page, QScrollBar::sub-page {{
        background: transparent;
    }}
    #download-row {{
        background: {palette.surface};
        border: 1px solid {palette.border};
        border-radius: 10px;
    }}
    #download-row:hover {{
        border-color: {palette.border_strong};
    }}
    #download-row[state="done"] {{
        border-color: {palette.success};
    }}
    #download-row[state="failed"] {{
        border-color: {palette.danger};
    }}
    #row-title {{
        font-weight: 600;
        font-size: 13px;
    }}
    #row-detail {{
        color: {palette.text_muted};
        font-size: 12px;
    }}
    #row-detail[state="error"] {{
        color: {palette.danger};
    }}
    #row-detail[state="success"] {{
        color: {palette.success};
    }}
    #badge {{
        background: {palette.surface_alt};
        border-radius: 6px;
        padding: 2px 8px;
        color: {palette.text_muted};
        font-size: 11px;
        font-weight: 600;
    }}
    #warning {{
        background: {palette.surface_alt};
        border: 1px solid {palette.border};
        border-radius: 8px;
        color: {palette.warning};
        padding: 8px 12px;
    }}
    QCheckBox {{
        spacing: 6px;
    }}
    QCheckBox::indicator {{
        width: 17px;
        height: 17px;
        border: 1px solid {palette.border_strong};
        border-radius: 4px;
        background: {palette.surface};
    }}
    QCheckBox::indicator:hover {{
        border-color: {palette.accent};
    }}
    QCheckBox::indicator:checked {{
        background: {palette.accent};
        border-color: {palette.accent};
    }}
    QToolTip {{
        background: {palette.surface};
        color: {palette.text};
        border: 1px solid {palette.border};
        padding: 5px 8px;
        border-radius: 6px;
        font-size: 12px;
    }}
    QLabel#section {{
        color: {palette.text_muted};
        font-weight: 600;
        font-size: 11px;
        letter-spacing: 0.5px;
    }}
    QFrame#separator {{
        background: {palette.border};
        max-height: 1px;
        border: none;
    }}
    #toast {{
        background: {palette.text};
        color: {palette.surface};
        border: 1px solid {palette.border};
        border-radius: 12px;
        padding: 10px 16px;
    }}
    #toast[severity="error"] {{
        background: {palette.danger};
        border-color: {palette.danger};
    }}
    #toast[severity="success"] {{
        background: {palette.success};
        border-color: {palette.success};
    }}
    #toast[severity="warning"] {{
        background: {palette.warning};
        border-color: {palette.warning};
    }}
    #toast QLabel {{
        color: {palette.surface};
        background: transparent;
        font-size: 13px;
        font-weight: 500;
    }}
    #toast[severity="error"] QLabel,
    #toast[severity="success"] QLabel,
    #toast[severity="warning"] QLabel {{
        color: #ffffff;
    }}
    """
