"""Native tray integration; never hide a window behind an unavailable tray."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QMenu, QSystemTrayIcon, QWidget

from kodikdown.gui.icons import app_icon
from kodikdown.i18n import t


class DesktopTray(QObject):
    show_requested = Signal()
    quit_requested = Signal()

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.icon = QSystemTrayIcon(app_icon(), parent)
        self.icon.setToolTip("KodikDown")
        self.menu = QMenu(parent)
        self.show_action = self.menu.addAction("")
        self.show_action.triggered.connect(self.show_requested.emit)
        self.menu.addSeparator()
        self.quit_action = self.menu.addAction("")
        self.quit_action.triggered.connect(self.quit_requested.emit)
        self.icon.setContextMenu(self.menu)
        self.icon.activated.connect(self._activated)
        self.retranslate()
        self.ensure_visible()

    def retranslate(self) -> None:
        self.show_action.setText(t("tray_show"))
        self.quit_action.setText(t("tray_quit"))

    def ensure_visible(self) -> bool:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return False
        self.icon.show()
        return True

    def _activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.show_requested.emit()

    def close(self) -> None:
        self.icon.hide()
