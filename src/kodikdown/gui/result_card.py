from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from kodikdown.gui.icons import icon
from kodikdown.gui.theme import Palette
from kodikdown.gui.widgets import CheckBox, FadeMixin
from kodikdown.i18n import t
from kodikdown.kodik.models import ResolvedVideo, StreamVariant


class ResultCard(QFrame):
    translation_changed = Signal()
    download_requested = Signal()
    folder_requested = Signal()

    def __init__(self, prefer_mp4: bool, palette: Palette) -> None:
        super().__init__()
        self.setObjectName("card")
        self.hide()
        self.name_edited = False
        self.variants: tuple[StreamVariant, ...] = ()
        self.quality: int | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(10)

        self.title_label = QLabel()
        self.title_label.setObjectName("panel-title")
        self.title_label.setTextFormat(Qt.TextFormat.PlainText)
        self.title_label.setWordWrap(True)
        layout.addWidget(self.title_label)

        self.warning_label = QLabel()
        self.warning_label.setObjectName("warning")
        self.warning_label.setWordWrap(True)
        self.warning_label.hide()
        layout.addWidget(self.warning_label)

        name_row = QHBoxLayout()
        name_row.setSpacing(8)
        self.name_caption = QLabel(t("file_name"))
        self.name_caption.setObjectName("muted")
        self.name_caption.setMinimumWidth(84)
        self.name_edit = QLineEdit()
        self.name_edit.textEdited.connect(self._on_name_edited)
        name_row.addWidget(self.name_caption)
        name_row.addWidget(self.name_edit, 1)
        layout.addLayout(name_row)

        self.translation_row = QWidget()
        translation_layout = QHBoxLayout(self.translation_row)
        translation_layout.setContentsMargins(0, 0, 0, 0)
        translation_layout.setSpacing(8)
        self.translation_caption = QLabel(t("translation"))
        self.translation_caption.setObjectName("muted")
        self.translation_caption.setMinimumWidth(84)
        self.translation_combo = QComboBox()
        self.translation_combo.currentIndexChanged.connect(self.translation_changed)
        translation_layout.addWidget(self.translation_caption)
        translation_layout.addWidget(self.translation_combo, 1)
        self.translation_row.hide()
        layout.addWidget(self.translation_row)

        quality_row = QHBoxLayout()
        quality_row.setSpacing(8)
        self.quality_caption = QLabel(t("quality"))
        self.quality_caption.setObjectName("muted")
        self.quality_caption.setMinimumWidth(84)
        self.quality_caption.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.quality_box = QWidget()
        self.quality_layout = QHBoxLayout(self.quality_box)
        self.quality_layout.setContentsMargins(0, 0, 0, 0)
        self.quality_layout.setSpacing(6)
        self.quality_layout.addStretch(1)
        self.quality_group = QButtonGroup(self)
        self.quality_group.setExclusive(True)
        quality_row.addWidget(self.quality_caption)
        quality_row.addWidget(self.quality_box, 1)
        layout.addLayout(quality_row)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.mp4_check = CheckBox(t("download_mp4"))
        self.mp4_check.setChecked(prefer_mp4)
        self.download_button = QPushButton(t("download"))
        self.download_button.setObjectName("primary")
        self.download_button.setIcon(icon("download", "#ffffff", 16))
        self.download_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.download_button.setMinimumWidth(130)
        self.download_button.clicked.connect(self.download_requested)
        self.open_folder_button = QPushButton(t("open_folder"))
        self.open_folder_button.setIcon(icon("folder", palette.text_muted, 15))
        self.open_folder_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_folder_button.clicked.connect(self.folder_requested)

        actions.addWidget(self.mp4_check)
        actions.addStretch(1)
        actions.addWidget(self.open_folder_button)
        actions.addWidget(self.download_button)
        layout.addLayout(actions)

    def _on_name_edited(self, _text: str) -> None:
        self.name_edited = True

    def populate(
        self, resolved: ResolvedVideo, keep_quality: int | None, default_quality: str
    ) -> None:
        self.title_label.setText(resolved.title or t("title_unknown"))
        if not self.name_edited:
            self.name_edit.setText(resolved.title or t("title_unknown"))

        self.warning_label.setVisible("proxy" in resolved.warnings)
        if resolved.warnings:
            self.warning_label.setText(t("warning_proxy"))

        has_choices = len(resolved.translations) > 1
        self.translation_row.setVisible(has_choices)
        if has_choices:
            self.translation_combo.blockSignals(True)
            self.translation_combo.clear()
            for item in resolved.translations:
                self.translation_combo.addItem(item.title, item.key)
            active = resolved.translation or resolved.translations[0]
            index = self.translation_combo.findData(active.key)
            self.translation_combo.setCurrentIndex(index if index >= 0 else 0)
            self.translation_combo.blockSignals(False)

        self.build_quality_pills(resolved, keep_quality, default_quality)
        self.download_button.setEnabled(True)
        self.show()
        FadeMixin.fade_in(self)

    def build_quality_pills(
        self, resolved: ResolvedVideo, keep_quality: int | None, default_quality: str
    ) -> None:
        self.variants = resolved.variants
        for button in list(self.quality_group.buttons()):
            self.quality_group.removeButton(button)
            self.quality_layout.removeWidget(button)
            button.hide()
            button.deleteLater()

        # Keep whatever the user had picked for this video, otherwise start
        # from the best stream the server offers.
        available = {variant.quality for variant in resolved.variants}
        preferred = int(default_quality) if default_quality != "ask" else None
        selected = keep_quality if keep_quality in available else resolved.pick(preferred).quality
        self.quality = selected

        for index, variant in enumerate(resolved.variants):
            label = variant.label if variant.quality else t("quality_auto")
            if index == 0:
                label += f" · {t('best_badge')}"
            pill = QPushButton(label)
            pill.setObjectName("quality")
            pill.setCheckable(True)
            pill.setChecked(variant.quality == selected)
            pill.setCursor(Qt.CursorShape.PointingHandCursor)
            pill.clicked.connect(
                lambda _checked=False, quality=variant.quality: self.select_quality(quality)
            )
            self.quality_group.addButton(pill)
            self.quality_layout.insertWidget(self.quality_layout.count() - 1, pill)
        self._refresh_mp4_hint()

    def select_quality(self, quality: int) -> None:
        self.quality = quality
        self._refresh_mp4_hint()

    def _refresh_mp4_hint(self) -> None:
        variant = self.selected_variant()
        self.mp4_check.setVisible(bool(variant and variant.direct_mp4))

    def selected_variant(self) -> StreamVariant | None:
        if not self.variants:
            return None
        quality = self.quality
        if quality is None:
            return self.variants[0]
        for variant in self.variants:
            if variant.quality == quality:
                return variant
        return self.variants[0]
