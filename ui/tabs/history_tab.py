"""History tab — full CRUD against `_history.json`.

Ported from `PromptForgeApp.build_history_tab` / `refresh_history_list` /
`on_history_select` / `copy_selected_history` / `restore_history_to_forge` /
`toggle_selected_favorite` / `delete_selected_history` / `add_to_history` /
`add_comfy_history_entry` / `favorite_last` in the original monolith.

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

`favorite_last` differs from the original in one necessary way: the
original read `self._last_generated` directly off the same God-object
that owned the Builder tab. Here, HistoryTab has no knowledge of the
Builder tab's state, so it takes the last-generated text as an explicit
parameter — the future cross-tab wiring (Session 13) calls
`history_tab.favorite_last(builder_tab.last_generated_text)`.
"""
import time
import uuid

from PyQt6.QtCore import Qt, pyqtSignal
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
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from backend.constants import HISTORY_FILE_NAME, LORA_NONE_VALUE
from backend.file_manager import FileManagerError, load_json, save_json
from backend import sound_manager
from ui.widgets.copyable_label import CopyableLabel
from ui.dialogs import themed_message_box

# Matches the original's `self.history = self.history[:200]` cap.
HISTORY_MAX_ENTRIES = 200


class HistoryTab(QWidget):
    """Self-contained History tab. Owns `self.history` (loaded from
    `<data_dir>/_history.json`) and persists every mutation immediately,
    exactly like the original's "save on every change" behavior.

    `restore_requested(str)` is emitted by "↺ Load into builder" — Session
    13 connects it to `BuilderTab.restore_from_history`. Until then it's a
    no-op signal with nothing listening, which is fine: the slot only
    needs to exist so this tab is independently testable now.
    """

    restore_requested = pyqtSignal(str)

    def __init__(self, data_dir: str, parent=None):
        super().__init__(parent)
        self.data_dir = data_dir
        self.history_file = f"{data_dir}/{HISTORY_FILE_NAME}"
        self.history: list = load_json(self.history_file, [])
        # Mirrors the original's `self._history_index_map`: maps the
        # currently-displayed list row -> real index in self.history,
        # since the "⭐ Favorites" filter means row N is not always
        # entry N.
        self._history_index_map: list = []

        # Session 11.5.2: set by MainWindow once GalleryTab exists (same
        # plain-attribute cross-tab wiring pattern BuilderTab already
        # uses for history_tab/library_tab/gallery_tab), so "🔍 Open
        # image" can route through Gallery's own full-view dialog.
        self.gallery_tab = None

        self._build_ui()
        self.refresh_history_list()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self):
        outer = QVBoxLayout(self)

        top = QHBoxLayout()
        title = QLabel("History of generated prompts")
        title.setObjectName("TitleLabel")
        top.addWidget(title)
        top.addStretch(1)

        self.radio_all = QRadioButton("All")
        self.radio_fav = QRadioButton("⭐ Favorites")
        self.radio_all.setChecked(True)
        self._filter_group = QButtonGroup(self)
        self._filter_group.addButton(self.radio_all)
        self._filter_group.addButton(self.radio_fav)
        self.radio_all.toggled.connect(lambda checked: checked and self.refresh_history_list())
        self.radio_fav.toggled.connect(lambda checked: checked and self.refresh_history_list())
        top.addWidget(self.radio_all)
        top.addWidget(self.radio_fav)
        outer.addLayout(top)

        body = QHBoxLayout()
        outer.addLayout(body, 1)

        self.list_history = QListWidget()
        self.list_history.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list_history.currentRowChanged.connect(self.on_history_select)
        body.addWidget(self.list_history, 1)

        right_box = QWidget()
        right_layout = QVBoxLayout(right_box)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self.txt_preview = QPlainTextEdit()
        self.txt_preview.setReadOnly(True)
        right_layout.addWidget(self.txt_preview, 2)

        # Session 35: 3-column ComfyUI-details row (LoRA / Generation /
        # Negative prompt), only populated (and only shown) for entries
        # generated through ComfyUI — plain "Generate prompt and copy"
        # entries never had this data gathered in the first place. Each
        # card is the same QFrame#Card + bold heading pattern Builder's
        # `_build_card` already established, so History doesn't invent
        # a second visual language for "card."
        self.details_row = QHBoxLayout()
        self.card_lora, self.lora_lines_layout = self._build_card("LoRA")
        self.card_generation, self.generation_layout = self._build_card("Generation")
        self.card_negative, negative_layout = self._build_card("Negative prompt")
        self.lbl_hist_negative = CopyableLabel("")
        self.lbl_hist_negative.setWordWrap(True)
        self.lbl_hist_negative.setObjectName("dim")
        negative_layout.addWidget(self.lbl_hist_negative)
        negative_layout.addStretch(1)
        self.details_row.addWidget(self.card_lora, 1)
        self.details_row.addWidget(self.card_generation, 1)
        self.details_row.addWidget(self.card_negative, 1)
        right_layout.addLayout(self.details_row)

        # Per your note — the click-to-copy behavior on every value
        # above is otherwise invisible/undiscoverable, so a small
        # reminder sits right under the details row telling people it
        # exists (only shown alongside the row itself, same visibility
        # toggle).
        self.lbl_copy_hint = QLabel("💡 Click any value above to copy it")
        self.lbl_copy_hint.setObjectName("dim")
        self.lbl_copy_hint.setAlignment(Qt.AlignmentFlag.AlignRight)
        right_layout.addWidget(self.lbl_copy_hint)
        self._set_details_row_visible(False)

        # "Open image" / "Open folder" — plain ghost buttons, not full
        # stretched cards (your screenshot flagged the "Image"/"Folder"
        # card headings as redundant chrome around a single button, and
        # the cards as wider than they need to be) — content-sized and
        # left-aligned instead, with a trailing stretch to keep them
        # from spreading across the whole row.
        action_cards_row = QHBoxLayout()
        self.btn_hist_open_image = QPushButton("Open image")
        self.btn_hist_open_image.setObjectName("ghost")
        self.btn_hist_open_image.clicked.connect(self._open_selected_history_image)
        self.btn_hist_open_folder = QPushButton("Open folder")
        self.btn_hist_open_folder.setObjectName("ghost")
        self.btn_hist_open_folder.clicked.connect(self._open_selected_history_folder)
        action_cards_row.addWidget(self.btn_hist_open_image)
        action_cards_row.addWidget(self.btn_hist_open_folder)
        action_cards_row.addStretch(1)
        right_layout.addLayout(action_cards_row)
        self._set_image_actions_visible(False)

        btn_row = QHBoxLayout()
        self.btn_copy = QPushButton("Copy")
        self.btn_restore = QPushButton("Load into builder")
        self.btn_fav = QPushButton("Favorite")
        self.btn_delete = QPushButton("🗑")
        self.btn_delete.setObjectName("danger")
        # Same chrome-vs-fixed-width clipping bug as Library's search-clear
        # button (see ui/tabs/library_tab.py): #danger doesn't override the
        # base QPushButton padding (6px 14px + 1px border each side = ~30px
        # of chrome alone), so a 40px-wide button only barely fits the
        # glyph. A local padding override keeps it a small icon-only button
        # without starving the emoji of room.
        self.btn_delete.setStyleSheet("padding: 4px 6px;")
        self.btn_delete.setFixedWidth(40)

        self.btn_copy.clicked.connect(self.copy_selected_history)
        self.btn_restore.clicked.connect(self.restore_history_to_forge)
        self.btn_fav.clicked.connect(self.toggle_selected_favorite)
        self.btn_delete.clicked.connect(self.delete_selected_history)

        btn_row.addWidget(self.btn_copy, 1)
        btn_row.addWidget(self.btn_restore, 1)
        btn_row.addWidget(self.btn_fav, 1)
        btn_row.addWidget(self.btn_delete)
        right_layout.addLayout(btn_row)

        body.addWidget(right_box, 1)

    def _build_card(self, title: str) -> tuple:
        """Local copy of Builder's `_build_card` (QFrame#Card + a bold
        `CardHeading` label as the card's own first row) — see that
        method's docstring for why this shape exists instead of a
        QGroupBox. Duplicated here rather than imported since it's a
        small, self-contained UI helper and History has no other
        dependency on BuilderTab. Returns (frame, inner_layout)."""
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

    def _set_details_row_visible(self, visible: bool):
        self.card_lora.setVisible(visible)
        self.card_generation.setVisible(visible)
        self.card_negative.setVisible(visible)
        self.lbl_copy_hint.setVisible(visible)

    def _set_image_actions_visible(self, visible: bool):
        self.btn_hist_open_image.setVisible(visible)
        self.btn_hist_open_folder.setVisible(visible)

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
    def refresh_history_list(self):
        self.list_history.blockSignals(True)
        self.list_history.clear()
        self._history_index_map = []
        show_fav_only = self.radio_fav.isChecked()

        for idx, entry in enumerate(self.history):
            if show_fav_only and not entry.get("favorite"):
                continue
            star = "⭐ " if entry.get("favorite") else ""
            ts = entry.get("timestamp", "")
            preview = entry.get("text", "").replace("\n", " ")[:50]
            QListWidgetItem(f"{star}{ts} — {preview}", self.list_history)
            self._history_index_map.append(idx)

        self.list_history.blockSignals(False)
        self.txt_preview.setPlainText("")
        self.btn_fav.setText("Favorite")
        self._set_details_row_visible(False)
        self._set_image_actions_visible(False)

    def _get_selected_history_entry(self):
        row = self.list_history.currentRow()
        if row < 0 or row >= len(self._history_index_map):
            return None
        real_idx = self._history_index_map[row]
        return real_idx, self.history[real_idx]

    def on_history_select(self, row: int):
        if row < 0 or row >= len(self._history_index_map):
            return
        _, entry = self._history_index_map[row], self.history[self._history_index_map[row]]
        self.txt_preview.setPlainText(entry.get("text", ""))
        self.btn_fav.setText(
            "Remove from favorites" if entry.get("favorite") else "Favorite"
        )
        self._render_hist_comfy_details(entry)

    def _render_hist_comfy_details(self, entry: dict):
        """Session 11.5.2 built the original hidden-by-default 'LoRA
        used:' label + 'Open image' button; Session 35 replaces both
        with the 3-column card row (LoRA / Generation / Negative
        prompt) plus the Open image / Open folder card row, still
        following the same "nothing shown unless the data actually
        exists" rule. Every value that lands in a card is a
        `CopyableLabel` per your click-to-copy note."""
        lora_used = entry.get("lora_used")
        generation = entry.get("generation")
        has_details = bool(lora_used or generation)
        self._set_details_row_visible(has_details)

        self._clear_layout(self.lora_lines_layout)
        heading = QLabel("LoRA")
        heading.setObjectName("CardHeading")
        self.lora_lines_layout.addWidget(heading)
        if lora_used:
            for lora in lora_used:
                line = f"{lora['name']} — {lora.get('strength', 1.0)}"
                self.lora_lines_layout.addWidget(CopyableLabel(line))
        else:
            lbl_none = QLabel("—")
            lbl_none.setObjectName("dim")
            self.lora_lines_layout.addWidget(lbl_none)
        self.lora_lines_layout.addStretch(1)

        self._clear_layout(self.generation_layout)
        heading = QLabel("Generation")
        heading.setObjectName("CardHeading")
        self.generation_layout.addWidget(heading)
        if generation:
            width, height = generation.get("width"), generation.get("height")
            if width and height:
                self.generation_layout.addWidget(CopyableLabel(f"Resolution: {width}×{height}"))
            seed = generation.get("seed")
            if seed is not None:
                self.generation_layout.addWidget(CopyableLabel(f"Seed: {seed}", copy_text=str(seed)))
            steps = generation.get("steps")
            if steps is not None:
                self.generation_layout.addWidget(CopyableLabel(f"Steps: {steps}"))
            # Placeholder row, per your note "сразу под количество шагов
            # плейсхолдер добавляй" — reserved for whatever generation
            # metadata gets added here next, so this card doesn't need
            # restructuring again for the next field.
            lbl_placeholder = QLabel("")
            lbl_placeholder.setObjectName("dim")
            self.generation_layout.addWidget(lbl_placeholder)
        self.generation_layout.addStretch(1)

        negative_text = (generation or {}).get("negative_text", "")
        self.lbl_hist_negative.setText(negative_text or "—", copy_text=negative_text)

        image_ref = entry.get("image_ref")
        self._set_image_actions_visible(bool(image_ref))

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
    def copy_selected_history(self):
        res = self._get_selected_history_entry()
        if not res:
            themed_message_box.information(self, "Copy", "First select a history entry.")
            return
        _, entry = res
        from PyQt6.QtWidgets import QApplication
        QApplication.clipboard().setText(entry.get("text", ""))
        themed_message_box.information(self, "Copied", "Prompt copied to clipboard.")

    def restore_history_to_forge(self):
        res = self._get_selected_history_entry()
        if not res:
            themed_message_box.information(self, "Load", "First select a history entry.")
            return
        _, entry = res
        self.restore_requested.emit(entry.get("text", ""))

    def toggle_selected_favorite(self):
        res = self._get_selected_history_entry()
        if not res:
            themed_message_box.information(self, "Favorite", "First select a history entry.")
            return
        real_idx, entry = res
        entry["favorite"] = not entry.get("favorite", False)
        self._save()
        self.refresh_history_list()

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

    def favorite_last(self, last_generated_text: str):
        """Favorites the most recent history entry if it matches
        `last_generated_text` exactly; otherwise creates a fresh
        text-only favorited entry. See the module docstring for why this
        takes the text as a parameter instead of reading it off shared
        app state."""
        if not last_generated_text:
            themed_message_box.information(self, "Favorite", "First generate a prompt.")
            return
        if self.history and self.history[0]["text"] == last_generated_text:
            self.history[0]["favorite"] = True
            self._save()
            self.refresh_history_list()
        else:
            self.add_to_history(last_generated_text, favorite=True)

    # ------------------------------------------------------------------
    def _save(self):
        try:
            save_json(self.history_file, self.history)
        except FileManagerError as exc:
            themed_message_box.critical(self, "Error", str(exc))
