"""Custom template editor — "✏ Create template" / "✏ Edit" in the
Builder tab's Custom template section. Ported from the original's
`open_custom_template_editor`.

A name field, a plain-text editor for the template body, and a toolbar
of "insert variable" buttons ([Name N]/[Description N]/[Outfit N] auto-
number to the next unused index for that kind; [Style]/[Scenario]/
[Tool] are singletons with no index). Save validates both fields are
non-empty and returns (name, text) via `get_result()`; a Delete button
is only shown when editing an existing template (`edit_name` given).

BuilderTab owns actually writing to `_custom_templates.json` — this
dialog only collects the two strings and, for Delete, reports that the
existing template should be removed via `delete_requested`.
"""
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
    QPushButton, QGroupBox, QMessageBox,
)

from backend.constants import CUSTOM_VAR_PATTERN
from ui.dialogs import themed_message_box


class CustomTemplateEditorDialog(QDialog):
    delete_requested = pyqtSignal(str)  # emits edit_name, dialog stays open until caller closes it

    def __init__(self, edit_name: str = None, initial_text: str = "", parent=None):
        super().__init__(parent)
        self.edit_name = edit_name
        self.setWindowTitle("Edit custom template" if edit_name else "New custom template")
        self.setMinimumSize(680, 560)

        self._result = None

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Template name:"))
        self.ent_name = QLineEdit(edit_name or "")
        layout.addWidget(self.ent_name)

        layout.addWidget(QLabel(
            "Template text — write it like a normal prompt, and insert variables "
            "using the buttons below:"))
        self.txt = QPlainTextEdit()
        self.txt.setPlainText(initial_text)
        layout.addWidget(self.txt, 1)

        toolbar = QGroupBox(" Insert variable ")
        toolbar_layout = QVBoxLayout(toolbar)
        row1 = QHBoxLayout()
        for label, kind in (("＋ Character Name", "Name"),
                            ("＋ Character Description", "Description"),
                            ("＋ Character Outfit", "Outfit")):
            btn = QPushButton(label)
            btn.clicked.connect(lambda _checked=False, k=kind: self._insert_var(k))
            row1.addWidget(btn)
        toolbar_layout.addLayout(row1)
        row2 = QHBoxLayout()
        for label, kind in (("＋ Style", "Style"), ("＋ Scenario", "Scenario"), ("＋ Tool", "Tool")):
            btn = QPushButton(label)
            btn.clicked.connect(lambda _checked=False, k=kind: self._insert_var(k))
            row2.addWidget(btn)
        toolbar_layout.addLayout(row2)
        layout.addWidget(toolbar)

        hint = QLabel(
            "Each click on \"Name/Description/Outfit\" adds a variable for the next "
            "template character in sequence (1, 2, 3…). Only the fields you actually "
            "used here will appear in the builder — if you don't need a style, scenario, "
            "or tool, just don't add them.")
        hint.setWordWrap(True)
        hint.setObjectName("dim")
        layout.addWidget(hint)

        btn_row = QHBoxLayout()
        if edit_name:
            btn_delete = QPushButton("🗑 Delete")
            btn_delete.setObjectName("danger")
            btn_delete.clicked.connect(self._on_delete)
            btn_row.addWidget(btn_delete)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.setObjectName("ghost")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)
        btn_save = QPushButton("💾 Save")
        btn_save.setObjectName("accent")
        btn_save.clicked.connect(self._on_save)
        btn_row.addWidget(btn_save)
        layout.addLayout(btn_row)

        self.ent_name.setFocus()

    def _insert_var(self, kind):
        if kind in ("Name", "Description", "Outfit"):
            current = self.txt.toPlainText()
            existing = [int(m.group(2)) for m in CUSTOM_VAR_PATTERN.finditer(current)
                        if m.group(1) == kind]
            next_idx = (max(existing) + 1) if existing else 1
            token = f"[{kind} {next_idx}]"
        else:
            token = f"[{kind}]"
        cursor = self.txt.textCursor()
        cursor.insertText(token)
        self.txt.setTextCursor(cursor)
        self.txt.setFocus()

    def _on_save(self):
        name = self.ent_name.text().strip()
        body = self.txt.toPlainText().strip()
        if not name:
            themed_message_box.warning(self, "Error", "Enter a template name.")
            return
        if not body:
            themed_message_box.warning(self, "Error", "Template text cannot be empty.")
            return
        self._result = (name, body)
        self.accept()

    def _on_delete(self):
        if not self.edit_name:
            return
        if themed_message_box.question(
                self, "Delete template",
                f'Delete the template "{self.edit_name}"?'
        ) != QMessageBox.StandardButton.Yes:
            return
        self.delete_requested.emit(self.edit_name)
        self.reject()

    def get_result(self):
        """Returns (name, body) after a successful Save, else None."""
        return self._result
