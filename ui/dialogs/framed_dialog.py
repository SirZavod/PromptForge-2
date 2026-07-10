"""Session 43: shared frameless + themed-title-bar treatment for
secondary `QDialog` windows (Guide, Gallery full-view image popup),
extracted out of what `MainWindow` already does for itself in
Session 38.

Deliberately the *safe* subset only -- `FramelessWindowHint` + the
existing `TitleBar` widget (in its close-only variant, since a modal
utility dialog restoring/maximizing is an unusual pattern) + manual
mouse-driven dragging on the strip (`TitleBar` already does this
itself). Nothing here touches `nativeEvent`/`WM_NCHITTEST` -- Session
41's Snap/native-message handling has no meaningful use case on a
modal dialog (`dlg.exec()` blocks the rest of the app, so there's no
"drag to a screen edge and keep working elsewhere" scenario), and
there's no reason to bring that still-newer code path near a plain
utility window.

Manual edge-resize is included anyway for consistency with how
`MainWindow` behaves, and because the Gallery viewer scales an image
to 90% of the screen -- a user might reasonably want to shrink that.
It's a much smaller version of `MainWindow`'s resize handling since a
dialog doesn't need the app-wide `eventFilter` trick (a dialog has far
fewer child widgets the cursor could be over): each dialog installs
this mixin's `eventFilter` on itself only.

Both dialogs are modal (`dlg.exec()`), so colors are read once at
construction time via `set_colors()` -- there's no live theme change
possible while a modal dialog is open, since Settings (the only place
theme changes) is unreachable behind it.

Usage: a `QDialog` subclass builds its own content onto a plain
`QWidget` (instead of laying it out directly on `self`), then calls
`self._init_frameless_titlebar(colors, content_widget)` once that
widget is built.
"""
from PyQt6.QtCore import QEvent, QRect, Qt
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from ui.title_bar import TitleBar

RESIZE_MARGIN = 6


class FramelessDialogMixin:
    """Mixed into a `QDialog` subclass. Call `_init_frameless_titlebar`
    once, after the dialog's own content layout is already built on
    `self` (or on a content widget passed in via `content_widget`)."""

    def _init_frameless_titlebar(self, colors: dict, content_widget: QWidget):
        """`content_widget` should already contain everything the
        dialog's own `__init__` built (i.e. build normal dialog content
        onto a plain `QWidget`, then pass that widget here instead of
        laying it out directly on `self`)."""
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.FramelessWindowHint)

        self._resize_edge = None
        self._resize_start_geo = None
        self._resize_start_pos = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.title_bar = TitleBar(self, colors, close_only=True)
        self.title_bar.set_window_icon(self.windowIcon())
        outer.addWidget(self.title_bar)
        outer.addWidget(content_widget, 1)

        self.installEventFilter(self)

    # ------------------------------------------------------------------
    # Manual edge-resize -- same recipe as MainWindow, scoped to this
    # single dialog rather than the whole app.
    def _resize_edge_at(self, local_pos) -> str | None:
        w, h = self.width(), self.height()
        x, y = local_pos.x(), local_pos.y()
        if not (-RESIZE_MARGIN <= x <= w + RESIZE_MARGIN and -RESIZE_MARGIN <= y <= h + RESIZE_MARGIN):
            return None
        left = x <= RESIZE_MARGIN
        right = x >= w - RESIZE_MARGIN
        top = y <= RESIZE_MARGIN
        bottom = y >= h - RESIZE_MARGIN
        if top and left:
            return "top_left"
        if top and right:
            return "top_right"
        if bottom and left:
            return "bottom_left"
        if bottom and right:
            return "bottom_right"
        if left:
            return "left"
        if right:
            return "right"
        if top:
            return "top"
        if bottom:
            return "bottom"
        return None

    _EDGE_CURSORS = {
        "left": Qt.CursorShape.SizeHorCursor, "right": Qt.CursorShape.SizeHorCursor,
        "top": Qt.CursorShape.SizeVerCursor, "bottom": Qt.CursorShape.SizeVerCursor,
        "top_left": Qt.CursorShape.SizeFDiagCursor, "bottom_right": Qt.CursorShape.SizeFDiagCursor,
        "top_right": Qt.CursorShape.SizeBDiagCursor, "bottom_left": Qt.CursorShape.SizeBDiagCursor,
    }

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            edge = self._resize_edge_at(self.mapFromGlobal(event.globalPosition().toPoint()))
            if edge:
                self._resize_edge = edge
                self._resize_start_geo = self.geometry()
                self._resize_start_pos = event.globalPosition().toPoint()
                return True
        elif event.type() == QEvent.Type.MouseMove:
            global_pos = event.globalPosition().toPoint()
            if self._resize_edge:
                self._apply_resize(global_pos)
                return True
            edge = self._resize_edge_at(self.mapFromGlobal(global_pos))
            self.setCursor(self._EDGE_CURSORS[edge]) if edge else self.unsetCursor()
        elif event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
            if self._resize_edge:
                self._resize_edge = None
                return True
        return super().eventFilter(obj, event)

    def _apply_resize(self, global_pos):
        dx = global_pos.x() - self._resize_start_pos.x()
        dy = global_pos.y() - self._resize_start_pos.y()
        geo = QRect(self._resize_start_geo)
        min_w, min_h = self.minimumWidth(), self.minimumHeight()

        if "left" in self._resize_edge:
            new_left = min(geo.left() + dx, geo.right() - min_w)
            geo.setLeft(new_left)
        elif "right" in self._resize_edge:
            geo.setRight(max(geo.right() + dx, geo.left() + min_w))

        if "top" in self._resize_edge:
            new_top = min(geo.top() + dy, geo.bottom() - min_h)
            geo.setTop(new_top)
        elif "bottom" in self._resize_edge:
            geo.setBottom(max(geo.bottom() + dy, geo.top() + min_h))

        self.setGeometry(geo)
