"""Line icons drawn from inline SVG, so no binary assets are needed.

Every icon is stroked with the colour of the widget it sits on, which keeps
them readable in both themes without shipping two sets of files.
"""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtSvg import QSvgRenderer

_PATHS: dict[str, str] = {
    "github": (
        '<path fill="currentColor" stroke="none" d="M12 .75a11.25 11.25 0 0 0-3.56 21.92'
        "c.56.1.77-.24.77-.54v-2.1c-3.13.68-3.79-1.33-3.79-1.33-.51-1.3-1.25-1.65-1.25-1.65"
        "-1.02-.7.08-.69.08-.69 1.13.08 1.73 1.16 1.73 1.16 1 1.72 2.63 1.22 3.27.93"
        ".1-.73.39-1.22.71-1.5-2.5-.29-5.13-1.25-5.13-5.56 0-1.23.44-2.23 1.16-3.02"
        "-.12-.28-.5-1.43.11-2.98 0 0 .95-.3 3.09 1.15a10.76 10.76 0 0 1 5.62 0"
        "c2.14-1.45 3.08-1.15 3.08-1.15.62 1.55.23 2.7.12 2.98.72.79 1.15 1.79 1.15 3.02"
        " 0 4.32-2.63 5.27-5.14 5.55.4.35.76 1.03.76 2.08v3.11c0 .3.2.65.78.54"
        'A11.25 11.25 0 0 0 12 .75z"/>'
    ),
    "library": (
        '<rect x="5" y="3" width="16" height="16" rx="2"/><path d="M2 7v14h15M11 7l6 4-6 4z"/>'
    ),
    "history": '<circle cx="12" cy="12" r="9"/><path d="M12 6v6l4 2"/>',
    "refresh": '<path d="M20 11a8 8 0 1 0-2 6M20 4v7h-7"/>',
    "sun": (
        '<circle cx="12" cy="12" r="4.1"/>'
        '<path d="M12 2.8v2.1M12 19.1v2.1M2.8 12h2.1M19.1 12h2.1'
        'M5.5 5.5l1.5 1.5M17 17l1.5 1.5M18.5 5.5L17 7M7 17l-1.5 1.5"/>'
    ),
    "moon": '<path d="M20.2 14.6A8.6 8.6 0 0 1 9.4 3.8a8.6 8.6 0 1 0 10.8 10.8z"/>',
    "settings": (
        '<path d="M4 7h9M17 7h3M4 12h3M11 12h9M4 17h9M17 17h3"/>'
        '<circle cx="15" cy="7" r="2"/><circle cx="9" cy="12" r="2"/>'
        '<circle cx="15" cy="17" r="2"/>'
    ),
    "folder": (
        '<path d="M3 7.5A1.5 1.5 0 0 1 4.5 6h4l2 2.2h7A1.5 1.5 0 0 1 19 9.7v7.8'
        'A1.5 1.5 0 0 1 17.5 19h-13A1.5 1.5 0 0 1 3 17.5z"/>'
    ),
    "close": '<path d="M6 6l12 12M18 6L6 18"/>',
    "check": '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    "clipboard": (
        '<rect x="6" y="4.5" width="12" height="15.5" rx="2.2"/>'
        '<path d="M9.5 4.5V3.6A1.1 1.1 0 0 1 10.6 2.5h2.8a1.1 1.1 0 0 1 1.1 1.1v.9z"/>'
    ),
    "download": '<path d="M12 3.5v11M7.5 10.5l4.5 4.5 4.5-4.5M4.5 19.5h15"/>',
    "trash": (
        '<path d="M4.5 7h15M9.5 7V5.4A.9.9 0 0 1 10.4 4.5h3.2a.9.9 0 0 1 .9.9V7"/>'
        '<path d="M6.5 7l.8 11.2A1.4 1.4 0 0 0 8.7 19.5h6.6a1.4 1.4 0 0 0 1.4-1.3'
        'L17.5 7"/><path d="M10.5 10.5v5.5M13.5 10.5v5.5"/>'
    ),
    "warning": (
        '<path d="M12 3.8l8.4 14.6H3.6z"/><path d="M12 9.5v4.2"/>'
        '<circle cx="12" cy="16.3" r="0.6" fill="none"/>'
    ),
    "play": '<path d="M8 5.5l10 6.5-10 6.5z"/>',
    "stop": '<rect x="6.5" y="6.5" width="11" height="11" rx="1.6"/>',
    "link": (
        '<path d="M10.5 13.5a3.7 3.7 0 0 0 5.2 0l2.6-2.6a3.7 3.7 0 0 0-5.2-5.2l-1 1"/>'
        '<path d="M13.5 10.5a3.7 3.7 0 0 0-5.2 0l-2.6 2.6a3.7 3.7 0 0 0 5.2 5.2l1-1"/>'
    ),
    "info": ('<circle cx="12" cy="12" r="9"/><path d="M12 8v.5M12 11v5"/>'),
}


def icon_svg(name: str, color: str) -> str:
    body = _PATHS[name]
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" color="{color}" '
        f'stroke="{color}" stroke-width="1.7" stroke-linecap="round" '
        f'stroke-linejoin="round">{body}</svg>'
    )


@lru_cache(maxsize=128)
def icon(name: str, color: str, size: int = 20) -> QIcon:
    renderer = QSvgRenderer(QByteArray(icon_svg(name, color).encode("utf-8")))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter)
    painter.end()
    return QIcon(pixmap)


@lru_cache(maxsize=16)
def app_icon(color: str = "#3B7DFF", size: int = 256) -> QIcon:
    """A rounded square with a play mark, painted at runtime."""
    result = QIcon()
    for pixels in sorted({16, 20, 24, 28, 32, 48, 64, 128, 256, size}):
        pixmap = QPixmap(pixels, pixels)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(pixels / 256, pixels / 256)
        body = QPainterPath()
        body.addRoundedRect(QRectF(16, 16, 224, 224), 56, 56)
        painter.fillPath(body, QColor(color))
        triangle = QPainterPath()
        triangle.moveTo(102, 78)
        triangle.lineTo(182, 128)
        triangle.lineTo(102, 178)
        triangle.closeSubpath()
        painter.fillPath(triangle, QColor("#FFFFFF"))
        painter.end()
        result.addPixmap(pixmap)
    return result
