from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QTimer, QUrl
from PySide6.QtGui import QKeyEvent, QKeySequence, QShortcut
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoFrame, QVideoSink
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from kodikdown.gui.desktop import open_path
from kodikdown.i18n import t


def check_playback(path: Path) -> int:
    """Check that this build can decode a video frame using its own Qt backend."""
    app = QApplication([])
    player = QMediaPlayer()
    sink = QVideoSink()
    timeout = QTimer()
    timeout.setSingleShot(True)
    timeout.timeout.connect(lambda: app.exit(1))

    def frame_changed(frame: QVideoFrame) -> None:
        if frame.isValid():
            app.exit(0)

    player.errorOccurred.connect(lambda *_: QTimer.singleShot(0, lambda: app.exit(1)))
    sink.videoFrameChanged.connect(frame_changed)
    player.setVideoSink(sink)
    player.setSource(QUrl.fromLocalFile(str(path.resolve())))
    QTimer.singleShot(0, player.play)
    timeout.start(10000)
    return app.exec()


class VideoPlayer(QDialog):
    def __init__(self, path: Path, config: Path, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle(path.stem)
        self.resize(860, 520)
        stat = path.stat()
        identity = f"{path.resolve()}\n{stat.st_size}\n{stat.st_mtime_ns}"
        self.key = sha256(identity.encode(errors="surrogatepass")).hexdigest()
        self.positions = QSettings(str(config / "playback.ini"), QSettings.Format.IniFormat)
        position = self.positions.value(self.key, 0, int)
        self.resume_at = position if isinstance(position, int) else 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        self.video = QVideoWidget(self)
        self.video.setStyleSheet("background-color: black")
        layout.addWidget(self.video, 1)
        self.message = QLabel(t("player_error"))
        self.message.setWordWrap(True)
        self.message.hide()
        layout.addWidget(self.message)

        self.seek = QSlider(Qt.Orientation.Horizontal)
        self.seek.setAccessibleName(t("player_position"))
        self.seek.setRange(0, 0)
        self.seek.actionTriggered.connect(lambda _: self._seek(self.seek.sliderPosition()))
        layout.addWidget(self.seek)

        controls = QHBoxLayout()
        self.toggle = QPushButton(t("pause_download"))
        self.toggle.setObjectName("primary")
        self.toggle.clicked.connect(self._toggle_playback)
        controls.addWidget(self.toggle)
        self.time = QLabel("0:00 / 0:00")
        controls.addWidget(self.time)
        controls.addStretch(1)
        speed = QComboBox()
        speed.setAccessibleName(t("player_speed"))
        for rate in (0.5, 0.75, 1, 1.25, 1.5, 1.75, 2):
            speed.addItem(f"{rate:g}\N{MULTIPLICATION SIGN}", rate)
        speed.setCurrentIndex(2)
        controls.addWidget(speed)
        self.fullscreen = QPushButton(t("player_fullscreen"))
        self.fullscreen.clicked.connect(self._toggle_fullscreen)
        controls.addWidget(self.fullscreen)
        external = QPushButton(t("external_player"))
        external.clicked.connect(lambda: self._external(path))
        controls.addWidget(external)
        layout.addLayout(controls)

        self.audio = QAudioOutput(self)
        self.media = QMediaPlayer(self)
        speed.currentIndexChanged.connect(
            lambda _: self.media.setPlaybackRate(float(speed.currentData()))
        )
        self.media.setAudioOutput(self.audio)
        self.media.setVideoOutput(self.video)
        self.media.positionChanged.connect(self._position_changed)
        self.media.durationChanged.connect(self._duration_changed)
        self.media.seekableChanged.connect(self._restore_position)
        self.media.playbackStateChanged.connect(self._playback_changed)
        self.media.errorOccurred.connect(lambda *_: self.message.show())
        self.media.mediaStatusChanged.connect(self._media_status)
        self.space = QShortcut(QKeySequence("Space"), self, self._toggle_playback)
        self.fullscreen_shortcut = QShortcut(QKeySequence("F"), self, self._toggle_fullscreen)
        self.timer = QTimer(self)
        self.timer.setInterval(5000)
        self.timer.timeout.connect(self._save_position)
        self.timer.start()
        self.finished.connect(self._finish_playback)
        self.media.setSource(QUrl.fromLocalFile(str(path)))
        self.media.play()

    def _duration_changed(self, duration: int) -> None:
        self.seek.setMaximum(duration // 1000)
        self._position_changed(self.media.position())
        self._restore_position()

    def _position_changed(self, position: int) -> None:
        if not self.seek.isSliderDown():
            self.seek.setValue(position // 1000)
        self.time.setText(f"{_time(position)} / {_time(self.media.duration())}")

    def _restore_position(self, *_: object) -> None:
        if self.resume_at and self.media.isSeekable() and self.media.duration() > 0:
            if self.resume_at < self.media.duration() - 1000:
                self.media.setPosition(self.resume_at)
            self.resume_at = 0

    def _seek(self, position: int) -> None:
        self.media.setPosition(position * 1000)

    def _playback_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        key = "pause_download" if state == QMediaPlayer.PlaybackState.PlayingState else "play"
        self.toggle.setText(t(key))

    def _toggle_playback(self) -> None:
        if self.media.isPlaying():
            self.media.pause()
        else:
            self.media.play()

    def _toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()
        self.fullscreen.setText(
            t("player_exit_fullscreen" if self.isFullScreen() else "player_fullscreen")
        )

    def _external(self, path: Path) -> None:
        self.media.pause()
        if not open_path(path):
            self.message.show()

    def _media_status(self, status: QMediaPlayer.MediaStatus) -> None:
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.positions.remove(self.key)

    def _save_position(self) -> None:
        position, duration = self.media.position(), self.media.duration()
        if duration and 1000 < position < duration - 2000:
            self.positions.setValue(self.key, position)
        elif duration and not self.resume_at:
            self.positions.remove(self.key)

    def _finish_playback(self) -> None:
        self.timer.stop()
        self._save_position()
        self.positions.sync()
        self.media.stop()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self.isFullScreen() and event.key() == Qt.Key.Key_Escape:
            self._toggle_fullscreen()
            event.accept()
            return
        super().keyPressEvent(event)


def _time(milliseconds: int) -> str:
    minutes, seconds = divmod(milliseconds // 1000, 60)
    return f"{minutes}:{seconds:02d}"
