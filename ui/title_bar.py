"""Custom title bar (Session 38, Option B) — replaces the OS title bar
on the now-frameless `MainWindow` with a hand-built strip styled from
the same `colors` dict every other themed surface in the app already
uses, so it automatically follows dark/light (and, once Session 39
lands, a custom accent) with no special-casing here.

Scope note: this widget only owns the strip itself (icon, title,
minimize/maximize-restore/close, dragging, double-click-to-maximize).
Manual edge-resize lives on `MainWindow` itself (a frameless window has
no OS-drawn resize border to hit-test against, and that logic needs the
whole window rect, not just this strip). Aero Snap / Windows 11 Snap
Layouts (native `WM_NCHITTEST`/`WM_NCCALCSIZE` handling) and the DWM
shadow/rounded-corner calls are **not** done in this pass -- per the
plan's own step 1 ("prototype frameless + custom strip first, dragging
only, before sinking time into snap/resize edge cases"), and because
verifying either needs a real Windows 10 *and* 11 machine to click
through, which isn't available in this environment. Both are flagged
as the next step once the visual direction here is confirmed live.
"""
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QWidget

HEIGHT = 36


class TitleBar(QWidget):
    def __init__(self, window, colors: dict, parent=None, close_only: bool = False):
        """`close_only=True` (Session 43) skips the minimize/maximize
        buttons entirely -- for secondary/utility dialogs (Guide, the
        Gallery full-view image popup) where restoring/maximizing a
        modal dialog isn't a meaningful action. `MainWindow` itself
        keeps the default three-button strip."""
        super().__init__(parent)
        self._window = window
        self._drag_offset = None
        self._close_only = close_only
        self.setFixedHeight(HEIGHT)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setObjectName("TitleBar")

        row = QHBoxLayout(self)
        row.setContentsMargins(10, 0, 0, 0)
        row.setSpacing(8)

        self.lbl_icon = QLabel()
        self.lbl_icon.setFixedSize(16, 16)
        self.lbl_icon.setScaledContents(True)
        row.addWidget(self.lbl_icon)

        self.lbl_title = QLabel(window.windowTitle())
        self.lbl_title.setObjectName("TitleBarText")
        row.addWidget(self.lbl_title)

        row.addStretch(1)

        self.btn_minimize = None
        self.btn_maximize = None
        if not close_only:
            self.btn_minimize = self._make_button("\u2013", "Minimize")
            self.btn_minimize.clicked.connect(window.showMinimized)
            row.addWidget(self.btn_minimize)

            self.btn_maximize = self._make_button("\u25a1", "Maximize")
            self.btn_maximize.clicked.connect(self._toggle_maximize)
            row.addWidget(self.btn_maximize)

        self.btn_close = self._make_button("\u2715", "Close")
        self.btn_close.setObjectName("TitleBarCloseButton")
        self.btn_close.clicked.connect(window.close)
        row.addWidget(self.btn_close)

        self.set_colors(colors)

    def _make_button(self, glyph: str, tooltip: str) -> QPushButton:
        btn = QPushButton(glyph)
        btn.setObjectName("TitleBarButton")
        btn.setToolTip(tooltip)
        btn.setFixedSize(44, HEIGHT)
        btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        btn.setCursor(Qt.CursorShape.ArrowCursor)
        return btn

    # ------------------------------------------------------------------
    def set_window_title(self, title: str):
        self.lbl_title.setText(title)

    def set_window_icon(self, icon: QIcon):
        if not icon.isNull():
            self.lbl_icon.setPixmap(icon.pixmap(16, 16))

    def set_colors(self, colors: dict):
        self.setStyleSheet(f"""
            #TitleBar {{
                background-color: {colors['bg_alt']};
                border-bottom: 1px solid {colors['border']};
            }}
            #TitleBarText {{
                color: {colors['fg_dim']};
                font-size: 12px;
            }}
            #TitleBarButton {{
                background-color: transparent;
                border: none;
                color: {colors['fg_dim']};
                font-size: 14px;
            }}
            #TitleBarButton:hover {{
                background-color: {colors['bg_card']};
                color: {colors['fg']};
            }}
            #TitleBarCloseButton:hover {{
                background-color: {colors['danger']};
                color: {colors['accent_text']};
            }}
        """)

    def sync_maximize_icon(self):
        if self.btn_maximize is None:
            return
        maximized = self._window.isMaximized()
        self.btn_maximize.setText("\u25a3" if maximized else "\u25a1")
        self.btn_maximize.setToolTip("Restore" if maximized else "Maximize")

    def _toggle_maximize(self):
        if self._close_only:
            return
        if self._window.isMaximized():
            self._window.showNormal()
        else:
            self._window.showMaximized()

    # ------------------------------------------------------------------
    # Dragging. Left button down anywhere on the strip except the three
    # control buttons (which consume their own clicks and never reach
    # here) starts a drag; double-click toggles maximize/restore, same
    # as a native title bar.
    def mousePressEvent(self, event):
        # Session 50: hand dragging off to the compositor via Qt's
        # native `startSystemMove()` instead of computing window
        # positions ourselves. `self._window.move(...)` (the old
        # approach, still used below as a fallback) relies on a client
        # being allowed to reposition its own top-level window -- true
        # on Windows, macOS, and X11, but deliberately *not* true under
        # native Wayland sessions (GNOME/KDE Wayland, not XWayland),
        # where only the compositor is allowed to move windows and
        # `startSystemMove()` is the sanctioned way to ask it to. Using
        # this one call covers every platform identically -- no
        # `sys.platform` branch needed -- and isn't a Linux-only patch,
        # it's simply the more correct way to do this everywhere.
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self._window.windowHandle()
            if handle is not None and hasattr(handle, "startSystemMove"):
                # Maximized windows still get the restore-under-cursor
                # treatment first so the grab point matches the
                # pre-maximize behavior; startSystemMove() itself
                # doesn't know about that, it just takes over from
                # wherever the window already is.
                if self._window.isMaximized():
                    cursor_ratio = event.position().x() / max(1, self.width())
                    self._window.showNormal()
                    new_w = self._window.width()
                    self._window.move(
                        event.globalPosition().toPoint().x() - int(new_w * cursor_ratio),
                        self._window.y(),
                    )
                handle.startSystemMove()
                self._drag_offset = None
                super().mousePressEvent(event)
                return
            # Fallback for the (currently no longer expected, but kept
            # cheap to retain) case of a Qt build without
            # `startSystemMove()` available -- old manual-move behavior.
            self._drag_offset = event.globalPosition().toPoint() - self._window.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            if self._window.isMaximized():
                # Restore-under-cursor: un-maximize first, then keep the
                # same relative grab point so the window doesn't jump.
                cursor_ratio = event.position().x() / max(1, self.width())
                self._window.showNormal()
                new_w = self._window.width()
                self._drag_offset = QPoint(int(new_w * cursor_ratio), self._drag_offset.y())
            self._window.move(event.globalPosition().toPoint() - self._drag_offset)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._toggle_maximize()
        super().mouseDoubleClickEvent(event)
