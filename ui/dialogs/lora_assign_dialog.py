"""LoRA assignment popup for a Library entry — ported from
`PromptForgeApp._assign_lib_lora` (a `tk.Toplevel` with a filtered
`tk.Listbox`) in the original monolith.

`LoraAssignDialog.get_selected_lora(parent, available_loras)` is the
intended entry point for Library: shows the dialog modally and returns the
chosen path, or `None` if the user cancelled / closed it without picking
anything.

Session 72 extra (D33): the same dialog also picks model files (diffusion
model / text encoder / VAE) through `get_selected_file(parent, files,
title, prompt, current=None)`.  The LoRA defaults and `get_selected_lora`
are unchanged; only the file mode adds a wider resizable window, middle-
elided rows with the full name in a tooltip and a one-line label under the
list showing the highlighted file in full.
"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)


class LoraAssignDialog(QDialog):
    def __init__(self, available_loras, parent=None, title="Assign LoRA",
                 prompt="Select a LoRA to bind to this entry:", current=None,
                 file_mode=False):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(420, 360)
        self._available_loras = list(available_loras)
        self._chosen = None
        self._file_mode = bool(file_mode)
        self._current = current

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(prompt))

        self.ent_search = QLineEdit()
        self.ent_search.textChanged.connect(self._populate)
        layout.addWidget(self.ent_search)

        self.list_widget = QListWidget()
        if self._file_mode:
            # Long, near-identical file names: keep the distinguishing
            # tail visible and never scroll sideways.
            self.list_widget.setTextElideMode(Qt.TextElideMode.ElideMiddle)
            self.list_widget.setHorizontalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.list_widget.setWordWrap(False)
            self.setSizeGripEnabled(True)
        self.list_widget.itemDoubleClicked.connect(lambda _item: self._commit())
        layout.addWidget(self.list_widget, 1)

        self.lbl_full_name = None
        if self._file_mode:
            # One line under the list with the full highlighted name, so
            # "flux1-dev.safetensors" and "flux1-dev-kv.safetensors" can
            # be told apart even when the row itself is elided.
            self.lbl_full_name = QLabel("")
            self.lbl_full_name.setObjectName("dim")
            self.lbl_full_name.setWordWrap(True)
            self.lbl_full_name.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse)
            layout.addWidget(self.lbl_full_name)
            self.list_widget.currentItemChanged.connect(
                self._on_current_item_changed)

        btn_row = QHBoxLayout()
        btn_assign = QPushButton("Assign")
        btn_assign.setObjectName("accent")
        btn_assign.clicked.connect(self._commit)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_assign)
        btn_row.addWidget(btn_cancel)
        layout.addLayout(btn_row)

        self._populate()
        if self._file_mode:
            self._apply_current()
        self.ent_search.setFocus()

    def _populate(self, filter_text: str = ""):
        self.list_widget.clear()
        needle = filter_text.lower()
        for lora in self._available_loras:
            if not needle or needle in lora.lower():
                item = QListWidgetItem(lora)
                if self._file_mode:
                    item.setToolTip(lora)
                self.list_widget.addItem(item)
        if self._file_mode and not filter_text:
            self._apply_current()

    def _apply_current(self):
        """Selects and centers the previously saved value, if any."""
        if not self._current:
            return
        for row in range(self.list_widget.count()):
            item = self.list_widget.item(row)
            if item.text() == self._current:
                self.list_widget.setCurrentItem(item)
                self.list_widget.scrollToItem(
                    item, QAbstractItemView.ScrollHint.PositionAtCenter)
                return

    def _on_current_item_changed(self, current, _previous):
        if self.lbl_full_name is not None:
            self.lbl_full_name.setText(current.text() if current else "")

    def _commit(self):
        item = self.list_widget.currentItem()
        if item is None:
            return
        self._chosen = item.text()
        self.accept()

    @staticmethod
    def get_selected_lora(parent, available_loras):
        dlg = LoraAssignDialog(available_loras, parent=parent)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            return dlg._chosen
        return None

    @staticmethod
    def get_selected_file(parent, files, title, prompt, current=None):
        dlg = LoraAssignDialog(files, parent=parent, title=title,
                               prompt=prompt, current=current,
                               file_mode=True)
        dlg.resize(640, 440)
        dlg.setMinimumSize(480, 320)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            return dlg._chosen
        return None
