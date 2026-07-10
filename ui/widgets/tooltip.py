"""Thin wrapper around Qt's native tooltip mechanism.

The original `Tooltip` class (promptforgeint.py) was ~30 lines of manual
Toplevel/Label management because Tkinter has no built-in hover tooltip.
Qt does — every QWidget already has `.setToolTip(text)`, and QSS already
styles `QToolTip` globally (see ui/theme.py). So there is nothing to
reimplement here; this module exists only so call sites that used to say
`Tooltip(widget, text, app)` have an equally short one-line replacement,
and so "how do I add a tooltip" has one obvious, greppable answer across
the codebase rather than every tab calling `.setToolTip()` directly with
slightly different conventions.
"""


def set_tooltip(widget, text: str) -> None:
    """Sets `text` as `widget`'s tooltip. A falsy `text` clears any
    existing tooltip rather than showing an empty bubble — mirrors the
    original's `if self.tip or not self.text: return` guard, which
    never showed a tooltip for empty text either."""
    widget.setToolTip(text or "")
