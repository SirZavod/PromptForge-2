"""Image preview/drop-zone widgets — ported from `_ImageCanvasBase`/
`ImageDropZone`/`ResultImageViewer` (Tkinter Canvas subclasses) in the
original monolith.

One deliberate, intentional deviation from a verbatim port: the
original used Pillow (PIL.Image + ImageTk.PhotoImage) to decode and
LANCZOS-resize every frame, including live TAESD preview bytes
streamed during generation. Qt's own QPixmap/QImage already decodes
every format this app uses (jpg/png/webp/bmp/gif) and
`Qt.TransformationMode.SmoothTransformation` gives a comparable resize
quality, so this module has zero Pillow dependency — one less
moderately expensive decode/resize step per frame during a live
generation stream, and one less import for a widget that has no
business needing image-processing library, as opposed to
backend/file_manager.py's process_and_store_image, which genuinely
needs Pillow's save-quality/optimize controls and stays exactly as
ported there.

Geometry/placeholder-drawing logic (the MIN_PERCENT/MAX_PERCENT/
DEFAULT_PERCENT panel-height scheme, the 0.92 max-area-ratio
proportional fit, the placeholder graphics) is a faithful, deliberate
port of the original's numbers and reasoning — see apply_panel_height's
docstring below, which keeps the original's explanation of why the
ceiling clamp matters almost word for word, since the bug it prevents
is real and non-obvious.
"""
import os

from PyQt6.QtCore import Qt, QRectF, QPointF, pyqtSignal
from PyQt6.QtGui import QPainter, QPixmap, QColor, QPen, QFont
from PyQt6.QtWidgets import QLabel, QFileDialog

from backend.constants import IMAGE_EXTENSIONS, VIDEO_EXTENSIONS
from ui.color_utils import qcolor_from_token


class ImageZoneBase(QLabel):
    """Shared rounded-card / placeholder / proportional-fit drawing logic
    for both the interactive Library drop zone and the read-only ComfyUI
    result viewer. Not used directly — subclasses must implement
    `_draw_placeholder`."""

    MIN_PERCENT = 12
    MAX_PERCENT = 65
    DEFAULT_PERCENT = 38
    MIN_PX = 130
    MAX_PX = 1400

    def __init__(self, colors, percent=None, parent=None):
        super().__init__(parent)
        self.colors = colors
        self.percent = percent if percent else self.DEFAULT_PERCENT

        self._pixmap = None
        self._has_image = False
        self._video_filename = None  # 46.3/46.4: set instead of _pixmap
        self._video_player = None  # 46.4b: lazily-created embedded VideoPlayerWidget
        self._last_panel_height = 0

        self.setText("")
        self.setMinimumHeight(self.MIN_PX)

    # ---------------------------------------------------------- public --
    def set_colors(self, colors):
        self.colors = colors
        if self._video_player is not None:
            self._video_player.set_colors(colors)
        self.update()

    def set_percent(self, percent):
        self.percent = max(self.MIN_PERCENT, min(self.MAX_PERCENT, percent))
        if self._last_panel_height:
            self.apply_panel_height(self._last_panel_height)

    def apply_panel_height(self, panel_height):
        """Sets the widget's pixel height according to where `percent`
        sits between MIN_PERCENT and MAX_PERCENT, interpolating from
        MIN_PX (at MIN_PERCENT) up to the full available budget (at
        MAX_PERCENT) — clamped to [MIN_PX, MAX_PX] for normal usability,
        but never exceeding `panel_height` itself.

        `panel_height` is the caller's actual available budget (e.g. the
        owning tab passes in "what's left after the slider row / status
        row / Open folder button"). The ceiling is whichever is smaller:
        MAX_PX, or the budget we were actually given — a very short
        window flooring at MIN_PX regardless would claim more space than
        exists and push those other rows out of view again, which is the
        exact bug this whole panel_height/chrome scheme exists to
        prevent.

        Earlier revisions computed `target` as a flat `percent` fraction
        of `panel_height` directly (i.e. capped at MAX_PERCENT% of the
        budget no matter what). That meant even at the slider's maximum
        position, (100 - MAX_PERCENT)% of the budget was always left on
        the table — a handful of pixels on a modest window, but a large,
        visibly wasted gap below the image on a tall/maximized one. The
        slider's actual job is "how big should the preview be, from
        small up to as-big-as-it-can-be" — so MAX_PERCENT should mean
        *fills the budget*, not *65% of it*.
        """
        self._last_panel_height = panel_height
        ceiling = min(self.MAX_PX, max(panel_height, 1))
        span = self.MAX_PERCENT - self.MIN_PERCENT
        frac = (self.percent - self.MIN_PERCENT) / span if span > 0 else 1.0
        frac = max(0.0, min(1.0, frac))
        target = int(self.MIN_PX + frac * (ceiling - self.MIN_PX))
        target = max(min(self.MIN_PX, ceiling), min(target, ceiling))
        if abs(target - self.height()) > 1:
            self.setFixedHeight(target)
            self.update()

    def show_placeholder(self):
        self._pixmap = None
        self._has_image = False
        self._video_filename = None
        self._hide_video_player()
        self.update()

    def show_video_placeholder(self, filename):
        """Deprecated as of Session 46.4b — kept only as a thin
        backward-compatible alias for `show_video_path(None, filename)`,
        i.e. "we know it's a video but have no file to actually play"
        (the pre-46.4b "ugly is fine" state, and still the right
        fallback if a caller somehow only has a filename, not a local
        path). New call sites should use `show_video_path` directly,
        which is what actually gets an embedded player on screen."""
        self.show_video_path(None, filename)

    def show_video_path(self, path, filename=None):
        """Session 46.4b: a ComfyUI result that's a video, shown via
        the shared embedded `VideoPlayerWidget` (see
        `ui/widgets/video_player.py`) rather than the placeholder text
        46.4 shipped as a stopgap. `path` is the local on-disk copy
        already saved by the caller (Builder's `_on_comfy_video_bytes`
        already writes one via `save_comfy_preview_image` before this
        is ever called) — if it's missing/unplayable, the player
        widget's own `playback_unavailable` signal degrades to a
        themed "can't play, use Open folder" message rather than this
        method silently doing nothing.
        Deliberately a separate state from `_pixmap`/`_has_image`
        rather than trying to make QPixmap show something video-shaped
        (it can't decode video frames at all), so `paintEvent` still
        branches on which of the two is set — the video state's actual
        content now lives in the embedded child widget, not in
        anything painted directly onto this QLabel.
        `filename` (the raw remote filename ComfyUI reported) is kept
        for identification purposes even though it's no longer painted
        as placeholder text — callers that don't have it can omit it."""
        self._pixmap = None
        self._has_image = False
        self._video_filename = filename or (os.path.basename(path) if path else "")
        player = self._ensure_video_player()
        player.setVisible(True)
        self._position_video_player()
        player.load(path)
        self.update()

    def show_image_path(self, path):
        if not path:
            self.show_placeholder()
            return
        pixmap = QPixmap(path)
        if pixmap.isNull():
            self.show_placeholder()
            return
        self._pixmap = pixmap
        self._has_image = True
        self._video_filename = None
        self._hide_video_player()
        self.update()

    def show_image_bytes(self, img_bytes):
        """Like show_image_path, but for an in-memory encoded image
        (JPEG/PNG) rather than a file on disk — used for live TAESD/
        latent preview frames streamed over ComfyUI's websocket during
        sampling, which never touch the filesystem.

        Deliberately does NOT fall back to show_placeholder() on
        failure: these frames arrive in a rapid stream mid-generation,
        so a single truncated/corrupt one should just be skipped,
        leaving whatever was already on screen, rather than flashing
        the placeholder.
        """
        if not img_bytes:
            return
        pixmap = QPixmap()
        if pixmap.loadFromData(img_bytes) and not pixmap.isNull():
            self._pixmap = pixmap
            self._has_image = True
            self._video_filename = None
            self._hide_video_player()
            self.update()

    # ------------------------------------------------------ video player --
    def _ensure_video_player(self):
        """Lazily creates the embedded `VideoPlayerWidget` — most
        instances of this widget (every `ImageDropZone`, and any
        `ResultImageViewer` session that never produces a video result)
        never need one at all, so this avoids constructing a
        `QMediaPlayer` up front for widgets that will never show one."""
        if self._video_player is None:
            from ui.widgets.video_player import VideoPlayerWidget
            self._video_player = VideoPlayerWidget(self.colors, parent=self)
        return self._video_player

    def _position_video_player(self):
        if self._video_player is None:
            return
        margin = 10
        self._video_player.setGeometry(
            margin, margin,
            max(self.width() - 2 * margin, 10),
            max(self.height() - 2 * margin, 10))

    def _hide_video_player(self):
        if self._video_player is not None:
            self._video_player.stop()
            self._video_player.setVisible(False)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_video_player()

    # ------------------------------------------------------------ draw --
    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        margin = 6

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(qcolor_from_token(self.colors["bg_card"]))
        painter.drawRoundedRect(margin, margin, w - 2 * margin, h - 2 * margin, 18, 18)

        if self._has_image and self._pixmap is not None:
            self._draw_image(painter, w, h)
        elif self._video_filename is not None:
            # 46.4b: the actual content is the embedded VideoPlayerWidget
            # sitting on top of this card (see _ensure_video_player /
            # _position_video_player) — nothing further to paint here
            # beyond the card background already drawn above.
            pass
        else:
            self._draw_placeholder(painter, w, h)
        painter.end()

    def _draw_image(self, painter, w, h, max_area_ratio=0.92):
        # max_area_ratio used to be 0.60, which capped the *picture* at
        # 60% of the widget's area no matter how tall the widget itself
        # grew. Combined with width also being a limiting factor for
        # portrait-ish images, that made the "Size" slider feel broken
        # near its upper end — moving it kept growing the (invisible)
        # widget but the visible picture barely changed. 0.92 leaves a
        # thin border around the image while letting it actually fill
        # the space the slider asked for.
        margin = 6
        avail_w = max(w - margin * 2, 10)
        avail_h = max(h - margin * 2, 10)

        img_w, img_h = self._pixmap.width(), self._pixmap.height()
        if img_w <= 0 or img_h <= 0:
            return
        fit_scale = min(avail_w / img_w, avail_h / img_h)
        fitted_w, fitted_h = img_w * fit_scale, img_h * fit_scale

        budget_area = avail_w * avail_h * max_area_ratio
        fitted_area = fitted_w * fitted_h
        if fitted_area > budget_area and fitted_area > 0:
            area_scale = (budget_area / fitted_area) ** 0.5
            fitted_w *= area_scale
            fitted_h *= area_scale

        fitted_w = max(int(fitted_w), 1)
        fitted_h = max(int(fitted_h), 1)

        # Session 48.5 fix: scale to the widget's actual PHYSICAL pixel
        # resolution (fitted_w/h * devicePixelRatioF), then tag the
        # result with that same ratio via setDevicePixelRatio so Qt
        # draws it back down to fitted_w x fitted_h LOGICAL pixels using
        # the extra physical detail it was just given. Every QPixmap
        # this widget scales used to be produced at a flat 1.0 device
        # pixel ratio regardless of the screen's real scale factor — on
        # a >100%-scaled display (e.g. Windows at 150%), that meant the
        # OS/Qt compositor had to stretch an already-fully-scaled,
        # already-out-of-headroom pixmap a second time to cover the
        # actual physical pixels the screen needed, producing visible
        # staircasing/blockiness with no relation to the source file's
        # own resolution. See additionalfeatures.md SESSION 48.5 for
        # the full diagnosis (confirmed by a real 150%-vs-100% test,
        # not just reasoning about it) and why this specifically only
        # showed up through this hand-painted `QPainter.drawPixmap`
        # path (Library's editor card) and not through `ResultImageViewer`
        # (48.3's own bug kept it too small to visibly stretch) or
        # Gallery's full-view (`QLabel.setPixmap`, not this method at
        # all).
        dpr = self.devicePixelRatioF() if self.devicePixelRatioF() > 0 else 1.0
        scaled = self._pixmap.scaled(
            max(int(fitted_w * dpr), 1), max(int(fitted_h * dpr), 1),
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        scaled.setDevicePixelRatio(dpr)
        x = (w - fitted_w) / 2
        y = (h - fitted_h) / 2
        painter.drawPixmap(int(x), int(y), scaled)

    def _draw_placeholder(self, painter, w, h):
        """Overridden by subclasses for their specific placeholder
        graphics/text."""
        raise NotImplementedError

    def _draw_video_ready(self, painter, w, h):
        """Deprecated as of Session 46.4b — `paintEvent` no longer
        calls this (the video state's content is now the embedded
        `VideoPlayerWidget`, not painted text). Left in place, unused,
        since it's still exactly the right fallback drawing if a
        future caller ever needs a text-only "video ready" placeholder
        again (e.g. before `_ensure_video_player` has created its
        child widget)."""
        painter.setPen(qcolor_from_token(self.colors["fg"]))
        painter.setFont(QFont("Segoe UI", 11, QFont.Weight.DemiBold))
        title_rect = QRectF(0, h / 2 - 34, w, 24)
        painter.drawText(title_rect, Qt.AlignmentFlag.AlignCenter, "🎬 Video ready")

        painter.setPen(qcolor_from_token(self.colors["fg_dim"]))
        painter.setFont(QFont("Segoe UI", 9))
        name = self._video_filename or ""
        detail_rect = QRectF(20, h / 2 - 6, max(w - 40, 10), 22)
        painter.drawText(detail_rect, Qt.AlignmentFlag.AlignCenter, name)

        painter.setFont(QFont("Segoe UI", 9))
        hint_rect = QRectF(20, h / 2 + 18, max(w - 40, 10), 22)
        painter.drawText(hint_rect, Qt.AlignmentFlag.AlignCenter,
                          "In-app preview lands in a later session — use \u201cOpen folder\u201d for now")


class ImageDropZone(ImageZoneBase):
    """A rounded, dashed-border preview/drop zone for a library entry's
    image.

    Two visual states:
      * empty   -> centered "UPLOAD IMAGE / drag 'n drop or click to
                   browse" placeholder text inside a soft dashed
                   rounded rectangle.
      * filled  -> the loaded image, proportionally scaled to fit
                   within the zone and centered both horizontally and
                   vertically.

    Interactions:
      * Click anywhere in the zone -> QFileDialog.getOpenFileName(...)
      * Drag'n'drop a file onto the zone (native Qt drag'n'drop, no
        extra dependency needed — unlike the original, which required
        the optional tkinterdnd2 package and silently lost drag'n'drop
        entirely without it).

    The zone itself never touches disk — it only reports the picked
    path via the `file_chosen` signal; the owner (LibraryTab, a later
    session) decides what to do with it (convert, resize, save, attach
    to the right entry, via backend.process_and_store_image).
    """

    file_chosen = pyqtSignal(str)
    unsupported_file_dropped = pyqtSignal(str)

    def __init__(self, colors, percent=None, parent=None):
        super().__init__(colors, percent=percent, parent=parent)
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    # --------------------------------------------------------- internal --
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # Session 48.4: the picker now also offers video files —
            # LibraryTab.handle_image_drop (the file_chosen callback)
            # already branches on the picked path's own extension to
            # decide image-vs-video handling, so this widget doesn't
            # need to know which kind was picked; it just needs to stop
            # filtering videos out of the dialog itself.
            img_patterns = " ".join(f"*{ext}" for ext in IMAGE_EXTENSIONS)
            vid_patterns = " ".join(f"*{ext}" for ext in VIDEO_EXTENSIONS)
            all_patterns = f"{img_patterns} {vid_patterns}"
            path, _ = QFileDialog.getOpenFileName(
                self, "Choose an image or video", "",
                f"Image/Video files ({all_patterns});;"
                f"Image files ({img_patterns});;"
                f"Video files ({vid_patterns});;All files (*.*)")
            if path:
                self.file_chosen.emit(path)
        super().mousePressEvent(event)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if not urls:
            event.ignore()
            return
        path = urls[0].toLocalFile()
        if path and (_has_image_extension(path) or _has_video_extension(path)):
            self.file_chosen.emit(path)
        elif path:
            # Caller's job to show a QMessageBox warning — this widget
            # has no business popping its own dialogs.
            self.unsupported_file_dropped.emit(path)
        event.acceptProposedAction()

    # ------------------------------------------------------------ draw --
    def _draw_placeholder(self, painter, w, h):
        margin, inset = 6, 14
        pen = QPen(qcolor_from_token(self.colors["border"]))
        pen.setWidth(2)
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(
            margin + inset, margin + inset,
            w - 2 * (margin + inset), h - 2 * (margin + inset), 14, 14)

        cx, cy = w / 2, h / 2
        icon_r = 16
        icon_pen = QPen(qcolor_from_token(self.colors["fg_dim"]))
        icon_pen.setWidth(2)
        icon_pen.setStyle(Qt.PenStyle.SolidLine)
        painter.setPen(icon_pen)
        painter.drawEllipse(QPointF(cx, cy - 28), icon_r, icon_r)
        painter.drawLine(QPointF(cx, cy - 28 - 7), QPointF(cx, cy - 28 + 7))
        painter.drawLine(QPointF(cx - 7, cy - 28), QPointF(cx + 7, cy - 28))

        painter.setPen(qcolor_from_token(self.colors["fg_dim"]))
        painter.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        painter.drawText(QRectF(0, cy, w, 24), Qt.AlignmentFlag.AlignHCenter, "UPLOAD IMAGE")
        painter.setFont(QFont("Segoe UI", 9))
        painter.drawText(QRectF(0, cy + 22, w, 20), Qt.AlignmentFlag.AlignHCenter,
                          "drag \u2019n drop or click to browse")


class ResultImageViewer(ImageZoneBase):
    """Read-only counterpart to ImageDropZone — no click-to-browse, no
    drag'n'drop. Used in the Builder tab to show the latest image that
    came back from a ComfyUI generation. The same proportional-fit /
    rounded-card drawing as the Library preview, just a different (and
    much plainer) empty-state placeholder.

    Overrides the inherited percent range: this viewer sits in its own
    full-height pane (the whole right-hand column of the Builder tab),
    not squeezed alongside a tags box and a handful of form fields like
    the Library zone is, so it can comfortably grow much larger.
    """

    MIN_PERCENT = 15
    MAX_PERCENT = 68
    DEFAULT_PERCENT = 45

    def _draw_placeholder(self, painter, w, h):
        painter.setPen(qcolor_from_token(self.colors["fg_dim"]))
        painter.setFont(QFont("Segoe UI", 10))
        painter.drawText(QRectF(0, 0, w, h), Qt.AlignmentFlag.AlignCenter,
                          "No image generated yet")


def _has_image_extension(path):
    lower = path.lower()
    return any(lower.endswith(ext) for ext in IMAGE_EXTENSIONS)


def _has_video_extension(path):
    """Session 48.4 companion to _has_image_extension — same
    extension-only classification VIDEO_EXTENSIONS is used for
    everywhere else (gallery_tab.py's _is_video_path, etc.)."""
    lower = path.lower()
    return any(lower.endswith(ext) for ext in VIDEO_EXTENSIONS)
