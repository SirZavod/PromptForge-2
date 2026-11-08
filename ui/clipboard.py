"""Best-effort clipboard write shared by History's copy icons.

Session 53 (plan 2.A / D6): the old whole-entry "Copy" button was
suspected in a hard crash, and every clipboard write in the app was a
bare `QApplication.clipboard().setText(...)` — a call that can fail on a
locked/absent clipboard and, inside a Qt slot, would surface as an
unhandled exception. This helper is the single place that touches the
clipboard for the new per-field copy buttons and never raises.

Returns True when something was actually put on the clipboard, False
for empty text / no QApplication / any platform error. Callers use the
return value only for feedback ("Copied!" vs "Nothing to copy").
"""


def copy_to_clipboard(text) -> bool:
    """Copies `text`; returns False instead of raising on any failure."""
    if text is None:
        return False
    text = str(text)
    if not text:
        return False
    try:
        from PyQt6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is None:
            return False
        clipboard = app.clipboard()
        if clipboard is None:
            return False
        clipboard.setText(text)
        return True
    except Exception:
        # Deliberately broad: clipboard access is a platform boundary and
        # no clipboard failure is worth crashing (or even reporting) over.
        return False
