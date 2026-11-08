"""History tab — full CRUD against `_history.json`.

Ported from `PromptForgeApp.build_history_tab` / `refresh_history_list` /
`on_history_select` / `delete_selected_history` / `add_to_history` /
`add_comfy_history_entry` in the original monolith. The original's
`copy_selected_history` / `restore_history_to_forge` /
`toggle_selected_favorite` / `favorite_last` were removed in Session 54:
their buttons disappeared in Session 52 and nothing called the slots any
more. The `favorite` key itself stays on stored entries (additive-only
rule); `add_to_history` still accepts it for data compatibility.

Scope note (Session 3, superseded by Session 11.5.2): the original's
ComfyUI-aware preview extras — the "LoRA used:" label and the "🔍 Open
image" button — were deliberately NOT built in Session 3, since they
depend on the Gallery tab's `_gallery_open_full_view` (Session 8) and
the ComfyUI generation queue (Session 11), neither of which existed
yet. Both dependencies now exist, so Session 11.5.2 finally builds
`_render_hist_comfy_details` / `_open_selected_history_image` below.
`lora_used` / `image_ref` were preserved verbatim on each entry dict
from the start so existing `_history.json` files round-trip losslessly
regardless of which session's build reads them. `add_comfy_history_entry`
was added in Session 3 already (pure data shaping, no UI dependency).

Session 52 (History redesign, part 1): the tab is now a two-pane layout
matching the mockup — list on the left, and on the right a vertical
column of image preview / prompt text / three detail cards / actions.
The Favorites radio, the "Copy" button, the "Load into builder" button
and the "click any value to copy" hint are gone from the UI (see the
plan's D2–D6); `Generated Images / All` is a two-way toggle defaulting
to `Generated Images` (Q1: not persisted — a fresh launch always starts
on it), and entries whose image file has since been deleted still show
up there with an explicit "Image file no longer available" placeholder
(Q2).

One addition from the user's post-S52 verification: when `Generated
Images` is empty, a dim hint under the list explains that images only
reach History when a generation ran through ComfyUI (plain "Generate
prompt and copy" entries live under `All`).

Session 53 (part 2): per-field copy icons (`ui/widgets/copy_icon_button.py`)
replaced the click-anywhere `CopyableLabel`s — one icon per LoRA line,
Resolution, Seed, the negative prompt (card heading) and the positive
prompt (inside the prompt box). Steps deliberately has none (Q5).
Clipboard writes go through `ui/clipboard.copy_to_clipboard()`, which
never raises.

Session 54: a missing image now has two distinct placeholders. If the
entry has a ComfyUI `remote_filename` but this run has never learned
ComfyUI's output folder (no saved path, not connected yet), the preview
says "Connect to ComfyUI to view this image" instead of claiming the
file was deleted. `main.py` persists the output folder in
`_settings.json` on every successful connect and seeds
`gallery_tab.comfy_output_dir` at startup, so the normal restart case
resolves the real file straight away.
"""
import os
import time
import uuid

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from backend.constants import (
    HISTORY_FILE_NAME,
    LORA_NONE_VALUE,
    THEMES,
    VIDEO_EXTENSIONS,
)
from backend.file_manager import FileManagerError, load_json, save_json
from backend import sound_manager
from ui.color_utils import qcolor_from_token
from ui.widgets.copy_icon_button import CopyIconButton
from ui.widgets.image_zone import ResultImageViewer
from ui.dialogs import themed_message_box

# Matches the original's `self.history = self.history[:200]` cap.
HISTORY_MAX_ENTRIES = 200


class _PromptPreview(QPlainTextEdit):
    """Read-only prompt box with a copy icon pinned to its top-right.

    Session 53: the positive prompt is the field the user actually
    pastes into Civitai, but the mockup has no room for a header row
    above the 150px block. The icon therefore lives *inside* the box, in
    a strip reserved with `setViewportMargins` so wrapped text never
    runs underneath it (the alternative — floating it over the text —
    hides the last characters of the first wrapped lines).
    """

    ICON_GAP = 8
    ICON_RESERVED = 52

    def __init__(self, colors, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setObjectName("PromptOutput")
        self.setViewportMargins(0, 0, self.ICON_RESERVED, 0)
        self.btn_copy_prompt = CopyIconButton(
            lambda: self.toPlainText(), tooltip="Copy prompt", colors=colors, parent=self)
        self.btn_copy_prompt.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Right edge minus the reserved strip, leaving the vertical
        # scrollbar (when visible) outside the button.
        self.btn_copy_prompt.move(
            self.width() - self.ICON_RESERVED + 12, self.ICON_GAP)

    def set_colors(self, colors):
        self.btn_copy_prompt.set_colors(colors)


class _HistoryImageViewer(ResultImageViewer):
    """`ResultImageViewer` with a caller-settable empty-state text.

    History has more than one "nothing to show" situation and they are
    not interchangeable: nothing selected yet, an entry that never had
    an image (a plain "Generate prompt and copy" entry), and — per Q2 —
    an entry whose generated file has since been deleted from disk. The
    Builder's fixed "No image generated yet" would be wrong or
    misleading for at least two of those."""

    def __init__(self, colors, parent=None):
        super().__init__(colors, parent=parent)
        self._placeholder_text = "Select a history entry"

    def set_placeholder_text(self, text: str):
        self._placeholder_text = text or ""
        self.update()

    def _draw_placeholder(self, painter, w, h):
        painter.setPen(qcolor_from_token(self.colors["fg_dim"]))
        painter.setFont(QFont("Segoe UI", 10))
        painter.drawText(
            QRectF(24, 0, max(w - 48, 10), h),
            int(Qt.AlignmentFlag.AlignCenter) | int(Qt.TextFlag.TextWordWrap),
            self._placeholder_text,
        )


class HistoryTab(QWidget):
    """Self-contained History tab. Owns `self.history` (loaded from
    `<data_dir>/_history.json`) and persists every mutation immediately,
    exactly like the original's "save on every change" behavior.
    """

    def __init__(self, data_dir: str, colors: dict = None, parent=None):
        super().__init__(parent)
        self.data_dir = data_dir
        self.history_file = f"{data_dir}/{HISTORY_FILE_NAME}"
        self.history: list = load_json(self.history_file, [])
        # Maps the currently-displayed list row -> real index in
        # self.history. Still needed after the Favorites filter went
        # away: `Generated Images` hides text-only entries, so row N is
        # still not always entry N.
        self._history_index_map: list = []

        # The image viewer paints its card/placeholder by hand (not via
        # QSS), so it needs the real palette. MainWindow calls
        # `set_colors()` on every tab when the theme changes; the
        # fallback here only covers construction order.
        self.colors = colors or THEMES["dark"]

        # Session 52: last path shown in the preview, so re-selecting an
        # already-selected entry (or a refresh that keeps the selection)
        # doesn't decode the same full-resolution file again.
        self._image_path_cache = None

        # Session 53: what the Negative card's heading copy icon copies.
        # Kept as state (not read back off the label) so the icon copies
        # the raw prompt, without the "—" placeholder used when empty.
        self._current_negative_text = ""

        # Session 11.5.2: set by MainWindow once GalleryTab exists (same
        # plain-attribute cross-tab wiring pattern BuilderTab already
        # uses for history_tab/library_tab/gallery_tab), so "Open
        # image" can route through Gallery's own full-view dialog and
        # "Open folder" through its reveal-in-explorer plumbing.
        self.gallery_tab = None

        self._build_ui()
        self.refresh_history_list()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setSpacing(12)

        top = QHBoxLayout()
        title = QLabel("History of generated prompts")
        title.setObjectName("TitleLabel")
        top.addWidget(title)
        top.addStretch(1)
        top.addWidget(self._build_filter_pill())
        outer.addLayout(top)

        # Session 52: splitter rather than a fixed 400px column — the
        # mockup's 400px is the starting width, but the user can drag it
        # (plan D8: "fixed ~400px ... user-resizable ideally").
        body = QSplitter(Qt.Orientation.Horizontal)
        body.setChildrenCollapsible(False)
        outer.addWidget(body, 1)

        self.list_history = QListWidget()
        self.list_history.setObjectName("HistoryList")
        self.list_history.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list_history.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_history.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.list_history.setMinimumWidth(320)
        self.list_history.setMaximumWidth(560)
        self.list_history.currentRowChanged.connect(self.on_history_select)

        # Session 53 (from post-S52 user feedback): images only ever reach
        # History when a generation actually ran through ComfyUI, so an
        # empty `Generated Images` list is expected for someone who only
        # uses "Generate prompt and copy". Say that out loud instead of
        # leaving an unexplained empty panel.
        left_box = QWidget()
        left_layout = QVBoxLayout(left_box)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)
        left_layout.addWidget(self.list_history, 1)

        self.lbl_filter_hint = QLabel(
            "Images are added to History when a generation runs through ComfyUI.\n"
            "Plain “Generate prompt and copy” entries are listed under All."
        )
        self.lbl_filter_hint.setObjectName("dim")
        self.lbl_filter_hint.setWordWrap(True)
        self.lbl_filter_hint.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.lbl_filter_hint.setVisible(False)
        left_layout.addWidget(self.lbl_filter_hint, 0)

        body.addWidget(left_box)

        right_box = QWidget()
        right_layout = QVBoxLayout(right_box)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(12)
        right_box.setMinimumWidth(520)

        # 1) Image preview — takes every pixel the fixed-size rows below
        # don't need. Same widget Builder/Gallery use, so proportional
        # fit and HiDPI handling are already solved.
        self.image_viewer = _HistoryImageViewer(self.colors)
        right_layout.addWidget(self.image_viewer, 1)

        # 2) Prompt text — fixed 150px, scrollable (mockup height). The
        # copy icon is the prompt box's own child (Session 53).
        self.txt_preview = _PromptPreview(self.colors)
        self.txt_preview.setFixedHeight(150)
        right_layout.addWidget(self.txt_preview, 0)

        # 3) LoRA / Generation / Negative — fixed 195px row, widths
        # 1 : 220px : 1 exactly like the mockup.
        cards_row = QHBoxLayout()
        cards_row.setContentsMargins(0, 0, 0, 0)
        cards_row.setSpacing(12)

        self.card_lora, lora_inner = self._build_card("LoRA")
        lora_content = QWidget()
        lora_content.setObjectName("CardBody")
        self.lora_lines_layout = QVBoxLayout(lora_content)
        self.lora_lines_layout.setContentsMargins(0, 0, 0, 0)
        self.lora_lines_layout.setSpacing(4)
        lora_inner.addWidget(self._make_card_scroll(lora_content), 1)

        self.card_generation, self.generation_layout = self._build_card("Generation")
        self.card_generation.setFixedWidth(220)

        self.card_negative, negative_inner = self._build_card(
            "Negative prompt",
            copy_provider=lambda: self._current_negative_text,
            copy_tooltip="Copy negative prompt")
        negative_content = QWidget()
        negative_content.setObjectName("CardBody")
        negative_body = QVBoxLayout(negative_content)
        negative_body.setContentsMargins(0, 0, 0, 0)
        negative_body.setSpacing(0)
        self.lbl_hist_negative = QLabel("")
        self.lbl_hist_negative.setWordWrap(True)
        self.lbl_hist_negative.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.lbl_hist_negative.setObjectName("dim")
        self.lbl_hist_negative.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        negative_body.addWidget(self.lbl_hist_negative)
        negative_body.addStretch(1)
        negative_inner.addWidget(self._make_card_scroll(negative_content), 1)

        cards_row.addWidget(self.card_lora, 1)
        cards_row.addWidget(self.card_generation, 0)
        cards_row.addWidget(self.card_negative, 1)

        cards_container = QWidget()
        cards_container.setObjectName("CardBody")
        cards_container.setLayout(cards_row)
        cards_container.setFixedHeight(195)
        self.cards_container = cards_container
        right_layout.addWidget(cards_container, 0)

        # 4) Actions — Open image / Open folder share the width, delete
        # is a 44px square (mockup), same #danger treatment as before.
        actions = QHBoxLayout()
        actions.setSpacing(12)
        self.btn_hist_open_image = QPushButton("Open image")
        self.btn_hist_open_image.clicked.connect(self._open_selected_history_image)
        self.btn_hist_open_folder = QPushButton("Open folder")
        self.btn_hist_open_folder.clicked.connect(self._open_selected_history_folder)
        self.btn_delete = QPushButton("🗑")
        self.btn_delete.setObjectName("danger")
        # #danger doesn't override the base QPushButton padding (6px 14px
        # + 1px border each side = ~30px of chrome), so a 44px-wide
        # button would barely fit the glyph.
        self.btn_delete.setStyleSheet("padding: 4px 6px;")
        self.btn_delete.setFixedWidth(44)
        self.btn_delete.setToolTip("Delete this entry")
        self.btn_delete.clicked.connect(self.delete_selected_history)

        actions.addWidget(self.btn_hist_open_image, 1)
        actions.addWidget(self.btn_hist_open_folder, 1)
        actions.addWidget(self.btn_delete, 0)
        right_layout.addLayout(actions, 0)

        body.addWidget(right_box)
        body.setStretchFactor(0, 0)
        body.setStretchFactor(1, 1)
        body.setSizes([400, 900])

        self._set_details_row_visible(False)
        self._set_image_actions_enabled(False)

    def _build_filter_pill(self) -> QWidget:
        """`Generated Images / All` — two checkable buttons in an
        exclusive group, drawn as one rounded pill (mockup). Session 52
        wires it for real rather than shipping a dead control for a
        session: the predicate is one line and the row->entry map it
        needs already exists."""
        frame = QFrame()
        frame.setObjectName("PillGroup")
        frame.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        row = QHBoxLayout(frame)
        row.setContentsMargins(2, 2, 2, 2)
        row.setSpacing(0)

        self.btn_filter_generated = QPushButton("Generated Images")
        self.btn_filter_all = QPushButton("All")
        for btn in (self.btn_filter_generated, self.btn_filter_all):
            btn.setObjectName("PillButton")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            row.addWidget(btn)

        # Q1: `Generated Images` is the default on every launch, and the
        # choice is deliberately not persisted.
        self.btn_filter_generated.setChecked(True)
        self._filter_group = QButtonGroup(self)
        self._filter_group.setExclusive(True)
        self._filter_group.addButton(self.btn_filter_generated)
        self._filter_group.addButton(self.btn_filter_all)
        self._filter_group.buttonClicked.connect(self._on_filter_changed)
        return frame

    def _build_card(self, title: str, copy_provider=None, copy_tooltip: str = "Copy") -> tuple:
        """Local copy of Builder's `_build_card` (QFrame#Card + a bold
        `CardHeading` label as the card's own first row) — see that
        method's docstring for why this shape exists instead of a
        QGroupBox. Duplicated here rather than imported since it's a
        small, self-contained UI helper and History has no other
        dependency on BuilderTab. Returns (frame, inner_layout).

        Session 52: the heading is created once here (it used to be
        re-added on every selection) and the body is a separate child
        layout, so per-entry rebuilds only touch the body.

        Session 53: passing `copy_provider` puts the card-level copy
        icon in the heading row, right-aligned (mockup: Negative
        prompt). The provider is called at click time, so it always
        reads the currently selected entry."""
        frame = QFrame()
        frame.setObjectName("Card")
        frame.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        inner = QVBoxLayout(frame)
        inner.setContentsMargins(6, 4, 6, 6)
        inner.setSpacing(6)

        heading_row = QHBoxLayout()
        heading_row.setContentsMargins(0, 0, 0, 0)
        heading_row.setSpacing(6)
        heading = QLabel(title)
        heading.setObjectName("CardHeading")
        heading_row.addWidget(heading)
        heading_row.addStretch(1)
        if copy_provider is not None:
            heading_row.addWidget(
                CopyIconButton(copy_provider, tooltip=copy_tooltip,
                               colors=self.colors), 0)
        inner.addLayout(heading_row)
        return frame, inner

    def _make_card_scroll(self, content: QWidget) -> QScrollArea:
        """A frameless, transparent scroll area for card bodies that can
        overflow the fixed 195px card height (many LoRAs, a long
        negative prompt). Without it the text is simply clipped."""
        area = QScrollArea()
        area.setObjectName("CardScroll")
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        area.setWidget(content)
        return area

    def set_colors(self, colors: dict):
        """Called from MainWindow's theme application, same pattern as
        GalleryTab.set_colors — the image viewer paints its own
        card/placeholder background, and the copy icons paint their
        border/glyph by hand (Session 53)."""
        self.colors = colors
        self.image_viewer.set_colors(colors)
        self.txt_preview.set_colors(colors)
        for btn in self.findChildren(CopyIconButton):
            btn.set_colors(colors)

    def _set_details_row_visible(self, visible: bool):
        self.cards_container.setVisible(visible)

    def _set_image_actions_enabled(self, image_available: bool, folder_available: bool = None):
        """Both actions used to be hidden entirely for entries without
        an image; the mockup keeps the row fixed, so they are always
        present and simply disabled when there is nothing to act on.
        A deleted image file still leaves "Open folder" useful (Q2)."""
        self.btn_hist_open_image.setEnabled(image_available)
        self.btn_hist_open_folder.setEnabled(
            image_available if folder_available is None else folder_available)

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    # ------------------------------------------------------------------
    # List rendering / selection
    # ------------------------------------------------------------------
    def _generated_only(self) -> bool:
        return self.btn_filter_generated.isChecked()

    def _on_filter_changed(self, _button=None):
        self.refresh_history_list()

    def refresh_history_list(self):
        """Rebuilds the list for the active filter, preserving the
        selected entry by id (not by row — the row index shifts when the
        filter changes or a new entry is prepended)."""
        selected_id = None
        current = self._get_selected_history_entry()
        if current is not None:
            selected_id = current[1].get("id")

        generated_only = self._generated_only()
        self.list_history.blockSignals(True)
        self.list_history.clear()
        self._history_index_map = []

        for idx, entry in enumerate(self.history):
            if generated_only and not entry.get("image_ref"):
                continue
            ts = entry.get("timestamp", "")
            preview = entry.get("text", "").replace("\n", " ")[:50]
            item = QListWidgetItem(f"{ts} — {preview}")
            item.setToolTip(entry.get("text", ""))
            self.list_history.addItem(item)
            self._history_index_map.append(idx)

        if not self._history_index_map:
            empty = QListWidgetItem(
                "No generated images yet" if generated_only else "No history entries yet")
            # Disabled item: visible as an empty-state hint, not
            # selectable, never added to the row->entry map.
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list_history.addItem(empty)

        self.list_history.blockSignals(False)

        # The hint is only true/useful when the empty list is the result
        # of the `Generated Images` filter — under `All` an empty list
        # means "no history at all", where the extra sentence would just
        # be noise.
        self.lbl_filter_hint.setVisible(generated_only and not self._history_index_map)

        if not self._history_index_map:
            self._show_empty_state()
            return

        target_row = 0
        if selected_id is not None:
            for row, real_idx in enumerate(self._history_index_map):
                if self.history[real_idx].get("id") == selected_id:
                    target_row = row
                    break
        self.list_history.setCurrentRow(target_row)

    def _select_history_by_id(self, entry_id):
        """Moves the list selection to `entry_id` if it's currently
        visible. Used after adding an entry, so a freshly generated
        prompt is the one on screen — `refresh_history_list` itself
        deliberately preserves whatever was selected before, which is
        the right behavior for filter toggles and metadata refreshes."""
        for row, real_idx in enumerate(self._history_index_map):
            if self.history[real_idx].get("id") == entry_id:
                self.list_history.setCurrentRow(row)
                return

    def _get_selected_history_entry(self):
        row = self.list_history.currentRow()
        if row < 0 or row >= len(self._history_index_map):
            return None
        real_idx = self._history_index_map[row]
        # Session 52: the map can briefly be stale — `delete_selected_history`
        # removes from `self.history` and only then calls
        # `refresh_history_list`, which reads the current selection before
        # rebuilding. Without this bound check, deleting the only (or the
        # last) entry indexed past the end of the list and raised
        # IndexError inside a Qt slot — a hard crash, the same failure
        # class the old Copy button was suspected of.
        if real_idx < 0 or real_idx >= len(self.history):
            return None
        return real_idx, self.history[real_idx]

    def on_history_select(self, row: int):
        res = self._get_selected_history_entry()
        if res is None:
            self._show_empty_state()
            return
        _, entry = res
        self.txt_preview.setPlainText(entry.get("text", ""))
        self._render_image(entry)
        self._render_hist_comfy_details(entry)

    def _show_empty_state(self):
        self.txt_preview.setPlainText("")
        self.image_viewer.set_placeholder_text("Select a history entry")
        self.image_viewer.show_placeholder()
        self._image_path_cache = None
        self._set_details_row_visible(False)
        self._set_image_actions_enabled(False)

    # ------------------------------------------------------------------
    # Image preview
    # ------------------------------------------------------------------
    def _resolve_image_path(self, image_ref: dict):
        """Same output-folder-over-local-cache priority Gallery's
        `_gallery_resolve_target` uses, so History shows exactly what
        "Open image" would open. Falls back to `local_path` when the
        Gallery tab isn't wired (tests) or the real output file is
        gone."""
        candidates = []
        if self.gallery_tab is not None:
            try:
                target, _folder = self.gallery_tab._gallery_resolve_target(image_ref)
                candidates.append(target)
            except Exception:
                pass
        candidates.append(image_ref.get("local_path"))
        for candidate in candidates:
            if candidate and os.path.isfile(candidate):
                return candidate
        return None

    def _known_output_dir(self):
        """ComfyUI's output folder as currently known to the app, or
        None. `gallery_tab.comfy_output_dir` is seeded from
        `_settings.json` at startup (Session 54) and refreshed on every
        successful connect, so this is normally available even before
        ComfyUI is running in this session."""
        if self.gallery_tab is None:
            return None
        return getattr(self.gallery_tab, "comfy_output_dir", None) or None

    def _missing_image_placeholder(self, image_ref: dict) -> str:
        """Q2 vs. "we simply don't know where to look yet" (Session 54).

        A `remote_filename` with no known output folder means the file
        may well exist on disk — the app just has no path to it until
        ComfyUI has been connected once. Saying "no longer available"
        there would be a lie, and it is exactly the state a fresh
        install/portable copy starts in.
        """
        if image_ref.get("remote_filename") and not self._known_output_dir():
            return "Connect to ComfyUI to view this image"
        return "Image file no longer available"

    def refresh_current_image(self):
        """Re-renders the preview for the currently selected entry.

        Session 54: the output folder can become known *after* the first
        render — seeded at startup (after `gallery_tab` is wired) or
        learned when ComfyUI connects. Without this, the already-selected
        entry keeps showing "Connect to ComfyUI to view this image" (or
        "no longer available") until the user clicks another row and
        comes back, even though the file is now resolvable.
        """
        res = self._get_selected_history_entry()
        if res is not None:
            self._render_image(res[1])

    def _render_image(self, entry: dict):
        image_ref = entry.get("image_ref")
        if not image_ref:
            self.image_viewer.set_placeholder_text("No image for this entry")
            self.image_viewer.show_placeholder()
            self._image_path_cache = None
            self._set_image_actions_enabled(False)
            return

        path = self._resolve_image_path(image_ref)
        if not path:
            # Q2: the entry stays visible (an image really was
            # generated), but the preview says plainly why there is
            # nothing to show instead of an unexplained blank card.
            self.image_viewer.set_placeholder_text(
                self._missing_image_placeholder(image_ref))
            self.image_viewer.show_placeholder()
            self._image_path_cache = None
            # "Open folder" is only useful when a folder is actually
            # known: ComfyUI's output dir, or — for a legacy entry with
            # no `remote_filename` — the local folder it came from. A
            # ComfyUI entry whose output dir has never been learned must
            # not offer it (the only local path is the wiped cache).
            if self._known_output_dir():
                folder_available = True
            elif image_ref.get("remote_filename"):
                folder_available = False
            else:
                local_path = image_ref.get("local_path")
                folder_available = bool(
                    local_path and os.path.isdir(os.path.dirname(local_path)))
            self._set_image_actions_enabled(False, folder_available=folder_available)
            return

        self._set_image_actions_enabled(True)
        if path == self._image_path_cache:
            return
        self._image_path_cache = path
        if self._is_video_path(path):
            self.image_viewer.show_video_path(
                path, image_ref.get("remote_filename") or os.path.basename(path))
        else:
            self.image_viewer.show_image_path(path)

    @staticmethod
    def _is_video_path(path: str) -> bool:
        return os.path.splitext(path)[1].lower() in VIDEO_EXTENSIONS

    def _render_hist_comfy_details(self, entry: dict):
        """Session 11.5.2 built the original hidden-by-default 'LoRA
        used:' label + 'Open image' button; Session 35 replaced both
        with the 3-column card row (LoRA / Generation / Negative
        prompt). Session 52 keeps that data model but rebuilds only the
        card bodies, and still follows the same "nothing shown unless
        the data actually exists" rule.

        Session 53: every copyable value now carries its own
        `CopyIconButton` (D6) instead of being a click-to-copy label.
        Per Q5, Resolution and Seed get one, Steps does not (there is no
        output for steps in the app or the connector), LoRA lines and
        the whole negative prompt do."""
        lora_used = entry.get("lora_used")
        generation = entry.get("generation")
        has_details = bool(lora_used or generation)
        self._set_details_row_visible(has_details)
        if not has_details:
            self._current_negative_text = ""
            return

        self._clear_layout(self.lora_lines_layout)
        if lora_used:
            for lora in lora_used:
                line = f"{lora.get('name', '')} — {lora.get('strength', 1.0)}"
                self._add_copy_row(self.lora_lines_layout, line, line, "Copy LoRA")
        else:
            lbl_none = QLabel("—")
            lbl_none.setObjectName("dim")
            self.lora_lines_layout.addWidget(lbl_none)
        self.lora_lines_layout.addStretch(1)

        self._clear_layout(self.generation_layout)
        if generation:
            width, height = generation.get("width"), generation.get("height")
            if width and height:
                text = f"Resolution: {width}×{height}"
                self._add_copy_row(self.generation_layout, text, text, "Copy resolution")
            seed = generation.get("seed")
            if seed is not None:
                self._add_copy_row(
                    self.generation_layout, f"Seed: {seed}", str(seed), "Copy seed")
            steps = generation.get("steps")
            if steps is not None:
                # Q5: deliberately no copy icon — Steps is not an input
                # the user can reproduce anywhere else.
                lbl_steps = QLabel(f"Steps: {steps}")
                lbl_steps.setObjectName("dim")
                self.generation_layout.addWidget(lbl_steps)
        self.generation_layout.addStretch(1)

        negative_text = (generation or {}).get("negative_text", "")
        self._current_negative_text = negative_text or ""
        self.lbl_hist_negative.setText(negative_text or "—")

    def _add_copy_row(self, layout, text: str, copy_text: str, tooltip: str):
        """One `value + clipboard icon` row, used inside the LoRA and
        Generation cards (the mockup's `.field-row`). The label wraps,
        the icon stays top-aligned and never stretches."""
        row = QWidget()
        row.setObjectName("CardBody")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(6)

        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setObjectName("dim")
        lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        row_layout.addWidget(lbl, 1)
        row_layout.addWidget(
            CopyIconButton(lambda: copy_text, tooltip=tooltip, colors=self.colors),
            0, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(row)

    def _open_selected_history_image(self):
        """'Open image' — same in-app preview as the Gallery's own
        magnifier/click-to-open, reused as-is (`_gallery_open_full_view`)
        rather than reveal-in-explorer, matching the original."""
        res = self._get_selected_history_entry()
        if not res:
            return
        _, entry = res
        image_ref = entry.get("image_ref")
        if not image_ref:
            return
        if self.gallery_tab is None:
            themed_message_box.information(self, "Open image", "Gallery is not available.")
            return
        self.gallery_tab._gallery_open_full_view(image_ref)

    def _open_selected_history_folder(self):
        """Session 35: "Open folder", copied from Gallery per your
        note — `image_ref` is stored in the exact same
        (local_path, remote_filename, remote_subfolder) shape Gallery's
        own entries use, so `GalleryTab._gallery_reveal_in_explorer` can
        be reused directly instead of re-implementing the same
        resolve_output_folder_for/reveal_file_in_explorer plumbing a
        third time."""
        res = self._get_selected_history_entry()
        if not res:
            return
        _, entry = res
        image_ref = entry.get("image_ref")
        if not image_ref:
            return
        if self.gallery_tab is None:
            themed_message_box.information(self, "Open folder", "Gallery is not available.")
            return
        self.gallery_tab._gallery_reveal_in_explorer(image_ref)

    # ------------------------------------------------------------------
    # Button actions
    # ------------------------------------------------------------------
    def delete_selected_history(self):
        res = self._get_selected_history_entry()
        if not res:
            themed_message_box.information(self, "Delete", "First select a history entry.")
            return
        real_idx, _entry = res
        confirm = themed_message_box.question(
            self, "Delete entry", "Delete this entry from history?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        del self.history[real_idx]
        self._save()
        self.refresh_history_list()

    # ------------------------------------------------------------------
    # Mutators (called by other tabs / cross-tab wiring later)
    # ------------------------------------------------------------------
    def add_to_history(self, text: str, favorite: bool = False, lora_used=None,
                        image_ref=None, generation=None) -> str:
        """Creates a new history entry and returns its id. `lora_used` /
        `image_ref` / `generation` are populated only by the future
        ComfyUI-submission path (Session 11, extended Session 35) --
        plain text entries never set them."""
        entry = {
            "id": str(uuid.uuid4()),
            "text": text,
            "timestamp": time.strftime("%Y-%m-%d %H:%M"),
            "favorite": favorite,
        }
        if lora_used:
            entry["lora_used"] = lora_used
        if image_ref:
            entry["image_ref"] = image_ref
        if generation:
            entry["generation"] = generation
        self.history.insert(0, entry)
        self.history = self.history[:HISTORY_MAX_ENTRIES]
        self._save()
        self.refresh_history_list()
        self._select_history_by_id(entry["id"])
        sound_manager.play(self.data_dir, "entry_added")
        return entry["id"]

    def add_comfy_history_entry(self, prompt_text: str, lora_slots_snapshot: list,
                                 seed=None, width=None, height=None, negative_text=None) -> str:
        """Builds `lora_used` from a frozen LoRA-slot snapshot taken at
        enqueue time (Session 11's generation queue) and delegates to
        `add_to_history`. Only slots with a real LoRA selected are kept.

        Session 35: also freezes the generation parameters known at
        this same enqueue moment (seed/width/height/negative_text) —
        everything `on_generate_in_comfy_clicked` already computes for
        the queue item — onto a `generation` dict on the entry. `steps`
        isn't known yet at this point (it only becomes available once
        the run actually starts producing progress updates), so it's
        added later by `attach_image_to_history_entry`. All of this is
        only ever called from the ComfyUI-submission path, matching
        your "only recorded when comfy_connected" note — a plain
        "Generate prompt and copy" entry never gets a `generation` key
        at all."""
        lora_used = [
            {"name": slot["name"], "strength": slot.get("strength", 1.0), "auto": bool(slot.get("auto"))}
            for slot in lora_slots_snapshot
            if (slot.get("name") or LORA_NONE_VALUE) != LORA_NONE_VALUE
        ]
        generation = None
        if seed is not None or width is not None or height is not None or negative_text is not None:
            generation = {
                "seed": seed,
                "width": width,
                "height": height,
                "negative_text": negative_text or "",
            }
        return self.add_to_history(prompt_text, lora_used=lora_used or None, generation=generation)

    def attach_image_to_history_entry(self, history_id: str, local_path: str,
                                       remote_filename: str, remote_subfolder: str, steps=None):
        """Session 11 hook: called once a queued ComfyUI generation's
        image actually comes back, to attach it to the history entry
        that was already created (by id, not by matching text — see
        `add_comfy_history_entry`'s caller) back when the item was
        queued. Stored as the same (local_path, remote_filename,
        remote_subfolder) triple the Gallery tab keeps for its own
        entries, so both tabs can resolve the real file through the
        identical `resolve_output_folder_for` logic — no separate
        path-resolution rule to maintain between the two. A no-op if
        `history_id` doesn't match any current entry (e.g. history was
        cleared mid-generation).

        Session 35: also fills in `steps` on the entry's `generation`
        dict, if present — steps isn't known at enqueue time (see
        `add_comfy_history_entry`'s docstring), only once the run has
        actually reported progress, so it arrives here alongside the
        finished image instead."""
        for entry in self.history:
            if entry.get("id") == history_id:
                entry["image_ref"] = {
                    "local_path": local_path,
                    "remote_filename": remote_filename or None,
                    "remote_subfolder": remote_subfolder or "",
                }
                if steps is not None:
                    entry.setdefault("generation", {})["steps"] = steps
                self._save()
                self.refresh_history_list()
                return

    # ------------------------------------------------------------------
    def _save(self):
        try:
            save_json(self.history_file, self.history)
        except FileManagerError as exc:
            themed_message_box.critical(self, "Error", str(exc))
