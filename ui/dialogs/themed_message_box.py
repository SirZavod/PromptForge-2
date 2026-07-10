"""Session 48.6: a themed, drop-in-signature replacement for
`QMessageBox.warning`/`information`/`critical`/`question`, so the ~66
call sites across this app that use those get PromptForge's own
frameless title bar (Session 38) instead of the native OS chrome a
plain `QMessageBox` always shows. See `additionalfeatures.md`'s
SESSION 48.6 for the full diagnosis — Session 43 already covered the
~6 named custom `QDialog` subclasses (`GuideDialog`, the Gallery
full-view popup, and the still-deferred rest); `QMessageBox` itself,
used far more pervasively, was never in that scope.

Deliberately a bespoke `QDialog` built to LOOK like a `QMessageBox`
(icon + text + Ok/Yes/No-style buttons), not a subclass of
`QMessageBox` itself and not an attempt to re-parent its internal
native layout onto a content widget — `QMessageBox` lays its content
out on itself directly via a layout Qt owns, and there's no supported
way to relocate that into something `FramelessDialogMixin` can wrap
without fighting Qt's own internals. A small drop-in replacement
matching `QMessageBox`'s own static-method call shape gets the same
practical result — themed chrome, identical call-site ergonomics —
without depending on undocumented internals.

Call-site migration is a pure `QMessageBox.warning(` ->
`themed_message_box.warning(` rename, nothing else: every function
here takes the exact same `(parent, title, text[, buttons])` shape
`QMessageBox`'s own static methods do, `question`'s default buttons
match Qt's own default (`Yes | No`, not `Ok` — `QMessageBox.question`
is the one static method with that different default; matched here on
purpose so the many 3-arg call sites that relied on it keep behaving
identically), and `question`'s return value is a real
`QMessageBox.StandardButton` so existing `if reply !=
QMessageBox.StandardButton.Yes:` comparisons downstream don't need to
change either. `colors` is deliberately NOT a parameter — every real
call site's `parent` is a tab/dialog that already has a `self.colors`
dict (confirmed by reading all five files these calls live in), so
each function reads `parent.colors` itself; a caller with no such
attribute falls back to a hardcoded dark palette rather than crashing,
since a message box failing to look themed is a much smaller problem
than a message box failing to appear at all.
"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
    QMessageBox, QStyle, QVBoxLayout, QWidget,
)

from ui.dialogs.framed_dialog import FramelessDialogMixin

# Fallback palette for the (currently theoretical -- every real caller
# has `.colors`) case of a parent with no `colors` attribute at all.
_FALLBACK_COLORS = {
    "bg": "#202020", "bg_card": "#282828", "border": "#3a3a3a",
    "fg": "#f0f0f0", "fg_dim": "#9a9a9a", "accent": "#5b8def",
    "accent_hover": "#6f9bf2",
}

_ICONS = {
    "warning": QStyle.StandardPixmap.SP_MessageBoxWarning,
    "information": QStyle.StandardPixmap.SP_MessageBoxInformation,
    "critical": QStyle.StandardPixmap.SP_MessageBoxCritical,
    "question": QStyle.StandardPixmap.SP_MessageBoxQuestion,
}


def _colors_for(parent):
    colors = getattr(parent, "colors", None)
    return colors if colors else _FALLBACK_COLORS


class _ThemedMessageBox(FramelessDialogMixin, QDialog):
    """One themed dialog instance per call — same lifecycle a plain
    `QMessageBox.warning(...)` call already has (construct, `.exec()`,
    discard), just with a real title-bar strip instead of relying on
    the OS to draw one."""

    def __init__(self, parent, colors, kind, title, text, buttons):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(380)
        self.setMaximumWidth(560)

        content = QWidget()
        content.setStyleSheet(f"background-color: {colors['bg_card']};")
        outer = QVBoxLayout(content)
        outer.setContentsMargins(20, 18, 20, 14)
        outer.setSpacing(18)

        row = QHBoxLayout()
        row.setSpacing(14)
        icon_label = QLabel()
        style = QApplication.style()
        if style is not None:
            pixmap = style.standardIcon(
                _ICONS.get(kind, QStyle.StandardPixmap.SP_MessageBoxInformation)).pixmap(32, 32)
            icon_label.setPixmap(pixmap)
        icon_label.setFixedSize(32, 32)
        row.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignTop)

        text_label = QLabel(text)
        text_label.setWordWrap(True)
        text_label.setStyleSheet(f"color: {colors['fg']}; font-size: 13px; background: transparent;")
        text_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        row.addWidget(text_label, 1)
        outer.addLayout(row)

        box = QDialogButtonBox(buttons)
        box.setStyleSheet(
            f"QPushButton {{ background-color: {colors['bg']}; color: {colors['fg']}; "
            f"border: 1px solid {colors['border']}; border-radius: 6px; "
            f"padding: 6px 18px; min-width: 64px; }}"
            f"QPushButton:hover {{ background-color: {colors['accent_hover']}; }}"
        )
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        outer.addWidget(box, 0, Qt.AlignmentFlag.AlignRight)

        self._init_frameless_titlebar(colors, content)


def _show(parent, kind, title, text, buttons):
    colors = _colors_for(parent)
    dlg = _ThemedMessageBox(parent, colors, kind, title, text, buttons)
    dlg.exec()


def warning(parent, title, text):
    _show(parent, "warning", title, text, QDialogButtonBox.StandardButton.Ok)


def information(parent, title, text):
    _show(parent, "information", title, text, QDialogButtonBox.StandardButton.Ok)


def critical(parent, title, text):
    _show(parent, "critical", title, text, QDialogButtonBox.StandardButton.Ok)


def question(parent, title, text, buttons=None):
    """Matches `QMessageBox.question`'s own default of `Yes | No`
    (not `Ok`, unlike the other three) — most real call sites pass no
    explicit `buttons` at all and rely on that default, so it's
    replicated here rather than requiring every call site to spell it
    out."""
    if buttons is None:
        buttons = QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
    dialog_buttons = QDialogButtonBox.StandardButton.Yes | QDialogButtonBox.StandardButton.No
    colors = _colors_for(parent)
    dlg = _ThemedMessageBox(parent, colors, "question", title, text, dialog_buttons)
    result = dlg.exec()
    return QMessageBox.StandardButton.Yes if result == QDialog.DialogCode.Accepted \
        else QMessageBox.StandardButton.No
