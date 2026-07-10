"""Library tab — Part 1 (Session 4): category bar, folder-aware tree
(read-only shape — create/rename/delete/drag&drop folder behavior is
Session 6), and the entry editor's static fields (name, tags, canon
binding). Part 2 (Session 5) fills in the image zone, the Source URL
row, and the LoRA binding row.

Ported from `PromptForgeApp.build_library_tab` / `switch_library_category`
/ `_apply_library_category` / `toggle_canon_char_selector` /
`refresh_library_list` / `on_library_select` / `start_new_library_entry` /
`duplicate_library_entry` / `delete_library_entry` / `save_to_library` /
`handle_image_drop` / `_on_image_zone_resize` / `_on_library_panel_resize`
/ `_build_lib_source_row` / `_render_lib_source_row` /
`_start_lib_source_edit` / `_cancel_lib_source_edit` /
`_save_lib_source_url` / `_build_lib_lora_row` / `_render_lib_lora_row` /
`_assign_lib_lora` / `_clear_lib_lora` / `_persist_current_lib_meta` /
`_refresh_lib_lora_visibility` in the original monolith.

Scope notes:
- The folder *toolbar* (Expand all / Collapse all / New folder) and the
  right-click "Move to..." menu are Session 6, not built here — the tree
  already groups entries under folder rows (no flat-list intermediate
  state), but those folder rows are currently just rendering, not yet
  interactive.
- LoRA-status row coloring (green/yellow/red tags on the tree) and the
  "🔍 Check LoRA dependencies" button require a live ComfyUI connection,
  which doesn't exist until Session 9/11 — `_refresh_lib_lora_visibility`
  and `_update_available_loras` below are the public hooks a later
  session wires up (per the migration plan's own Session 13 cross-tab
  wiring list); until then the LoRA binding row simply starts hidden,
  same as the original's `self.comfy_connected` starting False.
- `force_first` (the Tools category's "force this tag to the very start
  of the prompt" checkbox) is bundled with the rest of the per-entry
  metadata sidecar in the original's UI (its own `frame_tool_options`
  block, shown only for the "tools" category) but isn't built here yet —
  nothing in the Session 4/5 field list calls for it, and `save_to_library`
  always passes `force_first=False` for now, exactly as it did in
  Session 4. Revisit alongside the Tools-specific Builder work.
"""
import glob
import os
import shutil
import time
import uuid

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from backend.constants import (
    CANONICAL_OUTFITS_FOLDER,
    CATEGORIES,
    CATEGORY_LABELS,
    FOLDER_PATH_SEP,
    LIBRARY_FOLDERS_FILE_NAME,
    LIBRARY_ACTIVE_FILE_NAME,
    LORA_STRENGTH_MAX,
    LORA_STRENGTH_MIN,
    natural_sort_key,
    sanitize_filename,
    PIPELINE_MODE_VISIBLE_CATEGORIES,
    TOOLS_LIKE_CATEGORIES,
    VIDEO_EXTENSIONS,
)
from backend.file_manager import (
    ImageProcessingError,
    LibraryExportImportError,
    create_new_folder,
    delete_folder,
    delete_folder_active_entries,
    delete_library_image,
    delete_library_meta,
    delete_library_video,
    export_library,
    extract_library_zip,
    find_library_image,
    find_library_video,
    get_entry_folder,
    get_file_list,
    is_canon_outfit_name,
    is_entry_active,
    is_folder_active,
    is_protected_folder,
    library_image_path,
    library_video_path,
    list_all_folders,
    load_active_map,
    load_library_meta,
    load_json,
    merge_imported_library,
    move_entries_to_folder,
    process_and_store_image,
    process_and_store_video,
    read_file_content,
    remove_entry_active_entry,
    remove_entry_folder_entry,
    rename_entry_active_entry,
    rename_entry_folder_entry,
    rename_folder,
    rename_folder_active_entry,
    rename_library_image,
    rename_library_meta,
    rename_library_video,
    save_active_map,
    save_json,
    save_library_meta,
    set_entries_active,
    set_entry_folder,
    set_folders_active,
)
from backend.file_manager import _file_canon_outfit_into_folder as file_canon_outfit_into_folder
from backend.lora_deps import (
    apply_lora_candidate, compute_lora_dependency_status, scan_library_lora_dependencies,
)
from backend import sound_manager
from ui.color_utils import qcolor_from_token
from ui.dialogs import themed_message_box
from ui.dialogs.library_export_import_dialog import LibraryExportImportDialog
from ui.dialogs.library_folder_dialog import LibraryFolderDialog
from ui.dialogs.lora_assign_dialog import LoraAssignDialog
from ui.dialogs.lora_dependency_dialog import LoraDependencyReportDialog
from ui.widgets.autocomplete import AutocompleteCombobox
from ui.widgets.image_zone import ImageDropZone
from ui.widgets.no_scroll_spinbox import NoScrollDoubleSpinBox
from ui.widgets.video_player import PosterFrameGrabber

# Tree item kinds, stashed in Qt.ItemDataRole.UserRole.
_KIND_FOLDER = "folder"
_KIND_ENTRY = "entry"


def _is_video_file(path) -> bool:
    """Session 48.4: same extension-only classification used
    elsewhere (gallery_tab.py's own _is_video_path) — kept local
    rather than imported since it's a one-line check, not shared
    state, and image_zone.py's own copy (_has_video_extension) is a
    private module helper not meant to be imported across files."""
    if not path:
        return False
    return os.path.splitext(path)[1].lower() in VIDEO_EXTENSIONS

# Session 29: once every control in a row got its own card, packing them
# edge-to-edge with zero gap looked worse than the old mega-card version —
# this is the small horizontal gap between same-row cards, matching the
# card-to-card rhythm already used vertically.
_ROW_CARD_SPACING = 8


class _LibraryTreeWidget(QTreeWidget):
    """QTreeWidget specialized for the Library tab's folder tree.

    Entries can be dragged onto folder rows (and only folder rows) to
    move them; folders themselves are never drag sources — only
    "Move to..." (context menu) can relocate a folder's *contents*, and
    nothing in this plan supports reparenting a folder itself. Folder
    vs. entry drag/drop eligibility is enforced per-item via the
    Qt.ItemFlag.ItemIsDragEnabled / ItemIsDropEnabled flags set on each
    QTreeWidgetItem in LibraryTab.refresh_library_list, not here.

    Multi-selection drag is native Qt behavior — QAbstractItemView
    already distinguishes "click on a multi-selected row and release
    without moving" (collapses to that one row) from "click and drag"
    (drags the whole existing selection) out of the box, which is
    exactly the original's `_lib_drag_snapshot` intent, so no manual
    mouse-event bookkeeping is needed to reproduce it under Qt.

    `on_entries_dropped(folder_path, base_names)` is set by LibraryTab
    after construction — the only way this widget talks back to its
    owner, kept dependency-free so it has no knowledge of LibraryTab
    itself.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.on_entries_dropped = None
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)

    def _folder_target_at(self, pos):
        item = self.itemAt(pos)
        if item is None:
            return None
        data = item.data(0, Qt.ItemDataRole.UserRole) or {}
        return item if data.get("kind") == _KIND_FOLDER else None

    def dragMoveEvent(self, event):
        # Only ever highlight folders as drop targets — dropping an
        # entry "onto" another entry isn't a supported operation (no
        # manual ordering inside a folder, only alphabetical).
        if self._folder_target_at(event.position().toPoint()) is not None:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        target = self._folder_target_at(event.position().toPoint())
        if target is None:
            event.ignore()
            return
        folder_path = (target.data(0, Qt.ItemDataRole.UserRole) or {}).get("path", "")
        names = [
            (item.data(0, Qt.ItemDataRole.UserRole) or {}).get("base")
            for item in self.selectedItems()
            if (item.data(0, Qt.ItemDataRole.UserRole) or {}).get("kind") == _KIND_ENTRY
        ]
        names = [n for n in names if n]
        event.acceptProposedAction()
        # Deliberately NOT calling super().dropEvent() — letting Qt's
        # own internal-move machinery reparent QTreeWidgetItems would
        # fight with refresh_library_list(), which already rebuilds the
        # whole tree from folder_maps after every change. The actual
        # move is data-layer only; the visual tree always comes from a
        # fresh refresh.
        if names and self.on_entries_dropped:
            self.on_entries_dropped(folder_path, names)


class LibraryTab(QWidget):
    # Fired after an entry is saved/duplicated/deleted/renamed, or a
    # library is imported — i.e. whenever the on-disk file lists that
    # Builder's combos (`characters`/`styles`/`scenarios`/`tools`, plus
    # per-character outfit lists) are seeded from at widget-creation
    # time could have changed. Not fired from `refresh_library_list()`
    # itself (called on every search keystroke/category switch, most of
    # which change nothing on disk) — only from the four call sites
    # below that actually write/delete files.
    library_changed = pyqtSignal()

    def __init__(self, data_dir: str, colors: dict, settings: dict, settings_file: str, parent=None):
        super().__init__(parent)
        self.data_dir = data_dir
        self.colors = colors
        # Shared, mutable reference to MainWindow's settings dict/file —
        # same pattern as the original keeping `lib_image_zone_percent`
        # in `self.settings`. MainWindow owns the actual save-to-disk
        # call timing elsewhere except for this slider's own debounced
        # write, which (like the original) persists immediately rather
        # than waiting for some other action to flush it.
        self.settings = settings
        self.settings_file = settings_file

        self.folders_file = os.path.join(data_dir, LIBRARY_FOLDERS_FILE_NAME)
        # {category: {entry_name: "folder/path"}} — persisted.
        self.folder_maps: dict = load_json(self.folders_file, {})

        # Session 45: {category: {"entries": set(name), "folders":
        # set(folder_path)}} of everything currently marked INACTIVE —
        # see backend/file_manager.py's load_active_map for the on-disk
        # shape and the "absence = active" default.
        self.active_file = os.path.join(data_dir, LIBRARY_ACTIVE_FILE_NAME)
        self.active_map: dict = load_active_map(self.active_file)
        # {category: {folder_path, ...}} — folders created via "New
        # folder"/"New subfolder" that don't have anything filed into
        # them yet. In-memory only, same lifecycle as the original's
        # self._empty_folders — they become "real" the moment something
        # is filed into them; until then they'd otherwise vanish on the
        # next refresh since list_all_folders only derives paths from
        # entries that exist.
        self.empty_folders: dict = {}
        # {category: {folder_path, ...}} — which folders are currently
        # expanded. Session-only, reset every app restart, exactly like
        # the original's self._expanded_folders.
        self.expanded_folders: dict = {}

        self.current_category = "styles"
        self.selected_file = None  # base name of the entry being edited, or None for "new"
        self.editing_canon_owner = None  # (char_name, num) when editing an existing canon outfit
        self.cat_buttons: dict = {}

        # Session 48.4: PosterFrameGrabber instances must stay
        # referenced somewhere until their frame_grabbed signal fires
        # (a local variable inside handle_video_attach would be
        # garbage-collected before the async grab ever completes,
        # silently dropping the poster) — same lifetime problem
        # gallery_tab.py's own self._poster_grabbers list solves,
        # scoped down to "one in flight at a time" here since only one
        # entry's editor can be open at once.
        self._pending_poster_grabber = None

        # ---- Task 6 (Source URL) state ----
        self.lib_source_url = None
        self.lib_source_editing = False

        # ---- Task 7.1 (LoRA binding) state ----
        self.lib_entry_lora = None
        # Session 30: per-entry strength, default 1.0 for any entry that
        # doesn't already have one stored (see save_library_meta).
        self.lib_entry_lora_strength = 1.0
        # Populated later by Session 9/11's ComfyUI wiring via
        # `_update_available_loras` / `_refresh_lib_lora_visibility`.
        # Starts empty/disconnected, same as the original's
        # `self._available_loras = []` / `self.comfy_connected = False`
        # before a connection is ever made.
        self._available_loras: list = []
        # Session 31: {(category, base): "ok"|"missing"|"conflict"} from
        # the last explicit "Check LoRA dependencies" click. Empty means
        # "no check has been run since the last time this got cleared" —
        # refresh_library_list leaves rows uncolored in that state.
        # Deliberately a full-library map (every category at once, same
        # scope as scan_library_lora_dependencies), not recomputed per
        # category switch — one click colors every category you look at
        # until you either re-check or leave the Library page.
        self.lora_dep_status: dict = {}
        self.comfy_connected = False

        self._build_ui()
        self._apply_library_category("styles")

    # ------------------------------------------------------------------
    # Card helper (Design Code #3, same shape as BuilderTab._build_card
    # — kept as its own copy rather than a shared import since the two
    # tabs don't otherwise share a base class; title="" skips the
    # heading row entirely for clusters that don't need a label, e.g.
    # the Export/Import and folder-toolbar rows below.)
    # ------------------------------------------------------------------
    def _build_card(self, title: str = "") -> tuple:
        frame = QFrame()
        frame.setObjectName("Card")
        frame.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        inner = QVBoxLayout(frame)
        inner.setContentsMargins(10, 8, 10, 10)
        inner.setSpacing(6)
        if title:
            heading = QLabel(title)
            heading.setObjectName("CardHeading")
            inner.addWidget(heading)
        return frame, inner

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self):
        outer = QVBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(splitter)

        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_right_panel())
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        # Without an explicit setSizes() call, QSplitter's initial split is
        # driven by each child's sizeHint(), not by setStretchFactor() (that
        # only governs how *extra* space is distributed on a later resize).
        # The left panel's 5-button category bar reports a wide sizeHint —
        # wide enough that, left to its own devices, the splitter handed it
        # the vast majority of the width and squeezed the right "Entry
        # Editor" panel down to a sliver on first launch. Force a sane
        # starting split instead; stretch factors then take over correctly
        # from here on as the window is resized.
        splitter.setSizes([460, 640])
        splitter.setChildrenCollapsible(False)

    # Session 28 (Design Code #5): the image preview used to claim a
    # manually-computed pixel budget (percent slider × "everything else
    # in this panel's chrome") — same dead-space/second-manual-control
    # problem Builder's own result column had until Session 17.5 killed
    # its "Size" slider. `image_drop_zone` now just takes an Expanding
    # size policy and fills whatever `right_panel`'s layout gives it;
    # no percent scheme, no resizeEvent-driven budget recompute, no
    # debounced settings write. `ImageZoneBase`'s own
    # MIN_PERCENT/MAX_PERCENT/apply_panel_height machinery is untouched
    # (still used elsewhere, e.g. Builder's own pre-17.5 history) — this
    # tab simply stops calling it.

    def _build_left_panel(self) -> QWidget:
        left = QWidget()
        left.setMinimumWidth(320)
        layout = QVBoxLayout(left)
        layout.setContentsMargins(0, 0, 0, 0)

        # ---- Export/import row (Session 7), one card per control
        # (Session 29 amendment — a card is a themeable surface for a
        # single button, not a shared backdrop for two unrelated ones;
        # see Design Code #3 amendment) ----
        export_import_row = QHBoxLayout()
        export_import_row.setSpacing(_ROW_CARD_SPACING)
        box_export, export_inner = self._build_card("")
        btn_export = QPushButton("Export library")
        btn_export.clicked.connect(self.export_library)
        export_inner.addWidget(btn_export)
        export_import_row.addWidget(box_export)
        box_import, import_inner = self._build_card("")
        btn_import = QPushButton("Import library")
        btn_import.clicked.connect(self.import_library)
        import_inner.addWidget(btn_import)
        export_import_row.addWidget(box_import)
        layout.addLayout(export_import_row)

        # ---- Category tab bar, one card per button (Session 29), no
        # emoji prefix (Session 29's "remaining emoji" fix — see
        # CATEGORY_ICONS import removal below) ----
        cats_row = QHBoxLayout()
        cats_row.setSpacing(_ROW_CARD_SPACING)
        self.cat_boxes: dict = {}
        for cat in CATEGORIES:
            box_cat, cat_inner = self._build_card("")
            btn = QPushButton(CATEGORY_LABELS[cat])
            btn.clicked.connect(lambda checked=False, cc=cat: self.switch_library_category(cc))
            cat_inner.addWidget(btn)
            cats_row.addWidget(box_cat)
            self.cat_buttons[cat] = btn
            self.cat_boxes[cat] = box_cat
        layout.addLayout(cats_row)

        search_row = QHBoxLayout()
        self.ent_search = QLineEdit()
        self.ent_search.setPlaceholderText("Search…")
        self.ent_search.textChanged.connect(lambda _text: self.refresh_library_list())
        search_row.addWidget(self.ent_search, 1)
        btn_search_clear = QPushButton("✕")
        # The default QPushButton QSS rule (padding: 6px 14px + a 1px
        # border on each side) needs ~30px of chrome alone — wider than a
        # 28px fixed-width button, so the glyph had no room left and
        # rendered as an empty box. "ghost" has much tighter padding
        # (4px 8px), so a small fixed width actually leaves room to show
        # the "✕".
        btn_search_clear.setObjectName("ghost")
        btn_search_clear.setFixedWidth(32)
        btn_search_clear.clicked.connect(lambda: self.ent_search.setText(""))
        search_row.addWidget(btn_search_clear)
        layout.addLayout(search_row)

        # ---- Folder toolbar (Session 6), one card per button (Session 29) ----
        folder_toolbar = QHBoxLayout()
        folder_toolbar.setSpacing(_ROW_CARD_SPACING)
        box_new_folder, new_folder_inner = self._build_card("")
        btn_new_folder = QPushButton("New folder")
        btn_new_folder.clicked.connect(lambda: self._prompt_new_library_folder())
        new_folder_inner.addWidget(btn_new_folder)
        folder_toolbar.addWidget(box_new_folder)
        box_expand_all, expand_all_inner = self._build_card("")
        btn_expand_all = QPushButton("Expand all")
        btn_expand_all.clicked.connect(self.expand_all_library_folders)
        expand_all_inner.addWidget(btn_expand_all)
        folder_toolbar.addWidget(box_expand_all)
        box_collapse_all, collapse_all_inner = self._build_card("")
        btn_collapse_all = QPushButton("Collapse all")
        btn_collapse_all.clicked.connect(self.collapse_all_library_folders)
        collapse_all_inner.addWidget(btn_collapse_all)
        folder_toolbar.addWidget(box_collapse_all)
        layout.addLayout(folder_toolbar)

        self.tree_library = _LibraryTreeWidget()
        self.tree_library.setHeaderHidden(True)
        self.tree_library.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree_library.on_entries_dropped = self._move_selected_entries_to
        self.tree_library.itemSelectionChanged.connect(self._on_tree_selection_changed)
        self.tree_library.itemExpanded.connect(self._on_tree_item_expanded)
        self.tree_library.itemCollapsed.connect(self._on_tree_item_collapsed)
        # Session 48.7 fix: companion to refresh_library_list's lazy
        # tooltip loading above -- `itemEntered` only fires with mouse
        # tracking on, and is what actually reads a single entry's .txt
        # file on-demand the moment the mouse enters that row, instead
        # of `refresh_library_list` reading every entry's file whether
        # anyone hovers it or not.
        self.tree_library.setMouseTracking(True)
        self.tree_library.itemEntered.connect(self._on_library_item_entered)
        self.tree_library.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree_library.customContextMenuRequested.connect(self._on_tree_context_menu)
        layout.addWidget(self.tree_library, 1)

        count_row = QHBoxLayout()
        count_row.setSpacing(_ROW_CARD_SPACING)
        box_count, count_inner = self._build_card("")
        self.lbl_lib_count = QLabel("0 entries")
        count_inner.addWidget(self.lbl_lib_count)
        count_row.addWidget(box_count)
        count_row.addStretch(1)
        # ---- Session 45.1 Part A: the two Active/Inactive bulk buttons
        # moved onto this row (were their own row underneath, per the
        # screenshot) — dual-mode (whole-library when nothing's
        # selected, selection-scoped and re-labeled otherwise; see
        # _update_active_bulk_buttons). Same widgets/wiring as Session
        # 45, purely a layout change. ----
        box_inactive_all, inactive_all_inner = self._build_card("")
        self.btn_inactive_all = QPushButton("Inactive All")
        self.btn_inactive_all.clicked.connect(lambda: self._bulk_set_active(False))
        inactive_all_inner.addWidget(self.btn_inactive_all)
        count_row.addWidget(box_inactive_all)
        box_active_all, active_all_inner = self._build_card("")
        self.btn_active_all = QPushButton("Active All")
        self.btn_active_all.clicked.connect(lambda: self._bulk_set_active(True))
        active_all_inner.addWidget(self.btn_active_all)
        count_row.addWidget(box_active_all)
        box_check_deps, check_deps_inner = self._build_card("")
        self.btn_check_lora_deps = QPushButton("Check LoRA dependencies")
        # Design Code #4: disabled, not hidden, while disconnected — this
        # button already followed that pattern pre-Session-28 (it was
        # never setVisible-gated), unchanged here.
        self.btn_check_lora_deps.setEnabled(self.comfy_connected)
        self.btn_check_lora_deps.clicked.connect(self.check_library_lora_dependencies)
        check_deps_inner.addWidget(self.btn_check_lora_deps)
        count_row.addWidget(box_check_deps)
        layout.addLayout(count_row)

        return left

    def _build_right_panel(self) -> QWidget:
        # Session 28 (Design Code #2): no "Entry Editor" wrapper title —
        # a form with a Name field, Tags box, and Save/Delete buttons
        # already reads as an editor; the label restated the obvious.
        # Plain container instead of a titled QGroupBox.
        panel = QWidget()
        self.right_panel = panel
        layout = QVBoxLayout(panel)
        # Session 29: left panel's outer layout is explicitly zero-margin
        # (see _build_left_panel); this one wasn't, so it fell back to
        # Qt's default ~9px top margin and rendered visibly lower than
        # the left column's top edge. Match it so both panels' top edges
        # align.
        layout.setContentsMargins(0, 0, 0, 0)

        # ---- Canon binding block (outfits only), card treatment ----
        self.frame_canon_binding, canon_layout = self._build_card("")
        self.chk_canon = QCheckBox("Is this a character's canon outfit?")
        self.chk_canon.toggled.connect(self.toggle_canon_char_selector)
        canon_layout.addWidget(self.chk_canon)
        self.combo_canon_char = AutocompleteCombobox()
        self.combo_canon_char.setEnabled(False)
        canon_layout.addWidget(self.combo_canon_char)
        layout.addWidget(self.frame_canon_binding)

        # ---- Name / Tags, card treatment ----
        box_fields, fields_inner = self._build_card("")
        fields_inner.addWidget(QLabel("Name:"))
        self.ent_lib_name = QLineEdit()
        fields_inner.addWidget(self.ent_lib_name)

        fields_inner.addWidget(QLabel("Tags / content:"))
        self.txt_lib_tags = QPlainTextEdit()
        self.txt_lib_tags.setFixedHeight(64)  # ~3 lines — Session 29.2 halved
        # the old 6-line/120px height; the box still scrolls internally
        # and the whole right panel is itself resizable, so long content
        # isn't actually harder to reach, just less permanently-empty
        # by default.
        fields_inner.addWidget(self.txt_lib_tags)
        layout.addWidget(box_fields)

        # ---- Image preview / drag'n'drop zone (Design Code #5: no size
        # slider — the preview fills whatever space this card gives it,
        # same as Builder's result column since Session 17.5) ----
        box_image, image_inner = self._build_card("")
        # Session 29.2: ~65% of _build_card's default (10, 8, 10, 10)
        # margin — a point override, not a change to _build_card itself,
        # since the default margin is still right for every other card.
        image_inner.setContentsMargins(7, 5, 7, 7)
        self.image_drop_zone = ImageDropZone(self.colors)
        self.image_drop_zone.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.image_drop_zone.file_chosen.connect(self.handle_image_drop)
        self.image_drop_zone.unsupported_file_dropped.connect(self._on_unsupported_image_dropped)
        image_inner.addWidget(self.image_drop_zone)
        layout.addWidget(box_image, 1)

        # ---- Source URL (Task 6), card treatment ----
        self.frame_lib_source, self.layout_lib_source = self._build_card("")
        # Session 29.2: same ~65%-of-default point override as the image
        # card above — the tall dead band under the Source row was this
        # card's own oversized default padding, not extra content.
        self.frame_lib_source.layout().setContentsMargins(7, 5, 7, 7)
        layout.addWidget(self.frame_lib_source)
        self._render_lib_source_row()

        # ---- LoRA binding (Task 7.1) — Design Code #4: stays visible,
        # only Assign/Clear disable while disconnected (see
        # _render_lib_lora_row / _refresh_lib_lora_visibility below).
        # Session 29: label / Assign / Clear are three separate cards,
        # so this is a plain row layout, not another card wrapping them.
        # Session 30.1: the strength spin box lives in this same row too
        # (right of Clear, no label — the number is self-explanatory and
        # a second labeled card here was pure vertical cost against the
        # image preview, which is the panel's actual scarce resource). ----
        self.layout_lib_lora = QHBoxLayout()
        layout.addLayout(self.layout_lib_lora)

        self._render_lib_lora_row()
        self._refresh_lib_lora_visibility(self.comfy_connected)

        # ---- Action row, card treatment ----
        box_actions, actions_inner = self._build_card("")
        btn_row = QHBoxLayout()
        self.btn_lib_save = QPushButton("Save")
        self.btn_lib_save.setObjectName("accent")
        self.btn_lib_save.clicked.connect(self.save_to_library)
        self.btn_lib_new = QPushButton("New entry")
        self.btn_lib_new.clicked.connect(lambda: self.start_new_library_entry())
        self.btn_lib_duplicate = QPushButton("Duplicate")
        self.btn_lib_duplicate.clicked.connect(self.duplicate_library_entry)
        self.btn_lib_delete = QPushButton("Delete")
        self.btn_lib_delete.setObjectName("danger")
        self.btn_lib_delete.clicked.connect(self.delete_library_entry)
        for b in (self.btn_lib_save, self.btn_lib_new, self.btn_lib_duplicate, self.btn_lib_delete):
            btn_row.addWidget(b)
        actions_inner.addLayout(btn_row)

        self.lbl_lib_status = QLabel("")
        actions_inner.addWidget(self.lbl_lib_status)
        layout.addWidget(box_actions)

        return panel

    # ------------------------------------------------------------------
    # Category switching
    # ------------------------------------------------------------------
    def _highlight_category_button(self, active_cat: str):
        for cat, btn in self.cat_buttons.items():
            btn.setObjectName("accent" if cat == active_cat else "")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def switch_library_category(self, cat: str):
        self._apply_library_category(cat)
        self.start_new_library_entry(keep_category=True)

    def set_pipeline_mode_filter(self, pipeline_mode: str):
        """Session 46.1 scope item 5, updated by 46.2c and its revision: shows only
        the Library categories that actually make sense for the current
        pipeline mode -- t2i gets styles/characters/outfits/scenarios/
        tools, i2i gets only Image Actions, i2v gets only Video Actions.
        46.2c revision removed the old "t2i shows literally every category"
        special case: once Image Actions/Video Actions existed, that
        default started leaking both of the *other* modes' Actions
        categories into t2i's view too, which is exactly the kind of
        mismatch this filter exists to prevent. Called by BuilderTab
        whenever its mode switch changes; safe to call before the
        category bar exists (BuilderTab may construct before
        LibraryTab in some orderings) since it's a plain attribute
        check, not required at construction time."""
        if not hasattr(self, "cat_boxes"):
            return
        visible = PIPELINE_MODE_VISIBLE_CATEGORIES.get(pipeline_mode, ())
        for cat, box in self.cat_boxes.items():
            box.setVisible(cat in visible)
        # If the category currently being edited just got hidden,
        # fall back to the first still-visible one so the editor never
        # sits on an invisible category with no way back to it.
        if visible and self.current_category not in visible:
            self.switch_library_category(visible[0])

    def _apply_library_category(self, cat: str):
        self.current_category = cat
        # Session 28 (Design Code #2): the old "Editing: Character"
        # banner is gone — which category is active is already visible
        # from the highlighted category button above, so this restated
        # the obvious. `self.lbl_lib_status`'s "Editing existing entry:
        # …" line (see start_new_library_entry/on_library_select) is the
        # one label kept, since unsaved-vs-existing state isn't shown
        # anywhere else.
        if cat == "outfits":
            self.frame_canon_binding.setVisible(True)
            self.chk_canon.setEnabled(True)
            self.combo_canon_char.set_items(get_file_list(self.data_dir, "characters"))
        else:
            self.chk_canon.blockSignals(True)
            self.chk_canon.setChecked(False)
            self.chk_canon.blockSignals(False)
            self.frame_canon_binding.setVisible(False)
            self.chk_canon.setEnabled(False)
            self.combo_canon_char.setEnabled(False)
        self._highlight_category_button(cat)
        self.refresh_library_list()

    def toggle_canon_char_selector(self, checked: bool):
        self.combo_canon_char.setEnabled(checked)
        self.ent_lib_name.setEnabled(not checked)

    def set_colors(self, colors: dict):
        """Called by MainWindow on theme toggle — the image zone paints
        itself manually (not via QSS), so it needs its color dict
        refreshed explicitly."""
        self.colors = colors
        self.image_drop_zone.set_colors(colors)

    def handle_image_drop(self, source_path: str):
        """Callback wired to the ImageDropZone: a file was picked or
        dropped for the entry currently open in the editor. Uses the name
        field's current text when available (covers both new, unsaved
        entries and renames-in-progress); falls back to the already
        selected/loaded entry's name.

        Session 48.4: branches to _handle_video_drop for anything with
        a VIDEO_EXTENSIONS extension — this is the fix for the crash
        described in additionalfeatures.md SESSION 48.4 (dropping a
        .mp4 used to fall straight into process_and_store_image, whose
        unconditional PIL.Image.open() choked on it)."""
        cat = self.current_category
        if cat == "outfits" and self.chk_canon.isChecked():
            if self.editing_canon_owner:
                char_name, num = self.editing_canon_owner
                name = f"{char_name}_Canon_{num}"
            else:
                themed_message_box.information(self, "Save first",
                                         "Save this canon outfit once before attaching an image.")
                return
        else:
            name = self.ent_lib_name.text().strip()
            if not name:
                name = self.selected_file
            if not name:
                themed_message_box.information(self, "Name required",
                                         "Enter a name for this entry before attaching an image.")
                return
            name = sanitize_filename(name)

        if _is_video_file(source_path):
            self._handle_video_drop(cat, name, source_path)
            return

        try:
            saved_path = process_and_store_image(self.data_dir, source_path, cat, name)
        except ImageProcessingError as exc:
            themed_message_box.critical(self, "Error", str(exc))
            return

        # A fresh image attachment replaces any video this entry might
        # have had — one attachment slot per entry (see additionalfeatures.md
        # SESSION 48.4's storage model), so clear video_ext/delete the
        # old video file the same way _handle_video_drop below clears a
        # stale poster-vs-video mismatch in the other direction.
        self._clear_video_attachment(cat, name, refresh_meta=True)

        self.image_drop_zone.show_image_path(saved_path)
        self.lbl_lib_status.setText(f"✓ Image attached to {name}")

    def _handle_video_drop(self, cat: str, name: str, source_path: str):
        """Session 48.4: real video attachment — copies the video into
        the category folder (process_and_store_video), then kicks off
        an async poster-frame grab (PosterFrameGrabber, same class
        Gallery's grid already uses for video thumbnails) to produce
        the entry's {name}.jpg exactly as before, so every other
        display path (quick-preview, export, duplicate) keeps working
        completely unchanged per the additionalfeatures.md scope item 3."""
        try:
            dest_path, ext = process_and_store_video(self.data_dir, source_path, cat, name)
        except ImageProcessingError as exc:
            themed_message_box.critical(self, "Error", str(exc))
            return

        meta = load_library_meta(self.data_dir, cat, name)
        save_library_meta(self.data_dir, cat, name, source_url=meta["source_url"],
                           lora=meta["lora"], lora_strength=meta["lora_strength"],
                           force_first=meta["force_first"], video_ext=ext)

        # Show the video immediately via the same embedded player pair
        # (show_video_path/show_image_path) 46.3/46.4b already
        # established on this widget class — no need to wait for the
        # poster grab to finish before the user sees something.
        self.image_drop_zone.show_video_path(dest_path, os.path.basename(dest_path))
        self.lbl_lib_status.setText(f"✓ Video attached to {name}")

        grabber = PosterFrameGrabber(dest_path, parent=self)
        grabber.frame_grabbed.connect(
            lambda path, image, cat=cat, name=name: self._on_video_poster_ready(cat, name, image))
        self._pending_poster_grabber = grabber

    def _on_video_poster_ready(self, cat: str, name: str, image):
        """Companion to `_handle_video_drop` — writes the grabbed frame
        out to the entry's normal {name}.jpg poster path via the same
        library_image_path() every image entry already uses. A null
        image (playback unavailable, grab timed out) is expected and
        not an error, same graceful fail-closed behavior Gallery's own
        `_on_poster_frame_ready` has — the video itself still plays
        fine even with no poster on disk, this only affects places that
        read the poster without playing the video (e.g. a future
        quick-preview thumbnail)."""
        self._pending_poster_grabber = None
        if image is None or image.isNull():
            return
        from PyQt6.QtGui import QPixmap
        pixmap = QPixmap.fromImage(image)
        if pixmap.isNull():
            return
        dest = library_image_path(self.data_dir, cat, name)
        try:
            cat_dir = os.path.join(self.data_dir, cat)
            if not os.path.exists(cat_dir):
                os.makedirs(cat_dir)
            pixmap.save(dest, "JPG", quality=90)
        except Exception:
            pass

    def _clear_video_attachment(self, cat: str, name: str, refresh_meta: bool = False):
        """Detaches whatever video this entry had, if any -- removes
        the on-disk video file and clears video_ext from the meta
        sidecar. Used when a plain image gets (re-)attached to an
        entry that previously had a video, so the two attachment kinds
        never both linger for the same name."""
        if not name:
            return
        meta = load_library_meta(self.data_dir, cat, name)
        if not meta.get("video_ext"):
            return
        delete_library_video(self.data_dir, cat, name)
        if refresh_meta:
            save_library_meta(self.data_dir, cat, name, source_url=meta["source_url"],
                               lora=meta["lora"], lora_strength=meta["lora_strength"],
                               force_first=meta["force_first"], video_ext=None)

    def _on_unsupported_image_dropped(self, path: str):
        themed_message_box.warning(self, "Unsupported file",
                             f'"{os.path.basename(path)}" is not a supported image or video type.')

    # ------------------------------------------------------------------
    # Source URL (Task 6)
    # ------------------------------------------------------------------
    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
            else:
                child_layout = item.layout()
                if child_layout is not None:
                    self._clear_layout(child_layout)

    def _render_lib_source_row(self):
        self._clear_layout(self.layout_lib_source)

        if self.lib_source_editing:
            row = QHBoxLayout()
            row.addWidget(QLabel("Source:"))
            self.ent_lib_source_url = QLineEdit()
            if self.lib_source_url:
                self.ent_lib_source_url.setText(self.lib_source_url)
            self.ent_lib_source_url.returnPressed.connect(self._save_lib_source_url)
            row.addWidget(self.ent_lib_source_url, 1)
            btn_save = QPushButton("Save")
            btn_save.clicked.connect(self._save_lib_source_url)
            row.addWidget(btn_save)
            btn_cancel = QPushButton("Cancel")
            btn_cancel.clicked.connect(self._cancel_lib_source_edit)
            row.addWidget(btn_cancel)
            self.layout_lib_source.addLayout(row)
            self.lbl_lib_source_error = QLabel("")
            self.lbl_lib_source_error.setStyleSheet(f"color: {self.colors['danger']};")
            self.layout_lib_source.addWidget(self.lbl_lib_source_error)
            self.ent_lib_source_url.setFocus()
        elif self.lib_source_url:
            row = QHBoxLayout()
            lbl_source = QLabel("Source:")
            row.addWidget(lbl_source, 0, Qt.AlignmentFlag.AlignVCenter)
            link = QLabel(f'<a href="{self.lib_source_url}">{self.lib_source_url}</a>')
            link.setOpenExternalLinks(True)
            link.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
            # Session 29: dropped the 70-char ellipsis + hover-tooltip
            # stopgap now that Source lives in its own properly-sized
            # card (Session 28) — the full URL just wraps across lines
            # instead of being truncated with a tooltip standing in for
            # the real text.
            link.setWordWrap(True)
            row.addWidget(link, 1, Qt.AlignmentFlag.AlignVCenter)
            btn_edit = QPushButton("Edit")
            btn_edit.clicked.connect(self._start_lib_source_edit)
            row.addWidget(btn_edit, 0, Qt.AlignmentFlag.AlignVCenter)
            self.layout_lib_source.addLayout(row)
        else:
            row = QHBoxLayout()
            btn_add = QPushButton("Add source link")
            btn_add.clicked.connect(self._start_lib_source_edit)
            row.addWidget(btn_add)
            row.addStretch(1)
            self.layout_lib_source.addLayout(row)

    def _start_lib_source_edit(self):
        self.lib_source_editing = True
        self._render_lib_source_row()

    def _cancel_lib_source_edit(self):
        self.lib_source_editing = False
        self._render_lib_source_row()

    def _save_lib_source_url(self):
        url = self.ent_lib_source_url.text().strip()
        if url and not (url.startswith("http://") or url.startswith("https://")):
            self.lbl_lib_source_error.setText("URL must start with http:// or https://")
            return
        self.lib_source_url = url or None
        self.lib_source_editing = False
        self._render_lib_source_row()
        # Persisted immediately (not only on the main Save button) so the
        # link survives even if the user never touches the tags/name field
        # again this session — matches how the image drop zone behaves.
        self._persist_current_lib_meta()

    # ------------------------------------------------------------------
    # LoRA binding (Task 7.1)
    # ------------------------------------------------------------------
    def _refresh_lib_lora_visibility(self, connected: bool):
        """LoRA binding row is only fully *usable* once ComfyUI is
        connected — self._available_loras (the Assign source) is
        otherwise empty/stale. Session 28 (Design Code #4): the row and
        the Check-LoRA-dependencies button stay visible either way and
        just disable — same pattern Builder's own action cluster
        adopted in Session 22. Called by the ComfyUI wiring whenever the
        connection state changes; safe to call before the row even
        exists yet."""
        self.comfy_connected = connected
        if not hasattr(self, "layout_lib_lora"):
            return
        if hasattr(self, "btn_lib_lora_assign"):
            self.btn_lib_lora_assign.setEnabled(connected)
        if hasattr(self, "btn_lib_lora_clear"):
            self.btn_lib_lora_clear.setEnabled(connected)
        if hasattr(self, "btn_check_lora_deps"):
            self.btn_check_lora_deps.setEnabled(connected)

    def _update_available_loras(self, loras: list):
        """Public hook for Session 9/11's ComfyUI wiring: refreshes the
        list of LoRA paths the Assign dialog (and, in Session 7, the
        dependency scanner) draws from."""
        self._available_loras = list(loras)

    def _render_lib_lora_row(self):
        self._clear_layout(self.layout_lib_lora)
        self.layout_lib_lora.setSpacing(_ROW_CARD_SPACING)
        display = os.path.basename(self.lib_entry_lora) if self.lib_entry_lora else "None"
        box_label, label_inner = self._build_card("")
        lbl_lora = QLabel(f"LoRA: {display}")
        lbl_lora.setWordWrap(True)
        label_inner.addWidget(lbl_lora)
        self.layout_lib_lora.addWidget(box_label)
        box_assign, assign_inner = self._build_card("")
        self.btn_lib_lora_assign = QPushButton("Assign")
        self.btn_lib_lora_assign.setEnabled(self.comfy_connected)
        self.btn_lib_lora_assign.clicked.connect(self._assign_lib_lora)
        assign_inner.addWidget(self.btn_lib_lora_assign)
        self.layout_lib_lora.addWidget(box_assign)
        box_clear, clear_inner = self._build_card("")
        self.btn_lib_lora_clear = QPushButton("Clear")
        self.btn_lib_lora_clear.setEnabled(self.comfy_connected)
        self.btn_lib_lora_clear.clicked.connect(self._clear_lib_lora)
        clear_inner.addWidget(self.btn_lib_lora_clear)
        self.layout_lib_lora.addWidget(box_clear)
        # Session 30.1: strength sits right of Clear, same row, no label
        # card of its own — per your note, a bare number here reads
        # fine on its own and a labeled second row was pure vertical
        # cost against the image preview below.
        box_strength, strength_inner = self._build_card("")
        self.spin_lib_lora_strength = NoScrollDoubleSpinBox()
        self.spin_lib_lora_strength.setRange(LORA_STRENGTH_MIN, LORA_STRENGTH_MAX)
        self.spin_lib_lora_strength.setSingleStep(0.05)
        self.spin_lib_lora_strength.setDecimals(2)
        self.spin_lib_lora_strength.setValue(float(self.lib_entry_lora_strength))
        self.spin_lib_lora_strength.setMinimumWidth(90)
        self.spin_lib_lora_strength.valueChanged.connect(self._on_lib_lora_strength_changed)
        strength_inner.addWidget(self.spin_lib_lora_strength)
        self.layout_lib_lora.addWidget(box_strength)
        self.layout_lib_lora.addStretch(1)

    def _on_lib_lora_strength_changed(self, value: float):
        self.lib_entry_lora_strength = float(value)
        self._persist_current_lib_meta()

    def _assign_lib_lora(self):
        """Shows a small popup list of self._available_loras (same source
        as the LoRA Manager) and binds the chosen one to the entry."""
        if not self._available_loras:
            themed_message_box.information(
                self, "LoRA",
                "No LoRAs available yet — make sure ComfyUI is connected "
                "and the LoRA list has finished loading.")
            return
        chosen = LoraAssignDialog.get_selected_lora(self, self._available_loras)
        if chosen is None:
            return
        self.lib_entry_lora = chosen
        self._render_lib_lora_row()
        self._persist_current_lib_meta()

    def _clear_lib_lora(self):
        self.lib_entry_lora = None
        self._render_lib_lora_row()
        self._persist_current_lib_meta()

    def _persist_current_lib_meta(self):
        """Writes the metadata sidecar for the entry currently open in the
        editor, if it has actually been saved to disk yet (self.selected_file
        is None for a brand-new, not-yet-saved entry — its source_url/lora
        choices are picked up later by save_to_library() instead)."""
        if not self.selected_file:
            return
        cat = self.current_category
        name = (f"{self.editing_canon_owner[0]}_Canon_{self.editing_canon_owner[1]}"
                if (cat == "outfits" and self.editing_canon_owner) else self.selected_file)
        # Session 48.4: preserve video_ext -- this method only ever
        # updates source_url/lora fields, so it must not clobber a
        # video attachment that's not one of its concerns.
        existing_video_ext = load_library_meta(self.data_dir, cat, name)["video_ext"]
        save_library_meta(self.data_dir, cat, name, source_url=self.lib_source_url,
                           lora=self.lib_entry_lora, lora_strength=self.lib_entry_lora_strength,
                           force_first=False, video_ext=existing_video_ext)

    # ------------------------------------------------------------------
    # LoRA dependency scan (Session 7)
    # ------------------------------------------------------------------
    def check_library_lora_dependencies(self):
        """'🔍 Check LoRA dependencies' — scans every entry in every
        Library category for a bound LoRA and reports any that ComfyUI
        doesn't currently have, grouped by which entry(ies) reference
        each missing file. Requires a live ComfyUI connection (the
        button is disabled otherwise via `_refresh_lib_lora_visibility`)
        since "what LoRAs does ComfyUI actually have" is the whole point
        of the comparison."""
        if not self.comfy_connected:
            themed_message_box.information(
                self, "Check LoRA dependencies",
                "Connect to ComfyUI first — this check compares your library "
                "against ComfyUI's current LoRA list.")
            return
        if not self._available_loras:
            reply = themed_message_box.question(
                self, "Check LoRA dependencies",
                "ComfyUI's LoRA list hasn't loaded yet (or came back empty).\n\n"
                "Run the check anyway? Every bound LoRA will show up as \"missing\" "
                "until the list loads.")
            if reply != QMessageBox.StandardButton.Yes:
                return

        entry_count, missing = scan_library_lora_dependencies(
            self.data_dir, CATEGORIES, self._available_loras)

        self.lora_dep_status = compute_lora_dependency_status(
            self.data_dir, CATEGORIES, self._available_loras)
        self._apply_lora_dependency_colors()

        if not missing:
            themed_message_box.information(
                self, "Check LoRA dependencies",
                f"✓ All LoRAs bound across {entry_count} library entries "
                f"were found in ComfyUI. Nothing missing.")
            return

        lines = [f"{len(missing)} LoRA file(s) referenced by your library were NOT found in "
                 f"ComfyUI's current LoRA list:\n"]
        for lora_path in sorted(missing.keys(), key=natural_sort_key):
            lines.append(f"\n✗ {lora_path}")
            for category, name in missing[lora_path]:
                lines.append(f"    used by: [{CATEGORY_LABELS.get(category, category)}] {name}")
        lines.append(
            "\n\nDouble-check the file is actually present under ComfyUI's models/lora "
            "folder at that exact relative path, then reconnect (or just re-open this "
            "check) to refresh ComfyUI's LoRA list.")
        lines.append(
            "\n\nClick \"🔎 Find candidates\" below to search for files with a matching "
            "name elsewhere in ComfyUI's LoRA list (e.g. if you skipped recreating the "
            "exact folder structure) before manually re-pointing each entry.")

        dlg = LoraDependencyReportDialog(
            "\n".join(lines), missing, self._available_loras,
            self._apply_lora_candidate_and_refresh, parent=self)
        dlg.exec()

    def _apply_lora_candidate_and_refresh(self, old_path, new_path, affected_entries):
        """Callback handed to the dependency-report/candidates dialogs —
        applies the re-point via the backend, then reloads whatever's
        currently open in the editor in case the entry being edited was
        one of the ones just updated (mirrors the original's
        `reload_all_lists()` call after every candidate application)."""
        updated = apply_lora_candidate(self.data_dir, old_path, new_path, affected_entries)
        self.refresh_library_list()
        return updated

    # ------------------------------------------------------------------
    # Library export / import (Session 7)
    # ------------------------------------------------------------------
    def export_library(self):
        """'📦 Export library' — zips the whole data_dir tree (every
        category's .txt/.jpg/.meta.json triplets, _folders.json,
        templates, settings, history) EXCEPT _comfy_previews/, which is
        a disposable session-only cache with no business in a library
        backup or a bundle meant to be shared."""
        default_name = f"promptforge_library_{time.strftime('%Y%m%d_%H%M%S')}.zip"
        path, _filter = QFileDialog.getSaveFileName(
            self, "Export library", default_name, "Zip archive (*.zip)")
        if not path:
            return
        try:
            export_library(self.data_dir, path)
        except LibraryExportImportError as exc:
            themed_message_box.critical(self, "Export library", str(exc))
            return
        themed_message_box.information(self, "Export library", f"Library exported to:\n{path}")

    def import_library(self):
        """'📥 Import library' — merges another exported library zip
        into the current one. Strict skip-on-collision: any entry name
        already present in the destination library is left completely
        untouched, and the incoming one is skipped. A final report lists
        exactly what was imported and what was skipped (and why)."""
        zip_path, _filter = QFileDialog.getOpenFileName(
            self, "Import library", "", "Zip archive (*.zip)")
        if not zip_path:
            return

        tmp_dir = os.path.join(self.data_dir, f"_import_tmp_{uuid.uuid4().hex[:8]}")
        try:
            extract_library_zip(zip_path, tmp_dir)
        except LibraryExportImportError as exc:
            themed_message_box.critical(self, "Import library", str(exc))
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return

        try:
            imported, skipped = merge_imported_library(
                self.data_dir, tmp_dir, CATEGORIES, self.folder_maps, self.folders_file,
                active_map=self.active_map, active_file=self.active_file)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        self.refresh_library_list()
        if imported:
            self.library_changed.emit()

        lines = [f"Imported {len(imported)} entr{'y' if len(imported) == 1 else 'ies'}."]
        if imported:
            lines.append("")
            for category, name in imported:
                lines.append(f"  + [{CATEGORY_LABELS.get(category, category)}] {name}")
        if skipped:
            lines.append("")
            lines.append(f"Skipped {len(skipped)} entr{'y' if len(skipped) == 1 else 'ies'} "
                          f"(already exist in your library — nothing was overwritten):")
            for category, name in skipped:
                lines.append(f"  · [{CATEGORY_LABELS.get(category, category)}] {name}")
        LibraryExportImportDialog.show_report(self, "Library import results", "\n".join(lines))

    # ------------------------------------------------------------------
    # Tree rendering
    # ------------------------------------------------------------------
    def refresh_library_list(self):
        self.tree_library.blockSignals(True)
        self.tree_library.clear()

        cat = self.current_category
        query = self.ent_search.text().strip().lower()
        searching = bool(query)
        cat_map = self.folder_maps.get(cat, {})
        cat_path = os.path.join(self.data_dir, cat)
        files = sorted(glob.glob(os.path.join(cat_path, "*.txt")))

        root_node = {"entries": [], "subfolders": {}}

        def get_node(folder_path):
            if not folder_path:
                return root_node
            node = root_node
            for part in folder_path.split(FOLDER_PATH_SEP):
                node = node["subfolders"].setdefault(part, {"entries": [], "subfolders": {}})
            return node

        for folder_path in list_all_folders(self.folder_maps, self.empty_folders, cat):
            get_node(folder_path)

        count = 0
        matched_folder_paths = set()
        for f in files:
            base = os.path.splitext(os.path.basename(f))[0]
            if cat == "outfits" and is_canon_outfit_name(base):
                continue
            # Session 48.7 fix: content is only actually needed for two
            # things -- the search-query match below, and the hover
            # tooltip preview (`preview_short`, further down). Reading
            # every entry's .txt file synchronously on every single
            # refresh (category switch, folder rename, active-toggle,
            # anything that calls this) was the dominant confirmed cost
            # for a several-hundred-entry category (see
            # additionalfeatures.md SESSION 48.7 -- profiling on a real
            # library, not guessed) -- 589 blocking small-file reads on
            # the GUI thread before a single row can even be drawn.
            # When there's no active search query, nothing downstream
            # needs the content *at refresh time* -- only when someone
            # actually hovers a specific row (`_on_library_item_entered`
            # below reads that one file, on demand, only then). Content
            # is still read eagerly here whenever `searching` is True,
            # since query-matching genuinely does need it for every
            # entry to decide what's even in the list.
            if searching:
                try:
                    with open(f, "r", encoding="utf-8") as fh:
                        content = fh.read().strip()
                except OSError:
                    content = ""
            else:
                content = None
            if query and content is not None and query not in base.lower() and query not in content.lower():
                continue
            folder_path = cat_map.get(base, "")
            node = get_node(folder_path)
            node["entries"].append((base, base, content, f))
            if folder_path:
                parts = folder_path.split(FOLDER_PATH_SEP)
                for depth in range(1, len(parts) + 1):
                    matched_folder_paths.add(FOLDER_PATH_SEP.join(parts[:depth]))
            count += 1

        if cat == "outfits":
            for f in files:
                base = os.path.splitext(os.path.basename(f))[0]
                if not is_canon_outfit_name(base):
                    continue
                if searching:
                    try:
                        with open(f, "r", encoding="utf-8") as fh:
                            content = fh.read().strip()
                    except OSError:
                        content = ""
                else:
                    content = None
                if query and content is not None and query not in base.lower() and query not in content.lower():
                    continue
                char_name, num = base.split("_Canon_")
                display_name = f"{char_name} — Canon {num}"
                node = get_node(CANONICAL_OUTFITS_FOLDER)
                node["entries"].append((base, display_name, content, f))
                matched_folder_paths.add(CANONICAL_OUTFITS_FOLDER)
                count += 1

        cat_empty_folders = self.empty_folders.get(cat, set())
        cat_expanded = self.expanded_folders.get(cat, set())

        def insert_node(parent_item, parent_path, node):
            # Session 45: local (parent-container-scoped) sort — active
            # siblings first (alphabetical), inactive siblings sunk to
            # the bottom (also alphabetical among themselves). Uses
            # each folder's OWN inactive flag only, never an
            # ancestor-inherited one — an inactive folder moves as one
            # unit among its own siblings; its children's relative
            # order among each other is untouched by that (see the
            # Session 45 spec's two confirmed scenarios).
            cat_inactive_folders = self.active_map.get(cat, {}).get("folders", set())
            for folder_name in sorted(
                node["subfolders"].keys(),
                key=lambda fn: (
                    (f"{parent_path}{FOLDER_PATH_SEP}{fn}" if parent_path else fn) in cat_inactive_folders,
                    natural_sort_key(fn),
                ),
            ):
                folder_path = f"{parent_path}{FOLDER_PATH_SEP}{folder_name}" if parent_path else folder_name
                child = node["subfolders"][folder_name]
                if searching and folder_path not in matched_folder_paths and folder_path not in cat_empty_folders:
                    continue
                item = QTreeWidgetItem([f"📁 {folder_name}"])
                item.setData(0, Qt.ItemDataRole.UserRole, {"kind": _KIND_FOLDER, "path": folder_path})
                # Folders accept drops (entries dragged onto them) but
                # are never themselves drag sources — nothing in this
                # plan supports reparenting a folder by dragging it.
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                              | Qt.ItemFlag.ItemIsDropEnabled)
                if not is_folder_active(self.active_map, cat, folder_path):
                    color = qcolor_from_token(self.colors["fg_dim"])
                    color.setAlpha(140)
                    item.setForeground(0, color)
                if parent_item is None:
                    self.tree_library.addTopLevelItem(item)
                else:
                    parent_item.addChild(item)
                # While searching, a branch containing a match is forced
                # open so the match is visible; otherwise this folder's
                # manually-tracked expand state (collapsed by default,
                # same as the original's self._expanded_folders starting
                # empty every app restart) wins.
                should_open = folder_path in matched_folder_paths if searching else folder_path in cat_expanded
                item.setExpanded(should_open)
                insert_node(item, folder_path, child)
            cat_inactive_entries = self.active_map.get(cat, {}).get("entries", set())
            for base, display_name, content, path in sorted(
                node["entries"],
                key=lambda e: (e[0] in cat_inactive_entries, natural_sort_key(e[1])),
            ):
                item = QTreeWidgetItem([display_name])
                item.setData(0, Qt.ItemDataRole.UserRole, {"kind": _KIND_ENTRY, "base": base, "path": path})
                # Entries are drag sources (to be dropped onto a folder)
                # but never drop targets themselves — there's no manual
                # ordering inside a folder, only alphabetical.
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                              | Qt.ItemFlag.ItemIsDragEnabled)
                if not is_entry_active(self.active_map, self.folder_maps, cat, base):
                    color = qcolor_from_token(self.colors["fg_dim"])
                    color.setAlpha(140)
                    item.setForeground(0, color)
                # No separate "Tags preview" column (per the migration
                # plan's own Session 4 spec: "tags preview can be a
                # tooltip rather than a second column") — a hover here
                # shows the same preview text the original's tree column
                # displayed, just on hover instead of taking up width.
                #
                # Session 48.7 fix: `content` is only already-loaded
                # here when this refresh was a search (see above) — the
                # common case (plain category switch) leaves it `None`
                # on purpose, and the tooltip is populated lazily,
                # on-demand, the moment the mouse actually enters this
                # specific row (`_on_library_item_entered`), instead of
                # every one of a few hundred rows paying a synchronous
                # file-read cost nobody may ever hover over at all.
                if content is not None:
                    preview = content.replace("\n", " ")
                    preview_short = (preview[:200] + "…") if len(preview) > 200 else preview
                    if preview_short:
                        item.setToolTip(0, preview_short)
                if parent_item is None:
                    self.tree_library.addTopLevelItem(item)
                else:
                    parent_item.addChild(item)

        insert_node(None, "", root_node)
        self.tree_library.blockSignals(False)
        self.lbl_lib_count.setText(f"{count} {'entry' if count == 1 else 'entries'}")
        self._apply_lora_dependency_colors()
        self._update_active_bulk_buttons()

    def _apply_lora_dependency_colors(self):
        """Session 31: paints `self.lora_dep_status` onto whatever's
        currently in the tree. A no-op (leaves default row colors)
        until "Check LoRA dependencies" has actually been clicked, or
        after `clear_lora_dependency_colors()` ran on navigating away —
        `lora_dep_status` is empty in both cases. Safe to call after
        every tree rebuild since it only touches entry rows that have a
        status; folders and unbound entries are untouched."""
        if not self.lora_dep_status:
            return
        color_for_status = {
            "ok": QColor(self.colors["success"]),
            "missing": QColor(self.colors["warn"]),
            "conflict": QColor(self.colors["danger"]),
        }
        cat = self.current_category

        def walk(item):
            data = item.data(0, Qt.ItemDataRole.UserRole) or {}
            if data.get("kind") == _KIND_ENTRY:
                status = self.lora_dep_status.get((cat, data.get("base")))
                if status in color_for_status:
                    item.setForeground(0, color_for_status[status])
            for i in range(item.childCount()):
                walk(item.child(i))

        for i in range(self.tree_library.topLevelItemCount()):
            walk(self.tree_library.topLevelItem(i))

    def clear_lora_dependency_colors(self):
        """Called by MainWindow when navigating away from the Library
        page (per the plan: coloring persists only while Library stays
        the active page, and a return visit needs a fresh "Check LoRA
        dependencies" click). Discards the cached status outright rather
        than just hiding it — cheapest option, and the library could
        easily have changed while the person was on another page, so
        re-running from scratch on the next click is the correct
        behavior anyway, not just the simplest one."""
        if not self.lora_dep_status:
            return
        self.lora_dep_status = {}
        self.refresh_library_list()

    def _find_entry_item(self, base: str):
        """Recursively searches the tree for the entry item with this
        base name. Used to re-select an entry after save/duplicate."""
        def walk(item):
            for i in range(item.childCount()):
                child = item.child(i)
                data = child.data(0, Qt.ItemDataRole.UserRole) or {}
                if data.get("kind") == _KIND_ENTRY and data.get("base") == base:
                    return child
                found = walk(child)
                if found:
                    return found
            return None

        root = self.tree_library.invisibleRootItem()
        return walk(root)

    def _reveal_tree_item(self, item):
        """Expands every ancestor folder so `item` is actually visible
        before scrolling to it. The original's ttk Treeview auto-opens
        closed ancestors for free as part of `tree.see()`; Qt's
        QTreeWidget does not, so a save/duplicate that lands an entry
        inside a currently-collapsed folder needs this explicit walk-up
        or the entry would be selected but invisible."""
        parent = item.parent()
        while parent is not None:
            parent.setExpanded(True)
            parent = parent.parent()

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------
    def _on_tree_selection_changed(self):
        """Driven by itemSelectionChanged rather than currentItemChanged
        — the tree is now ExtendedSelection (Session 6, needed for
        multi-select "Move to..." / drag), and the original distinguishes
        a single-entry selection (load it into the editor) from a
        multi-entry selection (show a status count, leave the editor on
        whatever was last opened rather than guessing which one to show)
        via exactly this kind of "how many rows, what kind" check on
        selection-changed — see on_library_select's own docstring in the
        original for the same reasoning."""
        self._update_active_bulk_buttons()
        entry_items = [
            item for item in self.tree_library.selectedItems()
            if (item.data(0, Qt.ItemDataRole.UserRole) or {}).get("kind") == _KIND_ENTRY
        ]
        if not entry_items:
            return  # nothing selected, or only folder rows — both no-ops
        if len(entry_items) > 1:
            self.lbl_lib_status.setText(f"{len(entry_items)} entries selected")
            return
        base = entry_items[0].data(0, Qt.ItemDataRole.UserRole)["base"]
        self.on_library_select(base)

    # ------------------------------------------------------------------
    # Active/Inactive entries & folders (Session 45)
    # ------------------------------------------------------------------
    def _selected_entries_and_folders(self):
        """Returns (entry_base_names, folder_paths) currently selected
        in the tree, each a plain list. Used by both the bulk buttons
        (dual-mode: whole-library vs. selection-scoped) and their
        button-label refresh."""
        names, folders = [], []
        for item in self.tree_library.selectedItems():
            data = item.data(0, Qt.ItemDataRole.UserRole) or {}
            if data.get("kind") == _KIND_ENTRY:
                names.append(data["base"])
            elif data.get("kind") == _KIND_FOLDER:
                folders.append(data["path"])
        return names, folders

    def _update_active_bulk_buttons(self):
        """Keeps "Inactive All"/"Active All" re-labeled to
        "Set N Inactive"/"Set N Active" while something's selected, and
        back to the whole-library wording otherwise — per the Session
        45 spec, no separate count label is needed beyond this."""
        names, folders = self._selected_entries_and_folders()
        n = len(names) + len(folders)
        if n:
            self.btn_inactive_all.setText(f"Set {n} Inactive")
            self.btn_active_all.setText(f"Set {n} Active")
        else:
            self.btn_inactive_all.setText("Inactive All")
            self.btn_active_all.setText("Active All")

    def _set_active_and_refresh(self, entry_names: list, folder_paths: list, active: bool):
        """Shared entry point for the context-menu toggle and the
        selection-scoped bulk buttons — both just narrow to a list of
        entries/folders in the current category and flip them the same
        way."""
        cat = self.current_category
        if entry_names:
            set_entries_active(self.active_map, self.active_file, cat, entry_names, active)
        if folder_paths:
            set_folders_active(self.active_map, self.active_file, cat, folder_paths, active)
        self.refresh_library_list()
        # Session 45.1: an Active/Inactive toggle changes what Builder's
        # combos should be offering, exactly like a save/duplicate/
        # delete/import does — reuse the same Session 30.3 signal so
        # Builder's dropdowns refresh live instead of only on restart.
        self.library_changed.emit()

    def _bulk_set_active(self, active: bool):
        """"Inactive All" / "Active All". With a selection active
        (single entry, a folder, or a multi-select), scoped to exactly
        that selection within the current category — functionally the
        same action the context-menu toggle offers, and that overlap
        is expected, not a bug. With nothing selected, scoped to the
        ENTIRE library across every category — the fast-path "throw
        everything into Inactive/Active" button."""
        names, folders = self._selected_entries_and_folders()
        if names or folders:
            self._set_active_and_refresh(names, folders, active)
            return
        for cat in CATEGORIES:
            if active:
                # "Active All": simplest correct action for a whole
                # category is just to wipe its inactive sets outright.
                self.active_map[cat] = {"entries": set(), "folders": set()}
            else:
                # "Inactive All": mark every entry (including canon
                # outfits, which get_file_list itself excludes) and
                # every known folder in this category inactive.
                cat_path = os.path.join(self.data_dir, cat)
                all_names = [
                    os.path.splitext(os.path.basename(f))[0]
                    for f in glob.glob(os.path.join(cat_path, "*.txt"))
                ]
                all_folders = list_all_folders(self.folder_maps, self.empty_folders, cat)
                cat_active = self.active_map.setdefault(cat, {"entries": set(), "folders": set()})
                cat_active["entries"].update(all_names)
                cat_active["folders"].update(all_folders)
        save_active_map(self.active_file, self.active_map)
        self.refresh_library_list()
        # Session 45.1: whole-library branch doesn't go through
        # _set_active_and_refresh above, so it needs its own emit.
        self.library_changed.emit()

    # ------------------------------------------------------------------
    # Folders — toolbar actions, context menu, drag & drop (Session 6)
    # ------------------------------------------------------------------
    def _on_library_item_entered(self, item):
        """Session 48.7 fix: companion to `refresh_library_list`'s lazy
        tooltip loading — reads exactly one entry's .txt file, only
        when the mouse actually enters that specific row, instead of
        every entry in a several-hundred-item category paying that
        cost on every refresh whether it's ever hovered or not. Reads
        again on every hover rather than caching — a single small text
        file read is cheap, and caching would need its own
        invalidation story (an entry's tags can change via Save while
        its tree item is still alive) that isn't worth building for a
        cost this small.
        """
        if item is None:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole) or {}
        if data.get("kind") != _KIND_ENTRY:
            return
        if item.toolTip(0):
            return  # a search-triggered refresh already populated this one eagerly
        path = data.get("path")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as fh:
                content = fh.read().strip()
        except OSError:
            return
        preview = content.replace("\n", " ")
        preview_short = (preview[:200] + "…") if len(preview) > 200 else preview
        if preview_short:
            item.setToolTip(0, preview_short)

    def _on_tree_item_expanded(self, item):
        self._set_folder_expanded(item, True)

    def _on_tree_item_collapsed(self, item):
        self._set_folder_expanded(item, False)

    def _set_folder_expanded(self, item, expanded: bool):
        data = item.data(0, Qt.ItemDataRole.UserRole) or {}
        if data.get("kind") != _KIND_FOLDER:
            return
        # Don't let a search-driven auto-open pollute the persisted
        # state, matching the original's identical guard in
        # _on_library_folder_toggled.
        if self.ent_search.text().strip():
            return
        cat = self.current_category
        expanded_set = self.expanded_folders.setdefault(cat, set())
        folder_path = data["path"]
        if expanded:
            expanded_set.add(folder_path)
        else:
            expanded_set.discard(folder_path)

    def expand_all_library_folders(self):
        cat = self.current_category
        for folder_path in list_all_folders(self.folder_maps, self.empty_folders, cat):
            self.expanded_folders.setdefault(cat, set()).add(folder_path)
        self.refresh_library_list()

    def collapse_all_library_folders(self):
        cat = self.current_category
        self.expanded_folders[cat] = set()
        self.refresh_library_list()

    def _prompt_new_library_folder(self, parent_path: str = ""):
        """Asks for a folder name and registers it (initially empty)
        under parent_path ("" = top level of the category)."""
        cat = self.current_category
        if is_protected_folder(cat, parent_path):
            themed_message_box.information(self, "New folder",
                                     f'"{CANONICAL_OUTFITS_FOLDER}" is managed automatically.')
            return
        name = LibraryFolderDialog.get_folder_name(self, "New folder")
        if not name:
            return
        full_path = create_new_folder(self.empty_folders, cat, parent_path, name)
        if full_path is None:
            themed_message_box.warning(self, "New folder", 'Folder name can\'t be empty or contain "/".')
            return
        self.expanded_folders.setdefault(cat, set()).add(full_path)
        self.refresh_library_list()

    def _rename_library_folder(self, folder_path: str):
        cat = self.current_category
        old_name = folder_path.split(FOLDER_PATH_SEP)[-1]
        new_name = LibraryFolderDialog.get_folder_name(self, "Rename folder", initial_value=old_name)
        if not new_name or new_name == old_name:
            return
        if FOLDER_PATH_SEP in new_name:
            themed_message_box.warning(self, "Rename folder", 'Folder name can\'t contain "/".')
            return
        new_path = rename_folder(self.folder_maps, self.empty_folders, self.expanded_folders,
                                  self.folders_file, cat, folder_path, new_name)
        if new_path is None:
            return
        rename_folder_active_entry(self.active_map, self.active_file, cat, folder_path, new_path)
        self.refresh_library_list()

    def _delete_library_folder(self, folder_path: str):
        cat = self.current_category
        confirm = themed_message_box.question(
            self, "Delete folder",
            f'Delete folder "{folder_path}"?\n\nEntries inside it (and any subfolders) '
            f"will move to the category root — nothing is deleted.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        delete_folder(self.folder_maps, self.empty_folders, self.expanded_folders,
                       self.folders_file, cat, folder_path)
        delete_folder_active_entries(self.active_map, self.active_file, cat, folder_path)
        self.refresh_library_list()

    def _move_selected_entries_to(self, folder_path: str, names: list):
        """Moves a batch of entries into folder_path ("" = category
        root). Shared entry point for both drag & drop
        (`_LibraryTreeWidget.on_entries_dropped`) and the right-click
        "Move to..." submenu, exactly mirroring the original's note that
        both interaction styles exist side by side rather than being
        alternate UIs for the same underlying action."""
        cat = self.current_category
        if is_protected_folder(cat, folder_path):
            themed_message_box.information(
                self, "Move",
                f'"{CANONICAL_OUTFITS_FOLDER}" is managed automatically — '
                f"outfits are filed there only by marking them as canon.")
            return
        canon_in_selection = [n for n in names if cat == "outfits" and is_canon_outfit_name(n)]
        movable = [n for n in names if n not in canon_in_selection]
        moved = move_entries_to_folder(self.folder_maps, self.folders_file, cat, movable, folder_path)
        # The destination folder (and every ancestor of it, for nested
        # paths) MUST stay open after a successful move — the user just
        # watched their entries land inside it, so collapsing it out
        # from under them would look like the move silently failed.
        if moved and folder_path:
            expanded = self.expanded_folders.setdefault(cat, set())
            parts = folder_path.split(FOLDER_PATH_SEP)
            for depth in range(1, len(parts) + 1):
                expanded.add(FOLDER_PATH_SEP.join(parts[:depth]))
        self.refresh_library_list()
        # Keep the moved entries visibly selected so the user can see
        # exactly what just moved, instead of losing the selection the
        # instant the tree rebuilds.
        if movable:
            items = [self._find_entry_item(n) for n in movable]
            items = [i for i in items if i is not None]
            if items:
                self.tree_library.blockSignals(True)
                for item in items:
                    self._reveal_tree_item(item)
                    item.setSelected(True)
                self.tree_library.blockSignals(False)
                self.tree_library.scrollToItem(items[0])
        label = folder_path if folder_path else "the category root"
        msg = f"Moved {moved} entr{'y' if moved == 1 else 'ies'} to {label}"
        if canon_in_selection:
            msg += f" ({len(canon_in_selection)} canon outfit(s) skipped — moved automatically only)"
        self.lbl_lib_status.setText(msg)

    def _on_tree_context_menu(self, pos):
        item = self.tree_library.itemAt(pos)
        cat = self.current_category
        data = (item.data(0, Qt.ItemDataRole.UserRole) or {}) if item else {}
        menu = QMenu(self)

        if data.get("kind") == _KIND_FOLDER:
            folder_path = data["path"]
            protected = is_protected_folder(cat, folder_path)
            act_new_sub = menu.addAction("New subfolder here")
            act_new_sub.triggered.connect(lambda: self._prompt_new_library_folder(folder_path))
            menu.addSeparator()
            act_rename = menu.addAction("Rename folder")
            act_rename.setEnabled(not protected)
            act_rename.triggered.connect(lambda: self._rename_library_folder(folder_path))
            act_delete = menu.addAction("Delete folder (move contents to root)")
            act_delete.setEnabled(not protected)
            act_delete.triggered.connect(lambda: self._delete_library_folder(folder_path))
            menu.addSeparator()
            act_mark_inactive = menu.addAction("Mark Inactive")
            act_mark_inactive.triggered.connect(
                lambda: self._set_active_and_refresh([], [folder_path], False))
            act_mark_active = menu.addAction("Mark Active")
            act_mark_active.triggered.connect(
                lambda: self._set_active_and_refresh([], [folder_path], True))
        else:
            # Right-clicking an entry (or empty space) operates on
            # whatever is currently selected, falling back to just this
            # row if it wasn't already part of the selection.
            sel = [
                i for i in self.tree_library.selectedItems()
                if (i.data(0, Qt.ItemDataRole.UserRole) or {}).get("kind") == _KIND_ENTRY
            ]
            if item is not None and item not in sel:
                self.tree_library.setCurrentItem(item)
                sel = [item]
            # "New folder..." is always offered, even on empty space
            # with nothing selected — only "Move to..." actually needs
            # entries.
            menu.addAction("New folder…").triggered.connect(lambda: self._prompt_new_library_folder())
            if sel:
                names = [i.data(0, Qt.ItemDataRole.UserRole)["base"] for i in sel]
                menu.addSeparator()
                move_menu = menu.addMenu(
                    f"Move to… ({len(sel)} selected)" if len(sel) > 1 else "Move to…")
                move_menu.addAction("(Category root)").triggered.connect(
                    lambda: self._move_selected_entries_to("", names))
                existing_folders = [
                    f for f in list_all_folders(self.folder_maps, self.empty_folders, cat)
                    if not is_protected_folder(cat, f)
                ]
                if existing_folders:
                    move_menu.addSeparator()
                    for folder_path in existing_folders:
                        indent = "  " * folder_path.count(FOLDER_PATH_SEP)
                        label = indent + folder_path.split(FOLDER_PATH_SEP)[-1]
                        action = move_menu.addAction(label)
                        action.triggered.connect(
                            lambda checked=False, fp=folder_path: self._move_selected_entries_to(fp, names))
                menu.addSeparator()
                menu.addAction("Mark Inactive").triggered.connect(
                    lambda: self._set_active_and_refresh(names, [], False))
                menu.addAction("Mark Active").triggered.connect(
                    lambda: self._set_active_and_refresh(names, [], True))

        menu.exec(self.tree_library.viewport().mapToGlobal(pos))

    def on_library_select(self, base: str):
        cat = self.current_category
        content = read_file_content(self.data_dir, cat, base)

        self.selected_file = base
        self.txt_lib_tags.setPlainText(content)

        if cat == "outfits" and "_Canon_" in base:
            char_name, num = base.split("_Canon_")
            self.chk_canon.blockSignals(True)
            self.chk_canon.setChecked(True)
            self.chk_canon.blockSignals(False)
            self.combo_canon_char.setEnabled(True)
            self.combo_canon_char.set_items(get_file_list(self.data_dir, "characters"))
            self.combo_canon_char.set_value(char_name)
            self.ent_lib_name.setEnabled(True)
            self.ent_lib_name.setText("")
            self.ent_lib_name.setEnabled(False)
            self.editing_canon_owner = (char_name, num)
        else:
            self.chk_canon.blockSignals(True)
            self.chk_canon.setChecked(False)
            self.chk_canon.blockSignals(False)
            if cat == "outfits":
                self.combo_canon_char.setEnabled(False)
            self.ent_lib_name.setEnabled(True)
            self.ent_lib_name.setText(base)
            self.editing_canon_owner = None

        # Session 48.4: video-or-image, same precedence as everywhere
        # else a Library entry's attachment gets read -- an entry with
        # a video always has a poster .jpg too (see _handle_video_drop),
        # but the video itself is the "real" attachment and takes
        # priority for what actually gets displayed here.
        video_path = find_library_video(self.data_dir, cat, base)
        if video_path:
            self.image_drop_zone.show_video_path(video_path, os.path.basename(video_path))
        else:
            image_path = find_library_image(self.data_dir, cat, base)
            if image_path:
                self.image_drop_zone.show_image_path(image_path)
            else:
                self.image_drop_zone.show_placeholder()

        meta = load_library_meta(self.data_dir, cat, base)
        self.lib_source_url = meta["source_url"]
        self.lib_source_editing = False
        self._render_lib_source_row()
        self.lib_entry_lora = meta["lora"]
        self.lib_entry_lora_strength = meta["lora_strength"]
        self._render_lib_lora_row()

        self.lbl_lib_status.setText(f"Editing existing entry: {base}")

    def start_new_library_entry(self, keep_category: bool = False):
        self.selected_file = None
        self.editing_canon_owner = None
        self.tree_library.clearSelection()
        self.tree_library.setCurrentItem(None)
        self.ent_lib_name.setEnabled(True)
        self.ent_lib_name.setText("")
        self.txt_lib_tags.setPlainText("")
        self.image_drop_zone.show_placeholder()
        if not keep_category:
            self.chk_canon.blockSignals(True)
            self.chk_canon.setChecked(False)
            self.chk_canon.blockSignals(False)
            self.combo_canon_char.setEnabled(False)
        self.lib_source_url = None
        self.lib_source_editing = False
        if hasattr(self, "frame_lib_source"):
            self._render_lib_source_row()
        self.lib_entry_lora = None
        self.lib_entry_lora_strength = 1.0
        if hasattr(self, "layout_lib_lora"):
            self._render_lib_lora_row()
        self.lbl_lib_status.setText("New entry")

    # ------------------------------------------------------------------
    # Duplicate
    # ------------------------------------------------------------------
    def _unique_copy_name(self, cat: str, base: str) -> str:
        candidate = f"{base}_copy"
        n = 1
        existing = set(get_file_list(self.data_dir, cat))
        while candidate in existing:
            n += 1
            candidate = f"{base}_copy{n}"
        return candidate

    def duplicate_library_entry(self):
        if not self.selected_file:
            themed_message_box.information(self, "Duplicate", "First select an entry from the list.")
            return
        cat = self.current_category
        content = self.txt_lib_tags.toPlainText().strip()

        if cat == "outfits" and self.editing_canon_owner:
            char_name, _num = self.editing_canon_owner
            existing = glob.glob(os.path.join(self.data_dir, "outfits", f"{char_name}_Canon_*.txt"))
            new_idx = len(existing) + 1
            new_name = f"{char_name}_Canon_{new_idx}"
        else:
            base = self.selected_file
            new_name = self._unique_copy_name(cat, base)

        filepath = os.path.join(self.data_dir, cat, f"{new_name}.txt")
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
        except OSError as exc:
            themed_message_box.critical(self, "Error", f"Failed to duplicate: {exc}")
            return

        old_base = (
            f"{self.editing_canon_owner[0]}_Canon_{self.editing_canon_owner[1]}"
            if (cat == "outfits" and self.editing_canon_owner) else self.selected_file
        )

        # Carry the image over to the copy, if the original entry had one.
        src_image = find_library_image(self.data_dir, cat, old_base)
        if src_image:
            try:
                shutil.copyfile(src_image, library_image_path(self.data_dir, cat, new_name))
            except OSError:
                pass

        # Session 48.4: carry the video over too, if the original entry
        # had one -- same copy-not-move semantics as the image above.
        old_meta = load_library_meta(self.data_dir, cat, old_base)
        src_video = find_library_video(self.data_dir, cat, old_base)
        if src_video:
            try:
                shutil.copyfile(
                    src_video, library_video_path(self.data_dir, cat, new_name, old_meta["video_ext"]))
            except OSError:
                pass

        if (old_meta["source_url"] or old_meta["lora"] or old_meta["force_first"]
                or old_meta["lora_strength"] != 1.0 or old_meta["video_ext"]):
            save_library_meta(self.data_dir, cat, new_name, source_url=old_meta["source_url"],
                               lora=old_meta["lora"], lora_strength=old_meta["lora_strength"],
                               force_first=old_meta["force_first"],
                               video_ext=old_meta["video_ext"] if src_video else None)

        if cat == "outfits" and self.editing_canon_owner:
            file_canon_outfit_into_folder(self.folder_maps, self.folders_file, char_name, new_idx)
        else:
            old_folder = get_entry_folder(self.folder_maps, cat, old_base)
            if old_folder:
                set_entry_folder(self.folder_maps, self.folders_file, cat, new_name, old_folder)

        self.refresh_library_list()
        self.library_changed.emit()
        item = self._find_entry_item(new_name)
        if item:
            self._reveal_tree_item(item)
            self.tree_library.setCurrentItem(item)
            self.tree_library.scrollToItem(item)
        self.lbl_lib_status.setText(f"Copy created: {new_name}")

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------
    def delete_library_entry(self):
        if not self.selected_file:
            themed_message_box.information(self, "Delete", "First select an entry from the list.")
            return
        cat = self.current_category
        base = self.selected_file

        if cat == "characters":
            linked = glob.glob(os.path.join(self.data_dir, "outfits", f"{base}_Canon_*.txt"))
            if linked:
                confirm = themed_message_box.question(
                    self, "Delete character",
                    f'The character "{base}" has {len(linked)} canon outfit(s).\n'
                    f"Delete the character and all of their canon outfits?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if confirm != QMessageBox.StandardButton.Yes:
                    return
                for f in linked:
                    try:
                        os.remove(f)
                    except OSError:
                        pass
                    linked_base = os.path.splitext(os.path.basename(f))[0]
                    delete_library_image(self.data_dir, "outfits", linked_base)
                    delete_library_video(self.data_dir, "outfits", linked_base)
                    delete_library_meta(self.data_dir, "outfits", linked_base)
                    remove_entry_folder_entry(self.folder_maps, self.folders_file, "outfits", linked_base)
                    remove_entry_active_entry(self.active_map, self.active_file, "outfits", linked_base)
        else:
            confirm = themed_message_box.question(
                self, "Delete", f'Delete the entry "{base}"? This action cannot be undone.',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if confirm != QMessageBox.StandardButton.Yes:
                return

        filepath = os.path.join(self.data_dir, cat, f"{base}.txt")
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
        except OSError as exc:
            themed_message_box.critical(self, "Error", f"Failed to delete file: {exc}")
            return

        delete_library_image(self.data_dir, cat, base)
        delete_library_video(self.data_dir, cat, base)
        delete_library_meta(self.data_dir, cat, base)
        remove_entry_folder_entry(self.folder_maps, self.folders_file, cat, base)
        remove_entry_active_entry(self.active_map, self.active_file, cat, base)

        self.start_new_library_entry(keep_category=True)
        self.refresh_library_list()
        self.library_changed.emit()
        self.lbl_lib_status.setText(f"Deleted: {base}")

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------
    def save_to_library(self):
        cat = self.current_category
        tags = self.txt_lib_tags.toPlainText().strip()

        if not tags and cat not in TOOLS_LIKE_CATEGORIES:
            themed_message_box.warning(self, "Error", "The tags/content field cannot be empty!")
            return

        is_editing_canon = cat == "outfits" and self.editing_canon_owner is not None
        rename_from = None
        char_name = num = next_idx = None

        if cat == "outfits" and self.chk_canon.isChecked():
            if is_editing_canon:
                char_name, num = self.editing_canon_owner
                filename = f"{char_name}_Canon_{num}.txt"
            else:
                char_name = self.combo_canon_char.current_value()
                if not char_name or char_name == "None":
                    themed_message_box.warning(self, "Error", "Select a character for the canon outfit!")
                    return
                outfit_path = os.path.join(self.data_dir, "outfits")
                existing_canons = glob.glob(os.path.join(outfit_path, f"{char_name}_Canon_*.txt"))
                next_idx = len(existing_canons) + 1
                filename = f"{char_name}_Canon_{next_idx}.txt"
        else:
            name = self.ent_lib_name.text().strip()
            if not name or name == "None":
                themed_message_box.warning(self, "Error", "The \"Name\" field cannot be empty or 'None'!")
                return
            safe_name = sanitize_filename(name)
            if safe_name != name:
                confirm = themed_message_box.question(
                    self, "Invalid characters",
                    f'The name contains characters that are not allowed in file names.\n'
                    f'"{safe_name}" will be used instead. Continue?',
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if confirm != QMessageBox.StandardButton.Yes:
                    return
            name = safe_name
            old_name = self.selected_file
            filename = f"{name}.txt"

            if old_name and old_name != name:
                old_path = os.path.join(self.data_dir, cat, f"{old_name}.txt")
                new_path = os.path.join(self.data_dir, cat, filename)
                if os.path.exists(new_path) and os.path.abspath(new_path) != os.path.abspath(old_path):
                    themed_message_box.warning(self, "Error", f'An entry named "{name}" already exists.')
                    return
                if os.path.exists(old_path):
                    try:
                        os.remove(old_path)
                    except OSError:
                        pass
                rename_from = old_name

        filepath = os.path.join(self.data_dir, cat, filename)

        if not is_editing_canon and self.selected_file is None and os.path.exists(filepath):
            confirm = themed_message_box.question(
                self, "Entry exists",
                f'An entry named "{os.path.splitext(filename)[0]}" already exists. Overwrite?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if confirm != QMessageBox.StandardButton.Yes:
                return

        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(tags)
        except OSError as exc:
            themed_message_box.critical(self, "Error", f"Failed to save: {exc}")
            return

        if rename_from:
            saved_base_for_rename = os.path.splitext(filename)[0]
            rename_library_image(self.data_dir, cat, rename_from, saved_base_for_rename)
            # Session 48.4: must run before rename_library_meta below —
            # it reads the *old* name's meta sidecar to find the
            # video's current extension (see rename_library_video's
            # own docstring).
            rename_library_video(self.data_dir, cat, rename_from, saved_base_for_rename)
            rename_library_meta(self.data_dir, cat, rename_from, saved_base_for_rename)
            rename_entry_folder_entry(self.folder_maps, self.folders_file, cat, rename_from, saved_base_for_rename)
            rename_entry_active_entry(self.active_map, self.active_file, cat, rename_from, saved_base_for_rename)

        if cat == "outfits" and self.chk_canon.isChecked():
            canon_char, canon_num = (char_name, num) if is_editing_canon else (char_name, next_idx)
            file_canon_outfit_into_folder(self.folder_maps, self.folders_file, canon_char, canon_num)

        self.lbl_lib_status.setText(f"✓ Saved as {filename}")
        saved_base = os.path.splitext(filename)[0]
        self.selected_file = saved_base
        # Persists whatever source_url/lora are currently set in the
        # editor under the entry's final (possibly new/renamed) filename
        # — covers brand-new entries where Source/LoRA were filled in
        # before the first Save, since _persist_current_lib_meta() alone
        # is a no-op until self.selected_file already exists.
        # Session 48.4: preserve video_ext (already carried over to
        # saved_base's own sidecar by rename_library_meta above, or
        # untouched if this wasn't a rename) -- this call must not
        # clobber it, same reasoning as _persist_current_lib_meta.
        existing_video_ext = load_library_meta(self.data_dir, cat, saved_base)["video_ext"]
        save_library_meta(self.data_dir, cat, saved_base, source_url=self.lib_source_url,
                           lora=self.lib_entry_lora, lora_strength=self.lib_entry_lora_strength,
                           force_first=False, video_ext=existing_video_ext)
        self.refresh_library_list()
        self.library_changed.emit()
        # Session 37: same "an entry got added" action as History's own
        # `add_to_history` -- one configured sound regardless of which
        # tab produced the entry (per the finalized design, not two
        # separate History/Library actions).
        sound_manager.play(self.data_dir, "entry_added")
        item = self._find_entry_item(saved_base)
        if item:
            self._reveal_tree_item(item)
            self.tree_library.setCurrentItem(item)
            self.tree_library.scrollToItem(item)
