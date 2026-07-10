"""Session 46.4b tests — the shared embedded video player widget and
its three integration points (Builder's `ImageZoneBase`, Gallery's
grid/full-view). See `additionalfeatures.md`'s SESSION 46.4b for the
full design writeup.

Requires a QApplication instance (offscreen platform, same pattern
every other widget test in this suite uses). No real video file is
decoded here — this environment has no display and no guaranteed
codec set, so playback-dependent assertions stick to "does the widget
build/degrade correctly", not "does a real frame render", exactly the
same "verified by reading the code" honesty standard this session's
own write-up holds itself to for anything needing real hardware.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication

from backend.constants import VIDEO_EXTENSIONS
from ui.tabs.gallery_tab import GalleryTab, _is_video_path
from ui.widgets.image_zone import ResultImageViewer
from ui.widgets.video_player import VideoPlayerWidget, video_playback_available


COLORS = {
    "bg": "#202020", "bg_alt": "#242424", "bg_card": "#282828",
    "bg_input": "#2c2c2c", "border": "#3a3a3a", "fg": "#f0f0f0",
    "fg_dim": "#9a9a9a", "accent": "#5b8def", "accent_text": "#ffffff",
    "accent_hover": "#6f9bf2", "success": "#4caf50", "danger": "#e05252",
    "warn": "#e0a852", "tree_bg": "#242424", "tree_alt": "#262626",
    "select_bg": "#31445e",
}


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


# ---------------------------------------------------------------------
#                       VideoPlayerWidget itself
# ---------------------------------------------------------------------
def test_widget_constructs_without_crashing(qapp):
    w = VideoPlayerWidget(COLORS)
    assert w is not None


def test_set_colors_does_not_crash(qapp):
    w = VideoPlayerWidget(COLORS)
    other = dict(COLORS, bg_card="#111111")
    w.set_colors(other)
    assert w.colors["bg_card"] == "#111111"


def test_load_missing_file_signals_unavailable_not_crash(qapp):
    w = VideoPlayerWidget(COLORS)
    seen = []
    w.playback_unavailable.connect(lambda: seen.append(True))
    w.load("/does/not/exist.mp4")
    assert seen == [True]


def test_load_none_path_signals_unavailable(qapp):
    w = VideoPlayerWidget(COLORS)
    seen = []
    w.playback_unavailable.connect(lambda: seen.append(True))
    w.load(None)
    assert seen == [True]


def test_play_pause_stop_are_safe_even_before_load(qapp):
    w = VideoPlayerWidget(COLORS)
    # Should never raise, whether or not real playback is available.
    w.play()
    w.pause()
    w.stop()


# ---------------------------------------------------------------------
#           ImageZoneBase / ResultImageViewer integration
# ---------------------------------------------------------------------
def test_show_video_path_creates_and_shows_embedded_player(qapp):
    viewer = ResultImageViewer(COLORS)
    assert viewer._video_player is None
    viewer.show_video_path("/does/not/exist.mp4", "clip.mp4")
    assert viewer._video_player is not None
    assert viewer._video_player.isHidden() is False
    assert viewer._video_filename == "clip.mp4"
    assert viewer._has_image is False


def test_show_video_path_derives_filename_from_path_when_omitted(qapp):
    viewer = ResultImageViewer(COLORS)
    viewer.show_video_path("/tmp/some_result_007.mp4")
    assert viewer._video_filename == "some_result_007.mp4"


def test_show_image_path_after_video_hides_the_player(qapp, tmp_path):
    from PyQt6.QtGui import QColor, QImage
    img_path = str(tmp_path / "img.png")
    img = QImage(40, 40, QImage.Format.Format_RGB32)
    img.fill(QColor("red"))
    img.save(img_path)

    viewer = ResultImageViewer(COLORS)
    viewer.show_video_path("/does/not/exist.mp4", "clip.mp4")
    assert viewer._video_player.isHidden() is False

    viewer.show_image_path(img_path)
    assert viewer._has_image is True
    assert viewer._video_filename is None
    assert viewer._video_player.isHidden() is True


def test_show_placeholder_hides_the_player(qapp):
    viewer = ResultImageViewer(COLORS)
    viewer.show_video_path("/does/not/exist.mp4", "clip.mp4")
    viewer.show_placeholder()
    assert viewer._video_filename is None
    assert viewer._video_player.isHidden() is True


def test_deprecated_show_video_placeholder_still_works(qapp):
    """Backward-compat alias -- see its own docstring."""
    viewer = ResultImageViewer(COLORS)
    viewer.show_video_placeholder("legacy_clip.mp4")
    assert viewer._video_filename == "legacy_clip.mp4"
    assert viewer._video_player is not None


def test_set_colors_propagates_to_embedded_player(qapp):
    viewer = ResultImageViewer(COLORS)
    viewer.show_video_path("/does/not/exist.mp4", "clip.mp4")
    other = dict(COLORS, fg="#ffffff")
    viewer.set_colors(other)
    assert viewer._video_player.colors["fg"] == "#ffffff"


# ---------------------------------------------------------------------
#                       Gallery: video recognition
# ---------------------------------------------------------------------
def test_is_video_path_recognizes_every_video_extension():
    for ext in VIDEO_EXTENSIONS:
        assert _is_video_path(f"/some/dir/result{ext}") is True


def test_is_video_path_false_for_images_and_empty():
    assert _is_video_path("/some/dir/result.png") is False
    assert _is_video_path("") is False
    assert _is_video_path(None) is False


def test_gallery_register_video_result_adds_video_badge(qapp, tmp_path):
    gallery = GalleryTab(COLORS)
    video_path = str(tmp_path / "clip.mp4")
    with open(video_path, "wb") as fh:
        fh.write(b"not a real mp4, just bytes for the path check")

    gallery._gallery_register_result(
        local_path=video_path, remote_filename="clip.mp4",
        remote_subfolder="", display_name="clip.mp4")

    assert len(gallery.gallery_cells) == 1
    cell = gallery.gallery_cells[0]
    assert cell._is_video is True
    assert hasattr(cell, "lbl_video_badge")
    # A PosterFrameGrabber (not a QThreadPool _ThumbnailRunnable) should
    # have been kicked off and held alive for this video entry.
    assert len(gallery._poster_grabbers) == 1
    qapp.processEvents()


def test_gallery_register_image_result_has_no_video_badge(qapp, tmp_path):
    from PyQt6.QtGui import QColor, QImage
    img_path = str(tmp_path / "img.png")
    img = QImage(40, 40, QImage.Format.Format_RGB32)
    img.fill(QColor("blue"))
    img.save(img_path)

    gallery = GalleryTab(COLORS)
    gallery._gallery_register_result(
        local_path=img_path, remote_filename="img.png",
        remote_subfolder="", display_name="img.png")

    cell = gallery.gallery_cells[0]
    assert cell._is_video is False
    assert not hasattr(cell, "lbl_video_badge")
    assert len(gallery._poster_grabbers) == 0

    # _ThumbnailRunnable decodes on a QThreadPool worker thread; make
    # sure it's actually finished emitting before this GalleryTab (and
    # its cells' signal objects) get torn down at test end, or the
    # runnable can fire into an already-deleted QObject.
    from PyQt6.QtCore import QThreadPool
    QThreadPool.globalInstance().waitForDone(2000)
    qapp.processEvents()


def test_playback_availability_flag_is_a_bool(qapp):
    assert video_playback_available() in (True, False)
