"""LoRA assignment popup for a Library entry — ported from
`PromptForgeApp._assign_lib_lora` (a `tk.Toplevel` with a filtered
`tk.Listbox`) in the original monolith.

`LoraAssignDialog.get_selected_lora(parent, available_loras)` is the
intended entry point: shows the dialog modally and returns the chosen
path, or `None` if the user cancelled / closed it without picking
anything.
"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QVBoxLayout,
)


class LoraAssignDialog(QDialog):
    def __init__(self, available_loras, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Assign LoRA")
        self.resize(420, 360)
        self._available_loras = list(available_loras)
        self._chosen = None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Select a LoRA to bind to this entry:"))

        self.ent_search = QLineEdit()
        self.ent_search.textChanged.connect(self._populate)
        layout.addWidget(self.ent_search)

        self.list_widget = QListWidget()
        self.list_widget.itemDoubleClicked.connect(lambda _item: self._commit())
        layout.addWidget(self.list_widget, 1)

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
        self.ent_search.setFocus()

    def _populate(self, filter_text: str = ""):
        self.list_widget.clear()
        needle = filter_text.lower()
        for lora in self._available_loras:
            if not needle or needle in lora.lower():
                self.list_widget.addItem(lora)

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
