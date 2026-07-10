"""Gallery tab — scrollable grid of thumbnails for every image generated
through ComfyUI this session.

Ported from `PromptForgeApp.build_gallery_tab` / `_gallery_make_thumbnail`
/ `_gallery_build_cell` / `_gallery_add_cell` / `_gallery_relayout` /
`_gallery_relayout_now` / `_gallery_register_result` /
`_gallery_resolve_target` / `_gallery_reveal_in_explorer` /
`_gallery_open_full_view` in the original Tkinter monolith.

Two deliberate, intentional deviations from a verbatim port:

1. **No Pillow dependency for thumbnails.** Same call as
   `ui/widgets/image_zone.py` already made (see that module's
   docstring): `QImage`/`QPixmap` decode every format this app uses and
   `Qt.TransformationMode.SmoothTransformation` gives a comparable
   resize quality to Pillow's LANCZOS, so thumbnailing here has zero
   PIL dependency. `QImage` (not `QPixmap`) is what actually gets
   decoded/scaled inside the `QThreadPool` worker thread, since
   `QPixmap` is not safe to touch off the GUI thread on every platform
   — the `QImage` is only converted to a `QPixmap` back on the main
   thread, in `_on_thumbnail_ready`.
2. **`self.comfy_output_dir` starts as `None` and is a plain public
   attribute, not fetched here.** The original's
   `_resolve_output_folder_for` would reach out over HTTP to ComfyUI
   itself if `comfy_output_dir` hadn't been discovered yet. This tab
   has no `ComfyUIClient` of its own (that only exists from Session 9
   on, and is only wired to a live connection in Session 11's cross-tab
   signals per the migration plan's Session 13 step). Until then,
   `_gallery_resolve_target` simply falls back to the local
   preview-cache copy — exactly the same fallback the original used
   whenever `out_dir` couldn't be resolved, just reached a little
   sooner. Session 11 sets `gallery_tab.comfy_output_dir = ...` once a
   real connection exists.

Method names keep their original leading underscores exactly as the
migration plan names them (`_gallery_register_result`,
`_gallery_relayout`, etc.) since Session 13's cross-tab wiring refers
to them by these exact names.
"""
import os

from PyQt6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from backend.constants import GALLERY_CELL_OUTER_WIDTH, GALLERY_THUMB_SIZE, VIDEO_EXTENSIONS
from backend.file_manager import FileManagerError, resolve_output_folder_for, reveal_file_in_explorer
from ui.dialogs.framed_dialog import FramelessDialogMixin
from ui.dialogs import themed_message_box
from ui.widgets.video_player import PosterFrameGrabber, VideoPlayerWidget


def _is_video_path(path) -> bool:
    """Session 46.4b: the same extension-only classification used
    everywhere else a video result needs recognizing (see
    `additionalfeatures.md`'s "no `is_video` flag is stored anywhere"
    note under SESSION 46.4b — `local_path`'s own extension is already
    sufficient, so nothing new is stored on gallery/history entries)."""
    if not path:
        return False
    return os.path.splitext(path)[1].lower() in VIDEO_EXTENSIONS


# ============================================================
#         Background thumbnail decoding (QThreadPool)
# ============================================================
class _ThumbnailSignals(QObject):
    """A QRunnable can't itself be a QObject (it isn't one), so the
    pyqtSignal it needs to report back to the main thread lives on a
    small companion QObject instead — the standard Qt pattern for
    signals-out-of-a-QRunnable."""
    ready = pyqtSignal(int, QImage)


class _ThumbnailRunnable(QRunnable):
    """Loads and downscales one image off the main thread, so a slow
    disk (network share, spinning HDD, whatever) can't stall the UI
    while a burst of Gallery entries arrive. `index` is the entry's
    stable position in `GalleryTab.gallery_entries`/`gallery_cells`
    (both lists are append-only — see the module docstring — so an
    index captured at queue time is still valid whenever this runs)."""

    def __init__(self, index: int, path: str, size: int):
        super().__init__()
        self.index = index
        self.path = path
        self.size = size
        self.signals = _ThumbnailSignals()

    def run(self):
        image = QImage(self.path) if self.path and os.path.exists(self.path) else QImage()
        if not image.isNull():
            image = image.scaled(
                self.size, self.size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        self.signals.ready.emit(self.index, image)


# ============================================================
#                     One grid cell
# ============================================================
class GalleryCell(QFrame):
    """Fixed-size card: thumbnail box (or a 🖼 placeholder glyph until
    the real thumbnail decodes), the display name underneath, and two
    always-visible overlay buttons (📂 Reveal, 🔍 Full view) positioned
    in the thumbnail's top-right corner — the Qt equivalent of the
    original's `place()`-on-hover magnifier button, generalized to two
    actions per the Session 8 plan and made permanently visible per
    Session 32."""

    reveal_clicked = pyqtSignal()
    full_view_clicked = pyqtSignal()

    def __init__(self, entry: dict, colors: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("GalleryCell")
        self.setFixedWidth(GALLERY_THUMB_SIZE + 16)
        self._colors = colors

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)

        self.thumb = QLabel()
        self.thumb.setFixedSize(GALLERY_THUMB_SIZE, GALLERY_THUMB_SIZE)
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb.setCursor(Qt.CursorShape.PointingHandCursor)
        self._style_thumb_placeholder()
        self.thumb.mousePressEvent = self._on_thumb_clicked
        outer.addWidget(self.thumb)

        self._is_video = _is_video_path(entry.get("local_path"))
        if self._is_video:
            # 46.4b: a small always-on badge distinguishing a video
            # cell from an image one even once its poster frame has
            # loaded and looks like any other thumbnail.
            self.lbl_video_badge = QLabel("🎬", self.thumb)
            self.lbl_video_badge.setStyleSheet(
                "font-size: 14px; background-color: rgba(0,0,0,140); "
                "color: white; border-radius: 4px; padding: 1px 4px;")
            self.lbl_video_badge.move(6, 6)
            self.lbl_video_badge.show()

        name_text = entry.get("display_name") or os.path.basename(entry.get("local_path", ""))
        self.lbl_name = QLabel(name_text)
        self.lbl_name.setObjectName("dim")
        self.lbl_name.setWordWrap(True)
        self.lbl_name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(self.lbl_name)

        self.btn_reveal = QPushButton("📂", self.thumb)
        self.btn_reveal.setObjectName("GalleryOverlayBtn")
        self.btn_reveal.setFixedSize(28, 28)
        self.btn_reveal.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_reveal.setToolTip("Reveal in explorer")
        self.btn_reveal.clicked.connect(self.reveal_clicked.emit)

        self.btn_full = QPushButton("🔍", self.thumb)
        self.btn_full.setObjectName("GalleryOverlayBtn")
        self.btn_full.setFixedSize(28, 28)
        self.btn_full.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_full.setToolTip("Full view")
        self.btn_full.clicked.connect(self.full_view_clicked.emit)

        self._position_overlay()
        self._set_overlay_visible(True)

    # ------------------------------------------------------------------
    def _on_thumb_clicked(self, _event):
        self.full_view_clicked.emit()

    def _position_overlay(self):
        # Top-right corner of the thumbnail, stacked with a small gap —
        # matches the original's single place(relx=1.0, rely=0.0,
        # anchor="ne") magnifier, extended to two buttons.
        margin = 6
        self.btn_reveal.move(GALLERY_THUMB_SIZE - self.btn_reveal.width() - margin, margin)
        self.btn_full.move(
            GALLERY_THUMB_SIZE - self.btn_reveal.width() - self.btn_full.width() - margin - 4, margin)

    def _set_overlay_visible(self, visible: bool):
        self.btn_reveal.setVisible(visible)
        self.btn_full.setVisible(visible)

    def _style_thumb_placeholder(self):
        c = self._colors
        # QLabel shows either its text or its pixmap, never both — a
        # stray setPixmap(QPixmap()) here (even a null one) silently
        # wipes the glyph text, which is exactly what happened the
        # first time this was written and caught by the Session 8
        # on-screen check below. clear() is the correct way to drop
        # any previously-set pixmap before switching back to text.
        self.thumb.clear()
        self.thumb.setText("🖼")
        self.thumb.setStyleSheet(
            f"font-size: 40px; color: {c['fg_dim']}; "
            f"background-color: {c['bg_card']}; border-radius: 8px;"
        )

    def set_colors(self, colors: dict):
        self._colors = colors
        if self.thumb.pixmap() is None or self.thumb.pixmap().isNull():
            self._style_thumb_placeholder()

    def set_pixmap(self, pixmap: QPixmap):
        self.thumb.setText("")
        self.thumb.setStyleSheet(f"background-color: {self._colors['bg_card']}; border-radius: 8px;")
        self.thumb.setPixmap(pixmap)

    # ------------------------------------------------------------------
    # Session 32: overlay buttons are always visible now, so hover no
    # longer toggles them. Left as harmless no-op overrides in case a
    # future session wants the enter/leave hook for something else
    # (e.g. a hover highlight on the card itself).
    def enterEvent(self, event):
        super().enterEvent(event)

    def leaveEvent(self, event):
        super().leaveEvent(event)


# ============================================================
#                      GalleryTab
# ============================================================
class GalleryTab(QWidget):
    """Self-contained Gallery tab. Owns no persisted state of its own —
    `gallery_entries` is in-session-only, wiped on every app restart,
    exactly like the original's `self.gallery_entries`.

    `comfy_output_dir` (public attribute, default None) and
    `_gallery_register_result` (public entry point despite the
    underscore — see module docstring) are the two hooks Session
    11/13's cross-tab wiring uses: `BuilderTab.gallery_entry_ready(dict)
    → GalleryTab._gallery_register_result(...)` and
    `BuilderTab.comfy_connected_changed` setting `comfy_output_dir`
    once a live ComfyUI connection resolves it.
    """

    def __init__(self, colors: dict, parent=None):
        super().__init__(parent)
        self.colors = colors
        self.gallery_entries: list = []
        self.gallery_cells: list = []
        self.comfy_output_dir = None  # set externally once ComfyUI is connected (Session 11)

        self._threadpool = QThreadPool.globalInstance()
        # 46.4b: PosterFrameGrabber instances must stay referenced
        # somewhere until their frame_grabbed signal fires (a local in
        # _gallery_add_cell would get garbage-collected mid-grab) --
        # same "kept alive" reasoning as sound_manager.py's
        # _ACTIVE_EFFECTS list, just per-tab instead of module-global.
        self._poster_grabbers = []
        self._relayout_pending = False

        self._build_ui()
        self._update_count_label()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self):
        outer = QVBoxLayout(self)

        top = QHBoxLayout()
        title = QLabel("Generated images (this session)")
        title.setObjectName("TitleLabel")
        top.addWidget(title)
        self.lbl_count = QLabel("")
        self.lbl_count.setObjectName("dim")
        top.addWidget(self.lbl_count)
        top.addStretch(1)
        outer.addLayout(top)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.grid_host = QWidget()
        self.grid_layout = QGridLayout(self.grid_host)
        self.grid_layout.setContentsMargins(4, 4, 4, 4)
        self.grid_layout.setSpacing(10)
        self.grid_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.scroll.setWidget(self.grid_host)
        outer.addWidget(self.scroll, 1)

        self.lbl_placeholder = QLabel(
            "No images generated yet this session — results from "
            "\"🎨 Generate in ComfyUI\" will show up here."
        )
        self.lbl_placeholder.setObjectName("dim")
        self.lbl_placeholder.setWordWrap(True)
        self.grid_layout.addWidget(self.lbl_placeholder, 0, 0)
        self._placeholder_hidden = False

    def _update_count_label(self):
        n = len(self.gallery_entries)
        self.lbl_count.setText(f"{n} image{'s' if n != 1 else ''}" if n else "")

    def set_colors(self, colors: dict):
        """Called from MainWindow.toggle_theme, same pattern as
        LibraryTab.set_colors — the grid cells paint their thumbnail
        placeholder background manually (not via QSS alone for the
        text-glyph state), so they need an explicit refresh."""
        self.colors = colors
        for cell in self.gallery_cells:
            cell.set_colors(colors)

    # ------------------------------------------------------------------
    # Resize / relayout
    # ------------------------------------------------------------------
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._gallery_relayout()

    def showEvent(self, event):
        super().showEvent(event)
        self._gallery_relayout()

    def _gallery_relayout(self):
        """Debounced entry point — schedules `_gallery_relayout_now()`
        on the next event-loop pass via `QTimer.singleShot(0, ...)`,
        the Qt equivalent of the original's `root.after_idle(...)`.
        Coalesces a burst of resize/showEvent calls into exactly one
        real relayout, same reasoning as the original's
        `_gallery_relayout` docstring."""
        if self._relayout_pending:
            return
        self._relayout_pending = True
        QTimer.singleShot(0, self._gallery_relayout_now)

    def _gallery_relayout_now(self):
        self._relayout_pending = False
        if not self.gallery_cells:
            return
        width = self.scroll.viewport().width()
        cols = max(1, width // GALLERY_CELL_OUTER_WIDTH)
        for i, cell in enumerate(self.gallery_cells):
            row, col = divmod(i, cols)
            self.grid_layout.addWidget(cell, row, col)

    # ------------------------------------------------------------------
    # Registering new results / building cells
    # ------------------------------------------------------------------
    def _gallery_register_result(self, local_path, remote_filename, remote_subfolder, display_name):
        """Adds one freshly generated image to the in-session Gallery.
        Called (once Session 11 wires it up) for every successful
        ComfyUI generation."""
        entry = {
            "local_path": local_path,
            "remote_filename": remote_filename,
            "remote_subfolder": remote_subfolder or "",
            "display_name": display_name,
        }
        self.gallery_entries.append(entry)
        self._gallery_add_cell(entry)

    def _gallery_add_cell(self, entry):
        if not self._placeholder_hidden:
            self.grid_layout.removeWidget(self.lbl_placeholder)
            self.lbl_placeholder.hide()
            self._placeholder_hidden = True

        index = len(self.gallery_cells)
        cell = GalleryCell(entry, self.colors)
        cell.reveal_clicked.connect(lambda idx=index: self._gallery_reveal_in_explorer(self.gallery_entries[idx]))
        cell.full_view_clicked.connect(lambda idx=index: self._gallery_open_full_view(self.gallery_entries[idx]))
        self.gallery_cells.append(cell)

        if _is_video_path(entry.get("local_path")):
            # 46.4b: poster-frame grab instead of the QImage decode
            # path -- QImage can't decode video at all (returns null),
            # which is exactly the "fails closed, gracefully" gap this
            # session's write-up flagged (cell stays on its default 🖼
            # placeholder forever). PosterFrameGrabber must run on the
            # GUI thread (QMediaPlayer constraint), so this is a plain
            # attribute-held object, not a QThreadPool runnable like
            # the image path below.
            grabber = PosterFrameGrabber(entry["local_path"], parent=self)
            grabber.frame_grabbed.connect(
                lambda path, image, idx=index: self._on_poster_frame_ready(idx, image))
            # Session 49 audit fix: this list only ever grew -- a
            # one-shot grabber (and the QMediaPlayer/QVideoSink it
            # owns) was kept alive for the rest of the app's life for
            # every video ever added to the Gallery, well past the
            # point its single frame_grabbed had already fired. It's
            # only needed long enough to survive until that signal
            # fires (Python would otherwise be free to collect it
            # mid-grab since nothing else holds a reference), so drop
            # it from the list and schedule its actual deletion right
            # after.
            grabber.frame_grabbed.connect(lambda *_a, g=grabber: self._release_poster_grabber(g))
            self._poster_grabbers.append(grabber)
        else:
            runnable = _ThumbnailRunnable(index, entry["local_path"], GALLERY_THUMB_SIZE)
            runnable.signals.ready.connect(self._on_thumbnail_ready)
            self._threadpool.start(runnable)

        self._gallery_relayout()
        self._update_count_label()

    def _on_thumbnail_ready(self, index: int, image: QImage):
        if index >= len(self.gallery_cells) or image.isNull():
            return
        self.gallery_cells[index].set_pixmap(QPixmap.fromImage(image))

    def _release_poster_grabber(self, grabber):
        """Drops a one-shot `PosterFrameGrabber` once its single
        `frame_grabbed` has fired (success, failure, or timeout --
        `PosterFrameGrabber._finish` is itself guarded to run exactly
        once, so this is always called exactly once per grabber)."""
        if grabber in self._poster_grabbers:
            self._poster_grabbers.remove(grabber)
        grabber.deleteLater()

    def _on_poster_frame_ready(self, index: int, image: QImage):
        """Companion to `_on_thumbnail_ready` for video cells — a null
        image here (playback unavailable, grab timed out, or the file
        genuinely won't decode) is expected and not an error: the cell
        just keeps its 🎬-badged default placeholder, same graceful
        fail-closed behavior the image path already had, not a
        crash."""
        if index >= len(self.gallery_cells) or image.isNull():
            return
        scaled = image.scaled(
            GALLERY_THUMB_SIZE, GALLERY_THUMB_SIZE,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.gallery_cells[index].set_pixmap(QPixmap.fromImage(scaled))

    # ------------------------------------------------------------------
    # Reveal / full view
    # ------------------------------------------------------------------
    def _gallery_resolve_target(self, entry: dict):
        """Returns (target_file, folder) for a Gallery entry, preferring
        ComfyUI's real output/ folder over the local preview-cache copy
        — same output_dir-vs-local-copy priority as the original. See
        the module docstring for why `comfy_output_dir` starts unset."""
        remote_filename = entry.get("remote_filename")
        folder = resolve_output_folder_for(self.comfy_output_dir, entry.get("remote_subfolder"))
        if folder and remote_filename:
            target_file = os.path.join(folder, remote_filename)
        else:
            target_file = os.path.abspath(entry["local_path"])
            folder = os.path.dirname(target_file)
        return target_file, folder

    def _gallery_reveal_in_explorer(self, entry: dict):
        target_file, folder = self._gallery_resolve_target(entry)
        try:
            reveal_file_in_explorer(target_file, folder)
        except FileManagerError as exc:
            themed_message_box.warning(self, "Open folder", str(exc))

    def _gallery_open_full_view(self, entry: dict):
        """Click-on-thumbnail / 🔍 action: opens a QDialog scaled to
        fit 90% of the screen, preferring the real ComfyUI output file
        and falling back to the local preview-cache copy exactly like
        the original. Session 46.4b: branches on `_is_video_path` —
        a video result gets the shared embedded `VideoPlayerWidget`
        instead of a `QPixmap`, real in-place playback rather than a
        static frame."""
        target_file, _ = self._gallery_resolve_target(entry)
        if not os.path.isfile(target_file):
            target_file = entry["local_path"]
        if not os.path.isfile(target_file):
            themed_message_box.warning(self, "Open image", "This file is no longer available.")
            return

        screen = QApplication.primaryScreen().availableGeometry()
        max_w, max_h = int(screen.width() * 0.9), int(screen.height() * 0.9)

        dlg = QDialog(self)
        dlg.setWindowTitle(entry.get("display_name") or os.path.basename(target_file))
        content = QWidget()
        layout = QVBoxLayout(content)

        if _is_video_path(target_file):
            player = VideoPlayerWidget(self.colors)
            player.setFixedSize(max_w, max_h)
            layout.addWidget(player)
            FramelessDialogMixin._init_frameless_titlebar(dlg, self.colors, content)
            player.load(target_file)
            dlg.exec()
            player.stop()
            return

        pixmap = QPixmap(target_file)
        if pixmap.isNull():
            themed_message_box.warning(self, "Open image", "This image file could not be read.")
            return

        lbl = QLabel()
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Session 48.5 consistency fix: same devicePixelRatio handling
        # image_zone.py's _draw_image got — this dialog wasn't actually
        # showing the staircasing symptom (QLabel's own pixmap-display
        # path tolerates the missing ratio better than a hand-painted
        # QPainter.drawPixmap does), but it has the identical underlying
        # gap, so fixed here too rather than left as a "works by
        # accident" case.
        dpr = dlg.devicePixelRatioF() if dlg.devicePixelRatioF() > 0 else 1.0
        scaled = pixmap.scaled(
            max(int(max_w * dpr), 1), max(int(max_h * dpr), 1),
            Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        scaled.setDevicePixelRatio(dpr)
        lbl.setPixmap(scaled)
        layout.addWidget(lbl)
        FramelessDialogMixin._init_frameless_titlebar(dlg, self.colors, content)
        dlg.exec()
