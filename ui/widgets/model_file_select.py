"""Session 72 extra (D33): the model-file picker field.

One `ModelFileSelect` stands for one preset field (`diffusion_model`,
`clip` or `vae`).  It is a plain, non-editable `QComboBox` with a fixed
menu of exactly two visible rows:

    row 0  Workflow default   -> value "" (key the workflow untouched, D15)
    row 1  Assign…            -> opens the LoRA-style assign dialog
    row 2  hidden value row   -> holds the assigned file name, only shown
                                 as the combo's current row

The third row exists so `QComboBox` can display the current value without
adding a third visible menu entry; it is hidden with
`view().setRowHidden(2, True)` in every state.

Nothing can be typed: file names that ComfyUI does not know can no longer
be entered by hand.  Long names are middle-elided in the closed field so
the distinguishing tail (`… 9b KV`) survives, with the full name in the
tooltip.  The wheel never changes the value, matching the rest of the
Settings page.

`set_value` / `value` / `set_files` / `set_assign_enabled` are the state
API used by `ModelPresetRow`; the widget itself never touches the preset
dict or the backend.
"""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFontMetrics, QPalette
from PyQt6.QtWidgets import (
    QComboBox,
    QSizePolicy,
    QStyle,
    QStyleOptionComboBox,
    QStylePainter,
)

from ui.dialogs.lora_assign_dialog import LoraAssignDialog

WORKFLOW_DEFAULT_TEXT = "Workflow default"
ASSIGN_TEXT = "Assign…"
WORKFLOW_DEFAULT_ROW = 0
ASSIGN_ROW = 1
VALUE_ROW = 2
MISSING_TOOLTIP = "not found in ComfyUI's list"
ASSIGN_DISABLED_TOOLTIP = "No matching files in ComfyUI's list."
# The two semantic `warn` colours from `backend.constants.THEMES` (dark /
# light). Chosen by text luminance so derived/custom palettes match too.
WARN_ON_DARK = QColor("#e0a84e")
WARN_ON_LIGHT = QColor("#c5860f")


def elide_middle(text, width, metrics):
    """Middle-elides `text` to `width` pixels, keeping both ends (the
    tail is what tells a base model from its KV/GGUF variant)."""
    return metrics.elidedText(text, Qt.TextElideMode.ElideMiddle,
                              max(0, int(width)))


class ModelFileSelect(QComboBox):
    """Two-row dropdown that assigns one model file through a dialog."""

    value_changed = pyqtSignal(str)

    def __init__(self, dialog_title, dialog_prompt, parent=None):
        super().__init__(parent)
        self._dialog_title = dialog_title
        self._dialog_prompt = dialog_prompt

        self.setEditable(False)
        self.addItem(WORKFLOW_DEFAULT_TEXT, "")
        self.addItem(ASSIGN_TEXT, None)
        self.addItem("", "")
        self.view().setRowHidden(VALUE_ROW, True)
        self.setMinimumContentsLength(24)
        self.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Fixed)

        self._value = ""
        self._files = []
        self._files_known = False
        self._missing = False
        self._assign_enabled = True
        self._assign_note = ""

        self.activated.connect(self._on_activated)
        self._refresh_tooltip()

    # ------------------------------------------------------------ state --
    def value(self):
        return self._value

    def set_value(self, value):
        """Shows `value` (or Workflow default) without emitting anything.
        The hidden row carries the name; the current index follows it."""
        value = value or ""
        self._value = value
        self.blockSignals(True)
        try:
            self.setItemText(VALUE_ROW, value)
            self.setCurrentIndex(VALUE_ROW if value else WORKFLOW_DEFAULT_ROW)
        finally:
            self.blockSignals(False)
        self._refresh_tooltip()

    def set_files(self, files, known=True):
        """Stores the list offered by the dialog.  `known` is False while
        the list is loading / offline, so a stored value is not marked
        missing just because nothing has been fetched yet."""
        self._files = list(files or [])
        self._files_known = bool(known)
        self._refresh_tooltip()

    def set_assign_enabled(self, enabled, note=""):
        """Enables or disables only the "Assign…" row; Workflow default
        stays usable (offline still clears)."""
        self._assign_enabled = bool(enabled)
        self._assign_note = (note or "").strip()
        item = self.model().item(ASSIGN_ROW)
        if item is not None:
            item.setEnabled(self._assign_enabled)
            tip = ("" if self._assign_enabled else
                   self._assign_note or ASSIGN_DISABLED_TOOLTIP)
            item.setData(tip, Qt.ItemDataRole.ToolTipRole)
        self._refresh_tooltip()

    def is_assign_enabled(self):
        return self._assign_enabled

    def is_missing(self):
        return self._missing

    def _refresh_tooltip(self):
        self._missing = bool(self._value and self._files_known
                             and self._value not in self._files)
        if self._value:
            tip = self._value
            if self._missing:
                tip = f"{self._value}\n{MISSING_TOOLTIP}"
        else:
            tip = WORKFLOW_DEFAULT_TEXT
        self.setToolTip(tip)
        self.update()

    # --------------------------------------------------------- selecting --
    def _on_activated(self, index):
        if index == WORKFLOW_DEFAULT_ROW:
            self._choose_workflow_default()
        elif index == ASSIGN_ROW:
            self._open_assign_dialog()
        else:
            # The hidden value row is not reachable from the popup; keep
            # the field on whatever it showed before.
            self._restore_index()

    def _choose_workflow_default(self):
        if not self._value:
            self._restore_index()
            return
        self._value = ""
        self.blockSignals(True)
        try:
            self.setItemText(VALUE_ROW, "")
            self.setCurrentIndex(WORKFLOW_DEFAULT_ROW)
        finally:
            self.blockSignals(False)
        self._refresh_tooltip()
        self.value_changed.emit("")

    def _open_assign_dialog(self):
        if not self._assign_enabled:
            self._restore_index()
            return
        previous = self._value
        chosen = LoraAssignDialog.get_selected_file(
            self.window(), list(self._files), self._dialog_title,
            self._dialog_prompt, current=previous or None)
        if not chosen:
            # Cancel / close: no change, no signal.
            self._restore_index()
            return
        self._value = chosen
        self.blockSignals(True)
        try:
            self.setItemText(VALUE_ROW, chosen)
            self.setCurrentIndex(VALUE_ROW)
        finally:
            self.blockSignals(False)
        self._refresh_tooltip()
        self.value_changed.emit(chosen)

    def _restore_index(self):
        self.blockSignals(True)
        try:
            self.setCurrentIndex(
                VALUE_ROW if self._value else WORKFLOW_DEFAULT_ROW)
        finally:
            self.blockSignals(False)

    # ---------------------------------------------------------- painting --
    def paintEvent(self, event):
        painter = QStylePainter(self)
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        text = option.currentText
        option.currentText = ""
        painter.drawComplexControl(QStyle.ComplexControl.CC_ComboBox, option)
        painter.drawControl(QStyle.ControlElement.CE_ComboBoxLabel, option)

        field = self.style().subControlRect(
            QStyle.ComplexControl.CC_ComboBox, option,
            QStyle.SubControl.SC_ComboBoxEditField, self)
        if text:
            base = self.palette().color(QPalette.ColorRole.ButtonText)
            if not self.isEnabled():
                color = self.palette().color(
                    QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText)
            elif self._missing:
                color = (WARN_ON_LIGHT if base.lightness() > 128
                         else WARN_ON_DARK)
            else:
                color = base
            painter.setPen(color)
            painter.drawText(
                field, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                elide_middle(text, field.width(), QFontMetrics(self.font())))

    def wheelEvent(self, event):
        # Session 72 extra: the wheel must not change a model assignment
        # (same reason the other Settings combos ignore it) -- let the
        # event scroll the Settings page instead.
        event.ignore()
