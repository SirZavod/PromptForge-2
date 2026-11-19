"""Session 71: one collapsible model row in Settings' "Models" card.

The row is deliberately UI-only: it renders one resolved preset (from
`get_model_preset`), keeps the file/sampling fields editable and emits a
signal when something changed. Persisting, validating against the backend
and refreshing the card stay in `main.MainWindow`, so the same row can be
tested without a real ComfyUI or a data folder.

Collapsed, a row shows one summary line. Expanded, it reveals the three
model file fields, Steps / CFG and (for everything but Default) the LoRA
list source. File lists are fetched lazily on first expansion so building
the Settings page never blocks on ComfyUI.

Session 72 extra (D33): the three file fields are `ModelFileSelect`
dropdowns ("Workflow default" / "Assign…"); nothing can be typed, and the
assign dialog is the only way to set a name.

Session 73 extra (D34 / D35 / D37): the same dropdown also carries the
text encoder type, the sampler and the scheduler. Their values come from
ComfyUI's own node definitions (the `choices` of the model-files state)
and each field is enabled by *its own* list, so an old node pack disables
only the type, never the sampler / scheduler.
"""
from PyQt6.QtCore import QEvent, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ui.widgets.model_file_select import ModelFileSelect

# Preset field -> /promptforge/models kind.
FILE_KINDS = {
    "diffusion_model": "diffusion",
    "clip": "clip",
    "vae": "vae",
}

# Preset field -> assign-dialog title / prompt.
FILE_DIALOGS = {
    "diffusion_model": (
        "Assign diffusion model",
        "Select a diffusion model to use for this preset:"),
    "clip": (
        "Assign text encoder",
        "Select a text encoder to use for this preset:"),
    "vae": (
        "Assign VAE",
        "Select a VAE to use for this preset:"),
}

# Session 73 extra: choice-valued fields, in display order, with the noun
# used in the "ComfyUI did not list ..." note.
CHOICE_FIELDS = ("clip_type", "sampler", "scheduler")
CHOICE_NOUNS = {
    "clip_type": "text encoder types",
    "sampler": "samplers",
    "scheduler": "schedulers",
}
FILE_DIALOGS.update({
    "clip_type": (
        "Assign text encoder type",
        "Select the text encoder type to use for this preset:"),
    "sampler": (
        "Assign sampler",
        "Select a sampler to use for this preset:"),
    "scheduler": (
        "Assign scheduler",
        "Select a scheduler to use for this preset:"),
})
LOADING_NOTE = "Loading model files from ComfyUI…"

STEPS_MIN, STEPS_MAX = 1, 10000
CFG_MIN, CFG_MAX = 0.0, 100.0


def parse_steps(text):
    """Session 71: blank -> None; else a whole number in 1..10000.
    Raises ValueError with a user-facing sentence on bad input."""
    text = (text or "").strip()
    if not text:
        return None
    try:
        value = int(text)
    except ValueError:
        raise ValueError("Steps must be a whole number from 1 to 10000.")
    if not STEPS_MIN <= value <= STEPS_MAX:
        raise ValueError("Steps must be a whole number from 1 to 10000.")
    return value


def parse_cfg(text):
    """Session 71: blank -> None; else a decimal in 0..100. Both dot and
    comma are accepted, matching the Builder's CFG field (D29)."""
    text = (text or "").strip().replace(",", ".")
    if not text:
        return None
    try:
        value = float(text)
    except ValueError:
        raise ValueError("CFG must be a number from 0 to 100.")
    if not CFG_MIN <= value <= CFG_MAX:
        raise ValueError("CFG must be a number from 0 to 100.")
    return value


def choice_states(state):
    """Session 73 extra (D37): `{field: (values, note)}` for the three
    choice fields, from a `collect_model_files` result (state None = still
    loading). A field is usable exactly when its own list is not empty;
    `note` explains an empty one (the state's own message when ComfyUI is
    offline or the pack is too old, otherwise that ComfyUI did not list
    the values). A state with no `choices` key at all (the shape before
    this session) returns None: nothing is known, so the fields are left
    exactly as they were. Pure: no widgets, so Settings and the tests
    share it."""
    if state is None:
        return {field: ([], LOADING_NOTE) for field in CHOICE_FIELDS}
    if "choices" not in state:
        return None
    choices = state.get("choices") or {}
    result = {}
    for field in CHOICE_FIELDS:
        values = [v for v in (choices.get(field) or [])
                  if isinstance(v, str) and v]
        if values:
            result[field] = (values, "")
            continue
        note = ""
        status = state.get("status")
        if status in ("offline", "old_pack"):
            note = state.get("message") or ""
        if not note:
            note = f"ComfyUI did not list the {CHOICE_NOUNS[field]}."
        result[field] = ([], note)
    return result


def format_cfg(value):
    if value is None:
        return ""
    return f"{value:g}"


class ModelPresetRow(QFrame):
    """One collapsible row: Default first, then every added model."""

    field_changed = pyqtSignal(dict)
    source_changed = pyqtSignal(str)
    rename_requested = pyqtSignal(str)
    duplicate_requested = pyqtSignal()
    delete_requested = pyqtSignal()
    validation_failed = pyqtSignal(str)
    expanded_changed = pyqtSignal(bool)

    def __init__(self, preset, file_choices, source_choices=None,
                 source_names=None, dependents=(), expanded=False,
                 parent=None, choice_states=None):
        super().__init__(parent)
        self._choice_states = choice_states
        self.preset = dict(preset)
        self.is_default = bool(preset.get("is_default"))
        self.profile_id = preset.get("id")
        self._file_choices = file_choices
        self._source_names = dict(source_names or {})
        self._expanded = False
        self._hovered = False
        self._choices_loaded = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.btn_header = QPushButton()
        self.btn_header.setFlat(True)
        self.btn_header.setStyleSheet("text-align: left; padding: 2px 0;")
        self.btn_header.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_header.clicked.connect(
            lambda: self.set_expanded(not self._expanded))
        self.btn_header.installEventFilter(self)
        layout.addWidget(self.btn_header)

        self.body = QWidget()
        body_layout = QVBoxLayout(self.body)
        body_layout.setContentsMargins(8, 0, 0, 4)
        body_layout.setSpacing(6)

        self.name_row = QWidget()
        name_row = QHBoxLayout(self.name_row)
        name_row.setContentsMargins(0, 0, 0, 0)
        name_row.addWidget(QLabel("Name:"))
        self.name_edit = QLineEdit(self.preset.get("name", ""))
        self.name_edit.setMaxLength(40)
        self.name_edit.setReadOnly(self.is_default)
        self.name_edit.editingFinished.connect(self._on_name_edited)
        name_row.addWidget(self.name_edit, 1)
        self.btn_duplicate = QPushButton("Duplicate")
        self.btn_duplicate.clicked.connect(
            lambda _checked=False: self.duplicate_requested.emit())
        self.btn_delete = QPushButton("Delete")
        self.btn_delete.clicked.connect(
            lambda _checked=False: self.delete_requested.emit())
        if self.is_default:
            # Default is a preset too, but it cannot be renamed, copied or
            # deleted -- its summary line already names it.
            self.btn_duplicate.setVisible(False)
            self.btn_delete.setVisible(False)
            self.name_row.setVisible(False)
        else:
            name_row.addWidget(self.btn_duplicate)
            name_row.addWidget(self.btn_delete)
        body_layout.addWidget(self.name_row)

        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        # The file field takes the whole free width of the row; the label
        # column keeps its natural width and Steps / CFG stay short and
        # left-aligned to the same field column.
        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 1)

        self._file_combos = {}
        self.combo_diffusion = self._make_file_combo("diffusion_model")
        self.combo_clip = self._make_file_combo("clip")
        self.combo_vae = self._make_file_combo("vae")
        self.combo_clip_type = self._make_file_combo("clip_type")
        self.combo_sampler = self._make_file_combo("sampler")
        self.combo_scheduler = self._make_file_combo("scheduler")
        # Choice fields stay disabled until their list is known (D37).
        for field in CHOICE_FIELDS:
            self._file_combos[field].setEnabled(False)
        for row_index, (label, field) in enumerate((
                ("Diffusion model:", "diffusion_model"),
                ("Text encoder:", "clip"),
                ("Text encoder type:", "clip_type"),
                ("VAE:", "vae"))):
            grid.addWidget(QLabel(label), row_index, 0)
            grid.addWidget(self._file_combos[field], row_index, 1)

        self.edit_steps = QLineEdit(
            "" if preset.get("steps") is None else str(preset["steps"]))
        self.edit_steps.setPlaceholderText("from workflow")
        self.edit_steps.setMaximumWidth(140)
        self.edit_steps.editingFinished.connect(self._on_steps_edited)
        grid.addWidget(QLabel("Steps:"), 4, 0)
        grid.addWidget(self.edit_steps, 4, 1)

        self.edit_cfg = QLineEdit(format_cfg(preset.get("cfg")))
        self.edit_cfg.setPlaceholderText("from workflow")
        self.edit_cfg.setMaximumWidth(140)
        self.edit_cfg.editingFinished.connect(self._on_cfg_edited)
        grid.addWidget(QLabel("CFG:"), 5, 0)
        grid.addWidget(self.edit_cfg, 5, 1)
        grid.addWidget(QLabel("Sampler:"), 6, 0)
        grid.addWidget(self._file_combos["sampler"], 6, 1)
        grid.addWidget(QLabel("Scheduler:"), 7, 0)
        grid.addWidget(self._file_combos["scheduler"], 7, 1)

        self.combo_source = None
        if not self.is_default:
            self.combo_source = QComboBox()
            for label, data in (source_choices or []):
                self.combo_source.addItem(label, data)
            index = self.combo_source.findData(
                self.preset.get("lora_source") or "own")
            self.combo_source.setCurrentIndex(index if index >= 0 else 0)
            self.combo_source.activated.connect(
                lambda _index: self.source_changed.emit(
                    self.combo_source.currentData()))
            if dependents:
                names = ", ".join(f'"{name}"' for name in dependents)
                self.combo_source.setEnabled(False)
                self.combo_source.setToolTip(
                    f"Used as the LoRA list source by {names}. "
                    "Switch those models to another list first.")
            grid.addWidget(QLabel("LoRA list:"), 8, 0)
            grid.addWidget(self.combo_source, 8, 1)

        self.lbl_note = QLabel()
        self.lbl_note.setObjectName("dim")
        self.lbl_note.setWordWrap(True)
        self.lbl_note.setVisible(False)
        grid.addWidget(self.lbl_note, 9, 0, 1, 2)

        body_layout.addLayout(grid)
        layout.addWidget(self.body)

        if expanded:
            self.set_expanded(True, notify=False)
        else:
            self.body.setVisible(False)
            self._update_header()

    # ------------------------------------------------------------ files --
    def _make_file_combo(self, field):
        title, prompt = FILE_DIALOGS[field]
        combo = ModelFileSelect(title, prompt)
        combo.set_value(self.preset.get(field) or "")
        combo.value_changed.connect(
            lambda value, f=field: self._apply_field(f, value))
        self._file_combos[field] = combo
        return combo

    def _ensure_choices(self):
        if self._choices_loaded:
            return
        self._choices_loaded = True
        note = ""
        enabled = True
        files = {}
        for field in ("diffusion_model", "clip", "vae"):
            kind = FILE_KINDS[field]
            kind_files, kind_note, kind_enabled = self._file_choices(kind)
            files[kind] = kind_files
            note = note or kind_note
            enabled = enabled and kind_enabled
        choices = self._choice_states() if self._choice_states else None
        self.apply_file_choices(files, note, enabled, choices=choices)

    def apply_file_choices(self, files, note="", enabled=True, choices=None):
        """Session 71: fills the three fields from the MainWindow's cache
        (called both on first expansion and when a background fetch
        finishes). The stored value is always kept, even when the file
        is missing from the list or ComfyUI is offline.

        Session 72 extra: `files` is only trusted as a complete list when
        the provider is enabled and has no note (the ok state); loading,
        offline and error states must not mark a stored value missing.

        Session 73 extra (D37): `choices` is `choice_states(state)` --
        `{field: (values, note)}` for the type / sampler / scheduler. Each
        field is enabled by its own list; the notes of empty fields join
        the file note (same text is shown once). `None` leaves the three
        fields as they were."""
        if not self._choices_loaded:
            return
        known = enabled and not note
        for field in ("diffusion_model", "clip", "vae"):
            kind = FILE_KINDS[field]
            kind_files = files.get(kind, [])
            combo = self._file_combos[field]
            combo.set_files(kind_files, known=known)
            combo.setEnabled(enabled)
            combo.set_assign_enabled(enabled and bool(kind_files), note)
        notes = [note] if note else []
        for field in CHOICE_FIELDS:
            if choices is None or field not in choices:
                continue
            values, choice_note = choices[field]
            combo = self._file_combos[field]
            combo.set_files(values, known=bool(values))
            combo.setEnabled(bool(values))
            combo.set_assign_enabled(bool(values), choice_note)
            if choice_note and choice_note not in notes:
                notes.append(choice_note)
        if notes:
            self.lbl_note.setText("\n".join(notes))
            self.lbl_note.setVisible(True)
        else:
            self.lbl_note.clear()
            self.lbl_note.setVisible(False)

    # ------------------------------------------------------ steps / cfg --
    def _on_steps_edited(self):
        try:
            value = parse_steps(self.edit_steps.text())
        except ValueError as exc:
            self.validation_failed.emit(str(exc))
            self.edit_steps.setText(
                "" if self.preset.get("steps") is None
                else str(self.preset["steps"]))
            return
        self._apply_field("steps", value)

    def _on_cfg_edited(self):
        try:
            value = parse_cfg(self.edit_cfg.text())
        except ValueError as exc:
            self.validation_failed.emit(str(exc))
            self.edit_cfg.setText(format_cfg(self.preset.get("cfg")))
            return
        self._apply_field("cfg", value)

    # ----------------------------------------------------------- fields --
    def _apply_field(self, field, value):
        if self.preset.get(field) == value:
            return
        self.preset[field] = value
        self._refresh_header()
        self.field_changed.emit({field: value})

    def apply_preset(self, preset):
        """Adopt the backend's sanitized preset without rebuilding the row
        (used after Steps / CFG were clamped or a file was cleared)."""
        self.preset = dict(preset)
        self.edit_steps.setText(
            "" if preset.get("steps") is None else str(preset["steps"]))
        self.edit_cfg.setText(format_cfg(preset.get("cfg")))
        for field in ("diffusion_model", "clip", "vae") + CHOICE_FIELDS:
            self._file_combos[field].set_value(preset.get(field) or "")
        self._refresh_header()

    # ------------------------------------------------------------ name ---
    def _on_name_edited(self):
        if self.is_default:
            return
        new_name = " ".join(self.name_edit.text().split())
        if new_name and new_name != self.preset.get("name"):
            self.rename_requested.emit(new_name)

    # -------------------------------------------------------- expansion --
    def set_expanded(self, expanded, notify=True):
        self._expanded = bool(expanded)
        self.body.setVisible(self._expanded)
        if self._expanded:
            self._ensure_choices()
        else:
            # Re-expanding re-reads the provider, which is how an offline
            # fetch gets retried after ComfyUI starts (cached "ok" lists
            # are returned instantly).
            self._choices_loaded = False
        self._update_header()
        if notify:
            self.expanded_changed.emit(self._expanded)

    def is_expanded(self):
        return self._expanded

    def reload_file_choices(self):
        """Session 71: re-reads the provider (used when Settings is opened
        again, so a file dropped into ComfyUI's models/ folder appears
        without restarting either program)."""
        if not self._expanded:
            return
        self._choices_loaded = False
        self._ensure_choices()

    def _summary_text(self):
        parts = [self.preset.get("name") or "Default"]
        if not self.is_default:
            source = self.preset.get("lora_source") or "own"
            if source == "own":
                parts.append("own LoRAs")
            elif source == "default":
                parts.append("Default LoRAs")
            else:
                target = self._source_names.get(source) or "shared"
                parts.append(f"{target} LoRAs")
        if self.preset.get("steps") is not None:
            parts.append(f'{self.preset["steps"]} steps')
        if self.preset.get("cfg") is not None:
            parts.append(f'CFG {format_cfg(self.preset["cfg"])}')
        return " · ".join(parts)

    def _update_header(self):
        arrow = "▾" if self._expanded else ("▸" if self._hovered else "")
        text = self._summary_text()
        self.btn_header.setText(f"{arrow}  {text}" if arrow else text)

    def _refresh_header(self):
        self._update_header()

    def eventFilter(self, obj, event):
        if obj is self.btn_header:
            if event.type() == QEvent.Type.Enter:
                self._hovered = True
                self._update_header()
            elif event.type() == QEvent.Type.Leave:
                self._hovered = False
                self._update_header()
        return super().eventFilter(obj, event)
