"""Builder tab — Parts 1 & 2 (Sessions 10-11).

Left column: Prompt Template panel (Standard/Custom switch),
Style/Characters/Scenario/Tools blocks for the Standard template, the
Custom template's own dynamic form, the Negative prompt box, the
Generate button + prompt output, the ComfyUI connection panel, the
collapsible LoRA manager, and the "🎨 Generate in ComfyUI" queue row
(Session 11). Right column: the "Latest image" result viewer, progress
bar, status label, and Stop/Open-folder buttons (Session 11).

Ported from the original monolith's Builder-tab methods
(`build_builder_tab`, `on_template_category_changed`,
`add_character_slot`/`remove_character_slot`, `add_tool_slot`/
`remove_tool_slot`, `update_outfit_list`, `quick_preview`/
`quick_preview_outfit`, `open_order_dialog`, `save_current_as_template`,
`build_custom_template_form`, `open_custom_template_editor`,
`generate_prompt`/`generate_standard_prompt`/`generate_custom_prompt`,
`_finalize_generated_prompt` — Session 10 — plus, for Session 11:
`on_comfy_toggle`/`_on_comfy_check_done`, `_build_lora_slots`/
`_lora_create_slot`/`_lora_on_slot_changed`/`_lora_sync_data`/
`_lora_persist`/`_lora_update_combos`/`_lora_autofill_from_library`,
`on_generate_in_comfy_clicked`/`_maybe_start_next_queued_generation`/
`_start_comfy_generation`/`on_comfy_stop_clicked`/`clear_comfy_queue`,
`_on_comfy_progress`/`_on_comfy_preview_bytes`/`_on_comfy_image_bytes`/
`_on_comfy_video_bytes`/`_on_comfy_generation_failed`/`_on_comfy_generation_done`,
`comfy_open_output_folder`, `_resize_comfy_result_zone`).

The pure prompt-assembly logic lives in `backend.prompt_builder`
(Session 1); the ComfyUI network pipeline itself (graph fetch/patch/
submit/poll/download) lives entirely in `workers.comfy_worker`'s
`ComfyCheckWorker`/`ComfyGenerationWorker` (Session 9) — this file is
the widget layer that gathers values out of its own combo boxes/text
fields, hands them to those functions/workers, and reacts to their
signals. One consequence worth flagging: because the Session 9 workers
already own the entire fetch-graph → validate → patch → submit → poll
→ download pipeline internally, `_start_comfy_generation` here is far
shorter than the original's same-named method — it only builds the
queue-item dict and wires up `ComfyGenerationWorker`'s five signals,
none of the actual HTTP/graph-patching logic is duplicated here.

Cross-tab wiring note: `history_tab`/`library_tab`/`gallery_tab` are
plain public attributes, `None` until `main.py` sets them right after
constructing all four tabs (same pattern Session 10 started with
`prompt_generated`, just via direct method calls here instead of a
signal — synchronous calls are unavoidable for `add_comfy_history_entry`,
since its return value (the new history id) has to travel inside the
queue-item dict). Every call site checks `is not None` first, so this
tab stays fully constructible and independently testable without any
of the other tabs existing.
"""
import os
import random
import time

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QGroupBox, QLabel,
    QPushButton, QComboBox, QPlainTextEdit, QFrame, QMessageBox, QInputDialog,
    QDialog, QSizePolicy, QCheckBox, QLineEdit, QRadioButton, QButtonGroup,
    QProgressBar, QDoubleSpinBox, QTabWidget, QStackedWidget,
)

from backend.constants import (
    TEMPLATES_FILE_NAME, CUSTOM_TEMPLATES_FILE_NAME, BLOCK_ORDER_LABELS,
    COMFY_DEFAULT_HOST, COMFY_DEFAULT_PORT, COMFY_RESOLUTION_PRESETS,
    COMFY_QUEUE_DEBOUNCE_MS, MAX_LORA_SLOTS, LORA_NONE_VALUE,
    LORA_STRENGTH_MIN, LORA_STRENGTH_MAX,
    LIBRARY_FOLDERS_FILE_NAME, LIBRARY_ACTIVE_FILE_NAME,
    PIPELINE_MODES, PIPELINE_MODE_T2I, PIPELINE_MODE_I2I, PIPELINE_MODE_I2V,
)
from backend.file_manager import (
    load_json, save_json, read_file_content,
    resolve_output_folder_for,
    save_comfy_preview_image, reveal_file_in_explorer, FileManagerError,
    get_active_file_list, list_active_outfit_options_for_character, load_active_map,
)
from backend.prompt_builder import (
    parse_custom_template, generate_custom_prompt, generate_standard_prompt,
    collect_active_library_loras, compute_lora_autofill,
)
from backend.comfy_client import ComfyUIClient
from backend import sound_manager
from workers.comfy_worker import ComfyCheckWorker, ComfyGenerationWorker
from ui.widgets.autocomplete import AutocompleteCombobox
from ui.dialogs import themed_message_box
from ui.widgets.no_scroll_spinbox import NoScrollDoubleSpinBox
from ui.widgets.image_zone import ResultImageViewer, ImageDropZone
from ui.widgets.collapsible_section import CollapsibleSection
from ui.widgets.collapsible_rail import CollapsibleRail
from ui.dialogs.order_dialog import BlockOrderDialog
from ui.dialogs.custom_template_editor import CustomTemplateEditorDialog

DEFAULT_BLOCK_ORDER = ["style", "characters", "scenario", "tools"]

# 46.2c follow-up #3: the right-rail Tools card's title per pipeline
# mode -- see `_apply_pipeline_mode`'s retitle block for why this isn't
# just CATEGORY_LABELS (t2i's card keeps its original plural "Tools",
# CATEGORY_LABELS' "tools" entry is the singular "Tool" tuned for the
# Library category-bar button instead).
_TOOLS_CARD_TITLE = {
    PIPELINE_MODE_T2I: "Tools",
    PIPELINE_MODE_I2I: "Edit Tools",
    PIPELINE_MODE_I2V: "Video Tools",
}


class BuilderTab(QWidget):
    """`prompt_generated(str)` fires once per successful "Generate prompt
    and copy" click **while ComfyUI is not connected** — carrying the
    final assembled prompt text for `MainWindow` to hand straight to
    `HistoryTab.add_to_history`, same as Session 10. Once ComfyUI is
    connected, history recording moves to "🎨 Generate in ComfyUI"
    instead (via `add_comfy_history_entry`, called synchronously
    through `self.history_tab` at enqueue time so the returned id can
    travel inside the queue item) — see `_finalize_generated_prompt`'s
    own note for why.

    `comfy_connection_changed(bool)` fires whenever the ComfyUI
    connection state changes (connected+workflow-ready, or not) —
    `main.py` connects it to `LibraryTab._refresh_lib_lora_visibility`.
    """

    prompt_generated = pyqtSignal(str)
    comfy_connection_changed = pyqtSignal(bool)
    # Session 14: sidebar shell needs its own read of the ComfyUI
    # connection status/busy state, since the checkbox+label that used
    # to be the only UI for this moved (functionally) to the sidebar
    # footer. These mirror `lbl_comfy_status`'s text and "a connection
    # check is in flight" without the sidebar reaching into Builder
    # internals directly.
    comfy_status_message_changed = pyqtSignal(str)
    comfy_check_busy_changed = pyqtSignal(bool)

    def __init__(self, data_dir: str, colors: dict, settings: dict, settings_file: str, parent=None):
        super().__init__(parent)
        self.data_dir = data_dir
        self.colors = colors
        self.settings = settings
        self.settings_file = settings_file

        # Session 45: Library Active/Inactive. The Builder doesn't own
        # folder_maps/active_map the way LibraryTab does (it never
        # organizes or edits either), so these are read fresh off disk
        # on every call via the two small helpers below rather than
        # cached — the Library tab already writes both files
        # synchronously on every change, so a fresh read is never
        # meaningfully stale (same reasoning sound_manager.play() uses
        # for settings.json).

        # Cross-tab hooks — set by main.py right after all four tabs are
        # constructed. Every call site below checks `is not None` first,
        # so this tab stays fully constructible/testable on its own.
        self.history_tab = None
        self.library_tab = None
        self.gallery_tab = None
        # Session 48.2: MainWindow itself, wired the same post-
        # construction way — needed so `_apply_pipeline_mode` can push
        # the active mode's caption onto the sidebar's mode-switch
        # button regardless of which tab the sidebar click came from.
        self.main_window = None

        self.templates_file = os.path.join(data_dir, TEMPLATES_FILE_NAME)
        self.custom_templates_file = os.path.join(data_dir, CUSTOM_TEMPLATES_FILE_NAME)
        self.templates: dict = load_json(self.templates_file, {})
        self.custom_templates: dict = load_json(self.custom_templates_file, {})

        saved_order = self.settings.get("block_order")
        if isinstance(saved_order, list) and saved_order:
            order = list(saved_order)
            for key in BLOCK_ORDER_LABELS:
                if key not in order:
                    order.append(key)
            self.block_order = order
        else:
            self.block_order = list(DEFAULT_BLOCK_ORDER)

        self.active_characters: list = []
        self.active_tools: list = []
        # Session 46.2 follow-up: i2i/i2v "Actions" slots -- same
        # add/remove-slot mechanics as `active_characters`, just
        # against the Library's own per-mode Actions category
        # ("image_actions"/"video_actions" -- see `_actions_category`,
        # 46.2c), already scoped to this mode by
        # `set_pipeline_mode_filter`.
        self.active_actions: list = []
        self.custom_active_slots: list = []
        self.custom_active_tools: list = []
        self.current_custom_template_name = None
        self.current_custom_parsed = None
        self.last_generated_text = ""

        # ---- ComfyUI / LoRA / queue state (Session 11) ----
        self.comfy_client = None
        self.comfy_connected = False
        self.comfy_workflow_ok = False
        self.comfy_busy = False
        # Session 14: separate from `comfy_busy` (generation in flight)
        # — tracks "a ComfyCheckWorker connect/disconnect probe is in
        # flight", which the sidebar button needs to avoid double-firing
        # through a pending check.
        self.comfy_check_busy = False
        self.comfy_output_dir = None
        self.comfy_last_image_path = None
        self.comfy_last_remote_filename = None
        self.comfy_last_remote_subfolder = None
        self._comfy_queue: list = []
        self._comfy_queue_debounce_until = 0.0
        self._comfy_session_image_counter = 0
        self._comfy_current_history_id = None
        self._comfy_last_total_steps = None
        self._check_worker = None
        self._gen_worker = None
        self._available_loras: list = []
        self.lora_slots_data: list = list(self.settings.get("lora_slots") or [])
        self.lora_slots: list = []  # widget refs, populated by _build_lora_slots

        self._neg_save_timer = QTimer(self)
        self._neg_save_timer.setSingleShot(True)
        self._neg_save_timer.setInterval(500)
        self._neg_save_timer.timeout.connect(self._persist_negative_prompt)

        self._custom_neg_save_timer = QTimer(self)
        self._custom_neg_save_timer.setSingleShot(True)
        self._custom_neg_save_timer.setInterval(500)
        self._custom_neg_save_timer.timeout.connect(self._persist_custom_negative_prompt)

        self._lora_save_timer = QTimer(self)
        self._lora_save_timer.setSingleShot(True)
        self._lora_save_timer.setInterval(500)
        self._lora_save_timer.timeout.connect(self._persist_lora_slots)

        # Session 17.5: the result-zone percent save timer is gone
        # along with the Size slider — image sizing is pure layout
        # stretch now, nothing left to debounce-persist here.

        # ---- Session 46.1: pipeline mode (t2i/i2i/i2v) + input image ----
        # Bare-minimum plumbing: a cycling mode button + plain "choose
        # file" for the input image. 46.2 replaces this with the
        # lightning-bolt-icon design and a proper drop-zone widget —
        # this pass only proves the pipe works end to end.
        self.pipeline_mode = PIPELINE_MODE_T2I
        self.input_image_path = None

        self._build_ui()
        # Session 18: LoRA widgets are built eagerly here (not lazily
        # inside `build_lora_page`) so `self.lora_slots`/
        # `self.lora_list_layout` etc. exist and are safe to touch from
        # `generate_prompt`/`_lora_autofill_from_library` regardless of
        # whether/when `build_lora_page` gets called to host them on a
        # real page -- see that method's own docstring.
        self._init_lora_widgets()
        self._apply_template_category("Standard")
        self._apply_pipeline_mode()
        QTimer.singleShot(0, self._apply_result_panel_height)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # Session 17.5: QSplitter -> plain QHBoxLayout with fixed
        # stretch factors. No draggable handle between any of the 3
        # columns anymore -- the *only* thing that changes a column's
        # width from here on is the rail's own animated `railWidth`
        # property. A manually-dragged splitter handle used to be
        # able to desync the rail's real width from its `_expanded`
        # flag (drag the handle -> width changes outside the rail's
        # own state -> next programmatic toggle animates from the
        # wrong start value) -- removing the handle removes the root
        # cause, not just a symptom.
        columns = QHBoxLayout()
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setSpacing(8)
        outer.addLayout(columns)
        # Session 19.2 (your feedback pass, annotated screenshot): 1:1
        # was still too wide on the left -- your red/green markup calls
        # for the left column noticeably narrower than the result+rail
        # side. 3:5 (~1:1.67) instead of 1:1.
        columns.addWidget(self._build_left_column(), 3)
        columns.addWidget(self._build_right_column(), 5)
        self.comfy_rail = self._build_comfy_advanced_rail()
        # Rail is a fixed-width column driven by its own animation
        # (`CollapsibleRail.railWidth`); stretch 0 so QHBoxLayout never
        # hands it extra space beyond what that animation sets.
        columns.addWidget(self.comfy_rail, 0)
        # Hidden until ComfyUI connects (Session 17 step 1) — same
        # gating precedent as the old LoRA section / Negative tab.
        self.comfy_rail.setVisible(False)

    def _build_left_column(self) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        scroll.setWidget(content)
        self._layout = QVBoxLayout(content)
        self._layout.setContentsMargins(12, 12, 12, 12)
        self._layout.setSpacing(10)

        # Session 48.2: the plain "Mode: Text → Image" row that used to
        # sit here is gone -- mode switching moved to the sidebar (see
        # MainWindow._build_sidebar's mode-switch button, main.py),
        # freeing this vertical space for Style/Characters/Scenario (or
        # the i2i/i2v drop-zone/Actions) the way the original 46.2
        # plan's "temporary, will move to the ⚡ icon" note always
        # intended. `self.pipeline_mode`/`_cycle_pipeline_mode`/
        # `_apply_pipeline_mode` are all still exactly what they were --
        # only the button that used to live in this column is gone;
        # the sidebar calls `_cycle_pipeline_mode()` directly instead.
        self._template_panel = self._build_template_panel()
        self._layout.addWidget(self._template_panel)
        self.standard_section = self._build_standard_section()
        self._layout.addWidget(self.standard_section)
        self.custom_section = self._build_custom_section()
        self._layout.addWidget(self.custom_section)

        # ---- Prompt output: Positive/Negative tab pair (Session 15
        # step 4) instead of two stacked boxes. The Negative tab is
        # only inserted once `comfy_connected` is true (and the
        # Standard builder is active -- Custom templates carry their
        # own per-template negative prompt box inside custom_section,
        # untouched by this) -- see `_refresh_prompt_output_tabs`. The
        # tab pair itself is always present; only the Negative tab
        # comes and goes. ----
        self.tab_prompt_output = QTabWidget()
        self.tab_prompt_output.setObjectName("PromptOutputTabs")
        # Session 19.3 (your feedback pass): reverted the 19.1 height
        # cap below -- that round's actual task was column *width*
        # (see the 3:5 split above), not prompt-box *height*. Back to
        # Expanding vertically so the box reclaims the space it had
        # before 19.1's (mis-scoped) shrink.

        positive_tab = QWidget()
        positive_tab.setObjectName("PromptOutputPage")
        positive_tab.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        pos_layout = QVBoxLayout(positive_tab)
        pos_layout.setContentsMargins(6, 6, 6, 6)
        self.txt_output = QPlainTextEdit()
        self.txt_output.setObjectName("PromptOutput")
        # Hotfix Session 25.1: Positive must support hand-typed,
        # generated, and generated-then-edited prompts (per the Guide),
        # same as Negative already does — it was wrongly read-only.
        self.txt_output.setMinimumHeight(110)
        pos_layout.addWidget(self.txt_output)

        copy_row = QHBoxLayout()
        self.lbl_copy_status = QLabel("")
        self.lbl_copy_status.setObjectName("dim")
        copy_row.addWidget(self.lbl_copy_status, 1)
        # Manual-copy affordance (step 5) -- independent of the
        # auto-copy-on-generate in `_finalize_generated_prompt`, useful
        # for re-copying after switching tabs or after a ComfyUI
        # generation already consumed the initial auto-copy.
        btn_copy_output = QPushButton("📋 Copy")
        btn_copy_output.setObjectName("ghost")
        btn_copy_output.clicked.connect(self._copy_output_to_clipboard)
        copy_row.addWidget(btn_copy_output)
        pos_layout.addLayout(copy_row)
        self.tab_prompt_output.addTab(positive_tab, "Positive")

        self._negative_tab = QWidget()
        self._negative_tab.setObjectName("PromptOutputPage")
        self._negative_tab.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        neg_layout = QVBoxLayout(self._negative_tab)
        neg_layout.setContentsMargins(6, 6, 6, 6)
        self.txt_neg_prompt = QPlainTextEdit()
        self.txt_neg_prompt.setObjectName("PromptOutput")
        self.txt_neg_prompt.setPlainText(self.settings.get("negative_prompt", ""))
        self.txt_neg_prompt.setMinimumHeight(70)
        self.txt_neg_prompt.textChanged.connect(lambda: self._neg_save_timer.start())
        neg_layout.addWidget(self.txt_neg_prompt)
        # Not added as a tab here -- `_refresh_prompt_output_tabs`
        # inserts/removes it based on connection + template category so
        # it round-trips via settings even while hidden, same as
        # `lora_slots` already does pre-connection.

        self._layout.addWidget(self.tab_prompt_output)

        # Generate button sits directly under the tab pair it fills
        # (step 6), not above Characters.
        self.btn_generate = QPushButton("Generate prompt and copy")
        self.btn_generate.setObjectName("accent")
        self.btn_generate.setMinimumHeight(40)
        self.btn_generate.clicked.connect(self.generate_prompt)
        self._layout.addWidget(self.btn_generate)

        # ---- ComfyUI state widgets (Session 11, retired from the
        # visible column in Session 19) ----
        # Generate in ComfyUI / Clear queue used to live in a row here,
        # split from Stop / Open folder which lived in column 3. Session
        # 16 step 4 regroups all four into one action cluster at the
        # bottom of the Result column instead -- see `_build_right_column`.
        # Session 18: the LoRA manager itself no longer lives in this
        # column at all -- see `build_lora_page`. Session 19: the
        # "4. ComfyUI" box itself (checkbox/status/host/port) is gone
        # too -- see `_build_comfy_state_widgets`'s own docstring.
        self._build_comfy_state_widgets()

        self._layout.addStretch(1)
        self._left_scroll = scroll
        return scroll

    def _cycle_pipeline_mode(self):
        idx = PIPELINE_MODES.index(self.pipeline_mode)
        self.pipeline_mode = PIPELINE_MODES[(idx + 1) % len(PIPELINE_MODES)]
        self._apply_pipeline_mode()

    def _apply_pipeline_mode(self):
        """Reflects `self.pipeline_mode` onto the mode button's label,
        swaps the left panel between its t2i layout (Style + Characters
        + Scenario) and its i2i/i2v layout (image drop-zone + a real
        Actions slot list, per the corrected 46.2 follow-up mockup),
        and — if `library_tab` is already wired up — tells the Library
        which categories make sense in this mode (functional filtering
        from Session 46.1, now paired with the matching Builder-side
        layout)."""
        # Session 48.2 fix: this used to set `self.btn_pipeline_mode`'s
        # text -- that button is gone (moved to the sidebar). The
        # sidebar's own mode caption is refreshed here instead, via
        # `main_window` (wired up the same post-construction way
        # `library_tab`/`history_tab`/`gallery_tab` already are, in
        # main.py) -- guarded the same way those three already are,
        # since this method also runs once during BuilderTab's own
        # __init__, before main.py has had a chance to wire anything.
        if self.main_window is not None and hasattr(self.main_window, "update_sidebar_mode_caption"):
            self.main_window.update_sidebar_mode_caption(self.pipeline_mode)
        is_image_mode = self.pipeline_mode != PIPELINE_MODE_T2I

        self.image_input_zone.setVisible(is_image_mode)
        self.box_style.setVisible(not is_image_mode)
        self.box_chars.setVisible(not is_image_mode)
        self.box_scenario.setVisible(not is_image_mode)
        self.box_actions.setVisible(is_image_mode)

        if is_image_mode:
            # 48.8: freeze the drop-zone's height against the current
            # viewport/Actions-count snapshot -- deliberately not
            # re-run on every later add_action_slot/remove_action_slot.
            self._apply_image_input_zone_height()

        if not is_image_mode:
            self.input_image_path = None
            self.image_input_zone.show_placeholder()

        # Session 46.2c decision: Custom templates stay a t2i-only
        # concept rather than growing a parallel i2i/i2v form shape.
        # The Standard builder already has one in this mode (image
        # drop-zone + Actions), which is exactly what a Custom template
        # would otherwise need to duplicate for no real gain. 46.2c revision:
        # the Standard side of this same panel (block order / named
        # templates) is equally t2i-only -- there's no Style/Characters/
        # Scenario blocks to *order* in i2i/i2v -- so rather than just
        # hiding the Standard/Custom switch and leaving an empty-looking
        # card taking up space (see the flagged screenshot), the whole
        # `tpl_section` card is hidden in image modes. Forcing the combo
        # back to "Standard" still happens even while hidden, so the
        # panel is in a sane state the moment t2i makes it visible again
        # and nobody can return to a mode showing a hidden Custom
        # template with no visible way to switch back.
        self.tpl_section.setVisible(not is_image_mode)
        if is_image_mode and self.combo_template_category.currentText() != "Standard":
            self.combo_template_category.setCurrentText("Standard")

        if self.library_tab is not None and hasattr(self.library_tab, "set_pipeline_mode_filter"):
            self.library_tab.set_pipeline_mode_filter(self.pipeline_mode)

        # 46.2c: i2i and i2v each read Actions from their own category
        # now, so an existing Action slot's choices must be re-pulled
        # every time the mode flips between the two (a flip from t2i
        # is already covered by set_pipeline_mode_filter show/hide, but
        # i2i<->i2v is a same-"is_image_mode" transition that wouldn't
        # otherwise trigger anything).
        if is_image_mode:
            actions = ["None"] + self._lib_active_file_list(self._actions_category())
            for slot in self.active_actions:
                slot["action_combo"].set_items(actions)

        # 46.2c follow-up: the right-rail Tools list is visible in every
        # mode (t2i's own Tools, or i2i/i2v's own -- it never hides), so
        # unlike Actions above, this re-seed always has to run on every
        # mode switch, not just i2i<->i2v: t2i<->i2i and t2i<->i2v both
        # change which category "Tools" means too.
        #
        # 46.2c follow-up #3: also retitle the card itself to match --
        # "Tools" (t2i), "Edit Tools" (i2i), "Video Tools" (i2v) -- same
        # names as the Library's category bar (except t2i's card keeps
        # its original plural "Tools" rather than CATEGORY_LABELS's
        # singular "Tool", which is tuned for the category-bar button
        # and per-entry dialogs, not this card's heading), so the card
        # reads as this mode's Tools rather than a leftover t2i label.
        if getattr(self, "lbl_tools_heading", None) is not None:
            self.lbl_tools_heading.setText(_TOOLS_CARD_TITLE.get(self.pipeline_mode, "Tools"))
        mode_tools = ["None"] + self._lib_active_file_list(self._mode_tools_category())
        for slot in self.active_tools:
            slot["tool_combo"].set_items(mode_tools)

    def _on_image_input_chosen(self, path: str):
        """`ImageDropZone.file_chosen` handler — click-to-browse or a
        real drag'n'drop both land here. Replaces 46.1's bare
        `_choose_input_image` file-dialog method."""
        self.input_image_path = path
        self.image_input_zone.show_image_path(path)

    def _on_image_input_unsupported(self, path: str):
        themed_message_box.warning(
            self, "Unsupported file",
            f"\"{os.path.basename(path)}\" doesn't look like a supported "
            "image file.")

    def _build_right_column(self) -> QWidget:
        panel = QWidget()
        panel.setMinimumWidth(260)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)

        # Step 1: no "Latest image" group-box title -- an image viewer
        # that's obviously a preview doesn't need a labeled box stating
        # that (same reasoning as Session 15 step 7). QFrame#Card gives
        # a light bordered container without a QGroupBox's reserved
        # title strip.
        self.group_result = QFrame()
        self.group_result.setObjectName("Card")
        self.group_result.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        result_layout = QVBoxLayout(self.group_result)
        result_layout.setContentsMargins(6, 6, 6, 6)
        result_layout.setSpacing(6)

        # Session 17.5 step 5: the "Size" slider is gone -- it was a
        # second manually-dragged control competing with the rail's
        # own animated column-width for the same visual space, and a
        # source of dead space per Session 16's post-review. The
        # preview now always claims 100% of whatever the result
        # column's actual width/height are, which change automatically
        # (only via the rail's `«`/`»` animation) instead of via a
        # separate manual budget.
        self.result_zone = ResultImageViewer(self.colors)
        self.result_zone.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        result_layout.addWidget(self.result_zone, 1)

        # Session 22 step 1: the Session 16 `setMaximumWidth(140)` squeeze
        # was a stated-temporary measure for a narrower result column.
        # Session 19's 3:5 column retune already freed the width that was
        # working around -- restore the bar to a normal, readable width
        # (it fills the row; the "10/30" counter sits at the end).
        self.progress_frame = QWidget()
        progress_layout = QHBoxLayout(self.progress_frame)
        progress_layout.setContentsMargins(0, 0, 0, 0)
        self.progress_bar = QProgressBar()
        progress_layout.addWidget(self.progress_bar, 1)
        self.lbl_comfy_progress = QLabel("")
        self.lbl_comfy_progress.setObjectName("dim")
        progress_layout.addWidget(self.lbl_comfy_progress)
        self.progress_frame.setVisible(False)
        result_layout.addWidget(self.progress_frame)

        self.lbl_comfy_result_status = QLabel("")
        self.lbl_comfy_result_status.setObjectName("dim")
        self.lbl_comfy_result_status.setWordWrap(True)
        result_layout.addWidget(self.lbl_comfy_result_status)

        # Step 4-6: every Comfy action grouped in one cluster here
        # instead of split across two columns (Generate/Clear queue
        # used to live in column 2, Stop/Open folder here) -- primary
        # action gets its own full-width row, the three secondary
        # actions + the queue-count readout share the row below so
        # Stop never has to float alone in a corner and Open folder
        # always has a slot (hidden, not squeezed out, until the first
        # result exists -- same visibility rule as before).
        self.result_buttons_row = QWidget()
        actions_col = QVBoxLayout(self.result_buttons_row)
        actions_col.setContentsMargins(0, 0, 0, 0)
        actions_col.setSpacing(6)

        # Session 22 step 2: per your Frankenstein reference, these four
        # buttons render immediately once ComfyUI connects and simply
        # stay put from then on -- no more setVisible(False)-then-
        # appears-later. Enabled/dimmed state (not existence) carries
        # the "is this doable right now" meaning; see
        # `_refresh_comfy_action_buttons_state` for the one choke point
        # that recomputes all four together.
        self.btn_generate_comfy = QPushButton("Generate in ComfyUI")
        self.btn_generate_comfy.setObjectName("accent")
        self.btn_generate_comfy.clicked.connect(self.on_generate_in_comfy_clicked)
        self.btn_generate_comfy.setEnabled(False)
        actions_col.addWidget(self.btn_generate_comfy)

        secondary_row = QHBoxLayout()
        secondary_row.setSpacing(6)
        self.btn_comfy_stop = QPushButton("Stop")
        self.btn_comfy_stop.setObjectName("danger")
        self.btn_comfy_stop.clicked.connect(self.on_comfy_stop_clicked)
        self.btn_comfy_stop.setEnabled(False)
        secondary_row.addWidget(self.btn_comfy_stop)

        secondary_row.addStretch(1)

        # Session 22 step 3: the separate queue-count readout is gone --
        # its text folds into this button's own label instead (see
        # `_refresh_comfy_queue_label`), falling back to plain "Clear
        # queue" (disabled) at zero.
        self.btn_comfy_clear_queue = QPushButton("Clear queue")
        self.btn_comfy_clear_queue.setEnabled(False)
        self.btn_comfy_clear_queue.clicked.connect(self.clear_comfy_queue)
        secondary_row.addWidget(self.btn_comfy_clear_queue)

        self.btn_comfy_open_folder = QPushButton("Open folder")
        # Session 27: was "ghost" (border: none in theme.py), which made
        # it the one unbordered outlier in a row where Stop (#danger,
        # bordered) and Clear queue (default, bordered) both read as
        # part of the same button cluster. Default QPushButton styling
        # matches Clear queue's look exactly -- no new QSS needed.
        self.btn_comfy_open_folder.clicked.connect(self.comfy_open_output_folder)
        self.btn_comfy_open_folder.setEnabled(False)
        secondary_row.addWidget(self.btn_comfy_open_folder)

        actions_col.addLayout(secondary_row)
        result_layout.addWidget(self.result_buttons_row)

        layout.addWidget(self.group_result, 1)
        return panel

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_result_panel_height()
        self._apply_image_input_zone_height()

    def _compute_result_chrome_height(self) -> int:
        # Kept only for callers that still want a rough "non-image
        # chrome" figure (none currently do post-Session-17.5, but the
        # helper is cheap to leave in place rather than rip out every
        # call site under time pressure). No longer drives the image
        # viewer's own sizing -- see `resizeEvent` below.
        total = 0
        for w in (self.progress_frame, self.lbl_comfy_result_status, self.result_buttons_row):
            if w.isVisible():
                total += w.sizeHint().height() + 8
        return total + 24

    def _apply_result_panel_height(self):
        # Session 17.5 step 5: no-op now that ResultImageViewer has an
        # Expanding size policy and fills whatever `result_layout`
        # gives it -- the manual pixel-budget scheme
        # (percent-of-panel-height, MIN_PX/MAX_PX clamping) is gone
        # along with the Size slider that drove it. Left as a no-op
        # (rather than deleted outright) since several call sites
        # still invoke it via `QTimer.singleShot` -- harmless, and
        # keeps this session's diff smaller than rewriting every call
        # site in one pass.
        return

    def _apply_image_input_zone_height(self):
        """48.8: sizes `image_input_zone` directly off the left
        column's real scroll-viewport budget, deliberately independent
        of `box_actions`' own content-driven height -- see the "New
        regression" note under 48.8 in additionalfeatures.md for why
        sharing a stretch pool with Actions (48.3/first 48.8 attempt)
        made the drop-zone shrink every time a slot was added.

        Only called from `_apply_pipeline_mode` (mode entry) and this
        tab's own `resizeEvent` (real window resizes) -- deliberately
        NOT from `add_action_slot`/`remove_action_slot`, so the
        drop-zone's height stays frozen against Actions' slot count
        churn. If Actions' list later grows past whatever's left in the
        viewport at the frozen height, the surrounding `QScrollArea`
        simply scrolls -- that's what it's there for, rather than this
        widget shrinking to compensate.
        """
        if not getattr(self, "image_input_zone", None) or not self.image_input_zone.isVisible():
            return
        scroll = getattr(self, "_left_scroll", None)
        if scroll is None:
            return
        viewport_h = scroll.viewport().height()
        if viewport_h <= 0:
            return

        # Everything else sharing the outer (scroll-content) layout --
        # stable regardless of Actions' slot count.
        other_outer = (
            self._template_panel.sizeHint().height()
            + self.tab_prompt_output.sizeHint().height()
            + self.btn_generate.sizeHint().height()
        )
        # Everything else sharing standard_section's own inner layout,
        # in i2i/i2v mode that's just box_actions -- its *current*
        # sizeHint (slots and all) is used here since this only runs at
        # mode-entry/resize, not on every slot add/remove, so it's a
        # one-time snapshot rather than a continuously-shrinking target.
        other_inner = self.box_actions.sizeHint().height() if self.box_actions.isVisible() else 0

        # Margins/spacing overhead: outer layout margins (12px top+bottom)
        # + spacing between ~4 outer items, plus standard_section's own
        # inner margins/spacing for ~2 items (Style, hidden, contributes
        # a spacing gap anyway) -- approximate on purpose, same spirit
        # as the old `apply_panel_height`'s own "chrome" budget.
        overhead = 12 * 2 + self._layout.spacing() * 4 + 8 * 2 + 6 * 2

        budget = viewport_h - other_outer - other_inner - overhead
        target = max(self.image_input_zone.MIN_PX, min(520, budget))
        self.image_input_zone.setFixedHeight(target)

    def set_colors(self, colors: dict):
        """Called by MainWindow on theme toggle — the result zone paints
        itself manually (not via QSS), and the LoRA [A]/[M] tags use an
        inline stylesheet color, so both need refreshing explicitly."""
        self.colors = colors
        self.result_zone.set_colors(colors)
        self.image_input_zone.set_colors(colors)
        for slot in self.lora_slots:
            self._lora_apply_tag_color(slot)


    def _build_template_panel(self) -> CollapsibleSection:
        # Collapsed by default on a fresh install (step 1) -- unlike the
        # LoRA section (defaults expanded), Block order / named
        # templates / Custom Template Editor are "set once and forget"
        # controls, not something a new session needs open immediately.
        default_expanded = not self.settings.get("section_collapsed_template_panel", True)
        section = CollapsibleSection(
            self._template_panel_header_text("Standard"), "template_panel",
            default_expanded=default_expanded, card=True)
        section.toggled.connect(self._persist_template_panel_state)
        self.tpl_section = section

        top_row = QHBoxLayout()
        self.lbl_template_type = QLabel("Template type:")
        top_row.addWidget(self.lbl_template_type)
        self.combo_template_category = QComboBox()
        self.combo_template_category.addItems(["Standard", "Custom"])
        self.combo_template_category.currentTextChanged.connect(self._apply_template_category)
        top_row.addWidget(self.combo_template_category)
        top_row.addStretch(1)
        section.body_layout.addLayout(top_row)

        # ---- Standard controls ----
        self.tpl_controls_standard = QWidget()
        std_layout = QHBoxLayout(self.tpl_controls_standard)
        std_layout.setContentsMargins(0, 0, 0, 0)
        self.lbl_order_display = QLabel(self._order_to_text())
        std_layout.addWidget(self.lbl_order_display, 1)
        btn_order = QPushButton("Block order…")
        btn_order.clicked.connect(self.open_order_dialog)
        std_layout.addWidget(btn_order)
        self.combo_template = QComboBox()
        std_layout.addWidget(self.combo_template)
        self.combo_template.currentTextChanged.connect(self._on_template_selected)
        btn_save_template = QPushButton("Save")
        btn_save_template.setToolTip("Save current block order as a named template")
        btn_save_template.clicked.connect(self.save_current_as_template)
        std_layout.addWidget(btn_save_template)
        section.body_layout.addWidget(self.tpl_controls_standard)
        self._refresh_template_combo()

        # ---- Custom controls ----
        self.tpl_controls_custom = QWidget()
        cus_layout = QHBoxLayout(self.tpl_controls_custom)
        cus_layout.setContentsMargins(0, 0, 0, 0)
        self.combo_custom_template = QComboBox()
        self.combo_custom_template.currentTextChanged.connect(self._on_custom_template_selected)
        cus_layout.addWidget(self.combo_custom_template, 1)
        btn_create_custom = QPushButton("Create template")
        btn_create_custom.clicked.connect(lambda: self.open_custom_template_editor(None))
        cus_layout.addWidget(btn_create_custom)
        btn_edit_custom = QPushButton("Edit")
        btn_edit_custom.clicked.connect(
            lambda: self.open_custom_template_editor(self.combo_custom_template.currentText() or None))
        cus_layout.addWidget(btn_edit_custom)
        btn_delete_custom = QPushButton("Delete")
        btn_delete_custom.setObjectName("danger")
        btn_delete_custom.clicked.connect(self.delete_selected_custom_template)
        cus_layout.addWidget(btn_delete_custom)
        section.body_layout.addWidget(self.tpl_controls_custom)
        self.tpl_controls_custom.setVisible(False)

        return section

    @staticmethod
    def _template_panel_header_text(category: str) -> str:
        return f"Template: {category}"

    def _persist_template_panel_state(self, expanded: bool):
        self.settings["section_collapsed_template_panel"] = not expanded
        self._save_settings()

    def _order_to_text(self) -> str:
        return " → ".join(BLOCK_ORDER_LABELS[k] for k in self.block_order)

    # ---- Standard section: Style / Characters / Scenario (Tools moved
    # out of this column's visible flow -- see the note on `box_tools`
    # below) ----
    # ---- Card helper (Session 20 follow-up fix) ----
    def _build_card(self, title: str) -> tuple:
        """Replaces QGroupBox for Style/Characters/Scenario/Tools/Seed/
        Resolution. Your annotated screenshot flagged these titles as
        reading like floating labels sitting *above* the card rather
        than inside it -- QGroupBox's native title rendering (title
        straddling the top border) left a visible gap under this Qt
        style once `CompactGroup`'s margin-top was applied, instead of
        the connected "card header" look the rest of the app already
        has (e.g. the Template panel). Explicit QFrame#Card + a bold
        QLabel header as the card's own first row sidesteps native
        title-metric quirks entirely -- the heading is unambiguously
        *inside* the card's border every time, regardless of style
        plugin. Returns (frame, inner_layout) so callers add their
        existing rows into `inner_layout` exactly like they used to
        add them to the QGroupBox itself."""
        frame = QFrame()
        frame.setObjectName("Card")
        frame.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        inner = QVBoxLayout(frame)
        inner.setContentsMargins(10, 8, 10, 10)
        inner.setSpacing(6)
        heading = QLabel(title)
        heading.setObjectName("CardHeading")
        inner.addWidget(heading)
        return frame, inner

    def _build_standard_section(self) -> QWidget:
        section = QWidget()
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Style
        box_style, style_inner = self._build_card("Style")
        row = QHBoxLayout()
        style_inner.addLayout(row)
        self.combo_style = AutocompleteCombobox()
        self.combo_style.set_items(["None"] + self._lib_active_file_list("styles"))
        self.combo_style.set_value("None")
        row.addWidget(self.combo_style, 1)
        btn_style_preview = QPushButton("👁")
        btn_style_preview.setToolTip("Show style description")
        btn_style_preview.clicked.connect(
            lambda: self.quick_preview("styles", self.combo_style.current_value()))
        row.addWidget(btn_style_preview)
        layout.addWidget(box_style)
        # Session 46.2 follow-up: hidden in i2i/i2v -- a Style pick
        # doesn't apply to an editing/video pass over an existing
        # photo the way it does to a from-scratch generation. See
        # `_apply_pipeline_mode`.
        self.box_style = box_style

        # ---- Session 46.2: image input drop-zone. Sits directly under
        # Style, above Characters/Scenario, per the confirmed mockup
        # (screenshot 1's green arrow, screenshot 2's drop-zone). Only
        # visible in i2i/i2v mode -- `_apply_pipeline_mode` toggles it
        # alongside Characters/Scenario below. Reuses
        # ui/widgets/image_zone.py's existing ImageDropZone rather than
        # a new widget class, same family ResultImageViewer already
        # belongs to.
        #
        # Session 48.3 fix, superseded by 48.8: this used to be built
        # with the old percent/MIN_PX/MAX_PX manual sizing scheme
        # (`percent=30`), but nothing ever called `apply_panel_height()`
        # on it, so it just sat at `MIN_PX` (130px) permanently. 48.3
        # then tried giving it the same `Expanding` policy + stretch
        # factor `ResultImageViewer` uses -- but unlike ResultImageViewer,
        # this widget shares its layout with content-driven siblings
        # (Actions' slot list grows/shrinks as the user adds/removes
        # entries), and a shared stretch pool means every new Action
        # slot directly shrank this widget to keep the column's total
        # height matching the viewport (confirmed: 1 action vs 4
        # actions, same window, visibly smaller image each time -- see
        # additionalfeatures.md 48.8's "New regression" note).
        #
        # 48.8 fix: stop sharing a stretch pool with Actions entirely.
        # `setSizePolicy(Expanding, Fixed)` + a real `setFixedHeight`
        # computed once in `_apply_image_input_zone_height()` (called on
        # switching into i2i/i2v and on the tab's own `resizeEvent`, but
        # deliberately NOT on `add_action_slot`/`remove_action_slot`)
        # sizes this against the actual scroll-viewport budget directly,
        # frozen independently of how many Action slots exist. If
        # Actions' own list later grows past what's left in the
        # viewport, the column scrolls -- which is exactly what the
        # surrounding `QScrollArea` is already there for, rather than
        # this widget silently shrinking to make room.
        self.image_input_zone = ImageDropZone(self.colors)
        self.image_input_zone.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.image_input_zone.setMinimumHeight(self.image_input_zone.MIN_PX)
        self.image_input_zone.setMaximumHeight(520)
        self.image_input_zone.setFixedHeight(self.image_input_zone.MIN_PX)
        self.image_input_zone.file_chosen.connect(self._on_image_input_chosen)
        self.image_input_zone.unsupported_file_dropped.connect(self._on_image_input_unsupported)
        self.image_input_zone.setVisible(False)
        layout.addWidget(self.image_input_zone)

        # 2. Characters -- tightened per step 2 (this is the block most
        # responsible for hitting the "no scroll at 1-2 characters"
        # goal, so it gets real attention, not a uniform padding cut):
        # compact group chrome, smaller inter-row spacing, and the
        # per-slot Card frames themselves are tightened in
        # `add_character_slot`.
        box_chars, chars_layout = self._build_card("Characters")
        chars_layout.setSpacing(6)
        chars_header = QHBoxLayout()
        btn_add_char = QPushButton("＋ Add character")
        btn_add_char.setObjectName("accent")
        btn_add_char.clicked.connect(self.add_character_slot)
        chars_header.addWidget(btn_add_char)
        self.lbl_chars_count = QLabel("0 character(s)")
        self.lbl_chars_count.setObjectName("dim")
        chars_header.addWidget(self.lbl_chars_count)
        chars_header.addStretch(1)
        chars_layout.addLayout(chars_header)

        self.chars_list_widget = QWidget()
        self.chars_list_layout = QVBoxLayout(self.chars_list_widget)
        self.chars_list_layout.setContentsMargins(0, 0, 0, 0)
        self.chars_list_layout.setSpacing(6)
        chars_layout.addWidget(self.chars_list_widget)
        self.placeholder_chars = QLabel("No characters added. Click \"＋ Add character\".")
        self.placeholder_chars.setObjectName("dim")
        chars_layout.addWidget(self.placeholder_chars)
        layout.addWidget(box_chars)
        # Session 46.2: hidden in i2i/i2v -- see `_apply_pipeline_mode`.
        self.box_chars = box_chars

        # 3. Scenario
        box_scenario, srow_outer = self._build_card("Scenario")
        srow = QHBoxLayout()
        srow_outer.addLayout(srow)
        self.combo_scenario = AutocompleteCombobox()
        self.combo_scenario.set_items(["None"] + self._lib_active_file_list("scenarios"))
        self.combo_scenario.set_value("None")
        srow.addWidget(self.combo_scenario, 1)
        btn_scenario_preview = QPushButton("👁")
        btn_scenario_preview.setToolTip("Show scenario description")
        btn_scenario_preview.clicked.connect(
            lambda: self.quick_preview("scenarios", self.combo_scenario.current_value()))
        srow.addWidget(btn_scenario_preview)
        layout.addWidget(box_scenario)
        # Session 46.2: hidden in i2i/i2v -- see `_apply_pipeline_mode`.
        self.box_scenario = box_scenario

        # ---- Session 46.2 follow-up: Actions, i2i/i2v only. Fills the
        # slot Characters/Scenario just vacated, per your corrected
        # screenshot -- a real inline slot list ("＋ Add action" / count
        # / one card per slot), built the same way Characters already
        # is, not a link that sends the person to a different tab.
        # Backed by `self.active_actions`, populated from the Library's
        # "image_actions"/"video_actions" category (Session 46.2c;
        # `_actions_category()` picks the right one for the current
        # `self.pipeline_mode`) -- already scoped to this mode by
        # `set_pipeline_mode_filter` on the Library side too, so no new
        # filtering logic is needed here, just a UI copy of the
        # existing slot-row pattern.
        # One picker per row (mirrors `add_tool_slot`'s single "Tool:"
        # combo, not Characters' two-picker Who+Outfit shape) -- an
        # "action" entry doesn't currently carry a second, per-slot
        # value the way a character's outfit does; revisit if that
        # changes.
        self.box_actions, actions_layout = self._build_card("Actions")
        actions_header = QHBoxLayout()
        btn_add_action = QPushButton("＋ Add action")
        btn_add_action.setObjectName("accent")
        btn_add_action.clicked.connect(self.add_action_slot)
        actions_header.addWidget(btn_add_action)
        self.lbl_actions_count = QLabel("0 action(s)")
        self.lbl_actions_count.setObjectName("dim")
        actions_header.addWidget(self.lbl_actions_count)
        actions_header.addStretch(1)
        actions_layout.addLayout(actions_header)

        self.actions_list_widget = QWidget()
        self.actions_list_layout = QVBoxLayout(self.actions_list_widget)
        self.actions_list_layout.setContentsMargins(0, 0, 0, 0)
        self.actions_list_layout.setSpacing(6)
        actions_layout.addWidget(self.actions_list_widget)
        self.placeholder_actions = QLabel("No actions added. Click \"＋ Add action\".")
        self.placeholder_actions.setObjectName("dim")
        actions_layout.addWidget(self.placeholder_actions)
        layout.addWidget(self.box_actions)
        self.box_actions.setVisible(False)

        # 4. Tools -- built here (same add/remove-slot mechanics, same
        # `self.active_tools` backing list Standard generation reads
        # from) but deliberately NOT added to this column's `layout`:
        # `_build_comfy_advanced_rail` (Session 17) reparents
        # `self.box_tools` into the new ComfyUI-advanced rail's body
        # once that rail is built, right after this section returns.
        # Visible in every pipeline mode (see `box_tools.setVisible
        # (not is_custom)` below -- Custom is forced off in i2i/i2v, so
        # this is always True there), and reads from the mode-correct
        # category via `_mode_tools_category()` (46.2c follow-up #3) --
        # t2i's own "tools", "edit_tools" in i2i, "video_tools" in i2v --
        # its own dedicated category per mode, distinct from whatever
        # the Actions slot is reading.
        self.box_tools, tools_layout = self._build_card("Tools")
        self.lbl_tools_heading = self.box_tools.findChild(QLabel, "CardHeading")
        tools_header = QHBoxLayout()
        btn_add_tool = QPushButton("＋ Add tool")
        btn_add_tool.setObjectName("accent")
        btn_add_tool.clicked.connect(self.add_tool_slot)
        tools_header.addWidget(btn_add_tool)
        self.lbl_tools_count = QLabel("0 tool(s)")
        self.lbl_tools_count.setObjectName("dim")
        tools_header.addWidget(self.lbl_tools_count)
        tools_header.addStretch(1)
        tools_layout.addLayout(tools_header)

        self.tools_list_widget = QWidget()
        self.tools_list_layout = QVBoxLayout(self.tools_list_widget)
        self.tools_list_layout.setContentsMargins(0, 0, 0, 0)
        tools_layout.addWidget(self.tools_list_widget)
        self.placeholder_tools = QLabel("No tools added. Click \"＋ Add tool\".")
        self.placeholder_tools.setObjectName("dim")
        tools_layout.addWidget(self.placeholder_tools)
        self.box_tools.setParent(section)  # temporary parent, reparented into
        self.box_tools.hide()  # the rail by `_build_comfy_advanced_rail` right after

        return section

    # ---- Custom section (rebuilt dynamically per-template) ----
    def _build_custom_section(self) -> QWidget:
        section = QWidget()
        self.custom_section_layout = QVBoxLayout(section)
        self.custom_section_layout.setContentsMargins(0, 0, 0, 0)
        section.setVisible(False)
        self._show_custom_placeholder()
        return section

    # ------------------------------------------------------------------
    # ComfyUI connection panel (Session 11)
    # ------------------------------------------------------------------
    def _build_comfy_state_widgets(self):
        """Session 19: the visible '4. ComfyUI' box (checkbox + status
        label + Host/Port fields) is retired from the Builder column.
        The checkbox+status were already functionally duplicated by the
        sidebar's Run/Disconnect button + footer status since Session
        14 (see the plan's KEY LAYOUT MAPPING table); Host/Port move to
        the Settings page this session (`MainWindow._build_settings_page`).

        `chk_comfy_enabled` stays alive as a plain, never-shown
        `QCheckBox` purely because `sidebar_request_comfy_toggle` flips
        it and `on_comfy_toggle` is wired to its `toggled` signal —
        keeping one invisible checkbox is a far smaller diff than
        rewiring that whole chain to a plain method call.
        `lbl_comfy_status` stays alive the same way: `_set_comfy_status_text`
        still writes to it so `comfy_status_message_changed` keeps firing
        for the sidebar footer, even though nothing ever displays the
        label itself anymore.
        """
        self.chk_comfy_enabled = QCheckBox()
        self.chk_comfy_enabled.setVisible(False)
        self.chk_comfy_enabled.toggled.connect(self.on_comfy_toggle)
        self.lbl_comfy_status = QLabel("")
        self.lbl_comfy_status.setVisible(False)

    def _on_comfy_resolution_changed(self, choice: str):
        for label, w, h in COMFY_RESOLUTION_PRESETS:
            if label == choice:
                if w is None:
                    self.ent_comfy_width.setEnabled(True)
                    self.ent_comfy_height.setEnabled(True)
                else:
                    self.ent_comfy_width.setText(str(w))
                    self.ent_comfy_height.setText(str(h))
                    self.ent_comfy_width.setEnabled(False)
                    self.ent_comfy_height.setEnabled(False)
                return

    # ------------------------------------------------------------------
    # ComfyUI-advanced rail: Resolution / Seed / Tools (Session 17)
    # ------------------------------------------------------------------
    def _build_comfy_advanced_rail(self) -> CollapsibleRail:
        default_expanded = not self.settings.get("section_collapsed_comfy_rail", False)
        # Session 21: no header label -- the rail only ever renders once
        # comfy_connected is already true, so "ComfyUI options" restated
        # the obvious at the cost of a full row. settings_key stays
        # "comfy_rail" (persistence key, unrelated to the display title).
        rail = CollapsibleRail("", "comfy_rail", default_expanded=default_expanded)
        rail.toggled.connect(self._persist_comfy_rail_state)

        # Seed -- Session 20 follow-up: `_build_card` (same helper used
        # for Style/Characters/Scenario/Tools) instead of QGroupBox, to
        # fix the floating-title-above-card look flagged in your
        # annotated screenshot.
        box_seed, seed_box_layout = self._build_card("Seed")
        seed_row = QHBoxLayout()
        self.radio_seed_random = QRadioButton("Random")
        self.radio_seed_fixed = QRadioButton("Fixed")
        self.radio_seed_random.setChecked(True)
        self._comfy_seed_group = QButtonGroup(self)
        self._comfy_seed_group.addButton(self.radio_seed_random)
        self._comfy_seed_group.addButton(self.radio_seed_fixed)
        self.ent_comfy_seed = QLineEdit("0")
        self.ent_comfy_seed.setEnabled(False)
        self.radio_seed_fixed.toggled.connect(self.ent_comfy_seed.setEnabled)
        seed_row.addWidget(self.radio_seed_random)
        seed_row.addWidget(self.radio_seed_fixed)
        seed_box_layout.addLayout(seed_row)
        seed_box_layout.addWidget(self.ent_comfy_seed)
        rail.body_layout.addWidget(box_seed)

        # Resolution -- same card treatment.
        box_resolution, res_box_layout = self._build_card("Resolution")
        self.combo_comfy_resolution = QComboBox()
        self.combo_comfy_resolution.addItems([label for label, _w, _h in COMFY_RESOLUTION_PRESETS])
        self.combo_comfy_resolution.currentTextChanged.connect(self._on_comfy_resolution_changed)
        res_row = QHBoxLayout()
        self.ent_comfy_width = QLineEdit("1024")
        self.ent_comfy_width.setFixedWidth(60)
        res_row.addWidget(self.ent_comfy_width)
        res_row.addWidget(QLabel("×"))
        self.ent_comfy_height = QLineEdit("1024")
        self.ent_comfy_height.setFixedWidth(60)
        res_row.addWidget(self.ent_comfy_height)
        res_row.addStretch(1)
        res_box_layout.addWidget(self.combo_comfy_resolution)
        res_box_layout.addLayout(res_row)
        rail.body_layout.addWidget(box_resolution)
        self._on_comfy_resolution_changed(self.combo_comfy_resolution.currentText())

        # Tools -- `self.box_tools` is fully built already in
        # `_build_standard_section` (kept off-layout, hidden, pending
        # this session). Reparent it here instead of rebuilding.
        rail.body_layout.addWidget(self.box_tools)
        self.box_tools.setParent(rail.body)
        self.box_tools.show()

        rail.body_layout.addStretch(1)
        return rail

    def _persist_comfy_rail_state(self, expanded: bool):
        self.settings["section_collapsed_comfy_rail"] = not expanded
        self._save_settings()

    # ------------------------------------------------------------------
    # LoRA manager (Session 11)
    # ------------------------------------------------------------------
    def _init_lora_widgets(self):
        """Builds the actual slot-list widget + Add/Clear controls up
        front, during `__init__`/`_build_ui` -- deliberately *not*
        parented to any page here. `build_lora_page` (called later by
        `main.py`, once every tab exists) just wraps this pre-built
        content in a page shell; nothing about `generate_prompt`'s
        (or the Library autofill's) reliance on `self.lora_list_layout`/
        `self.lora_slots` etc. has to wait for that page to exist, so
        this stays exactly as safe to call from a test that never
        touches `build_lora_page` at all as it was when this content
        lived permanently inside Builder's own column."""
        self.lora_content = QWidget()
        content_layout = QVBoxLayout(self.lora_content)
        content_layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.lora_list_widget = QWidget()
        self.lora_list_layout = QVBoxLayout(self.lora_list_widget)
        self.lora_list_layout.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(self.lora_list_widget)
        content_layout.addWidget(scroll, 1)

        bottom_row = QHBoxLayout()
        self.btn_lora_add = QPushButton("+ Add slot")
        self.btn_lora_add.clicked.connect(self._lora_add_slot)
        bottom_row.addWidget(self.btn_lora_add)
        btn_lora_clear = QPushButton("Clear all")
        btn_lora_clear.clicked.connect(self._lora_clear_all)
        bottom_row.addWidget(btn_lora_clear)
        content_layout.addLayout(bottom_row)

        self._build_lora_slots()

    def build_lora_page(self) -> QWidget:
        """Session 18: LoRA management's own sidebar page (was a
        collapsible-in-place section inside Builder's left column
        through Session 17.5 -- see `KEY LAYOUT MAPPING` in
        UIRework.md). All the actual slot data/backend wiring
        (`_lora_sync_data`, debounced persistence to
        `settings["lora_slots"]`, autofill from Library) is completely
        unchanged and already built by `_init_lora_widgets` before this
        ever runs; this method only wraps that pre-built content in a
        page shell and slots it into `MainWindow.stack` (via `main.py`
        calling this once, right after constructing every tab).

        The page has two faces, swapped via `self.lora_page_stack`
        (a bare 2-page `QStackedWidget`, not to be confused with
        `MainWindow.stack`):
          - index 0: empty-state message, shown while `comfy_connected`
            is False -- LoRA assignment is meaningless without a LoRA
            list from ComfyUI to assign from, same spirit as the old
            `_refresh_lib_lora_visibility` gating, just page-level
            instead of a visibility toggle on an in-Builder widget.
          - index 1: the real slot list + Add/Clear controls
            (`self.lora_content`).
        `_refresh_lora_page_visibility` (called from every place that
        used to touch `self.lora_section.setVisible(...)`) picks which
        face is showing.
        """
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(12)

        # Same ad-hoc title styling `main.py._build_placeholder_page`
        # already uses for the other sidebar pages (Settings) --
        # matches instead of introducing a new, undefined QSS
        # objectName.
        title = QLabel("LoRA")
        title_font = title.font()
        title_font.setFamily("Segoe UI")
        title_font.setPointSize(18)
        title_font.setBold(True)
        title.setFont(title_font)
        outer.addWidget(title)

        self.lora_page_stack = QStackedWidget()
        outer.addWidget(self.lora_page_stack, 1)

        empty_state = QWidget()
        empty_layout = QVBoxLayout(empty_state)
        empty_layout.addStretch(1)
        lbl_empty = QLabel("Connect to ComfyUI to manage LoRAs")
        lbl_empty.setObjectName("dim")
        lbl_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_empty.setWordWrap(True)
        empty_layout.addWidget(lbl_empty)
        empty_layout.addStretch(1)
        self.lora_page_stack.addWidget(empty_state)

        self.lora_page_stack.addWidget(self.lora_content)

        self._refresh_lora_page_visibility()
        return page

    def _refresh_lora_page_visibility(self):
        """Single choke point for which face of `lora_page_stack` shows
        -- replaces every former `self.lora_section.setVisible(...)`
        call site. Guarded with `hasattr` since `build_lora_page` runs
        after `_build_ui`/`__init__` (main.py calls it once every tab
        exists, same ordering as the old cross-tab attribute wiring),
        so this is a safe no-op if called before the page exists."""
        if not hasattr(self, "lora_page_stack"):
            return
        self.lora_page_stack.setCurrentIndex(1 if self.comfy_connected else 0)

    def _build_lora_slots(self):
        while self.lora_list_layout.count():
            item = self.lora_list_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self.lora_slots = []

        source = self.lora_slots_data if self.lora_slots_data else []
        if not source:
            source = [{"name": LORA_NONE_VALUE, "strength": 1.0, "auto": False}]
        for entry in source:
            self._lora_create_slot(
                entry.get("name", LORA_NONE_VALUE), entry.get("strength", 1.0), entry.get("auto", False))
        # Session 18 visual-pass fix: each row now sizes to its own
        # content height (see `_lora_create_slot`'s
        # `QSizePolicy.Policy.Fixed`) instead of a `QVBoxLayout` with
        # no trailing stretch handing every row an equal share of the
        # whole page's height. This stretch is what actually pins the
        # (now-compact) rows to the top of the list and pushes the
        # leftover space below them, rather than between them.
        self.lora_list_layout.addStretch(1)
        self._lora_update_add_button()

    def _lora_create_slot(self, name=LORA_NONE_VALUE, strength=1.0, auto=False) -> dict:
        row = QFrame()
        row.setObjectName("Card")
        row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # Session 18 visual-pass fix: without an explicit vertical size
        # policy, this row happily stretched to fill whatever share of
        # the page's height the (stretch-less) `lora_list_layout` gave
        # it -- fine with 1-2 slots, absurd with 1 (a single row
        # filling the entire page) or merely odd with a handful (huge
        # gaps between compact-looking rows). `Fixed` + `setFixedHeight`
        # locks it to its natural content height regardless of how much
        # vertical space the list container has to give away.
        # Session 18 second visual-pass fix: 48px was too tight once
        # `QHBoxLayout`'s *default* margins (style-dependent, ~11px a
        # side on this Fusion-derived theme) were subtracted from it --
        # combo/spin/delete-button/[M]-[A] tag all got squeezed below
        # their natural content height instead of comfortably centered.
        # Explicit tighter margins free up real room inside the same
        # row, and the row itself is a bit taller per your "increase it
        # a bit" note.
        row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        row.setFixedHeight(60)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(12, 8, 12, 8)
        row_layout.setSpacing(10)

        lbl_tag = QLabel()
        lbl_tag.setFixedWidth(28)
        lbl_tag.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row_layout.addWidget(lbl_tag)

        combo = AutocompleteCombobox()
        choices = [LORA_NONE_VALUE] + self._available_loras
        if name not in choices:
            choices = [name] + choices
        combo.set_items(choices)
        combo.set_value(name)
        combo.setMinimumHeight(34)
        row_layout.addWidget(combo, 1)

        spin = NoScrollDoubleSpinBox()
        spin.setRange(LORA_STRENGTH_MIN, LORA_STRENGTH_MAX)
        spin.setSingleStep(0.05)
        spin.setDecimals(2)
        spin.setValue(float(strength))
        # Session 18 second visual-pass fix: no explicit width meant
        # the spin box could shrink to barely wider than its up/down
        # arrows -- wide enough to show the stepper but not the actual
        # number ("1,00" became an unreadable "-|"). A fixed minimum
        # keeps the value itself visible at every row count.
        spin.setMinimumWidth(90)
        spin.setMinimumHeight(34)
        row_layout.addWidget(spin)

        btn_del = QPushButton("✕")
        btn_del.setMinimumHeight(34)
        row_layout.addWidget(btn_del)

        slot = {"frame": row, "combo": combo, "spin": spin, "lbl_tag": lbl_tag, "auto": auto}
        combo.item_selected.connect(lambda _t, s=slot: self._lora_on_slot_changed(downgrade_slot=s))
        spin.valueChanged.connect(lambda _v, s=slot: self._lora_on_slot_changed(downgrade_slot=s))
        btn_del.clicked.connect(lambda: self._lora_remove_slot_by_ref(row))

        # Insert before the trailing stretch (if `_build_lora_slots`
        # already added one) rather than always appending at the very
        # end -- otherwise a slot added via `_lora_add_slot` after the
        # initial build would land *after* the stretch and never
        # actually show up above the empty space.
        insert_at = self.lora_list_layout.count()
        if insert_at > 0:
            last_item = self.lora_list_layout.itemAt(insert_at - 1)
            if last_item is not None and last_item.spacerItem() is not None:
                insert_at -= 1
        self.lora_list_layout.insertWidget(insert_at, row)
        self.lora_slots.append(slot)
        self._lora_update_add_button()
        self._lora_apply_tag_color(slot)
        return slot

    def _lora_apply_tag_color(self, slot: dict):
        slot["lbl_tag"].setText("[A]" if slot["auto"] else "[M]")
        color = self.colors["accent"] if slot["auto"] else self.colors["fg_dim"]
        slot["lbl_tag"].setStyleSheet(f"color: {color}; font-weight: 600;")

    def _lora_remove_slot_by_ref(self, row_frame: QFrame):
        idx = next((i for i, s in enumerate(self.lora_slots) if s["frame"] is row_frame), None)
        if idx is None:
            return
        if len(self.lora_slots) <= 1:
            # Last slot: clear values instead of destroying — always
            # keep at least one row, same as the original.
            slot = self.lora_slots[0]
            slot["combo"].set_value(LORA_NONE_VALUE)
            slot["spin"].setValue(1.0)
            if slot["auto"]:
                slot["auto"] = False
                self._lora_apply_tag_color(slot)
            self._lora_on_slot_changed()
            return
        self.lora_slots[idx]["frame"].setParent(None)
        self.lora_slots[idx]["frame"].deleteLater()
        self.lora_slots.pop(idx)
        self._lora_update_add_button()
        self._lora_on_slot_changed()

    def _lora_add_slot(self):
        if len(self.lora_slots) >= MAX_LORA_SLOTS:
            return
        self._lora_create_slot()
        self._lora_on_slot_changed()

    def _lora_clear_all(self):
        for slot in self.lora_slots:
            slot["frame"].setParent(None)
            slot["frame"].deleteLater()
        self.lora_slots = []
        self._lora_create_slot()
        self._lora_update_add_button()
        self._lora_on_slot_changed()

    def _lora_update_add_button(self):
        if hasattr(self, "btn_lora_add"):
            self.btn_lora_add.setEnabled(len(self.lora_slots) < MAX_LORA_SLOTS)

    def _lora_on_slot_changed(self, downgrade_slot: dict = None):
        """Syncs in-memory slot data and (debounced) persists to
        settings. If `downgrade_slot` is given, the edit came from the
        user directly touching that slot's widgets — if it was an
        autofill-owned ("auto") slot, it stops being one, so the next
        autofill pass won't silently overwrite a value just set by
        hand."""
        if downgrade_slot is not None and downgrade_slot.get("auto"):
            downgrade_slot["auto"] = False
            self._lora_apply_tag_color(downgrade_slot)
        self._lora_sync_data()
        self._lora_save_timer.start()

    def _lora_sync_data(self):
        result = []
        for slot in self.lora_slots:
            name = slot["combo"].current_value().strip()
            result.append({"name": name, "strength": slot["spin"].value(), "auto": bool(slot.get("auto"))})
        self.lora_slots_data = result

    def _persist_lora_slots(self):
        self.settings["lora_slots"] = self.lora_slots_data
        self._save_settings()

    def _lora_update_combos(self):
        choices = [LORA_NONE_VALUE] + self._available_loras
        for slot in self.lora_slots:
            current = slot["combo"].current_value()
            slot_choices = choices if current in choices else [current] + choices
            slot["combo"].set_items(slot_choices)
            slot["combo"].set_value(current)

    def _collect_active_library_entries(self) -> list:
        """Mirrors the original's `_collect_active_library_loras`
        ordering logic (renamed here per the Session 1 note — this is
        the UI-gathering half; `backend.prompt_builder.
        collect_active_library_loras` is the pure-data half that turns
        this list into de-duplicated LoRA names). Walks whichever
        builder path (Standard or Custom) is currently active, in
        mention order, resolving the same "Canon N" ->
        f"{char_name}_Canon_{n}" outfit name every other builder path
        already uses."""
        entries = []

        def add(category, name):
            if name and name != "None":
                entries.append((category, name))

        def add_outfit(char_name, o_selection):
            if o_selection and o_selection != "None":
                if o_selection.startswith("Canon "):
                    num = o_selection.split(" ", 1)[1]
                    add("outfits", f"{char_name}_Canon_{num}")
                else:
                    add("outfits", o_selection)

        if self.combo_template_category.currentText() == "Custom":
            for slot in self.custom_active_slots:
                char_name = slot["char_combo"].current_value()
                add("characters", char_name)
                outfit_combo = slot.get("outfit_combo")
                if outfit_combo is not None:
                    add_outfit(char_name, outfit_combo.current_value())
            if getattr(self, "custom_style_combo", None) is not None:
                add("styles", self.custom_style_combo.current_value())
            if getattr(self, "custom_scenario_combo", None) is not None:
                add("scenarios", self.custom_scenario_combo.current_value())
            for slot in self.custom_active_tools:
                add("tools", slot["tool_combo"].current_value())
        else:
            add("styles", self.combo_style.current_value())
            for slot in self.active_characters:
                char_name = slot["char_combo"].current_value()
                add("characters", char_name)
                add_outfit(char_name, slot["outfit_combo"].current_value())
            add("scenarios", self.combo_scenario.current_value())
            for slot in self.active_tools:
                add(self._mode_tools_category(), slot["tool_combo"].current_value())
        return entries

    def _lora_autofill_from_library(self):
        """Thin wrapper around the Session 1 backend functions, per
        that module's own docstring: recomputes the auto-owned LoRA
        slots from whichever library entries are currently active,
        leaving manually-edited slots untouched. Safe to call on every
        "Generate" — a no-op when there are no active library->LoRA
        bindings or the result doesn't change."""
        auto_loras = collect_active_library_loras(self.data_dir, self._collect_active_library_entries())
        self.lora_slots_data = compute_lora_autofill(self.lora_slots_data, auto_loras, LORA_NONE_VALUE)
        self._build_lora_slots()
        self._persist_lora_slots()

    # ------------------------------------------------------------------
    # Template category switch
    # ------------------------------------------------------------------
    def _apply_template_category(self, category: str):
        is_custom = category == "Custom"
        self.tpl_controls_standard.setVisible(not is_custom)
        self.tpl_controls_custom.setVisible(is_custom)
        self.standard_section.setVisible(not is_custom)
        self.custom_section.setVisible(is_custom)
        # `box_tools` now lives in the ComfyUI-advanced rail (Session
        # 17), not inside `standard_section` -- it needs its own
        # category gate since it no longer inherits visibility from
        # that section. Custom templates have their own, separate
        # tools box built inside `custom_section` instead.
        self.box_tools.setVisible(not is_custom)
        self.tpl_section.header.setText(self._template_panel_header_text(category))
        # Custom templates carry their own per-template negative prompt
        # box inside custom_section — the shared Negative tab (Session
        # 15) only applies to the Standard builder.
        self._refresh_prompt_output_tabs()
        if is_custom:
            self._refresh_custom_template_combo()
            name = self.combo_custom_template.currentText()
            if name and name in self.custom_templates:
                self._build_custom_template_form(name)
            else:
                self._show_custom_placeholder()

    # ------------------------------------------------------------------
    # Standard: block-order templates
    # ------------------------------------------------------------------
    def _actions_category(self) -> str:
        """Session 46.2c: which Library category the i2i/i2v Actions
        slot currently reads from -- "image_actions" in i2i, "video_
        actions" in i2v. Falls back to "image_actions" if called in
        t2i (the Actions box is hidden there anyway; see
        `_apply_pipeline_mode`), so this never returns something
        nonsensical if ever called before a mode switch happens."""
        if self.pipeline_mode == PIPELINE_MODE_I2V:
            return "video_actions"
        return "image_actions"

    def _mode_tools_category(self) -> str:
        """Session 46.2c follow-up #3: which Library category the
        right-side rail's "Tools" slot list (`self.box_tools`/
        `self.active_tools` -- a separate list from the main column's
        Actions slot) reads from for the *current* pipeline mode.

        Deliberately its OWN category per mode, not the same one
        Actions uses: an Actions entry needs a text instruction (an
        edit or camera-move description); a Tools entry often has none
        at all -- a LoRA-only "Anatomy Fixer" is just a stack strength,
        no prompt text -- and its correct strength is scenario-specific
        per its author, unrelated to whatever's in Actions. Those are
        two genuinely different kinds of entries even within one
        pipeline mode. t2i keeps its original "tools" category, i2i
        reads "edit_tools", i2v reads "video_tools". See
        `_actions_category` for the sibling helper this pairs with (kept
        separate rather than merged, since Actions has no t2i case to
        cover and this does)."""
        if self.pipeline_mode == PIPELINE_MODE_I2V:
            return "video_tools"
        if self.pipeline_mode == PIPELINE_MODE_I2I:
            return "edit_tools"
        return "tools"

    def _lib_active_file_list(self, category: str) -> list:
        """Session 45: Builder-facing replacement for a bare
        get_file_list(...) call — same listing minus anything Inactive
        (the entry itself, or filed under an Inactive folder). See the
        Session 45 note on __init__ for why folder_maps/active_map are
        read fresh here rather than cached."""
        folders_file = os.path.join(self.data_dir, LIBRARY_FOLDERS_FILE_NAME)
        active_file = os.path.join(self.data_dir, LIBRARY_ACTIVE_FILE_NAME)
        folder_maps = load_json(folders_file, {})
        active_map = load_active_map(active_file)
        return get_active_file_list(self.data_dir, category, folder_maps, active_map)

    def _lib_active_outfit_options(self, char_name: str) -> list:
        """Session 45: Builder-facing replacement for a bare
        list_outfit_options_for_character(...) call — same rules, minus
        anything Inactive."""
        folders_file = os.path.join(self.data_dir, LIBRARY_FOLDERS_FILE_NAME)
        active_file = os.path.join(self.data_dir, LIBRARY_ACTIVE_FILE_NAME)
        folder_maps = load_json(folders_file, {})
        active_map = load_active_map(active_file)
        return list_active_outfit_options_for_character(self.data_dir, char_name, folder_maps, active_map)

    def _refresh_template_combo(self):
        names = list(self.templates.keys())
        self.combo_template.blockSignals(True)
        self.combo_template.clear()
        self.combo_template.addItems(["— template —"] + names)
        self.combo_template.setCurrentText("— template —")
        self.combo_template.blockSignals(False)

    def _on_template_selected(self, name: str):
        if name in self.templates:
            loaded_order = list(self.templates[name])
            for key in BLOCK_ORDER_LABELS:
                if key not in loaded_order:
                    loaded_order.append(key)
            self.block_order = loaded_order
            self.lbl_order_display.setText(self._order_to_text())

    def open_order_dialog(self):
        dlg = BlockOrderDialog(self.block_order, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.block_order = dlg.get_order()
            self.lbl_order_display.setText(self._order_to_text())
            self.settings["block_order"] = list(self.block_order)
            self._save_settings()

    def save_current_as_template(self):
        name, ok = QInputDialog.getText(self, "Save template", "Template name:")
        name = (name or "").strip()
        if not ok or not name:
            return
        self.templates[name] = list(self.block_order)
        try:
            save_json(self.templates_file, self.templates)
        except FileManagerError as exc:
            themed_message_box.critical(self, "Error", str(exc))
            return
        self._refresh_template_combo()
        self.combo_template.setCurrentText(name)

    # ------------------------------------------------------------------
    # Standard: Character slots
    # ------------------------------------------------------------------
    def add_character_slot(self):
        frame = QFrame()
        frame.setObjectName("Card")
        frame.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        flayout = QVBoxLayout(frame)
        flayout.setContentsMargins(6, 6, 6, 6)
        flayout.setSpacing(4)

        top_row = QHBoxLayout()
        idx_label = QLabel(f"Character {len(self.active_characters) + 1}")
        top_row.addWidget(idx_label)
        top_row.addStretch(1)
        btn_remove = QPushButton("✕")
        btn_remove.setToolTip("Remove character")
        top_row.addWidget(btn_remove)
        flayout.addLayout(top_row)

        who_row = QHBoxLayout()
        who_row.addWidget(QLabel("Who:"))
        combo_char = AutocompleteCombobox()
        combo_char.set_items(["None"] + self._lib_active_file_list("characters"))
        combo_char.set_value("None")
        who_row.addWidget(combo_char, 1)
        btn_char_preview = QPushButton("👁")
        btn_char_preview.clicked.connect(
            lambda: self.quick_preview("characters", combo_char.current_value()))
        who_row.addWidget(btn_char_preview)
        flayout.addLayout(who_row)

        outfit_row = QHBoxLayout()
        outfit_row.addWidget(QLabel("Outfit:"))
        combo_outfit = AutocompleteCombobox()
        combo_outfit.set_items(["None"])
        combo_outfit.set_value("None")
        outfit_row.addWidget(combo_outfit, 1)
        btn_outfit_preview = QPushButton("👁")
        btn_outfit_preview.clicked.connect(
            lambda: self.quick_preview_outfit(combo_char.current_value(), combo_outfit.current_value()))
        outfit_row.addWidget(btn_outfit_preview)
        flayout.addLayout(outfit_row)

        slot_info = {
            "frame": frame, "char_combo": combo_char, "outfit_combo": combo_outfit,
            "idx_label": idx_label,
        }
        combo_char.item_selected.connect(
            lambda _text, cc=combo_char, oc=combo_outfit: self._update_outfit_list(cc, oc))
        btn_remove.clicked.connect(lambda: self.remove_character_slot(slot_info))

        self.chars_list_layout.addWidget(frame)
        self.active_characters.append(slot_info)
        self._update_chars_placeholder()

    def remove_character_slot(self, info: dict):
        info["frame"].setParent(None)
        info["frame"].deleteLater()
        self.active_characters.remove(info)
        for i, slot in enumerate(self.active_characters, start=1):
            slot["idx_label"].setText(f"Character {i}")
        self._update_chars_placeholder()

    def _update_chars_placeholder(self):
        self.placeholder_chars.setVisible(not self.active_characters)
        self.lbl_chars_count.setText(f"{len(self.active_characters)} character(s)")

    def refresh_library_backed_combos(self):
        """Re-reads `characters`/`styles`/`scenarios`/`tools` (and each
        active character slot's outfit list) off disk and pushes the
        fresh choices into every already-built combo that was seeded
        from `get_file_list`/`list_outfit_options_for_character` at
        widget-creation time. `AutocompleteCombobox.set_items()` only
        replaces the popup's master list — it never touches the line
        edit's current text (see its docstring) — so this is purely
        additive from the person's point of view: nothing they already
        picked changes, new entries just become choosable without a
        restart.

        Connected to `LibraryTab.library_changed`, which only fires on
        an actual save/duplicate/delete/import — not on every Library
        search keystroke — so this stays cheap to call.
        """
        styles = ["None"] + self._lib_active_file_list("styles")
        scenarios = ["None"] + self._lib_active_file_list("scenarios")
        characters = ["None"] + self._lib_active_file_list("characters")
        tools = ["None"] + self._lib_active_file_list("tools")
        mode_tools = ["None"] + self._lib_active_file_list(self._mode_tools_category())
        actions = ["None"] + self._lib_active_file_list(self._actions_category())

        self.combo_style.set_items(styles)
        self.combo_scenario.set_items(scenarios)

        for slot in self.active_characters:
            slot["char_combo"].set_items(characters)
            self._refresh_outfit_choices(slot["char_combo"], slot["outfit_combo"])

        for slot in self.active_tools:
            slot["tool_combo"].set_items(mode_tools)

        for slot in self.active_actions:
            slot["action_combo"].set_items(actions)

        for slot in self.custom_active_slots:
            slot["char_combo"].set_items(characters)
            if slot["outfit_combo"] is not None:
                self._refresh_outfit_choices(slot["char_combo"], slot["outfit_combo"])

        if getattr(self, "custom_style_combo", None) is not None:
            self.custom_style_combo.set_items(styles)
        if getattr(self, "custom_scenario_combo", None) is not None:
            self.custom_scenario_combo.set_items(scenarios)

        for slot in self.custom_active_tools:
            slot["tool_combo"].set_items(tools)

    def _refresh_outfit_choices(self, char_combo: AutocompleteCombobox, outfit_combo: AutocompleteCombobox):
        """Same option refresh as `_update_outfit_list`, but without
        resetting the current selection to \"None\" — this is called on
        a library-change refresh, not a character-changed event, so
        whatever outfit was already picked (if it's still valid) should
        stay picked."""
        char_name = char_combo.current_value()
        options = self._lib_active_outfit_options(char_name)
        outfit_combo.set_items(options)

    def _update_outfit_list(self, char_combo: AutocompleteCombobox, outfit_combo: AutocompleteCombobox):
        char_name = char_combo.current_value()
        options = self._lib_active_outfit_options(char_name)
        outfit_combo.set_items(options)
        outfit_combo.set_value("None")

    # ------------------------------------------------------------------
    # Standard: Tool slots
    # ------------------------------------------------------------------
    def add_tool_slot(self):
        frame = QFrame()
        frame.setObjectName("Card")
        frame.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        flayout = QVBoxLayout(frame)

        top_row = QHBoxLayout()
        idx_label = QLabel(f"Tool {len(self.active_tools) + 1}")
        top_row.addWidget(idx_label)
        top_row.addStretch(1)
        btn_remove = QPushButton("✕")
        btn_remove.setToolTip("Remove tool")
        top_row.addWidget(btn_remove)
        flayout.addLayout(top_row)

        tool_row = QHBoxLayout()
        tool_row.addWidget(QLabel("Tool:"))
        combo_tool = AutocompleteCombobox()
        combo_tool.set_items(["None"] + self._lib_active_file_list(self._mode_tools_category()))
        combo_tool.set_value("None")
        tool_row.addWidget(combo_tool, 1)
        btn_tool_preview = QPushButton("👁")
        btn_tool_preview.clicked.connect(
            lambda: self.quick_preview(self._mode_tools_category(), combo_tool.current_value()))
        tool_row.addWidget(btn_tool_preview)
        flayout.addLayout(tool_row)

        slot_info = {"frame": frame, "tool_combo": combo_tool, "idx_label": idx_label}
        btn_remove.clicked.connect(lambda: self.remove_tool_slot(slot_info))

        self.tools_list_layout.addWidget(frame)
        self.active_tools.append(slot_info)
        self._update_tools_placeholder()

    def remove_tool_slot(self, info: dict):
        info["frame"].setParent(None)
        info["frame"].deleteLater()
        self.active_tools.remove(info)
        for i, slot in enumerate(self.active_tools, start=1):
            slot["idx_label"].setText(f"Tool {i}")
        self._update_tools_placeholder()

    def _update_tools_placeholder(self):
        self.placeholder_tools.setVisible(not self.active_tools)
        self.lbl_tools_count.setText(f"{len(self.active_tools)} tool(s)")

    # ------------------------------------------------------------------
    # i2i/i2v: Action slots (Session 46.2 follow-up)
    # ------------------------------------------------------------------
    def add_action_slot(self):
        frame = QFrame()
        frame.setObjectName("Card")
        frame.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        flayout = QVBoxLayout(frame)

        top_row = QHBoxLayout()
        idx_label = QLabel(f"Action {len(self.active_actions) + 1}")
        top_row.addWidget(idx_label)
        top_row.addStretch(1)
        btn_remove = QPushButton("✕")
        btn_remove.setToolTip("Remove action")
        top_row.addWidget(btn_remove)
        flayout.addLayout(top_row)

        action_row = QHBoxLayout()
        action_row.addWidget(QLabel("Action:"))
        combo_action = AutocompleteCombobox()
        combo_action.set_items(["None"] + self._lib_active_file_list(self._actions_category()))
        combo_action.set_value("None")
        action_row.addWidget(combo_action, 1)
        btn_action_preview = QPushButton("👁")
        btn_action_preview.clicked.connect(
            lambda: self.quick_preview(self._actions_category(), combo_action.current_value()))
        action_row.addWidget(btn_action_preview)
        flayout.addLayout(action_row)

        slot_info = {"frame": frame, "action_combo": combo_action, "idx_label": idx_label}
        btn_remove.clicked.connect(lambda: self.remove_action_slot(slot_info))

        self.actions_list_layout.addWidget(frame)
        self.active_actions.append(slot_info)
        self._update_actions_placeholder()

    def remove_action_slot(self, info: dict):
        info["frame"].setParent(None)
        info["frame"].deleteLater()
        self.active_actions.remove(info)
        for i, slot in enumerate(self.active_actions, start=1):
            slot["idx_label"].setText(f"Action {i}")
        self._update_actions_placeholder()

    def _update_actions_placeholder(self):
        self.placeholder_actions.setVisible(not self.active_actions)
        self.lbl_actions_count.setText(f"{len(self.active_actions)} action(s)")

    # ------------------------------------------------------------------
    # Quick preview
    # ------------------------------------------------------------------
    def quick_preview(self, category: str, name: str):
        if not name or name == "None":
            themed_message_box.information(self, "Preview", "Nothing is selected.")
            return
        content = read_file_content(self.data_dir, category, name)
        self._show_preview_dialog(f"{category.rstrip('s').capitalize()}: {name}", content or "(empty)")

    def quick_preview_outfit(self, char_name: str, outfit_selection: str):
        if not outfit_selection or outfit_selection == "None":
            themed_message_box.information(self, "Preview", "Nothing is selected.")
            return
        if outfit_selection.startswith("Canon "):
            num = outfit_selection.split(" ", 1)[1]
            content = read_file_content(self.data_dir, "outfits", f"{char_name}_Canon_{num}")
            title = f"Outfit: {char_name} — Canon {num}"
        else:
            content = read_file_content(self.data_dir, "outfits", outfit_selection)
            title = f"Outfit: {outfit_selection}"
        self._show_preview_dialog(title, content or "(empty)")

    def _show_preview_dialog(self, title: str, content: str):
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        dlg.setMinimumSize(420, 260)
        layout = QVBoxLayout(dlg)
        txt = QPlainTextEdit(content)
        txt.setReadOnly(True)
        layout.addWidget(txt)
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(dlg.accept)
        layout.addWidget(btn_close)
        dlg.exec()

    # ------------------------------------------------------------------
    # Custom templates
    # ------------------------------------------------------------------
    def _refresh_custom_template_combo(self):
        names = list(self.custom_templates.keys())
        self.combo_custom_template.blockSignals(True)
        self.combo_custom_template.clear()
        self.combo_custom_template.addItems(names)
        if not names:
            self.combo_custom_template.setCurrentText("")
        elif self.combo_custom_template.currentText() not in names:
            self.combo_custom_template.setCurrentIndex(0)
        self.combo_custom_template.blockSignals(False)

    def _on_custom_template_selected(self, name: str):
        if name and name in self.custom_templates:
            self._build_custom_template_form(name)

    def _clear_custom_section(self):
        while self.custom_section_layout.count():
            item = self.custom_section_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self.custom_active_slots = []
        self.custom_active_tools = []

    def _show_custom_placeholder(self):
        self._clear_custom_section()
        self.current_custom_template_name = None
        self.current_custom_parsed = None
        lbl = QLabel(
            "No custom templates have been created yet.\n"
            "Click \"Create template\" to write your first one — with your own text\n"
            "and variables (character name/description/outfit, style, scenario).")
        lbl.setObjectName("dim")
        self.custom_section_layout.addWidget(lbl)

    def _build_custom_template_form(self, name: str):
        self._clear_custom_section()
        self.current_custom_template_name = name

        text = self.custom_templates.get(name, {}).get("text", "")
        parsed = parse_custom_template(text)
        self.current_custom_parsed = parsed

        header = QHBoxLayout()
        header.addWidget(QLabel(name))
        header.addStretch(1)
        self.custom_section_layout.addLayout(header)

        slot_indices = sorted(set(parsed["name_idx"]) | set(parsed["desc_idx"]) | set(parsed["outfit_idx"]))

        if slot_indices:
            box_chars = QGroupBox(" Template Characters ")
            chars_layout = QVBoxLayout(box_chars)
            for idx in slot_indices:
                row_frame = QFrame()
                row_frame.setObjectName("Card")
                row_frame.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
                row_layout = QVBoxLayout(row_frame)
                row_layout.addWidget(QLabel(f"Character {idx}:"))

                who_row = QHBoxLayout()
                who_row.addWidget(QLabel("Who:"))
                combo_char = AutocompleteCombobox()
                combo_char.set_items(["None"] + self._lib_active_file_list("characters"))
                combo_char.set_value("None")
                who_row.addWidget(combo_char, 1)
                row_layout.addLayout(who_row)

                combo_outfit = None
                if idx in parsed["outfit_idx"]:
                    outfit_row = QHBoxLayout()
                    outfit_row.addWidget(QLabel("Outfit:"))
                    combo_outfit = AutocompleteCombobox()
                    combo_outfit.set_items(["None"])
                    combo_outfit.set_value("None")
                    outfit_row.addWidget(combo_outfit, 1)
                    row_layout.addLayout(outfit_row)
                    combo_char.item_selected.connect(
                        lambda _t, cc=combo_char, oc=combo_outfit: self._update_outfit_list(cc, oc))

                chars_layout.addWidget(row_frame)
                self.custom_active_slots.append({
                    "index": idx, "char_combo": combo_char, "outfit_combo": combo_outfit,
                })
            self.custom_section_layout.addWidget(box_chars)
        else:
            lbl = QLabel("This template doesn't use any characters.")
            lbl.setObjectName("dim")
            self.custom_section_layout.addWidget(lbl)

        self.custom_style_combo = None
        if parsed["use_style"]:
            box_style = QGroupBox(" Style ")
            sl = QVBoxLayout(box_style)
            self.custom_style_combo = AutocompleteCombobox()
            self.custom_style_combo.set_items(["None"] + self._lib_active_file_list("styles"))
            self.custom_style_combo.set_value("None")
            sl.addWidget(self.custom_style_combo)
            self.custom_section_layout.addWidget(box_style)

        self.custom_scenario_combo = None
        if parsed["use_scenario"]:
            box_scen = QGroupBox(" Scenario ")
            sl2 = QVBoxLayout(box_scen)
            self.custom_scenario_combo = AutocompleteCombobox()
            self.custom_scenario_combo.set_items(["None"] + self._lib_active_file_list("scenarios"))
            self.custom_scenario_combo.set_value("None")
            sl2.addWidget(self.custom_scenario_combo)
            self.custom_section_layout.addWidget(box_scen)

        if parsed["use_tool"]:
            box_tools = QGroupBox(" Tools ")
            tl = QVBoxLayout(box_tools)
            tools_header = QHBoxLayout()
            btn_add_tool = QPushButton("＋ Add tool")
            btn_add_tool.setObjectName("accent")
            btn_add_tool.clicked.connect(self.add_custom_tool_slot)
            tools_header.addWidget(btn_add_tool)
            self.lbl_custom_tools_count = QLabel("0 tool(s)")
            self.lbl_custom_tools_count.setObjectName("dim")
            tools_header.addWidget(self.lbl_custom_tools_count)
            tools_header.addStretch(1)
            tl.addLayout(tools_header)
            self.custom_tools_list_widget = QWidget()
            self.custom_tools_list_layout = QVBoxLayout(self.custom_tools_list_widget)
            self.custom_tools_list_layout.setContentsMargins(0, 0, 0, 0)
            tl.addWidget(self.custom_tools_list_widget)
            self.placeholder_custom_tools = QLabel("No tools added. Click \"＋ Add tool\".")
            self.placeholder_custom_tools.setObjectName("dim")
            tl.addWidget(self.placeholder_custom_tools)
            self.custom_section_layout.addWidget(box_tools)

        if not slot_indices and not parsed["use_style"] and not parsed["use_scenario"] and not parsed["use_tool"]:
            lbl = QLabel("This template consists only of fixed text.")
            lbl.setObjectName("dim")
            self.custom_section_layout.addWidget(lbl)

        box_neg = QGroupBox(" Negative prompt ")
        nl = QVBoxLayout(box_neg)
        self.txt_neg_prompt_custom = QPlainTextEdit()
        self.txt_neg_prompt_custom.setFixedHeight(60)
        neg_saved = self.custom_templates.get(name, {}).get("negative_prompt", "")
        self.txt_neg_prompt_custom.setPlainText(neg_saved)
        self.txt_neg_prompt_custom.textChanged.connect(lambda: self._custom_neg_save_timer.start())
        nl.addWidget(self.txt_neg_prompt_custom)
        self.custom_section_layout.addWidget(box_neg)

    def add_custom_tool_slot(self):
        frame = QFrame()
        frame.setObjectName("Card")
        frame.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        row = QHBoxLayout(frame)
        combo_tool = AutocompleteCombobox()
        combo_tool.set_items(["None"] + self._lib_active_file_list("tools"))
        combo_tool.set_value("None")
        row.addWidget(combo_tool, 1)
        btn_remove = QPushButton("✕")
        row.addWidget(btn_remove)

        slot_info = {"frame": frame, "tool_combo": combo_tool}
        btn_remove.clicked.connect(lambda: self.remove_custom_tool_slot(slot_info))

        self.custom_tools_list_layout.addWidget(frame)
        self.custom_active_tools.append(slot_info)
        self._update_custom_tools_placeholder()

    def remove_custom_tool_slot(self, info: dict):
        info["frame"].setParent(None)
        info["frame"].deleteLater()
        self.custom_active_tools.remove(info)
        self._update_custom_tools_placeholder()

    def _update_custom_tools_placeholder(self):
        self.placeholder_custom_tools.setVisible(not self.custom_active_tools)
        self.lbl_custom_tools_count.setText(f"{len(self.custom_active_tools)} tool(s)")

    def open_custom_template_editor(self, edit_name: str = None):
        initial_text = ""
        if edit_name and edit_name in self.custom_templates:
            initial_text = self.custom_templates[edit_name].get("text", "")
        dlg = CustomTemplateEditorDialog(edit_name, initial_text, self)
        dlg.delete_requested.connect(self._delete_custom_template)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            result = dlg.get_result()
            if result is None:
                return
            name, body = result
            if edit_name and edit_name != name and edit_name in self.custom_templates:
                del self.custom_templates[edit_name]
            self.custom_templates[name] = {"text": body}
            self._save_custom_templates()
            self._refresh_custom_template_combo()
            self.combo_custom_template.setCurrentText(name)
            self._build_custom_template_form(name)

    def _delete_custom_template(self, name: str):
        if name in self.custom_templates:
            del self.custom_templates[name]
            self._save_custom_templates()
        self._refresh_custom_template_combo()
        new_name = self.combo_custom_template.currentText()
        if new_name:
            self._build_custom_template_form(new_name)
        else:
            self._show_custom_placeholder()

    def delete_selected_custom_template(self):
        name = self.combo_custom_template.currentText()
        if not name or name not in self.custom_templates:
            themed_message_box.information(self, "Delete template", "First select a custom template from the list.")
            return
        if themed_message_box.question(
                self, "Delete template", f'Delete the custom template "{name}"?'
        ) != QMessageBox.StandardButton.Yes:
            return
        self._delete_custom_template(name)

    def _save_custom_templates(self):
        try:
            save_json(self.custom_templates_file, self.custom_templates)
        except FileManagerError as exc:
            themed_message_box.critical(self, "Error", str(exc))

    def _persist_custom_negative_prompt(self):
        name = self.current_custom_template_name
        if not name or name not in self.custom_templates:
            return
        self.custom_templates[name]["negative_prompt"] = self.txt_neg_prompt_custom.toPlainText()
        self._save_custom_templates()

    # ------------------------------------------------------------------
    # Negative prompt (Standard) persistence
    # ------------------------------------------------------------------
    def _persist_negative_prompt(self):
        self.settings["negative_prompt"] = self.txt_neg_prompt.toPlainText()
        self._save_settings()

    def _save_settings(self):
        try:
            save_json(self.settings_file, self.settings)
        except FileManagerError as exc:
            themed_message_box.critical(self, "Error", str(exc))

    # ------------------------------------------------------------------
    # Generate
    # ------------------------------------------------------------------
    def generate_prompt(self):
        """Entry point: routes to Standard or Custom prompt assembly.

        Autofills the LoRA Manager from active library entries first
        (Task 7.2 in the original) — only `if self.comfy_connected`,
        since the LoRA Manager doesn't exist/isn't visible otherwise
        and there's no point writing lora_slots data a disconnected
        user will never see. Deliberately only on "Generate prompt and
        copy", not on "Generate in ComfyUI" — that gives the user a
        window to fine-tune strengths before actually submitting."""
        if self.comfy_connected:
            self._lora_autofill_from_library()

        if self.combo_template_category.currentText() == "Custom":
            self._generate_custom_prompt()
        else:
            self._generate_standard_prompt()

    def _generate_standard_prompt(self):
        valid_chars = []
        for slot in self.active_characters:
            char_name = slot["char_combo"].current_value()
            if char_name and char_name != "None":
                valid_chars.append({
                    "char_name": char_name,
                    "outfit_selection": slot["outfit_combo"].current_value(),
                })
        active_tool_names = [slot["tool_combo"].current_value() for slot in self.active_tools]
        # Session 47.2 fix: the i2i/i2v "Actions" card (self.active_actions)
        # used to be gathered nowhere at all -- populated correctly by its
        # own slot UI, but never read by any prompt-assembly code, so an
        # Action never actually reached the prompt and the empty-prompt
        # check below fired even with one filled in. See additionalfeatures.md
        # SESSION 47.2/47.3 for the full diagnosis.
        active_action_names = [slot["action_combo"].current_value() for slot in self.active_actions]

        final_prompt = generate_standard_prompt(
            self.data_dir,
            self.combo_style.current_value(),
            valid_chars,
            self.combo_scenario.current_value(),
            active_tool_names,
            self.block_order,
            tools_category=self._mode_tools_category(),
            active_action_names=active_action_names,
            actions_category=self._actions_category(),
        )

        if not final_prompt.strip():
            if self.pipeline_mode == PIPELINE_MODE_T2I:
                message = "Select at least one style, character, scenario, or tool."
            else:
                # 47.2 fix: t2i's message talks about Style/Character/
                # Scenario, none of which exist in i2i/i2v mode (that
                # UI is hidden entirely) -- the accurate version here is
                # about Actions/Tools instead.
                message = "Select at least one action or tool."
            themed_message_box.information(self, "Empty prompt", message)
            return

        self._finalize_generated_prompt(final_prompt)

    def _generate_custom_prompt(self):
        name = self.current_custom_template_name
        if not name or name not in self.custom_templates:
            themed_message_box.information(self, "Custom template", "First select or create a custom template.")
            return

        text = self.custom_templates[name].get("text", "")
        parsed = self.current_custom_parsed or parse_custom_template(text)

        name_vals, desc_vals, outfit_vals = {}, {}, {}
        for slot in self.custom_active_slots:
            idx = slot["index"]
            char_name = slot["char_combo"].current_value()
            if char_name and char_name != "None":
                name_vals[idx] = char_name
                desc_vals[idx] = read_file_content(self.data_dir, "characters", char_name)
            else:
                name_vals[idx] = ""
                desc_vals[idx] = ""

            outfit_combo = slot.get("outfit_combo")
            o_selection = outfit_combo.current_value() if outfit_combo is not None else ""
            if o_selection and o_selection != "None":
                if o_selection.startswith("Canon "):
                    num = o_selection.split(" ", 1)[1]
                    outfit_vals[idx] = read_file_content(self.data_dir, "outfits", f"{char_name}_Canon_{num}")
                else:
                    outfit_vals[idx] = read_file_content(self.data_dir, "outfits", o_selection)
            else:
                outfit_vals[idx] = ""

        style_val = ""
        if parsed["use_style"] and getattr(self, "custom_style_combo", None) is not None:
            sv = self.custom_style_combo.current_value()
            if sv and sv != "None":
                style_val = read_file_content(self.data_dir, "styles", sv)

        scenario_val = ""
        if parsed["use_scenario"] and getattr(self, "custom_scenario_combo", None) is not None:
            scv = self.custom_scenario_combo.current_value()
            if scv and scv != "None":
                scenario_val = read_file_content(self.data_dir, "scenarios", scv)

        tool_val = ""
        if parsed["use_tool"]:
            tool_parts = []
            for slot in self.custom_active_tools:
                tool_name = slot["tool_combo"].current_value()
                if not tool_name or tool_name == "None":
                    continue
                tags = read_file_content(self.data_dir, "tools", tool_name)
                if tags:
                    tool_parts.append(tags)
            tool_val = ", ".join(tool_parts)

        final_prompt = generate_custom_prompt(
            text, name_vals, desc_vals, outfit_vals, style_val, scenario_val, tool_val)

        if not final_prompt:
            themed_message_box.information(self, "Empty prompt", "Fill in at least one template variable.")
            return

        self._finalize_generated_prompt(final_prompt)

    def _finalize_generated_prompt(self, final_prompt: str):
        """Common tail for both builders. Updates the output box and
        always copies to the clipboard. History recording (ComfyUI-aware
        history, per the original): when ComfyUI is NOT connected, there
        is no later "Generate in ComfyUI" submission to defer to, so the
        result is recorded to history right here, same as Session 10.
        When ComfyUI IS connected, this step intentionally does NOT
        write a history entry — "Generate prompt and copy" is typically
        just an intermediate step before fine-tuning LoRA strengths and
        clicking "🎨 Generate in ComfyUI", which creates its own fresh
        history entry (complete with a LoRA snapshot) at the moment the
        job is queued instead — see `on_generate_in_comfy_clicked`."""
        self.txt_output.setPlainText(final_prompt)
        self.last_generated_text = final_prompt
        if not self.comfy_connected:
            self.prompt_generated.emit(final_prompt)

        # Session 27 (Design Code #6): the Session 11.5.2 decision above
        # to always auto-copy, even while connected, is reversed. Once
        # ComfyUI is connected, this text is about to be consumed
        # directly by "Generate in ComfyUI" -- silently overwriting the
        # person's clipboard on every single generate is noise, not a
        # convenience, and the explicit Copy button already covers
        # anyone who does want it on the clipboard in that state.
        # Auto-copy stays for the disconnected "build text, paste it
        # somewhere else" workflow, where it's the whole point.
        if not self.comfy_connected:
            clipboard = None
            app = self._qapp()
            if app is not None:
                clipboard = app.clipboard()
            if clipboard is not None:
                clipboard.setText(final_prompt)
            self.lbl_copy_status.setText("Prompt generated and copied to clipboard")
        else:
            self.lbl_copy_status.setText("Prompt generated — use Copy to copy it")

    def _copy_output_to_clipboard(self):
        """Manual Copy button next to the Positive tab's output (Session
        15 step 5) -- same clipboard path as the auto-copy in
        `_finalize_generated_prompt`, just re-triggerable on demand."""
        text = self.txt_output.toPlainText()
        if not text.strip():
            return
        app = self._qapp()
        if app is not None:
            app.clipboard().setText(text)
        self.lbl_copy_status.setText("✓ Copied to clipboard")

    def _refresh_prompt_output_tabs(self):
        """Show/hide the Negative tab (Session 15 step 4). Shown only
        when ComfyUI is connected AND the Standard builder is active --
        Custom templates have their own negative prompt box, and a pure
        build-text-and-copy-elsewhere workflow has no use for a
        negative prompt at all. `settings["negative_prompt"]` still
        round-trips through `txt_neg_prompt` while the tab is absent,
        exactly like `lora_slots` persists while the LoRA section is
        hidden pre-connection."""
        is_custom = self.combo_template_category.currentText() == "Custom"
        should_show = self.comfy_connected and not is_custom
        idx = self.tab_prompt_output.indexOf(self._negative_tab)
        has_tab = idx != -1
        if should_show and not has_tab:
            self.tab_prompt_output.addTab(self._negative_tab, "Negative")
        elif not should_show and has_tab:
            self.tab_prompt_output.removeTab(idx)

    @staticmethod
    def _qapp():
        from PyQt6.QtWidgets import QApplication
        return QApplication.instance()

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------
    def clear_forge(self):
        """Ported from the original's `clear_forge` — resets every
        Standard-builder selection back to empty. Not wired to a button
        yet (the original's sat in `actions_frame` next to Generate; no
        session in this plan adds a dedicated button for it, so it
        remains available for a future polish pass / F-key binding)."""
        self.combo_style.set_value("None")
        self.combo_scenario.set_value("None")
        for slot in list(self.active_characters):
            self.remove_character_slot(slot)
        for slot in list(self.active_tools):
            self.remove_tool_slot(slot)
        self.txt_output.clear()
        self.lbl_copy_status.setText("")
        if hasattr(self, "result_zone"):
            self.result_zone.show_placeholder()
            self.lbl_comfy_result_status.setText("")
            self.comfy_last_image_path = None
            self.comfy_last_remote_filename = None
            self.comfy_last_remote_subfolder = None
            self._refresh_comfy_action_buttons_state()

    # ------------------------------------------------------------------
    # ComfyUI connection toggle (Session 11)
    # ------------------------------------------------------------------
    def _set_comfy_status_text(self, text: str):
        """Single choke point for `lbl_comfy_status`'s text so the
        sidebar footer (Session 14) can mirror it via
        `comfy_status_message_changed` without polling or reaching into
        Builder internals directly."""
        self.lbl_comfy_status.setText(text)
        self.comfy_status_message_changed.emit(text)

    def sidebar_request_comfy_toggle(self):
        """Entry point for the sidebar's Run/Disconnect button (Session
        14) — flips the same `chk_comfy_enabled` checkbox the old
        Builder-local UI used, so every bit of connect/disconnect logic
        below (host/port read, ComfyCheckWorker, cross-tab wiring)
        stays exactly as-is; only the widget that *triggers* it gained
        a second front-end."""
        if self.comfy_check_busy:
            return
        self.chk_comfy_enabled.setChecked(not self.comfy_connected)

    def on_comfy_toggle(self, checked: bool):
        if not checked:
            self.comfy_connected = False
            self.comfy_workflow_ok = False
            self.comfy_client = None
            self.comfy_rail.setVisible(False)
            self._refresh_lora_page_visibility()
            self._set_comfy_status_text("")
            if self._comfy_queue:
                self._comfy_queue.clear()
            self._refresh_comfy_queue_label()
            self.comfy_connection_changed.emit(False)
            self._refresh_prompt_output_tabs()
            QTimer.singleShot(0, self._apply_result_panel_height)
            return

        # Session 19: host/port live on the Settings page now
        # (`MainWindow._build_settings_page`), which writes straight
        # into this same shared `self.settings` dict -- read from there
        # instead of a since-removed Builder-local `QLineEdit` pair.
        host = self.settings.get("comfy_host", COMFY_DEFAULT_HOST) or COMFY_DEFAULT_HOST
        try:
            port = int(self.settings.get("comfy_port", COMFY_DEFAULT_PORT) or COMFY_DEFAULT_PORT)
        except (TypeError, ValueError):
            themed_message_box.warning(
                self, "Invalid port",
                "Port must be a number. Fix it on the Settings page.")
            self.chk_comfy_enabled.blockSignals(True)
            self.chk_comfy_enabled.setChecked(False)
            self.chk_comfy_enabled.blockSignals(False)
            return

        self.comfy_client = ComfyUIClient(host, port)

        self._set_comfy_status_text("Checking connection…")
        self.chk_comfy_enabled.setEnabled(False)
        self.comfy_check_busy = True
        self.comfy_check_busy_changed.emit(True)

        self._check_worker = ComfyCheckWorker(self.comfy_client)
        self._check_worker.check_done.connect(self._on_comfy_check_done)
        self._check_worker.start()

    def _on_comfy_check_done(self, success: bool, error_msg: str, out_dir: str,
                              workflow_ok: bool, workflow_msg: str, loras: list):
        self.chk_comfy_enabled.setEnabled(True)
        self.comfy_check_busy = False
        self.comfy_check_busy_changed.emit(False)

        if not success:
            self.comfy_connected = False
            self.comfy_workflow_ok = False
            self.chk_comfy_enabled.blockSignals(True)
            self.chk_comfy_enabled.setChecked(False)
            self.chk_comfy_enabled.blockSignals(False)
            self.comfy_rail.setVisible(False)
            self._refresh_lora_page_visibility()
            self._set_comfy_status_text(f"✗ {error_msg}")
            if self._comfy_queue:
                self._comfy_queue.clear()
            self._refresh_comfy_queue_label()
            self.comfy_connection_changed.emit(False)
            self._refresh_prompt_output_tabs()
            themed_message_box.critical(self, "ComfyUI", f"Could not connect to ComfyUI:\n{error_msg}")
            return

        self.comfy_connected = True
        self.comfy_output_dir = out_dir or None
        self.comfy_workflow_ok = workflow_ok
        self._available_loras = list(loras)
        self._lora_update_combos()
        self.comfy_connection_changed.emit(True)
        self._refresh_prompt_output_tabs()

        if self.gallery_tab is not None:
            self.gallery_tab.comfy_output_dir = self.comfy_output_dir
        if self.library_tab is not None:
            self.library_tab._refresh_lib_lora_visibility(True)
            self.library_tab._update_available_loras(loras)
            if hasattr(self.library_tab, "refresh_library_list"):
                self.library_tab.refresh_library_list()

        if workflow_ok:
            self._set_comfy_status_text("✓ Connected — graph ready")
            self.comfy_rail.setVisible(True)
            self._refresh_lora_page_visibility()
        else:
            self._set_comfy_status_text(f"⚠ {workflow_msg}")
            self.comfy_rail.setVisible(False)
            self._refresh_lora_page_visibility()
        self._refresh_comfy_queue_label()
        QTimer.singleShot(0, self._apply_result_panel_height)

    # ------------------------------------------------------------------
    # Generation queue (Session 11)
    # ------------------------------------------------------------------
    def on_generate_in_comfy_clicked(self):
        """Entry point for "🎨 Generate in ComfyUI". Deliberately does
        NOT rebuild the prompt from the blocks/template — it takes
        whatever text currently sits in the output box (which the user
        may have hand-edited after generating) and submits exactly
        that. This click always succeeds (appends to `self._comfy_queue`)
        rather than refusing when `comfy_busy` is True — every parameter
        this generation will need (seed, resolution, negative prompt,
        LoRA snapshot) is frozen right here, on the main thread, at the
        moment of the click, so a later click that changes a LoRA
        strength can never retroactively affect a generation already
        sitting in the queue. A new history entry is also created right
        here — see `HistoryTab.attach_image_to_history_entry`'s
        docstring for why it's tied together by id from this moment,
        not by matching text later."""
        now = time.monotonic()
        if now < self._comfy_queue_debounce_until:
            return  # absorbs a panicked double/triple-click on the same press
        self._comfy_queue_debounce_until = now + (COMFY_QUEUE_DEBOUNCE_MS / 1000.0)

        prompt_text = self.txt_output.toPlainText().strip()
        if not prompt_text:
            themed_message_box.information(
                self, "Empty prompt", "Generate a prompt first (or type one into the result box).")
            return

        # Session 46.1: i2i/i2v genuinely need an input image — t2i
        # doesn't set/read input_image_path at all (stays None), so this
        # is a no-op for every pre-46.1 t2i flow.
        if self.pipeline_mode != PIPELINE_MODE_T2I and not self.input_image_path:
            themed_message_box.information(
                self, "No input image",
                "Choose an input image first (this mode needs one).")
            return

        if self.radio_seed_fixed.isChecked():
            try:
                seed = int(self.ent_comfy_seed.text().strip())
            except ValueError:
                themed_message_box.warning(self, "Invalid seed", "Seed must be a whole number.")
                return
        else:
            seed = random.randint(0, 2**32 - 1)
            self.ent_comfy_seed.setText(str(seed))

        try:
            width = int(self.ent_comfy_width.text().strip())
            height = int(self.ent_comfy_height.text().strip())
            if width <= 0 or height <= 0:
                raise ValueError
        except ValueError:
            themed_message_box.warning(
                self, "Invalid resolution", "Width and height must be positive whole numbers.")
            return

        missing_loras = [
            entry["name"] for entry in self.lora_slots_data
            if entry.get("name", LORA_NONE_VALUE) != LORA_NONE_VALUE
            and entry["name"] not in self._available_loras
        ]
        if missing_loras:
            if not self._available_loras:
                self.lbl_comfy_result_status.setText(
                    "⚠ LoRA list not loaded yet — skipping LoRA validation.")
            else:
                themed_message_box.critical(
                    self, "Missing LoRA",
                    "The following LoRAs were not found in ComfyUI:\n"
                    + "\n".join(f"- {n}" for n in missing_loras))
                return

        lora_slots_snapshot = [dict(e) for e in self.lora_slots_data]

        if (self.combo_template_category.currentText() == "Custom"
                and hasattr(self, "txt_neg_prompt_custom")):
            negative_text = self.txt_neg_prompt_custom.toPlainText().strip()
        else:
            negative_text = self.txt_neg_prompt.toPlainText().strip()

        history_id = None
        if self.history_tab is not None:
            history_id = self.history_tab.add_comfy_history_entry(
                prompt_text, lora_slots_snapshot,
                seed=seed, width=width, height=height, negative_text=negative_text)

        queue_item = {
            "prompt_text": prompt_text,
            "seed": seed,
            "width": width,
            "height": height,
            "negative_text": negative_text,
            "lora_slots_snapshot": lora_slots_snapshot,
            "history_id": history_id,
            # Session 46.1: None in plain t2i mode — ComfyGenerationWorker
            # treats a falsy value here as "nothing to upload/patch".
            "input_image_path": self.input_image_path,
            # Session 47.4 fix: which pipeline mode queued this item, so
            # ComfyGenerationWorker can wait with COMFY_VIDEO_POLL_TIMEOUT
            # instead of the much shorter COMFY_POLL_TIMEOUT for i2v runs
            # — a real video generation can legitimately take 10-30
            # minutes, well past the 300s ceiling that was sized for
            # t2i/i2i. Snapshotted at enqueue time like everything else
            # in this dict, so a mode switch while an item is still
            # queued doesn't retroactively change an already-queued
            # item's timeout.
            "pipeline_mode": self.pipeline_mode,
        }
        self._comfy_queue.append(queue_item)
        self._refresh_comfy_queue_label()
        self._maybe_start_next_queued_generation()

    def _refresh_comfy_queue_label(self):
        """Session 22 step 3: the queue count used to live in its own
        `lbl_comfy_queue_count` readout next to Stop; that label is gone
        now and the count folds straight into Clear queue's own text --
        "in flight" is already visible via the progress bar/status line,
        so this only needs to say how many are *pending* behind it."""
        n = len(self._comfy_queue)
        self.btn_comfy_clear_queue.setText(f"Clear queue ({n})" if n > 0 else "Clear queue")
        self._refresh_comfy_action_buttons_state()

    def _refresh_comfy_action_buttons_state(self):
        """Session 22 step 2: the one choke point that recomputes all
        four result-column actions together, so their *enabled* state
        (never their existence -- they're always visible once built)
        reflects what's currently doable:
          - Generate in ComfyUI: connected, graph ready. Session 23
            bugfix: this must stay enabled while a generation is
            already in flight too -- disabling it on `comfy_busy` was
            silently breaking the whole "queue another one while this
            one runs" flow the app already supports (see
            `_maybe_start_next_queued_generation` / `_comfy_queue`).
            Every other action here genuinely depends on run state;
            this one doesn't.
          - Stop: only while a generation is actually in flight.
          - Clear queue: only when something is pending (text itself
            carries the count -- see `_refresh_comfy_queue_label`).
          - Open folder: only once at least one image has been saved
            this session.
        """
        ready = self.comfy_connected and self.comfy_workflow_ok
        self.btn_generate_comfy.setEnabled(ready)
        self.btn_comfy_stop.setEnabled(ready and self.comfy_busy)
        self.btn_comfy_clear_queue.setEnabled(ready and bool(self._comfy_queue))
        self.btn_comfy_open_folder.setEnabled(ready and bool(self.comfy_last_image_path))

    def clear_comfy_queue(self):
        """Removes every PENDING item — matches native ComfyUI's own
        "Clear queue": never touches whatever is currently sampling.
        Stop is the separate, deliberate action for that."""
        n = len(self._comfy_queue)
        if n == 0:
            return
        if themed_message_box.question(
                self, "Clear queue",
                f"Remove {n} pending generation(s) from the queue?\n\n"
                f"The one currently generating (if any) keeps running — "
                f"use Stop for that."
        ) != QMessageBox.StandardButton.Yes:
            return
        self._comfy_queue.clear()
        self._refresh_comfy_queue_label()
        self.lbl_comfy_result_status.setText("Queue cleared.")

    def _maybe_start_next_queued_generation(self):
        """Pops the next item off the local queue and submits it, but
        only if ComfyUI isn't already busy — the one place that keeps
        exactly one job in flight at a time. Called after every enqueue
        and after every completion/failure/stop, so the queue drains
        itself automatically."""
        if self.comfy_busy or not self._comfy_queue:
            return
        queue_item = self._comfy_queue.pop(0)
        self._start_comfy_generation(queue_item)
        self._refresh_comfy_queue_label()

    def _start_comfy_generation(self, queue_item: dict):
        """Submits one already-fully-snapshotted queue item. Short by
        design — see this module's docstring for why: the entire fetch-
        graph/validate/patch/submit/poll/download pipeline already lives
        in `ComfyGenerationWorker` (Session 9); this only wires up its
        five signals and flips the busy/UI state around the run."""
        self.comfy_busy = True
        self._comfy_current_history_id = queue_item.get("history_id")
        self._comfy_last_total_steps = None
        self.lbl_comfy_result_status.setText("Submitting to ComfyUI…")
        self.result_zone.show_placeholder()
        self.progress_frame.setVisible(True)
        self.progress_bar.setValue(0)
        self.lbl_comfy_progress.setText("")
        self.btn_comfy_stop.setText("Stop")
        self._refresh_comfy_action_buttons_state()
        QTimer.singleShot(0, self._apply_result_panel_height)

        self._gen_worker = ComfyGenerationWorker(self.comfy_client, queue_item)
        self._gen_worker.progress_updated.connect(self._on_comfy_progress)
        self._gen_worker.preview_ready.connect(self._on_comfy_preview_bytes)
        self._gen_worker.image_ready.connect(self._on_comfy_image_bytes)
        self._gen_worker.video_ready.connect(self._on_comfy_video_bytes)
        self._gen_worker.generation_failed.connect(self._on_comfy_generation_failed)
        self._gen_worker.generation_finished.connect(self._on_comfy_generation_finished)
        self._gen_worker.start()

    def on_comfy_stop_clicked(self):
        if self._gen_worker is not None and self.comfy_busy:
            self.btn_comfy_stop.setEnabled(False)
            self.btn_comfy_stop.setText("Stopping…")
            self._gen_worker.stop()

    # ---- ComfyGenerationWorker signal handlers ----
    def _on_comfy_progress(self, current: int, total: int):
        self.progress_bar.setMaximum(max(total, 1))
        self.progress_bar.setValue(current)
        self.lbl_comfy_progress.setText(f"{current}/{total}")
        # Session 35: History's "Generation" card wants a steps count,
        # which isn't known at enqueue time — only once the run starts
        # reporting real progress. Last value seen wins (final update
        # carries the true total), consumed by `_on_comfy_image_bytes`.
        self._comfy_last_total_steps = total

    def _on_comfy_preview_bytes(self, img_bytes: bytes):
        self.result_zone.show_image_bytes(img_bytes)

    def _on_comfy_image_bytes(self, img_bytes: bytes, filename: str, subfolder: str):
        self.comfy_last_remote_filename = filename
        self.comfy_last_remote_subfolder = subfolder or ""
        self._comfy_session_image_counter += 1
        ext = os.path.splitext(filename)[1] or ".png"
        try:
            local_path = save_comfy_preview_image(
                self.data_dir, img_bytes, self._comfy_session_image_counter, ext)
        except FileManagerError as exc:
            self._on_comfy_generation_failed(str(exc))
            return

        self.comfy_last_image_path = local_path
        self.result_zone.show_image_path(local_path)
        display_name = filename or os.path.basename(local_path)
        self.lbl_comfy_result_status.setText(f"✓ {display_name}")

        # Session 37: "gen_ready" and "image_saved" are two distinct,
        # independently configurable notifications, but both resolve to
        # the same real-world instant -- the generation's result is
        # both done AND written to disk at the same point in this
        # handler (there's no separate earlier "done, not yet saved"
        # moment in this pipeline). Resolved the naming ambiguity
        # flagged in the design doc this way (completion, not submit)
        # since "your generation is ready" reads as "go look at the
        # result", not "ComfyUI accepted the job" -- the latter is
        # already covered by `lbl_comfy_result_status`'s own text.
        sound_manager.play(self.data_dir, "gen_ready")
        sound_manager.play(self.data_dir, "image_saved")

        if self.gallery_tab is not None:
            self.gallery_tab._gallery_register_result(
                local_path=local_path, remote_filename=filename,
                remote_subfolder=subfolder, display_name=display_name)

        if self.history_tab is not None and self._comfy_current_history_id:
            self.history_tab.attach_image_to_history_entry(
                self._comfy_current_history_id, local_path, filename, subfolder,
                steps=self._comfy_last_total_steps)
        self._comfy_current_history_id = None

        self._refresh_comfy_action_buttons_state()
        QTimer.singleShot(0, self._apply_result_panel_height)

    def _on_comfy_video_bytes(self, video_bytes: bytes, filename: str, subfolder: str):
        """Session 46.3/46.4's video counterpart to
        `_on_comfy_image_bytes` above — same save/notify/register
        plumbing, reused rather than duplicated, just:
        (a) saved with the video's own extension instead of always
            ".png" (`save_comfy_preview_image` doesn't care what bytes
            or extension it's given — it's a plain file write), and
        (b) shown via `result_zone.show_video_path` instead of
            `show_image_path` — Session 46.4b's shared embedded
            `VideoPlayerWidget` now actually plays the file back
            in-app, rather than the plain "video ready, open the
            folder yourself" placeholder text 46.4 shipped as a
            stopgap. `comfy_last_image_path` is reused as-is (not
            renamed to something video-neutral) despite the name — it
            was already "last result's local path" in function, used
            by `on_comfy_open_folder_clicked` and the Open-folder
            button's enabled-state check, neither of which cares
            whether that path happens to be an image or a video.
        Gallery/History registration is identical to the image path —
        both now recognize a video `local_path` via `VIDEO_EXTENSIONS`
        and show a poster frame / in-place playback instead of a
        broken-looking image placeholder (Session 46.4b)."""
        self.comfy_last_remote_filename = filename
        self.comfy_last_remote_subfolder = subfolder or ""
        self._comfy_session_image_counter += 1
        ext = os.path.splitext(filename)[1] or ".mp4"
        try:
            local_path = save_comfy_preview_image(
                self.data_dir, video_bytes, self._comfy_session_image_counter, ext)
        except FileManagerError as exc:
            self._on_comfy_generation_failed(str(exc))
            return

        self.comfy_last_image_path = local_path
        self.result_zone.show_video_path(local_path, filename)
        display_name = filename or os.path.basename(local_path)
        self.lbl_comfy_result_status.setText(f"✓ {display_name}")

        sound_manager.play(self.data_dir, "gen_ready")
        sound_manager.play(self.data_dir, "image_saved")

        if self.gallery_tab is not None:
            self.gallery_tab._gallery_register_result(
                local_path=local_path, remote_filename=filename,
                remote_subfolder=subfolder, display_name=display_name)

        if self.history_tab is not None and self._comfy_current_history_id:
            self.history_tab.attach_image_to_history_entry(
                self._comfy_current_history_id, local_path, filename, subfolder,
                steps=self._comfy_last_total_steps)
        self._comfy_current_history_id = None

        self._refresh_comfy_action_buttons_state()
        QTimer.singleShot(0, self._apply_result_panel_height)

    def _on_comfy_generation_failed(self, error_msg: str):
        was_user_stop = bool(self._gen_worker is not None and self._gen_worker.was_stopped)
        self._comfy_current_history_id = None
        if was_user_stop:
            # Expected, user-initiated abort — not an error, so no
            # error dialog (that would read as a confusing "failure"
            # popup for something the user explicitly asked for).
            self.lbl_comfy_result_status.setText("Generation stopped.")
        else:
            self.lbl_comfy_result_status.setText("✗ Generation failed")
            themed_message_box.critical(self, "ComfyUI generation failed", error_msg)

    def _on_comfy_generation_finished(self):
        """`ComfyGenerationWorker.generation_finished` fires exactly
        once, always last, on success, failure, OR stop alike — the one
        signal this tab needs to know "this slot is free, try the next
        queued item" (see that worker's own docstring)."""
        self.comfy_busy = False
        self._gen_worker = None
        self.progress_frame.setVisible(False)
        self.progress_bar.setValue(0)
        self.lbl_comfy_progress.setText("")
        self.btn_comfy_stop.setText("Stop")
        self._refresh_comfy_queue_label()
        QTimer.singleShot(0, self._apply_result_panel_height)
        self._maybe_start_next_queued_generation()

    def comfy_open_output_folder(self):
        """Opens the folder containing the last generated image in the
        OS file explorer, with that image already selected/highlighted.
        Prefers ComfyUI's real output/ folder (+ whatever subfolder the
        node saved into) over the local throwaway preview copy used
        just to render the thumbnail."""
        if not self.comfy_last_image_path:
            return
        folder = resolve_output_folder_for(self.comfy_output_dir, self.comfy_last_remote_subfolder)
        if folder and self.comfy_last_remote_filename:
            target_file = os.path.join(folder, self.comfy_last_remote_filename)
        else:
            target_file = os.path.abspath(self.comfy_last_image_path)
            folder = os.path.dirname(target_file)
        try:
            reveal_file_in_explorer(target_file, folder)
        except FileManagerError as exc:
            themed_message_box.warning(self, "Open folder", str(exc))
