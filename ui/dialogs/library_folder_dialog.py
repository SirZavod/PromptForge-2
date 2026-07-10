"""Tiny single-field folder-name dialog — ported from the original's
two `simpledialog.askstring(...)` call sites (`prompt_new_library_folder`
and `_rename_library_folder`). Reused for both "New folder"/"New
subfolder" and "Rename folder" since the two only differ in title and
whether a starting value is pre-filled, exactly like the original
shared `simpledialog.askstring` for both.

`LibraryFolderDialog.get_folder_name(parent, title, initial_value="")`
is the intended entry point: shows the dialog modally and returns the
entered name (already `.strip()`-ped), or `None` if the user cancelled,
closed the dialog, or left it blank.
"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)


class LibraryFolderDialog(QDialog):
    def __init__(self, title: str, initial_value: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(320, 110)
        self._result = None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Folder name:"))

        self.ent_name = QLineEdit()
        self.ent_name.setText(initial_value)
        self.ent_name.selectAll()
        self.ent_name.returnPressed.connect(self._commit)
        layout.addWidget(self.ent_name)

        btn_row = QHBoxLayout()
        btn_ok = QPushButton("OK")
        btn_ok.setObjectName("accent")
        btn_ok.clicked.connect(self._commit)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_ok)
        btn_row.addWidget(btn_cancel)
        layout.addLayout(btn_row)

        self.ent_name.setFocus()

    def _commit(self):
        text = self.ent_name.text().strip()
        if not text:
            self.reject()
            return
        self._result = text
        self.accept()

    @staticmethod
    def get_folder_name(parent, title: str, initial_value: str = ""):
        dlg = LibraryFolderDialog(title, initial_value=initial_value, parent=parent)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            return dlg._result
        return None
