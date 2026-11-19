"""Session 73 extra: a QComboBox the mouse wheel cannot change.

In a scrolling rail a wheel turn over a combo would silently change a
generation setting; the event is passed on so the rail scrolls instead
(same rule as `no_scroll_spinbox` and the Settings model pickers).
"""
from PyQt6.QtWidgets import QComboBox


class NoScrollComboBox(QComboBox):
    def wheelEvent(self, event):
        event.ignore()
