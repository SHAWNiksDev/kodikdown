"""Modal settings dialog: folder, language, theme, concurrency."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from kodikdown.config import (
    LANGUAGE_CHOICES,
    MAX_CONCURRENT_DOWNLOADS,
    MIN_CONCURRENT_DOWNLOADS,
    THEME_CHOICES,
    ConfigStore,
    Settings,
)
from kodikdown.gui.desktop import open_directory
from kodikdown.i18n import LANGUAGE_NAMES, t


class SettingsDialog(QDialog):
    def __init__(
        self, settings: Settings, store: ConfigStore, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("settings_title"))
        self.setModal(True)
        self.setMinimumWidth(460)
        self._store = store
        self._original = settings
        self._result = settings

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(14)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        form.setSpacing(10)

        self.folder_edit = QLineEdit(str(settings.download_dir))
        browse = QPushButton(t("browse"))
        browse.clicked.connect(self._browse)
        folder_row = QHBoxLayout()
        folder_row.setSpacing(8)
        folder_row.addWidget(self.folder_edit, 1)
        folder_row.addWidget(browse)
        form.addRow(t("download_dir"), folder_row)

        self.language_combo = QComboBox()
        for code in LANGUAGE_CHOICES:
            label = t("language_auto") if code == "auto" else LANGUAGE_NAMES.get(code, code)
            self.language_combo.addItem(label, code)
        _select(self.language_combo, settings.language)
        form.addRow(t("language"), self.language_combo)

        self.theme_combo = QComboBox()
        for code in THEME_CHOICES:
            self.theme_combo.addItem(t(f"theme_{code}"), code)
        _select(self.theme_combo, settings.theme)
        form.addRow(t("theme"), self.theme_combo)

        self.concurrent_spin = QSpinBox()
        self.concurrent_spin.setRange(MIN_CONCURRENT_DOWNLOADS, MAX_CONCURRENT_DOWNLOADS)
        self.concurrent_spin.setValue(settings.concurrent_downloads)
        form.addRow(t("concurrent_downloads"), self.concurrent_spin)

        self.mp4_check = QCheckBox(t("prefer_mp4"))
        self.mp4_check.setChecked(settings.prefer_mp4)
        mp4_row = QVBoxLayout()
        mp4_row.setSpacing(2)
        mp4_row.addWidget(self.mp4_check)
        hint = QLabel(t("prefer_mp4_hint"))
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        mp4_row.addWidget(hint)
        form.addRow("", mp4_row)

        layout.addLayout(form)

        path_label = QLabel(t("settings_path", path=store.path))
        path_label.setObjectName("muted")
        path_label.setWordWrap(True)
        layout.addWidget(path_label)

        buttons = QDialogButtonBox()
        open_button = buttons.addButton(t("open_folder"), QDialogButtonBox.ButtonRole.ActionRole)
        open_button.clicked.connect(self._open_folder)
        buttons.addButton(t("close"), QDialogButtonBox.ButtonRole.RejectRole)
        save_button = buttons.addButton(t("save"), QDialogButtonBox.ButtonRole.AcceptRole)
        save_button.setObjectName("primary")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def settings(self) -> Settings:
        return self._result

    # -- actions -----------------------------------------------------------
    def _browse(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, t("download_dir"), self.folder_edit.text() or str(Path.home())
        )
        if chosen:
            self.folder_edit.setText(chosen)

    def _open_folder(self) -> None:
        folder = Path(self.folder_edit.text().strip()).expanduser()
        if not folder.is_dir():
            QMessageBox.warning(self, t("settings_title"), t("folder_missing"))
            return
        if not open_directory(folder):
            QMessageBox.warning(self, t("settings_title"), t("folder_open_failed", detail=folder))

    def _save(self) -> None:
        folder = Path(self.folder_edit.text().strip()).expanduser()
        if not folder.parent.exists() and not folder.exists():
            QMessageBox.warning(
                self, t("settings_title"), t("folder_not_created", detail=str(folder.parent))
            )
            return
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.warning(self, t("settings_title"), t("folder_not_created", detail=exc))
            return

        self._result = Settings(
            download_dir=folder,
            language=str(self.language_combo.currentData()),
            theme=str(self.theme_combo.currentData()),
            concurrent_downloads=self.concurrent_spin.value(),
            prefer_mp4=self.mp4_check.isChecked(),
        )
        self.accept()


def _select(combo: QComboBox, value: str) -> None:
    index = combo.findData(value)
    combo.setCurrentIndex(index if index >= 0 else 0)
