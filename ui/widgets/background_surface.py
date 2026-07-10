"""Session 40 — the paint surface behind everything else in the window.

`MainWindow`'s central widget is now one of these instead of a plain
`QWidget`. Why not just a QSS `background-image` rule on `#CentralBg`
the way every other themed surface in `ui/theme.py` works: QSS's
`background-image` only tiles or pins at a fixed corner, it has no
"stretch to fill" or "cover, cropping the overflow" mode, and both of
those are needed here (see additionalfeatures.md SESSION 40, "Fit
mode"). A real `paintEvent` override is the direct way to get
stretch/fit+crop/tile with an arbitrary window size, so that's what
this is.

Only paints the image (or, with none set, a flat fill). Every card,
sidebar, tab page etc. still gets its own opaque background from
`theme.py`'s QSS same as before — this widget only shows through the
outer margins/gaps around that content, which is exactly the "behind
the sidebar/page stack, not literally every card" scope the plan
called for (Session 40 follow-up widened those specific surfaces to
transparent so the image is actually visible there).

Session 40.1 — blur: there's no live "blur whatever's behind this
particular translucent card" compositor pass in QWidgets (that's a
QML/compositor thing, not a raster-paint thing) — trying to fake that
per-card, per-frame would mean re-grabbing and re-blurring a pixmap
under every card on every repaint/resize, which does not scale. Instead
this blurs the *source* background image itself, once, whenever the
image or blur radius changes (`_rebuild_blurred_pixmap` — a Pillow
Gaussian blur, cheap because it only depends on the image's own
resolution, not the window size or how many cards sit on top). The
existing stretch/fit_crop/tile drawing in `paintEvent` then just draws
that pre-blurred pixmap exactly like it drew the sharp one — same
per-frame cost as before, blur or not.
"""
from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QBrush, QColor, QImage, QPainter, QPixmap
from PyQt6.QtWidgets import QWidget

try:
    from PIL import Image, ImageFilter
    _PIL_AVAILABLE = True
except Exception:
    Image = None
    ImageFilter = None
    _PIL_AVAILABLE = False

FIT_MODES = ("stretch", "fit_crop", "tile")


def _blur_pixmap(pixmap: QPixmap, radius: int) -> QPixmap:
    """Gaussian-blurs `pixmap` via Pillow and returns a new QPixmap.
    Returns `pixmap` unchanged if Pillow isn't available or `radius` is
    0 — a missing optional dependency degrades to "no blur", not a
    crash."""
    if not _PIL_AVAILABLE or radius <= 0:
        return pixmap
    qimg = pixmap.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    w, h = qimg.width(), qimg.height()
    stride = qimg.bytesPerLine()
    ptr = qimg.constBits()
    ptr.setsize(qimg.sizeInBytes())
    buf = bytes(ptr)
    pil_img = Image.frombuffer("RGBA", (w, h), buf, "raw", "RGBA", stride, 1)
    blurred = pil_img.filter(ImageFilter.GaussianBlur(radius=radius))
    blurred_bytes = blurred.tobytes("raw", "RGBA")
    out_img = QImage(blurred_bytes, w, h, QImage.Format.Format_RGBA8888).copy()
    return QPixmap.fromImage(out_img)


class BackgroundSurface(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._source_pixmap: QPixmap | None = None  # always the sharp original
        self._pixmap: QPixmap | None = None  # what actually gets painted (blurred or not)
        self._fit_mode = "stretch"
        self._opacity = 100  # 0-100, brightness toward black — a convenience
        # slider, not automatic legibility protection (see the plan's
        # explicit "not our problem" call).
        self._blur_radius = 0
        self._bg_color = QColor("#1e1f26")
        self._loaded_path = None
        self._loaded_radius = None

    def set_bg_color(self, hex_color: str):
        """Flat fallback fill — used whenever no background image is
        set, and as the correct empty state (not a leftover image) once
        Custom is deselected."""
        self._bg_color = QColor(hex_color)
        self.update()

    def set_background(self, path: str | None, fit_mode: str = "stretch",
                        opacity: int = 100, blur_radius: int = 0):
        """`path=None` clears the image back to the flat fill. A path
        that fails to load (missing/corrupt file — the Session 40
        "moved/deleted on disk" case) also falls back to the flat fill
        rather than raising, so a stale settings entry can't crash
        startup."""
        self._fit_mode = fit_mode if fit_mode in FIT_MODES else "stretch"
        self._opacity = max(0, min(100, opacity))
        new_radius = max(0, blur_radius)
        if not path:
            self._source_pixmap = None
            self._pixmap = None
            self._blur_radius = new_radius
            self._loaded_path = None
            self._loaded_radius = None
            self.update()
            return
        if path == self._loaded_path and new_radius == self._loaded_radius:
            # Same image, same blur — only fit-mode/opacity may have
            # changed, both of which are applied at paint time, not
            # here. Skip the decode+blur entirely.
            self.update()
            return
        pm = QPixmap(path)
        if pm.isNull():
            self._source_pixmap = None
            self._pixmap = None
            self._blur_radius = new_radius
            self._loaded_path = None
            self._loaded_radius = None
            self.update()
            return
        self._source_pixmap = pm
        self._blur_radius = new_radius
        self._pixmap = _blur_pixmap(pm, new_radius)
        self._loaded_path = path
        self._loaded_radius = new_radius
        self.update()

    def has_image(self) -> bool:
        return self._pixmap is not None

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), self._bg_color)
        if self._pixmap is not None:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            if self._fit_mode == "stretch":
                painter.drawPixmap(self.rect(), self._pixmap, QRectF(self._pixmap.rect()).toRect())
            elif self._fit_mode == "tile":
                painter.drawTiledPixmap(self.rect(), self._pixmap)
            else:  # fit_crop — scale to cover, center-crop the overflow
                scaled = self._pixmap.scaled(
                    self.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation)
                x = (scaled.width() - self.width()) // 2
                y = (scaled.height() - self.height()) // 2
                painter.drawPixmap(0, 0, scaled, x, y, self.width(), self.height())
            if self._opacity < 100:
                dim = QColor(0, 0, 0, int((100 - self._opacity) / 100 * 255))
                painter.fillRect(self.rect(), QBrush(dim))
        painter.end()

