"""In-app multi-language Guide dialog (❓ Guide button / F1).

Ported from the original's `open_guide`. All the actual guide text
lives in `backend/guide_content.py` (Session 1, plain data, not touched
here) — this module is purely the presentation layer: a language
combobox (display names, e.g. "Русский" — resolved back to the
GUIDE_CONTENT language code via a display->code lookup), a section-nav
QListWidget on the left, and a read-only body QPlainTextEdit on the
right.

Behavioral contract preserved from the original (see SESSION 12 plan):
- Switching language re-populates section titles in the new language
  but keeps whichever section index was selected selected — it must
  never silently jump back to section 0.
- The chosen language code is persisted to settings["guide_language"]
  immediately on change (same "save immediately" pattern every other
  settings-backed control in this app already follows), via the same
  mutable `settings` dict + `settings_file` path every other dialog/tab
  that persists settings is handed.
- A language entirely absent from GUIDE_CONTENT falls back to English
  section-by-section (GUIDE_CONTENT.get(lang, GUIDE_CONTENT["en"]) plus
  a per-key .get(...) fallback) — GUIDE_CONTENT itself already fills in
  every declared language with explicit "translation pending" text via
  backend/guide_content.py's _guide_pending loop, so in practice this
  fallback only matters for a language code that isn't in
  GUIDE_LANGUAGES at all (e.g. a stale settings file from a future
  build with a language this build doesn't know).
"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from backend.file_manager import FileManagerError, save_json
from backend.guide_content import GUIDE_CONTENT, GUIDE_LANGUAGES, GUIDE_SECTION_ORDER
from ui.dialogs.framed_dialog import FramelessDialogMixin


class GuideDialog(FramelessDialogMixin, QDialog):
    def __init__(self, settings: dict, settings_file: str, colors: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("PromptForge Guide")
        self.resize(760, 560)
        self.setMinimumSize(720, 520)

        self.settings = settings
        self.settings_file = settings_file

        # Combobox shows display names ("English", "Русский", ...) but
        # everything else here keys off the language code — keep a
        # lookup both ways so picking a display name resolves back to
        # the code GUIDE_CONTENT is actually indexed by.
        self._code_by_display = {v: k for k, v in GUIDE_LANGUAGES.items()}
        self._lang_code = self.settings.get("guide_language", "en")
        if self._lang_code not in GUIDE_LANGUAGES:
            self._lang_code = "en"

        content = QWidget()
        outer = QVBoxLayout(content)

        top_row = QHBoxLayout()
        title = QLabel("❓ PromptForge Guide")
        title.setObjectName("Title")
        top_row.addWidget(title)
        top_row.addStretch(1)
        top_row.addWidget(QLabel("Language:"))
        self.lang_combo = QComboBox()
        self.lang_combo.addItems(list(GUIDE_LANGUAGES.values()))
        self.lang_combo.setCurrentText(GUIDE_LANGUAGES.get(self._lang_code, "English"))
        self.lang_combo.currentTextChanged.connect(self._on_language_changed)
        top_row.addWidget(self.lang_combo)
        outer.addLayout(top_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(splitter, 1)

        nav_wrap = QWidget()
        nav_layout = QVBoxLayout(nav_wrap)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        self.section_list = QListWidget()
        self.section_list.setMinimumWidth(200)
        self.section_list.setMaximumWidth(260)
        self.section_list.currentRowChanged.connect(self._on_section_selected)
        nav_layout.addWidget(self.section_list)
        splitter.addWidget(nav_wrap)

        self.guide_txt = QPlainTextEdit()
        self.guide_txt.setReadOnly(True)
        splitter.addWidget(self.guide_txt)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([220, 540])

        btn_close = QPushButton("Close")
        btn_close.setObjectName("ghost")
        btn_close.clicked.connect(self.accept)
        outer.addWidget(btn_close)

        self._populate_section_list()
        if self.section_list.count():
            self.section_list.setCurrentRow(0)
        else:
            self._render_section(0)

        self._init_frameless_titlebar(colors, content)

    # ------------------------------------------------------------------
    def _current_content(self) -> dict:
        return GUIDE_CONTENT.get(self._lang_code, GUIDE_CONTENT["en"])

    def _populate_section_list(self):
        content = self._current_content()
        self.section_list.blockSignals(True)
        self.section_list.clear()
        for key in GUIDE_SECTION_ORDER:
            title, _ = content.get(key, GUIDE_CONTENT["en"][key])
            self.section_list.addItem(title)
        self.section_list.blockSignals(False)

    def _render_section(self, index: int):
        if not (0 <= index < len(GUIDE_SECTION_ORDER)):
            self.guide_txt.setPlainText("")
            return
        content = self._current_content()
        section_key = GUIDE_SECTION_ORDER[index]
        _title, text = content.get(section_key, GUIDE_CONTENT["en"][section_key])
        self.guide_txt.setPlainText(text)

    def _on_section_selected(self, index: int):
        self._render_section(index)

    def _on_language_changed(self, display_name: str):
        code = self._code_by_display.get(display_name, "en")
        self._lang_code = code
        self.settings["guide_language"] = code
        try:
            save_json(self.settings_file, self.settings)
        except FileManagerError:
            # Guide language is a nice-to-have persisted preference, not
            # something worth interrupting reading the guide over — a
            # failed save here just means it'll default to "en" (or the
            # last successfully-saved language) next launch.
            pass

        # Re-populate titles in the new language, but keep whatever
        # section was selected selected — switching language must never
        # silently jump back to section 0.
        current_index = self.section_list.currentRow()
        if current_index < 0:
            current_index = 0
        self._populate_section_list()
        if self.section_list.count():
            self.section_list.setCurrentRow(min(current_index, self.section_list.count() - 1))
        else:
            self._render_section(current_index)
