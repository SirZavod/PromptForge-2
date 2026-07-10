"""Shared embedded video player widget (Session 46.4b) — Builder's
result panel, Gallery's full-view dialog, and (via Gallery's own
`_gallery_open_full_view`/`_gallery_reveal_in_explorer` reuse, per
`history_tab.py`'s own docstring) History's "Open image" action all
end up going through this one class rather than three divergent
playback paths. See `additionalfeatures.md`'s SESSION 46.4b for the
full design writeup (why a shared widget, what already existed before
this session, the two-approach decision for the Builder integration
point).

Deliberately not a full-featured media-player clone — play/pause/
scrub/volume covers every call site's real need (see that section's
scope item 1).

`PyQt6.QtMultimedia` is already a known, optional-import quantity in
this codebase (`backend/sound_manager.py` imports `QSoundEffect` from
it behind a `try/except`). What's genuinely new here is
`PyQt6.QtMultimediaWidgets` (for `QVideoWidget`) and `QMediaPlayer`
itself — this module follows `sound_manager.py`'s own optional-import/
graceful-degrade pattern for both, but with a visible fallback message
instead of a silent no-op: a missing notification sound is easy to not
notice, a video that never appears and never explains why is not.
"""
import os

from PyQt6.QtCore import QObject, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

try:
    from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoSink
    from PyQt6.QtMultimediaWidgets import QVideoWidget
    _VIDEO_PLAYBACK_AVAILABLE = True
except Exception:
    QAudioOutput = None
    QMediaPlayer = None
    QVideoSink = None
    QVideoWidget = None
    _VIDEO_PLAYBACK_AVAILABLE = False


def video_playback_available() -> bool:
    """Whether in-app playback (QtMultimediaWidgets + QMediaPlayer) is
    actually importable on this machine — checked once at import time,
    exposed as a function (not a bare module constant) so call sites
    read as a deliberate check rather than a magic boolean."""
    return _VIDEO_PLAYBACK_AVAILABLE


def _fmt_ms(ms) -> str:
    if not ms or ms < 0:
        ms = 0
    total_seconds = ms // 1000
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes}:{seconds:02d}"


class VideoPlayerWidget(QWidget):
    """`QMediaPlayer` + `QVideoWidget` wrapper, themed through the same
    `colors` dict as every other widget in this app. Exposes just
    load(path)/play()/pause()/stop() plus a `frame_ready` signal cheap
    enough to also serve as the poster-frame hook (see
    `PosterFrameGrabber` below for the actual off-widget grab used by
    Gallery's grid, which can't afford a full playing widget per cell).

    Degrades gracefully (a themed message, not a crash or silent
    no-op) if `QtMultimediaWidgets`/`QMediaPlayer` aren't importable —
    see the module docstring for why that's a visible message here
    rather than `sound_manager.py`'s silent no-op.
    """

    playback_unavailable = pyqtSignal()

    def __init__(self, colors, parent=None):
        super().__init__(parent)
        self.colors = colors
        self._path = None
        self._had_first_frame = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        if _VIDEO_PLAYBACK_AVAILABLE:
            self._build_real_player(layout)
        else:
            self._build_fallback(layout)

    # ---------------------------------------------------- real player --
    def _build_real_player(self, layout):
        self._video_widget = QVideoWidget(self)
        self._video_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self._video_widget, 1)

        self._player = QMediaPlayer(self)
        self._audio_output = QAudioOutput(self)
        self._player.setAudioOutput(self._audio_output)
        self._player.setVideoOutput(self._video_widget)
        self._player.errorOccurred.connect(self._on_error)
        self._player.playbackStateChanged.connect(self._on_state_changed)
        self._player.positionChanged.connect(self._on_position_changed)
        self._player.durationChanged.connect(self._on_duration_changed)

        controls = QHBoxLayout()
        controls.setContentsMargins(4, 0, 4, 4)
        controls.setSpacing(6)

        self.btn_play = QPushButton("▶")
        self.btn_play.setFixedWidth(32)
        self.btn_play.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_play.clicked.connect(self._toggle_play)
        controls.addWidget(self.btn_play)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.sliderMoved.connect(self._on_slider_moved)
        controls.addWidget(self.slider, 1)

        self.lbl_time = QLabel("0:00 / 0:00")
        controls.addWidget(self.lbl_time)

        layout.addLayout(controls)
        self._apply_colors()

    def _build_fallback(self, layout):
        self._fallback_label = QLabel(
            "🎬 In-app video playback isn't available on this system\n"
            "(the QtMultimedia/QtMultimediaWidgets backend didn't load).\n"
            "Use \u201cOpen folder\u201d to view the file instead.")
        self._fallback_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._fallback_label.setWordWrap(True)
        layout.addWidget(self._fallback_label, 1)
        self._apply_colors()

    def _apply_colors(self):
        c = self.colors
        self.setStyleSheet(
            f"QPushButton {{ background-color: {c['bg_card']}; color: {c['fg']}; "
            f"border: 1px solid {c['border']}; border-radius: 6px; padding: 4px; }}"
            f"QPushButton:hover {{ background-color: {c['accent_hover']}; }}"
            f"QLabel {{ color: {c['fg_dim']}; }}"
            f"QSlider::groove:horizontal {{ background: {c['bg_card']}; height: 4px; border-radius: 2px; }}"
            f"QSlider::handle:horizontal {{ background: {c['accent']}; width: 12px; "
            f"margin: -5px 0; border-radius: 6px; }}"
        )

    # ------------------------------------------------------------ api --
    def set_colors(self, colors):
        self.colors = colors
        self._apply_colors()

    def load(self, path):
        """Loads and starts playing `path` (a local file). Autoplaying
        is deliberate, not an oversight — it's the cheapest reliable
        way to get a real decoded first frame on screen (and to fire
        `playback_unavailable`/`frame_ready` promptly if something's
        wrong), the same way a browser's `<video autoplay>` element
        would. Callers that don't want sound-on-arrival can call
        `pause()` immediately after."""
        self._path = path
        self._had_first_frame = False
        if not _VIDEO_PLAYBACK_AVAILABLE:
            self.playback_unavailable.emit()
            return
        if not path or not os.path.exists(path):
            self.playback_unavailable.emit()
            return
        self._player.setSource(QUrl.fromLocalFile(path))
        self._player.play()

    def play(self):
        if _VIDEO_PLAYBACK_AVAILABLE:
            self._player.play()

    def pause(self):
        if _VIDEO_PLAYBACK_AVAILABLE:
            self._player.pause()

    def stop(self):
        if _VIDEO_PLAYBACK_AVAILABLE:
            self._player.stop()

    # -------------------------------------------------------- internal --
    def _toggle_play(self):
        if not _VIDEO_PLAYBACK_AVAILABLE:
            return
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
        else:
            self._player.play()

    def _on_state_changed(self, state):
        self.btn_play.setText(
            "⏸" if state == QMediaPlayer.PlaybackState.PlayingState else "▶")

    def _on_error(self, error, _error_string):
        if error != QMediaPlayer.Error.NoError:
            self.playback_unavailable.emit()

    def _on_slider_moved(self, value):
        if _VIDEO_PLAYBACK_AVAILABLE:
            self._player.setPosition(value)

    def _on_position_changed(self, position):
        if not self.slider.isSliderDown():
            self.slider.setValue(position)
        self.lbl_time.setText(f"{_fmt_ms(position)} / {_fmt_ms(self._player.duration())}")

    def _on_duration_changed(self, duration):
        self.slider.setRange(0, duration)
        self.lbl_time.setText(f"{_fmt_ms(self._player.position())} / {_fmt_ms(duration)}")


class PosterFrameGrabber(QObject):
    """One-shot first-frame grab for a video file, used by Gallery's
    grid so a finished video doesn't sit there looking like a broken/
    still-loading image next to real image thumbnails (see
    `additionalfeatures.md` SESSION 46.4b item 4 — "grabbing a frame
    via the same player widget rather than a separate ffmpeg-style
    dependency, if Qt's own frame-grab is sufficient").

    Unlike `gallery_tab.py`'s `_ThumbnailRunnable` (a `QRunnable` doing
    real decode work on a `QThreadPool` worker thread), this can NOT
    move off the GUI thread — `QMediaPlayer` is a GUI-thread-only Qt
    object, same constraint `VideoPlayerWidget` above has. Kept as a
    lightweight on-demand object (no visible widget, no `QVideoWidget`
    at all — `QVideoSink` alone is enough to receive decoded frames)
    rather than a background queue, since Gallery only ever needs one
    of these per newly-added video cell, not a persistent pool.

    Verified by reading the code, not against a real running video
    file in this environment (no GUI/media backend available here) —
    flagged the same way this session's own write-up flags real-
    hardware-only verification elsewhere.
    """

    frame_grabbed = pyqtSignal(str, QImage)  # (path, image) — image may be null on failure/timeout

    TIMEOUT_MS = 4000

    def __init__(self, path, parent=None):
        super().__init__(parent)
        self._path = path
        self._done = False

        if not _VIDEO_PLAYBACK_AVAILABLE:
            QTimer.singleShot(0, lambda: self._finish(QImage()))
            return

        self._player = QMediaPlayer(self)
        self._sink = QVideoSink(self)
        self._player.setVideoSink(self._sink)
        self._sink.videoFrameChanged.connect(self._on_frame)
        self._player.errorOccurred.connect(lambda *_a: self._finish(QImage()))
        QTimer.singleShot(self.TIMEOUT_MS, lambda: self._finish(QImage()))

        self._player.setSource(QUrl.fromLocalFile(path))
        self._player.play()

    def _on_frame(self, frame):
        if self._done or not frame.isValid():
            return
        image = frame.toImage()
        self._player.pause()
        self._finish(image)

    def _finish(self, image):
        if self._done:
            return
        self._done = True
        self.frame_grabbed.emit(self._path, image)
