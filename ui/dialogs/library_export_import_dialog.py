"""Shared read-only report dialog for the Library export/import flow —
same shape as the original's `_show_preview_dialog` (title + read-only
scrollable text + Close), reused here rather than building two near-
identical dialogs for "exported to ..." confirmation and "N imported /
M skipped" results, per the migration plan.

`LibraryExportImportDialog.show_report(parent, title, content)` is the
intended entry point.
"""
from PyQt6.QtWidgets import QDialog, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout


class LibraryExportImportDialog(QDialog):
    def __init__(self, title: str, content: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(480, 360)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(title))

        txt = QPlainTextEdit()
        txt.setReadOnly(True)
        txt.setPlainText(content)
        layout.addWidget(txt, 1)

        btn_close = QPushButton("Close")
        btn_close.setObjectName("ghost")
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close)

    @staticmethod
    def show_report(parent, title: str, content: str):
        dlg = LibraryExportImportDialog(title, content, parent=parent)
        dlg.exec()
