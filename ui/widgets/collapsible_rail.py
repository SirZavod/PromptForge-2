"""Collapsible-width side rail — Session 17's ComfyUI-advanced column
(Resolution/Seed/Tools) needs a `>>`/`<<` control that eases the whole
column's *width* between a full panel and a thin rail, which is a
different behavior from `CollapsibleSection` (that one hides body
content but keeps the section's own width unchanged — fine for a
strip inside a vertically-scrolling column, wrong for a splitter
column that's supposed to give its horizontal space back to its
neighbors when collapsed). Kept as its own widget rather than
overloading `CollapsibleSection` with a second collapse behavior.

Session 21 change (see UIRework.md "SESSION 21"): `title` is now
optional. A rail whose visibility already implies its own identity
(e.g. the ComfyUI-advanced rail, which only ever renders once
`comfy_connected` is true) can pass `title=""` to skip the header row
entirely -- no wasted row restating something already obvious from
context. Rails that still benefit from a label (future non-ComfyUI
rails, if any) keep passing a real title and get the header exactly
as before.

Session 17.5 changes (see UIRework.md "SESSION 17.5"):
  - The rail no longer lives inside a `QSplitter` — its owner
    (`BuilderTab._build_ui`) now hosts it in a plain `QHBoxLayout`
    alongside the other two columns, so there's no draggable handle
    left to desync `self.width()` from the `_expanded` flag between
    animated toggles.
  - Arrow mapping fixed: the glyph now points the direction the
    rail's *right edge* is about to move, not the direction it just
    came from. Expanded, about-to-collapse -> the edge retreats
    rightward -> `»`. Collapsed, about-to-expand -> the edge grows
    back leftward -> `«`.
  - Expanded width 240 -> 320px (fits a realistic tool name without
    clipping, plus headroom for future per-tool parameters).
  - The toggle is now a fixed-size handle pinned to the rail's own
    left edge, vertically centered, positioned via `resizeEvent`
    rather than living in the header row next to a title label that
    disappears on collapse — so it never shifts and is easy to find
    by muscle memory.
"""
from PyQt6.QtCore import Qt, pyqtSignal, pyqtProperty, QPropertyAnimation, QEasingCurve
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QWidget


class CollapsibleRail(QWidget):
    """A fixed-width column (not user-draggable) that slides between
    `expanded_width` and `collapsed_width` on an eased
    `QPropertyAnimation`. Content lives in `body_layout`; a title
    label sits in a header row, and a fixed-position toggle handle
    sits pinned to the rail's left edge, independent of that header.

    Usage:
        rail = CollapsibleRail("ComfyUI", "comfy_rail", default_expanded=True)
        rail.body_layout.addWidget(my_content)
        rail.toggled.connect(lambda expanded: ...persist to settings...)
    """

    toggled = pyqtSignal(bool)  # emitted only on user-driven toggle (see set_expanded)

    ANIM_MS = 220
    HANDLE_SIZE = 28

    def __init__(self, title: str, settings_key: str, expanded_width: int = 320,
                 collapsed_width: int = 44, default_expanded: bool = True, parent=None):
        super().__init__(parent)
        self.settings_key = settings_key
        self._expanded_width = expanded_width
        self._collapsed_width = collapsed_width
        self._expanded = default_expanded

        outer = QVBoxLayout(self)
        # Left margin makes room for the fixed toggle handle so it
        # never overlaps the header/body content, at either width.
        outer.setContentsMargins(self.HANDLE_SIZE + 8, 0, 0, 0)
        outer.setSpacing(6)

        # Session 21: an empty title means "skip the header row
        # entirely" -- used by rails whose visibility already implies
        # their identity, so a restating label would just eat a row.
        self._has_title = bool(title)
        self.lbl_title = None
        if self._has_title:
            header = QHBoxLayout()
            self.lbl_title = QLabel(title)
            self.lbl_title.setObjectName("dim")
            header.addWidget(self.lbl_title, 1)
            outer.addLayout(header)

        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(10)
        outer.addWidget(self.body, 1)

        # Fixed-position toggle handle -- a child of `self` directly
        # (not the layout), so its screen position is set explicitly
        # in `resizeEvent` and never depends on sibling widgets'
        # visibility, unlike the old header-row button.
        self.btn_toggle = QToolButton(self)
        self.btn_toggle.setObjectName("RailHandle")
        self.btn_toggle.setFixedSize(self.HANDLE_SIZE, self.HANDLE_SIZE)
        self.btn_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        # QToolButton defaults to icon-only display; with no icon set
        # (only setText in _apply_state) that renders as a blank
        # button -- exactly the empty white square from your
        # screenshot. Force text-only so the »/« glyph actually shows.
        self.btn_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.btn_toggle.clicked.connect(self._on_toggle_clicked)

        self._anim = QPropertyAnimation(self, b"railWidth", self)
        self._anim.setDuration(self.ANIM_MS)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._anim.finished.connect(self._on_anim_finished)

        self._apply_state(animate=False)

    # -- animated width property: driving both min/max together keeps
    # the widget at a fixed width at every point of the animation, so
    # the owning layout just reflows its neighbors as this shrinks/
    # grows instead of fighting over the free space. --
    def _get_rail_width(self) -> int:
        return self.width()

    def _set_rail_width(self, value: int):
        self.setMinimumWidth(value)
        self.setMaximumWidth(value)

    railWidth = pyqtProperty(int, _get_rail_width, _set_rail_width)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Pin the handle to the rail's left edge, vertically centered
        # -- recomputed on every resize (including every animation
        # frame), so it tracks the rail's height but never its width
        # -- it's always at the same x offset regardless of expand/
        # collapse state.
        x = 6
        y = max(0, (self.height() - self.HANDLE_SIZE) // 2)
        self.btn_toggle.move(x, y)
        self.btn_toggle.raise_()

    def _on_toggle_clicked(self):
        self.set_expanded(not self._expanded)
        self.toggled.emit(self._expanded)

    def is_expanded(self) -> bool:
        return self._expanded

    def set_expanded(self, expanded: bool, animate: bool = True):
        """Programmatic or user-driven expand/collapse. Does NOT emit
        `toggled` itself — callers restoring persisted state should
        call this directly; `_on_toggle_clicked` emits after calling
        it for the user-driven path, mirroring `CollapsibleSection`'s
        split between `set_expanded` (silent) and the click handler
        (emits)."""
        self._expanded = expanded
        self._apply_state(animate=animate)

    def _apply_state(self, animate: bool):
        target = self._expanded_width if self._expanded else self._collapsed_width
        # Arrow points the direction the right edge is about to move
        # (or currently sits, at rest): expanded -> collapsing next ->
        # edge retreats rightward -> "»". Collapsed -> expanding next
        # -> edge grows back leftward -> "«".
        self.btn_toggle.setText("»" if self._expanded else "«")
        self.btn_toggle.setToolTip("Collapse" if self._expanded else "Expand")
        if self.lbl_title is not None:
            self.lbl_title.setVisible(self._expanded)
        if not animate:
            self._set_rail_width(target)
            self.body.setVisible(self._expanded)
            return
        if self._expanded:
            # Expanding: show body immediately so its content is
            # already there once the width animation catches up,
            # rather than popping in after the fact.
            self.body.setVisible(True)
        self._anim.stop()
        self._anim.setStartValue(self.width())
        self._anim.setEndValue(target)
        self._anim.start()

    def _on_anim_finished(self):
        # Collapsing: hide body only once the column has actually
        # reached its thin-rail width, so content doesn't visibly
        # clip/reflow mid-animation.
        if not self._expanded:
            self.body.setVisible(False)
