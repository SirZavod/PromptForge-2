"""Small clipboard icon button used by History's per-field copy (Session 53).

Replaces the Session 35 click-anywhere `CopyableLabel` for the History
tab: the plan (D6) asks for a visible clipboard glyph next to every
copyable value, because "click the text" was undiscoverable. Shape is
the mockup's 28×28 rounded square with a 1px border.

Why a hand-painted `QToolButton` instead of an emoji/icon font: the app
has no icon theme and deliberately de-emojied its UI in Session 35, and
an emoji's colour/weight differs per Windows build. Painting the two
glyphs (clipboard, check) keeps them identical to the mockup's SVG and
lets them follow the active theme tokens, including custom themes whose
tokens may be CSS `rgba(...)` (hence `qcolor_from_token`).

The button copies whatever `text_provider()` returns *at click time*,
not a snapshot taken at construction — History rebuilds its card bodies
on every selection, but the prompt box's button lives for the whole
tab, so a stored string would go stale.

`copy_to_clipboard` is the never-raising clipboard helper from
`ui/clipboard.py`; this widget only turns its bool into feedback.
"""
from PyQt6.QtCore import QRectF, QSize, Qt, QTimer
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QToolButton

from ui.clipboard import copy_to_clipboard
from ui.color_utils import qcolor_from_token

BUTTON_SIZE = 28
GLYPH_SIZE = 15.0
# The mockup's clipboard path lives in a 24×24 viewBox.
GLYPH_VIEWBOX = 24.0
FEEDBACK_MS = 1200


class CopyIconButton(QToolButton):
    def __init__(self, text_provider, tooltip: str = "Copy", colors: dict = None, parent=None):
        super().__init__(parent)
        self._text_provider = text_provider
        self._colors = colors or {}
        self._hover = False
        self._copied = False

        self._tooltip = tooltip
        self.setToolTip(tooltip)
        self.setAccessibleName(tooltip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(QSize(BUTTON_SIZE, BUTTON_SIZE))
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

        self._feedback_timer = QTimer(self)
        self._feedback_timer.setSingleShot(True)
        self._feedback_timer.timeout.connect(self._reset_feedback)
        self.clicked.connect(self._on_clicked)

    # ------------------------------------------------------------------
    def set_colors(self, colors: dict):
        self._colors = colors or {}
        self.update()

    def set_text_provider(self, provider):
        self._text_provider = provider

    # ------------------------------------------------------------------
    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def _on_clicked(self):
        text = ""
        if self._text_provider is not None:
            try:
                text = self._text_provider() or ""
            except Exception:
                text = ""
        ok = copy_to_clipboard(text)
        self._copied = ok
        self.setToolTip("Copied!" if ok else "Nothing to copy")
        self.update()
        self._feedback_timer.start(FEEDBACK_MS)

    def _reset_feedback(self):
        self._copied = False
        self.setToolTip(self._tooltip)
        self.update()

    # ------------------------------------------------------------------
    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        w, h = self.width(), self.height()
        border_token = "accent" if (self._hover or self._copied) else "border"
        border = qcolor_from_token(self._colors.get(border_token, "#808080"))
        fill = qcolor_from_token(self._colors.get("bg_alt", "#000000")) if self._hover else QColor(0, 0, 0, 0)

        painter.setPen(QPen(border, 1))
        painter.setBrush(fill)
        painter.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 6, 6)

        if self._copied:
            glyph_token = "accent"
        elif self._hover:
            glyph_token = "fg"
        else:
            glyph_token = "fg_dim"
        glyph = qcolor_from_token(self._colors.get(glyph_token, "#c0c0c0"))

        painter.setPen(QPen(glyph, 2.2, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.translate((w - GLYPH_SIZE) / 2.0, (h - GLYPH_SIZE) / 2.0)
        painter.scale(GLYPH_SIZE / GLYPH_VIEWBOX, GLYPH_SIZE / GLYPH_VIEWBOX)

        if self._copied:
            check = QPainterPath()
            check.moveTo(5, 12)
            check.lineTo(10, 17)
            check.lineTo(19, 7)
            painter.drawPath(check)
        else:
            # Back plate (left/top of the clipboard) then the front sheet,
            # matching the mockup's two-overlapping-rounded-rects glyph.
            painter.drawRoundedRect(QRectF(4, 3, 11, 14), 2, 2)
            painter.drawRoundedRect(QRectF(9, 9, 12, 12), 2, 2)
