"""Hotfix Session 25.3: a plain `QDoubleSpinBox` accepts mouse-wheel
events on mere hover, silently stepping its value while the user is
just scrolling the page past it (this is exactly how the LoRA
"strength" field was misbehaving). `NoScrollDoubleSpinBox` requires the
field to actually have keyboard focus (i.e. be clicked into first)
before a wheel event is allowed to change its value — same "click
before it reacts" rule `AutocompleteCombobox` already applies to its
own wheel handling.
"""
from PyQt6.QtWidgets import QDoubleSpinBox


class NoScrollDoubleSpinBox(QDoubleSpinBox):
    def wheelEvent(self, event):
        # Hotfix Session 25 follow-up: same correction as
        # AutocompleteCombobox — never let the wheel change the value,
        # focused or not. Only the step buttons or typing should.
        event.ignore()
