"""Block order dialog — "Block order…" button in the Builder tab's
Standard template panel. Ported from the original's `open_order_dialog`.

Four rows (Style / Characters / Scenario / Tools), Up/Down move the
selected row, Done applies. `block_order` is a plain list of the
canonical keys (`"style"`, `"characters"`, `"scenario"`, `"tools"`) —
this dialog only ever reorders that list in place and reports back via
`get_order()`; callers decide what to do with the result (BuilderTab
persists it as the active order and, separately, as a named template
via the "💾 Save as template" flow next to it).
"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QPushButton,
)

from backend.constants import BLOCK_ORDER_LABELS


class BlockOrderDialog(QDialog):
    def __init__(self, block_order: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Prompt block order")
        self.setMinimumSize(380, 320)
        self._order = list(block_order)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Choose the block order from top to bottom:"))

        self.listbox = QListWidget()
        for key in self._order:
            self.listbox.addItem(BLOCK_ORDER_LABELS.get(key, key))
        if self.listbox.count():
            self.listbox.setCurrentRow(0)
        layout.addWidget(self.listbox, 1)

        btn_row = QHBoxLayout()
        btn_up = QPushButton("▲ Up")
        btn_down = QPushButton("▼ Down")
        btn_up.clicked.connect(lambda: self._move(-1))
        btn_down.clicked.connect(lambda: self._move(1))
        btn_row.addWidget(btn_up)
        btn_row.addWidget(btn_down)
        layout.addLayout(btn_row)

        btn_done = QPushButton("Done")
        btn_done.setObjectName("accent")
        btn_done.clicked.connect(self.accept)
        layout.addWidget(btn_done)

    def _move(self, delta):
        row = self.listbox.currentRow()
        if row < 0:
            return
        new_row = row + delta
        if 0 <= new_row < self.listbox.count():
            self._order[row], self._order[new_row] = self._order[new_row], self._order[row]
            item = self.listbox.takeItem(row)
            self.listbox.insertItem(new_row, item)
            self.listbox.setCurrentRow(new_row)

    def get_order(self) -> list:
        return list(self._order)
