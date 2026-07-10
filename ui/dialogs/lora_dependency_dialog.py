"""LoRA dependency report + candidate-picker dialogs — ported from the
original's `_show_lora_dependency_report` / `_show_lora_candidates_dialog`
in the Tkinter monolith (promptforgeint.py).

Two dialogs live here:

- `LoraDependencyReportDialog` — read-only report of every missing LoRA
  path and which library entries use it, plus a "🔎 Find candidates"
  button that hands off to the second dialog.
- `LoraCandidatesDialog` — the interactive candidate-confirmation UI.
  For each missing path: a single same-basename match elsewhere in
  ComfyUI's LoRA list gets a one-click "Use this" button; a genuine
  name collision (2+ matches) lists every option with its own button
  (never auto-picked); no match gets plain text and no button. A
  "✓ Use all N single-match candidates" bulk button is offered when
  there's at least one single-match row, matching the original's bulk
  shortcut — it only ever fires the single-match rows, collisions are
  never included.

Both dialogs are read/act-only against data the caller already
collected (`missing`, `available_loras`) — actually applying a
candidate goes through `backend.lora_deps.apply_lora_candidate`, called
by the caller-supplied `on_apply_candidate` callback so this module
doesn't need to import backend.file_manager directly.
"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from backend.constants import CATEGORY_LABELS, natural_sort_key
from backend.lora_deps import find_lora_candidates


class LoraDependencyReportDialog(QDialog):
    def __init__(self, report_text: str, missing: dict, available_loras: list,
                 on_apply_candidate, parent=None):
        super().__init__(parent)
        self.setWindowTitle("LoRA dependency check")
        self.resize(560, 420)
        self._missing = missing
        self._available_loras = available_loras
        self._on_apply_candidate = on_apply_candidate

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("LoRA dependency check"))

        txt = QPlainTextEdit()
        txt.setReadOnly(True)
        txt.setPlainText(report_text)
        layout.addWidget(txt, 1)

        btn_row = QHBoxLayout()
        btn_find = QPushButton("🔎 Find candidates")
        btn_find.setObjectName("accent")
        btn_find.clicked.connect(self._open_candidates)
        btn_close = QPushButton("Close")
        btn_close.setObjectName("ghost")
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_find, 1)
        btn_row.addWidget(btn_close, 1)
        layout.addLayout(btn_row)

    def _open_candidates(self):
        self.accept()
        dlg = LoraCandidatesDialog(self._missing, self._available_loras,
                                    self._on_apply_candidate, parent=self.parent())
        dlg.exec()


class LoraCandidatesDialog(QDialog):
    def __init__(self, missing: dict, available_loras: list, on_apply_candidate, parent=None):
        super().__init__(parent)
        self.setWindowTitle("LoRA candidates")
        self.resize(600, 460)
        self._missing = missing
        self._on_apply_candidate = on_apply_candidate
        self._candidates = find_lora_candidates(available_loras, list(missing.keys()))

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("🔎 LoRA candidates"))

        hint = QLabel(
            "Matched by filename only, ignoring folder — review each one before "
            "applying. A path with more than one match is a real name collision "
            "(e.g. two different LoRAs for different base models): nothing is "
            "picked automatically, choose which one is actually correct.")
        hint.setWordWrap(True)
        hint.setObjectName("dim")
        layout.addWidget(hint)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._list_widget = QWidget()
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(self._list_widget)
        layout.addWidget(scroll, 1)

        self._row_use_this = {}  # missing_path -> callable, single-match rows only
        for missing_path in sorted(missing.keys(), key=natural_sort_key):
            self._list_layout.addWidget(self._build_row(missing_path))
        self._list_layout.addStretch(1)

        self._bulk_btn = None
        single_match_paths = [mp for mp, result in self._candidates.items()
                               if isinstance(result, str)]
        if single_match_paths:
            self._bulk_btn = QPushButton(
                f"✓ Use all {len(single_match_paths)} single-match candidate"
                f"{'s' if len(single_match_paths) != 1 else ''}")
            self._bulk_btn.setObjectName("accent")
            self._bulk_btn.clicked.connect(self._use_all_single_matches)
            layout.addWidget(self._bulk_btn)

        btn_close = QPushButton("Close")
        btn_close.setObjectName("ghost")
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close)

    def _build_row(self, missing_path: str) -> QFrame:
        row = QFrame()
        row.setObjectName("card")
        row_layout = QVBoxLayout(row)

        lbl_title = QLabel(f"✗ {missing_path}")
        lbl_title.setWordWrap(True)
        row_layout.addWidget(lbl_title)

        affected = self._missing[missing_path]
        affected_desc = ", ".join(
            f"[{CATEGORY_LABELS.get(cat, cat)}] {name}" for cat, name in affected)
        lbl_used_by = QLabel(f"used by: {affected_desc}")
        lbl_used_by.setWordWrap(True)
        lbl_used_by.setObjectName("dim")
        row_layout.addWidget(lbl_used_by)

        result = self._candidates.get(missing_path)
        if result is None:
            lbl_none = QLabel("No matching filename found anywhere in ComfyUI's "
                               "LoRA list — nothing to suggest.")
            lbl_none.setObjectName("dim")
            row_layout.addWidget(lbl_none)
            return row

        option_paths = [result] if isinstance(result, str) else result
        if len(option_paths) > 1:
            lbl_warn = QLabel(f"⚠ {len(option_paths)} files share this name — "
                               f"pick the correct one:")
            lbl_warn.setObjectName("dim")
            row_layout.addWidget(lbl_warn)

        for candidate_path in option_paths:
            cand_row = QHBoxLayout()
            lbl_cand = QLabel(f"→ {candidate_path}")
            lbl_cand.setWordWrap(True)
            cand_row.addWidget(lbl_cand, 1)
            btn_use = QPushButton("Use this")

            def use_this(_checked=False, mp=missing_path, cp=candidate_path,
                         aff=affected, r=row, b=btn_use):
                self._apply_row(mp, cp, aff, r)

            btn_use.clicked.connect(use_this)
            cand_row.addWidget(btn_use)
            row_layout.addLayout(cand_row)

            if len(option_paths) == 1:
                self._row_use_this[missing_path] = lambda mp=missing_path, cp=candidate_path, \
                    aff=affected, r=row: self._apply_row(mp, cp, aff, r)

        return row

    def _apply_row(self, missing_path, candidate_path, affected, row):
        updated = self._on_apply_candidate(missing_path, candidate_path, affected)
        # Clear the row and replace it with a confirmation, same as the
        # original — the dialog stays open for the remaining rows.
        layout = row.layout()
        while layout.count():
            item = layout.takeAt(0)
            child = item.widget()
            if child is not None:
                child.deleteLater()
            else:
                sub = item.layout()
                if sub is not None:
                    while sub.count():
                        sub_item = sub.takeAt(0)
                        if sub_item.widget() is not None:
                            sub_item.widget().deleteLater()
        lbl_done = QLabel(f"✓ Re-pointed to {candidate_path}")
        layout.addWidget(lbl_done)
        lbl_count = QLabel(f"{updated} entr{'y' if updated == 1 else 'ies'} updated.")
        lbl_count.setObjectName("dim")
        layout.addWidget(lbl_count)

    def _use_all_single_matches(self):
        # Snapshot first — _apply_row mutates the row in place as it
        # goes, which would otherwise disturb iteration order.
        for fn in list(self._row_use_this.values()):
            fn()
        if self._bulk_btn is not None:
            self._bulk_btn.setEnabled(False)
            self._bulk_btn.setText("✓ Applied")
