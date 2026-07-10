"""Drop-in autocomplete "combobox" — SESSION 25.4 FULL REWRITE.

## Why this was rewritten instead of patched again

Two prior hotfixes (25, 25.2, 25.3, and an attempted 25.4 patch that
only added `self.setCompleter(None)`) all tried to fix bugs from
*inside* a `QComboBox` subclass. That was the actual mistake, not any
one specific bug. An editable `QComboBox` has THREE independent things
that all want to own Up/Down/Enter/Escape on the same line edit:

  1. Our own custom filtering/popup logic.
  2. Qt's default `QCompleter`, silently attached by `setEditable(True)`
     unless you opt out (this is what the 25.4 patch disabled).
  3. `QComboBox`'s OWN built-in keyboard handling for an editable combo
     (Up/Down cycles the underlying item *model*, rewriting the line
     edit's text independently of anything we do; Enter/Escape have
     their own native meaning too).

Disabling #2 alone still left #3 in the picture, installed as an
internal event filter on the same line edit ours is also filtering,
with no documented ordering guarantee between the two. That's why the
targeted patch "worked" in an isolated unit test (small model, no
contention) but not in the real app.

This version doesn't subclass QComboBox at all, so #2 and #3 don't
exist to fight with. It's a plain QFrame containing an ordinary
QLineEdit (no combo, no completer) plus a small dropdown-arrow button.
Every key press on that QLineEdit passes through exactly one
eventFilter: ours. There is exactly one place that tracks "what's
currently highlighted": `self._listbox.currentRow()` on our own popup
QListWidget. Nothing else in Qt has an opinion about it.

The frameless, non-activating top-level popup (`Qt.WindowType.Tool` +
`Qt.WindowAttribute.WA_ShowWithoutActivating`) is unchanged from the
original design — that part was never the problem; it's the right fix
for the same focus-stealing issue the original Tkinter
`AutocompleteCombobox` docstring described (a native popup grabs
keyboard focus on first keystroke, which breaks live filtering).

API (unchanged from before, so callers in builder_tab.py / library_tab.py
need no changes):
  - `set_items(values)` — replace the master (unfiltered) list.
  - `set_value(value)` / `current_value()` — programmatic get/set.
  - `item_selected = pyqtSignal(str)` — emitted on every commit (typed
    exact match, popup pick, or Enter), regardless of whether the value
    was already a known item.
  - `lineEdit()` / `count()` / `findText()` / `setCurrentIndex()` — thin
    QComboBox-parity shims kept only because existing tests and a couple
    of call sites use them; they're not backed by a real QComboBox model.

Commit rules on Enter / focus-out are unchanged from the original: an
exact match (case-insensitive) normalizes to the value's canonical
stored case; an empty field resolves to "None"; unrecognized text falls
back to the last validly committed value.
"""
from PyQt6.QtCore import Qt, QEvent, QPoint, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


class AutocompleteCombobox(QFrame):
    item_selected = pyqtSignal(str)

    # App-wide registry of whichever instance currently owns an open
    # popup, so only one popup can ever be open at once (Session 25.2
    # behavior, preserved).
    _open_instance = None

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("AutocompleteCombobox")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self._all_values = []
        self._last_committed = ""
        self._popup = None
        self._listbox = None
        self._popup_values = []

        outer = QHBoxLayout(self)
        outer.setContentsMargins(8, 2, 4, 2)
        outer.setSpacing(2)

        # Plain QLineEdit — no QComboBox involved, so nothing auto-attaches
        # a completer or its own key handling to it.
        self._edit = QLineEdit(self)
        self._edit.setObjectName("AutocompleteLineEdit")
        self._edit.setFrame(False)
        self._edit.textEdited.connect(self._on_text_edited)
        self._edit.installEventFilter(self)
        outer.addWidget(self._edit, 1)

        self._arrow_btn = QToolButton(self)
        self._arrow_btn.setObjectName("AutocompleteArrow")
        self._arrow_btn.setText("\u25be")
        self._arrow_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._arrow_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._arrow_btn.setAutoRaise(True)
        self._arrow_btn.clicked.connect(self._trigger_open_from_click)
        outer.addWidget(self._arrow_btn)

        # Keyboard focus lands on the line edit; hasFocus()/QSS :focus on
        # this frame still reflect that via the proxy relationship.
        self.setFocusProxy(self._edit)

        app = QApplication.instance()
        if app is not None:
            # Alt+Tab / clicking another application leaves Qt's internal
            # focus widget unchanged, so plain FocusOut never fires for
            # that case — needs its own hook (Session 11.5.1).
            app.applicationStateChanged.connect(self._on_app_state_changed)
            # A press on truly empty space (no focus policy of its own)
            # never fires a FocusOut either — an app-wide filter is the
            # only way to see those (Session 25 follow-up).
            app.installEventFilter(self)

            def _cleanup(_obj=None, app=app, self_ref=self):
                try:
                    app.removeEventFilter(self_ref)
                except RuntimeError:
                    pass
            self.destroyed.connect(_cleanup)

    # ---------------------------------------- QComboBox-parity shims --
    def lineEdit(self):
        return self._edit

    def count(self):
        return len(self._all_values)

    def findText(self, text):
        for i, value in enumerate(self._all_values):
            if value == text:
                return i
        return -1

    def setCurrentIndex(self, idx):
        if 0 <= idx < len(self._all_values):
            self._edit.setText(self._all_values[idx])

    # ------------------------------------------------------------ API --
    def set_items(self, values):
        """The equivalent of the original's `combo["values"] = [...]`.
        Use this (not any addItem-style call) everywhere a slot's
        dropdown contents get (re)populated, so `_all_values` — the
        master unfiltered list the popup searches — stays in sync."""
        self._all_values = list(values)

    def current_value(self):
        return self._edit.text()

    def set_value(self, value):
        self._edit.setText(value)
        self._last_committed = value

    # ------------------------------------------------------------- popup --
    def _create_popup(self):
        popup = QFrame(self.window(), Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        popup.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        popup.setObjectName("AutocompletePopup")
        layout = QVBoxLayout(popup)
        layout.setContentsMargins(1, 1, 1, 1)

        listbox = QListWidget(popup)
        listbox.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        listbox.setFrameShape(QFrame.Shape.NoFrame)
        listbox.itemClicked.connect(lambda item: self._pick(item.text()))
        layout.addWidget(listbox)

        self._popup = popup
        self._listbox = listbox

    def _open_popup(self, matches):
        # Session 25.4 rewrite: previously this fully closed and rebuilt
        # a brand-new top-level `Qt.Tool` window on EVERY keystroke.
        # Repeatedly show()/close()-ing a real top-level window floods
        # the platform with activation-related events, and on some
        # platforms/timings that causes the line edit to spuriously lose
        # focus (a real FocusOut with no new focus target) even though
        # nothing the user did asked for that — which is what made Enter
        # and Escape look broken (state got torn down out from under
        # them). Fix: build the popup window ONCE lazily, then just
        # repopulate its list and reposition/resize it while filtering.
        # It's only actually shown once per interaction and only
        # destroyed by `_close_popup()` at the end of one (Escape, a
        # commit, an outside click, losing the tab, etc.) — not on every
        # typed character.
        other = AutocompleteCombobox._open_instance
        if other is not None and other is not self:
            other._close_popup()

        if not matches:
            self._close_popup()
            return

        self._popup_values = matches
        if self._popup is None:
            self._create_popup()

        self._listbox.clear()
        self._listbox.addItems(matches)
        self._listbox.setCurrentRow(0)

        # Cap how many rows show at once before the (native, mouse-wheel
        # scrollable) QListWidget needs to scroll — generous enough to
        # show a full small library without needing to scroll for it.
        visible_rows = max(1, min(len(matches), 10))
        row_h = self._listbox.sizeHintForRow(0) if self._listbox.count() else 22
        popup_h = row_h * visible_rows + 4

        pos = self.mapToGlobal(QPoint(0, self.height()))
        popup_w = max(self.width(), 120)
        self._popup.setGeometry(pos.x(), pos.y(), popup_w, popup_h)
        if not self._popup.isVisible():
            self._popup.show()

        AutocompleteCombobox._open_instance = self

    def _close_popup(self):
        if self._popup is not None:
            self._popup.close()
            self._popup.deleteLater()
        self._popup = None
        self._listbox = None
        self._popup_values = []
        if AutocompleteCombobox._open_instance is self:
            AutocompleteCombobox._open_instance = None

    # -------------------------------------------------------------- click --
    def mousePressEvent(self, event):
        # A single click anywhere on the frame (margins, arrow button
        # area not otherwise consumed by a child) opens the full list,
        # exactly like clicking a normal combo box.
        if event.button() == Qt.MouseButton.LeftButton:
            self._trigger_open_from_click()
            return
        super().mousePressEvent(event)

    def _trigger_open_from_click(self):
        self._edit.setFocus()
        self._open_popup(list(self._all_values))
        # Standard combobox behavior: a click that opens the dropdown
        # also selects the field's current text, so the very next
        # keystroke replaces it outright instead of inserting at
        # whatever cursor position the click happened to land on.
        # Without this, clicking a box showing "None" and typing "Anime"
        # produced "NoneAnime" (typed text inserted, not replacing), and
        # clicking a box with an already-picked value and typing more
        # appended instead of replacing.
        self._edit.selectAll()

    def wheelEvent(self, event):
        # Value changes should only ever come from a click on a dropdown
        # row or an Enter/typed commit — never the wheel.
        event.ignore()

    def hideEvent(self, event):
        # The popup is a top-level `Qt.Tool` window, so it does NOT get
        # auto-hidden just because this widget's parent tab page was
        # switched away from. Without this, switching tabs left the
        # popup floating over whatever tab the user switched to.
        self._close_popup()
        super().hideEvent(event)

    def _on_app_state_changed(self, state):
        if state != Qt.ApplicationState.ApplicationActive:
            self._close_popup()

    # --------------------------------------------------------- filtering --
    def _on_text_edited(self, text):
        if text:
            needle = text.lower()
            matches = [v for v in self._all_values if needle in v.lower()]
        else:
            matches = list(self._all_values)
        self._open_popup(matches)

    def eventFilter(self, obj, event):
        try:
            return self._event_filter_impl(obj, event)
        except RuntimeError:
            # This instance's underlying C/C++ object has already been
            # destroyed (e.g. its parent tab/dialog was torn down) but
            # it's still registered as an app-wide event filter — Qt's
            # own cleanup and PyQt's wrapper-deletion timing don't
            # always line up. Nothing to filter for a dead widget.
            return False

    def _event_filter_impl(self, obj, event):
        if (
            self._popup is not None
            and event.type() == QEvent.Type.MouseButtonPress
            and isinstance(obj, QWidget)
            and obj is not self
            and obj is not self._edit
            and obj is not self._arrow_btn
            and not self._popup.isAncestorOf(obj)
        ):
            # A press anywhere outside both this widget and its own
            # popup — including empty space that never would have fired
            # a FocusOut — closes it, same as focus genuinely moving away.
            self._close_popup()
            self._finalize()
        if obj is self._edit:
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                # Clicks land on the QLineEdit child directly, not on
                # this frame's own mousePressEvent — without handling
                # it here, only the frame's margins/arrow button were
                # actually clickable, and the text area itself (the
                # obviously-clickable-looking middle of the box) did
                # nothing. Consume the event (don't let the normal
                # QLineEdit click-to-position-cursor behavior run) since
                # we're about to select-all anyway.
                self._trigger_open_from_click()
                return True
            if event.type() == QEvent.Type.KeyPress:
                if self._handle_key_press(event):
                    return True
            elif event.type() == QEvent.Type.Wheel:
                # Same reasoning as wheelEvent(): never let the wheel
                # silently change the value while it happens to sit over
                # the field.
                return True
            elif event.type() == QEvent.Type.FocusOut:
                # Deferred by one event-loop tick: clicking a popup row
                # means clicking a different top-level window, which on
                # some platforms can generate this FocusOut before the
                # click is actually delivered to the list as a
                # selection. Closing the popup synchronously here would
                # make clicking look unresponsive.
                QTimer.singleShot(0, self._on_focus_out)
        return super().eventFilter(obj, event)

    def _handle_key_press(self, event):
        key = event.key()
        if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            self._on_arrow(key)
            return True
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._on_return()
            return True
        if key == Qt.Key.Key_Escape:
            self._close_popup()
            return True
        return False

    def _on_arrow(self, key):
        if self._listbox is None:
            # Dropdown not open yet (e.g. pressed Down with nothing
            # typed) — open it with whatever is currently typed, same
            # as a keystroke would.
            self._on_text_edited(self._edit.text())
            return
        size = len(self._popup_values)
        if size == 0:
            return
        idx = self._listbox.currentRow()
        idx = (idx + (1 if key == Qt.Key.Key_Down else -1)) % size
        self._listbox.setCurrentRow(idx)

    def _pick(self, value):
        self._edit.setText(value)
        self._edit.end(False)
        self._last_committed = value
        self._close_popup()
        self._edit.setFocus()
        self.item_selected.emit(value)

    # ------------------------------------------------------------ commit --
    def _on_return(self):
        # If a row is highlighted in an open popup, Enter commits THAT
        # row (this is also how an Up/Down-navigated pick, e.g. a
        # second match, gets committed instead of always the top one).
        if self._listbox is not None and self._listbox.currentItem() is not None:
            self._pick(self._listbox.currentItem().text())
            return
        # If there's typed text but for some reason no popup/highlighted
        # row exists yet, recompute the same top match the popup would
        # show and commit it, instead of losing the obvious partial-text
        # intent by falling through to exact-match-only _finalize().
        typed = self._edit.text().strip()
        if typed:
            needle = typed.lower()
            matches = [v for v in self._all_values if needle in v.lower()]
            if matches:
                self._pick(matches[0])
                return
        self._close_popup()
        self._finalize()

    def _on_focus_out(self):
        # A FocusOut whose new focus target is None is NOT a real "user
        # moved focus elsewhere" signal — a real focus move (Tab to the
        # next field, clicking a different real widget) always lands on
        # some actual widget. A None target only ever happens here as a
        # side effect of our OWN popup (a `Qt.WindowType.Tool` top-level
        # window) being shown — `WA_ShowWithoutActivating` reduces but
        # does not eliminate this on every platform. Genuine "clicked
        # truly empty space" departures are already caught independently
        # by the app-wide MouseButtonPress filter below, so there is
        # nothing left for a None-target FocusOut to legitimately mean.
        # Restore focus and keep going instead of finalizing/closing.
        if self._popup is not None:
            focused = QApplication.focusWidget()
            if focused is None:
                self._edit.setFocus()
                return
            if self._popup.isAncestorOf(focused):
                return  # focus is inside our own popup — let the click finish
        self._close_popup()
        self._finalize()

    def _finalize(self):
        typed = self._edit.text().strip()
        previous = self._last_committed

        if not typed:
            final_value = "None"
        else:
            final_value = previous
            for value in self._all_values:
                if value.lower() == typed.lower():
                    final_value = value
                    break

        if self._edit.text() != final_value:
            self._edit.setText(final_value)
        self._last_committed = final_value

        if final_value != previous:
            self.item_selected.emit(final_value)
