"""A QLabel that copies its own text to the clipboard on click.

Session 35 need: History's new ComfyUI-details cards (seed, per-LoRA
lines, negative prompt) should all be click-to-copy, and nothing like
that existed anywhere in the codebase yet (checked — the only
`mousePressEvent` overrides in `ui/widgets/` are unrelated click
handling in `autocomplete.py`/`image_zone.py`). Kept intentionally
small: this is a `QLabel`, not a button, so it drops into any layout
exactly like a normal label and only adds a pointing-hand cursor plus
the copy behavior.

`copy_text` defaults to whatever `setText()` was given, but can differ
from the *displayed* text — e.g. a card shows "1024×1024" while still
wanting to copy a plain "1024x1024" (or whichever exact string the
caller wants on the clipboard). Pass `copy_text=` explicitly whenever
the visible string isn't what should land in the clipboard.
"""
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QApplication, QLabel


class CopyableLabel(QLabel):
    def __init__(self, text: str = "", copy_text: str = None, parent=None):
        super().__init__(text, parent)
        self._copy_text = copy_text if copy_text is not None else text
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        base_tip = "Click to copy"
        self._base_tooltip = base_tip
        self.setToolTip(base_tip)

    def setText(self, text: str, copy_text: str = None):
        """Overload note: also updates the copy payload. If `copy_text`
        isn't given, it defaults to `text` — the common case where the
        visible string and the clipboard string are the same."""
        super().setText(text)
        self._copy_text = copy_text if copy_text is not None else text

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._copy_text:
            QApplication.clipboard().setText(self._copy_text)
            self.setToolTip("Copied!")
            QTimer.singleShot(1200, lambda: self.setToolTip(self._base_tooltip))
        super().mousePressEvent(event)
