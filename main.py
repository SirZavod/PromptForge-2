"""PromptForge — PyQt6 entry point.

Session 13: integration/polish pass — window-state restore snap
(maximized -> normal snaps back to the comfortable default size,
centered, same as the original's `_on_root_configure`), a real
content-derived minimum size (`_apply_computed_minsize`, computed once
every tab actually exists instead of the Session 3 provisional
1040x680 floor), explicit HiDPI policy (`AA_EnableHighDpiScaling` +
`PassThrough` rounding), and the PyInstaller `.spec`. Cross-tab wiring
itself was already done in Session 11 (and extended in 11.5.2) via
plain attributes + the two signals below — nothing about that wiring
changes here, this session only adds the window-chrome pieces the
plan explicitly deferred until every tab existed.
"""
import os
import shutil
import sys

from PyQt6.QtCore import QEvent, QObject, QPoint, QRect, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QIcon, QShortcut, QKeySequence
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QColorDialog,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QSlider,
    QStackedWidget,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from backend.constants import (
    BACKGROUND_FIT_LABELS, BACKGROUND_FIT_MODES, CATEGORIES, COMFY_DEFAULT_HOST,
    COMFY_DEFAULT_PORT, DATA_DIR_NAME, DEFAULT_BACKGROUND_BLUR, DEFAULT_BACKGROUND_FIT,
    DEFAULT_BACKGROUND_OPACITY, DEFAULT_CARD_ALPHA, MAX_BACKGROUND_BLUR,
    SETTINGS_FILE_NAME, SOUND_ACTIONS, SOUND_ACTION_LABELS, THEMES,
    PIPELINE_MODE_LABELS, PIPELINE_MODE_SHORT_LABELS, PIPELINE_MODE_T2I,
)
from backend.file_manager import FileManagerError, init_folders, load_json, save_json
from backend import sound_manager
from backend import theme_background
from backend.theme_derive import apply_surface_alpha, contrast_ratio, derive_palette
from ui.theme import apply_theme
from ui.title_bar import TitleBar
from ui.widgets.background_surface import BackgroundSurface
from ui.dialogs.guide_dialog import GuideDialog
from ui.tabs.builder_tab import BuilderTab
from ui.tabs.gallery_tab import GalleryTab
from ui.tabs.history_tab import HistoryTab
from ui.tabs.library_tab import LibraryTab
from workers.comfy_worker import ComfyCheckWorker, ComfyGenerationWorker  # noqa: F401 (import-path check)


def _app_root_dir() -> str:
    """Folder that contains this script, or — when packaged with
    PyInstaller — the folder that contains the .exe. Deliberately
    independent from `backend.file_manager.app_dir()`: that helper
    resolves relative to `file_manager.py`'s own location (i.e.
    `.../promptforge/backend`), which is the right "next to the data
    helpers" notion for nothing in particular yet, but wrong for finding
    things that sit next to the *program* (icon.ico, the data folder).
    Session 13 revisits this when the PyInstaller spec is finalized."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


# Session 37: bundled ("Default") sound assets need `sys._MEIPASS`
# inside a frozen build, not the folder-next-to-the-.exe rule above --
# see `backend.sound_manager.bundled_assets_dir()`, which owns that
# resolution (kept there, not here, so every call site can use it
# without importing `main.py`). `PromptForge.spec`'s `datas` entry for
# `assets/sounds` is what actually puts the files where that resolver
# expects them at runtime.


class _SoundComboDelegate(QStyledItemDelegate):
    """Paints a small red x at the right edge of every custom-sound
    row in the Sounds dropdowns, so deleting a saved sound happens
    inline in the list (matching how a "manage this list" combo is
    expected to work) instead of via an always-present, easy-to-miss
    button sitting next to the volume slider (Session 37 follow-up)."""

    DELETE_ZONE_WIDTH = 26

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        data = index.data(Qt.ItemDataRole.UserRole)
        if isinstance(data, str) and data.startswith("custom:"):
            painter.save()
            zone = self._delete_zone(option.rect)
            painter.setPen(QColor("#d9534f"))
            font = painter.font()
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(zone, Qt.AlignmentFlag.AlignCenter, "\u2715")
            painter.restore()

    def _delete_zone(self, item_rect) -> QRect:
        return QRect(item_rect.right() - self.DELETE_ZONE_WIDTH, item_rect.top(),
                     self.DELETE_ZONE_WIDTH, item_rect.height())

    def delete_zone_contains(self, item_rect, pos) -> bool:
        return self._delete_zone(item_rect).contains(pos)


class _SoundComboDeleteFilter(QObject):
    """Installed on a Sounds combo's popup viewport. Intercepts clicks
    that land in the delegate's delete zone before Qt turns them into
    a normal item-selection, so clicking the x deletes that custom
    sound instead of selecting it."""

    def __init__(self, combo, delegate, action_key, owner):
        super().__init__(combo)
        self._combo = combo
        self._delegate = delegate
        self._action_key = action_key
        self._owner = owner

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.MouseButtonPress:
            view = self._combo.view()
            pos = event.pos()
            index = view.indexAt(pos)
            if index.isValid():
                data = index.data(Qt.ItemDataRole.UserRole)
                if isinstance(data, str) and data.startswith("custom:"):
                    if self._delegate.delete_zone_contains(view.visualRect(index), pos):
                        idx = int(data.split(":", 1)[1])
                        self._combo.hidePopup()
                        self._owner._delete_custom_sound_by_idx(self._action_key, idx)
                        return True
        return super().eventFilter(obj, event)


RESIZE_MARGIN = 6  # px from any window edge that counts as a resize handle

# Session 38 follow-up, reverted: a Windows-native-Snap variant of this
# title bar (WM_NCCALCSIZE/WM_NCHITTEST message handling to recover
# Aero Snap/Snap Layouts + DWM shadow/rounded corners) was attempted
# and crashed hard on real hardware -- twice, in two different ways.
# The root cause traced back to the mere presence of an overridden
# `nativeEvent` on this class: PyQt's virtual-method dispatch back into
# Python can be called (e.g. for WM_WINDOWPOSCHANGING) *during this
# window's own CreateWindowEx*, before the C++/Python object linkage is
# fully wired up -- so even a `nativeEvent` body that does nothing but
# immediately delegate to `super()` was enough to corrupt memory on the
# machine this was tested on. Gating the logic behind a runtime flag
# wasn't sufficient, since the method still existed on the class either
# way; it's removed from this file entirely rather than left disabled
# behind a flag, and would need a real architectural split (a separate
# subclass that only exists when actually wanted, verified from a
# debugger on real hardware) to revisit safely. See
# additionalfeatures.md, SESSION 38 follow-up, for the full post-mortem.


class MainWindow(QMainWindow):
    # Session 39 follow-up: max one full QSS rebuild per this many ms
    # while dragging a Base/Accent color picker -- see
    # `_preview_custom_color`.
    _PREVIEW_THROTTLE_MS = 60

    def _use_frameless_hint(self):
        """Session 42 crash follow-up: hook so a subclass (namely
        `MainWindowWinSnap`) can opt out of `FramelessWindowHint` at
        construction time, rather than having it set here and then
        stripped off afterward with a second `setWindowFlags()` call --
        see the comment at the call site in `__init__` for why the
        "toggle it off later" version crashes on real hardware."""
        return True

    def __init__(self):
        super().__init__()
        self.setWindowTitle("PromptForge v2.0")

        # Session 38: fully-owned title bar (Option B). Frameless +
        # our own mouse-driven drag/resize, on every platform. (A
        # Windows-native-Snap variant was attempted as a follow-up and
        # reverted after crashing real hardware -- see
        # additionalfeatures.md, SESSION 38 follow-up, for the
        # post-mortem and why it's not just gated behind a flag but
        # removed from this class entirely.)
        #
        # Session 42 crash follow-up: this must be decided ONCE, here,
        # before the native window is ever created -- never toggled
        # afterward via a second setWindowFlags() call once the window
        # already exists. Changing FramelessWindowHint post-construction
        # forces Qt to destroy and recreate the underlying HWND (a
        # second CreateWindowEx), and on the WinSnap subclass that
        # recreation happens with nativeEvent already live on the
        # vtable -- the exact same class of race the Session 38
        # post-mortem documented, just moved from "class definition
        # time" to "flag-change time" instead of being eliminated. See
        # `_use_frameless_hint()` below, which `MainWindowWinSnap`
        # overrides to answer False so it never sets this flag in the
        # first place -- no post-hoc removal, no recreation, no race.
        if self._use_frameless_hint():
            self.setWindowFlags(self.windowFlags() | Qt.WindowType.FramelessWindowHint)
        self._resize_edge = None
        self._resize_start_geo = None
        self._resize_start_pos = None


        self.data_dir = os.path.join(_app_root_dir(), DATA_DIR_NAME)
        init_folders(self.data_dir, CATEGORIES)

        self.settings_file = os.path.join(self.data_dir, SETTINGS_FILE_NAME)
        self.settings = load_json(self.settings_file, {"theme": "dark"})
        _theme_setting = self.settings.get("theme", "dark")
        self.theme_name = _theme_setting if (_theme_setting in THEMES or _theme_setting == "custom") else "dark"
        # Session 39: Custom theme's Base/Accent/ladder-direction, persisted
        # the same way `theme_name` already is. Defaults to the dark
        # theme's own accent so a freshly-picked "Custom" starts from
        # something reasonable rather than an arbitrary color.
        self.settings.setdefault("custom_theme_base", THEMES["dark"]["bg"])
        self.settings.setdefault("custom_theme_accent", THEMES["dark"]["accent"])
        self.settings.setdefault("custom_theme_mode", "dark")
        # Session 40: optional background image carried *by* the Custom
        # theme (not a fourth theme type — see additionalfeatures.md,
        # SESSION 40). `custom_theme_bg_image` is a stored path (inside
        # `prompt_forge_data/theme/`, see `backend/theme_background.py`)
        # or None.
        self.settings.setdefault("custom_theme_bg_image", None)
        self.settings.setdefault("custom_theme_bg_fit", DEFAULT_BACKGROUND_FIT)
        self.settings.setdefault("custom_theme_bg_opacity", DEFAULT_BACKGROUND_OPACITY)
        # Session 40.1: card translucency + background pre-blur, both
        # cosmetic add-ons with no effect unless a background image is
        # actually set.
        self.settings.setdefault("custom_theme_card_alpha", DEFAULT_CARD_ALPHA)
        self.settings.setdefault("custom_theme_bg_blur", DEFAULT_BACKGROUND_BLUR)
        # Graceful "moved/deleted on disk after being set" handling —
        # fails back to the plain derived color instead of erroring out
        # on launch, same spirit as Session 37's sound startup_check.
        if self.settings["custom_theme_bg_image"] and not theme_background.resolve_background_path(
                self.settings["custom_theme_bg_image"]):
            self.settings["custom_theme_bg_image"] = None

        # Session 39 follow-up: `QColorDialog.currentColorChanged` fires
        # on every pixel of a wheel/slider drag -- rebuilding and
        # reapplying the *entire* app QSS string that often visibly
        # lags. Coalesce into one repaint per short window instead:
        # each signal just records the latest pending pick and
        # (re)starts a short singleShot timer; only the timer's timeout
        # actually rebuilds/applies, so a fast drag collapses to a
        # handful of repaints instead of one per pixel.
        self._custom_preview_timer = QTimer(self)
        self._custom_preview_timer.setSingleShot(True)
        self._custom_preview_timer.timeout.connect(self._apply_pending_custom_preview)
        self._pending_custom_preview = None

        # Session 37: scan for any "selected" sound pointing at a
        # custom file that's since gone missing (deleted outside the
        # app, quarantined, etc.) once here at startup rather than
        # waiting for the next matching event -- see
        # `sound_manager.startup_check`'s own docstring. Runs against
        # the settings file directly and may rewrite it, so re-load
        # `self.settings` right after instead of risking a stale
        # in-memory copy that silently un-does the reset on next save.
        self._reset_sound_actions = sound_manager.startup_check(self.data_dir)
        if self._reset_sound_actions:
            self.settings = load_json(self.settings_file, self.settings)

        self._apply_app_icon()
        self._default_window_size = self._size_to_screen()
        self._last_window_state = self.windowState()

        # Session 40: a plain QWidget can't show a stretch/fit-crop/tile
        # background image (QSS `background-image` only tiles or pins a
        # corner) — `BackgroundSurface` paints it directly. Everything
        # else (title bar, sidebar, cards, tab pages) keeps its own
        # opaque background from theme.py's QSS on top of this, so the
        # image only ever shows through the outer gaps, per the plan.
        central = BackgroundSurface()
        self.central = central
        self.setCentralWidget(central)
        outer_v = QVBoxLayout(central)
        outer_v.setContentsMargins(0, 0, 0, 0)
        outer_v.setSpacing(0)

        self.title_bar = TitleBar(self, self._active_colors())
        self.title_bar.set_window_icon(self.windowIcon())
        outer_v.addWidget(self.title_bar)

        content = QWidget()
        content.setObjectName("ContentSurface")
        self.content_surface = content
        outer_v.addWidget(content, 1)
        root = QHBoxLayout(content)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Manual resize replacement for the OS-drawn border a frameless
        # window loses -- an app-wide event filter rather than an
        # override on `content`/`title_bar` individually, since those
        # child widgets swallow mouse events before they'd ever bubble
        # up to `MainWindow` otherwise.
        QApplication.instance().installEventFilter(self)

        root.addWidget(self._build_sidebar())

        page_col = QWidget()
        page_col.setObjectName("PageColumn")
        self.page_col = page_col
        page_outer = QVBoxLayout(page_col)
        page_outer.setContentsMargins(18, 14, 18, 14)
        page_outer.setSpacing(14)
        # Session 14.5: the top-right strip (Guide + theme toggle) is
        # gone — Guide moved to the bottom of the sidebar nav (see
        # `_build_sidebar`), theme toggle has no UI until Session 19's
        # Settings page. Nothing replaces this strip; the page column
        # starts directly at its content, which also lowers scroll risk
        # for Session 15's declutter pass.

        self.stack = QStackedWidget()
        page_outer.addWidget(self.stack, 1)
        root.addWidget(page_col, 1)

        # Built in this order so the stack index order matches the
        # original tab order (Builder, Library, History, Gallery), plus
        # the two new placeholder destinations (LoRA/Settings — real
        # content lands in Sessions 18/19).
        self.tab_builder = BuilderTab(
            self.data_dir, self._active_colors(), self.settings, self.settings_file)
        self.tab_library = LibraryTab(
            self.data_dir, self._active_colors(), self.settings, self.settings_file)
        self.tab_history = HistoryTab(self.data_dir)
        self.tab_gallery = GalleryTab(self._active_colors())
        # Session 18: LoRA is a real page now, built by BuilderTab
        # itself (it owns all the slot data/backend wiring already) --
        # see `BuilderTab.build_lora_page`'s own docstring for why this
        # lives there instead of as a standalone tab class.
        self.page_lora = self.tab_builder.build_lora_page()
        # Session 19: Settings is a real page now -- ComfyUI host/port
        # (moved out of Builder's old "4. ComfyUI" panel) and the theme
        # toggle (UI-less since Session 14.5) both land here for real.
        # See `_build_settings_page`.
        self.page_settings = self._build_settings_page()

        self.stack.addWidget(self.tab_builder)
        self.stack.addWidget(self.tab_library)
        self.stack.addWidget(self.tab_history)
        self.stack.addWidget(self.tab_gallery)
        self.stack.addWidget(self.page_lora)
        self.stack.addWidget(self.page_settings)

        # Cross-tab hooks (Session 11) — BuilderTab's ComfyUI pipeline
        # needs to reach into the other three tabs (LoRA-binding
        # visibility/data, gallery registration, history attach). Set
        # as plain attributes rather than passed into BuilderTab's
        # constructor, since all four tabs need to exist first.
        self.tab_builder.history_tab = self.tab_history
        self.tab_builder.library_tab = self.tab_library
        # Session 48.2: wired here too (not just library_tab above) so
        # the one _apply_pipeline_mode() call right below also gets the
        # sidebar's mode caption correctly synced on the very first
        # real pass, the same "fix it at the actual wiring point" logic
        # as the 48.1 fix this call is already part of.
        self.tab_builder.main_window = self
        # Session 48.1 fix: BuilderTab.__init__ already called
        # _apply_pipeline_mode() once during construction, but
        # self.tab_builder.library_tab didn't exist yet at that point
        # (this line is what creates it) -- that first call's Library
        # sync silently no-op'd on its own `if self.library_tab is not
        # None` guard, leaving Library showing every category until
        # whatever later interaction happened to call
        # _apply_pipeline_mode() again (e.g. cycling the mode button
        # once). Re-running it right here, now that the reference
        # genuinely exists, closes that gap at the source instead of
        # relying on incidental later calls.
        self.tab_builder._apply_pipeline_mode()
        self.tab_builder.gallery_tab = self.tab_gallery
        # Session 11.5.2: History's "🔍 Open image" reuses Gallery's own
        # full-view dialog (_gallery_open_full_view) — same
        # plain-attribute cross-tab wiring pattern as the three lines
        # above.
        self.tab_history.gallery_tab = self.tab_gallery

        # BuilderTab records straight to history on every successful
        # "Generate prompt and copy" while ComfyUI isn't connected; once
        # connected, "Generate in ComfyUI" records its own history entry
        # directly via self.history_tab instead — see
        # BuilderTab._finalize_generated_prompt's own note.
        self.tab_builder.prompt_generated.connect(self.tab_history.add_to_history)
        # LoRA-binding row (Library tab) is only meaningful once ComfyUI
        # is actually connected — see LibraryTab._refresh_lib_lora_visibility.
        self.tab_builder.comfy_connection_changed.connect(self.tab_library._refresh_lib_lora_visibility)
        # Session 30.3: a Library save/duplicate/delete/import used to
        # only show up in Builder's Who/Style/Scenario/Tool combos after
        # a full app restart, since those combos are seeded from
        # `get_file_list` once at widget-creation time. Library now
        # fires `library_changed` on the four calls that actually touch
        # files on disk; Builder repopulates every affected combo in
        # place without disturbing the person's current picks — see
        # `BuilderTab.refresh_library_backed_combos`.
        self.tab_library.library_changed.connect(self.tab_builder.refresh_library_backed_combos)
        # Session 14 (text simplified in 14.5): sidebar footer mirrors
        # Builder's ComfyUI connect/busy state — see
        # `_refresh_sidebar_comfy_status`'s own note for why the
        # sidebar's text is state-driven rather than a verbatim mirror
        # of Builder's own status label.
        self.tab_builder.comfy_connection_changed.connect(self._on_comfy_connection_changed)
        self.tab_builder.comfy_status_message_changed.connect(self._on_comfy_status_message)
        self.tab_builder.comfy_check_busy_changed.connect(self._on_comfy_check_busy_changed)

        apply_theme(QApplication.instance(), self._active_colors())
        self._refresh_theme_icon()

        QShortcut(QKeySequence("F1"), self).activated.connect(self.open_guide)

        # Real content-derived minimum size, now that every tab actually
        # exists to measure — replaces the Session 3 provisional
        # 1040x680 floor. Mirrors the original's `_apply_computed_minsize`,
        # called once at the very end of __init__.
        self._apply_computed_minsize()

        if self._reset_sound_actions:
            names = ", ".join(SOUND_ACTION_LABELS[k] for k in self._reset_sound_actions)
            QMessageBox.information(
                self, "Sound file missing",
                f"The custom sound for: {names} could no longer be found on "
                f"disk and has been reset to \"None\". You can pick a new one "
                f"in Settings → Sounds.")

    # ------------------------------------------------------------------
    # Sidebar rail (Session 14, polished in Session 14.5) — replaces the
    # old top QTabWidget + title/subtitle top bar. Fixed-width rail:
    # icon-only brand mark, one icon-over-label nav row per page
    # destination, a divider, then Guide (an action, not a page — kept
    # visually distinct from the page nav rows above it), then the
    # ComfyUI status/connect footer at the very bottom. The top-right
    # strip that used to hold Guide + the theme toggle is gone entirely
    # as of 14.5: Guide moved down into this rail, and the theme toggle
    # has no UI at all until Session 19 formally gives it one on the
    # Settings page (see `toggle_theme`/`_refresh_theme_icon`'s own
    # notes — the logic is intentionally still intact and callable,
    # just currently unwired to any button).
    # ------------------------------------------------------------------
    _NAV_ITEMS = (
        ("🛠", "Builder"),
        ("📚", "Library"),
        ("🕘", "History"),
        ("🖼", "Gallery"),
        ("⚙️", "LoRA"),
        ("🔧", "Settings"),
    )

    def _build_sidebar(self) -> QFrame:
        rail = QFrame()
        rail.setObjectName("SidebarRail")
        rail.setFixedWidth(92)
        col = QVBoxLayout(rail)
        col.setContentsMargins(6, 14, 6, 10)
        col.setSpacing(2)

        # Session 48.2: the static "⚡" brand label is now the
        # pipeline-mode switch — clicking it cycles T2I/I2I/I2V from
        # ANYWHERE in the app (not just while Builder is the visible
        # tab), per your own clarification that this needed to work
        # while e.g. Library is open, not just double as "go to
        # Builder" (which the separate 🛠 Builder nav button below
        # already does, unchanged). Taller than a standard SidebarNav
        # button (`setMinimumHeight(64)` vs. the nav rows' 50) so the
        # short mode caption underneath the icon has room to actually
        # be legible, per your own ASCII sketch of icon-then-caption.
        self.btn_sidebar_mode_switch = QPushButton()
        self.btn_sidebar_mode_switch.setObjectName("SidebarModeSwitch")
        self.btn_sidebar_mode_switch.setFlat(True)
        self.btn_sidebar_mode_switch.setMinimumHeight(64)
        self.btn_sidebar_mode_switch.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        self.btn_sidebar_mode_switch.clicked.connect(self._on_sidebar_mode_switch_clicked)
        col.addWidget(self.btn_sidebar_mode_switch)
        # Initial caption/tooltip: Builder hasn't necessarily run its
        # own _apply_pipeline_mode() sync yet at this exact point in
        # __init__ (tab construction order) — update_sidebar_mode_caption
        # is called for real once `self.tab_builder.main_window = self`
        # is wired up further down, same pattern as the 48.1 Library
        # sync fix. This first call just avoids the button sitting
        # completely blank before that happens.
        self.update_sidebar_mode_caption(PIPELINE_MODE_T2I)
        col.addSpacing(12)

        # ---- Page nav rows: icon over label, not icon beside label
        # (Session 14.5 step 1) — reads closer to the Frankenstein
        # mockup's icon-forward language and leaves room in this same
        # fixed width for future destinations, per your count of the
        # sidebar's free vertical space. ----
        self.nav_buttons: list[QPushButton] = []
        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        for icon, label in self._NAV_ITEMS:
            btn = QPushButton(f"{icon}\n{label}")
            btn.setObjectName("SidebarNav")
            btn.setCheckable(True)
            btn.setFlat(True)
            btn.setMinimumHeight(50)
            btn.clicked.connect(lambda _checked, i=len(self.nav_buttons): self._on_nav_clicked(i))
            self._nav_group.addButton(btn)
            self.nav_buttons.append(btn)
            col.addWidget(btn)
        self.nav_buttons[0].setChecked(True)

        col.addStretch(1)

        # ---- Guide: bottom of the nav list, below Settings (Session
        # 14.5 step 4) — an action (opens a dialog), not a page swap,
        # so it's not part of the exclusive nav QButtonGroup above and
        # gets a thin divider to read as visually separate. ----
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setObjectName("SidebarDivider")
        col.addWidget(divider)

        self.btn_guide = QPushButton("❓\nGuide")
        self.btn_guide.setObjectName("SidebarNav")
        self.btn_guide.setFlat(True)
        self.btn_guide.setMinimumHeight(50)
        self.btn_guide.setToolTip("Open the in-app guide (F1)")
        self.btn_guide.clicked.connect(self.open_guide)
        col.addWidget(self.btn_guide)

        # ---- ComfyUI status + Run/Disconnect button (Session 14,
        # shrunk in 14.5 step 2 — this was reading as a primary action
        # button; it's a secondary/status control now) ----
        footer = QFrame()
        footer.setObjectName("SidebarComfyFooter")
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(6, 14, 6, 10)
        footer_layout.setSpacing(8)

        self.lbl_sidebar_comfy_dot = QLabel("Disconnected")
        self.lbl_sidebar_comfy_dot.setObjectName("dim")
        self.lbl_sidebar_comfy_dot.setWordWrap(True)
        self.lbl_sidebar_comfy_dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Micro-fix: "Connected" fit the 80px-wide footer at the default
        # size, "Disconnected" (3 chars longer) didn't and clipped past
        # the rail edge — a couple points smaller keeps both states
        # inside the same box instead of only fixing the common case.
        self.lbl_sidebar_comfy_dot.setStyleSheet("font-size: 10px;")
        footer_layout.addWidget(self.lbl_sidebar_comfy_dot)

        self.btn_sidebar_comfy = QPushButton("Run")
        self.btn_sidebar_comfy.setObjectName("SidebarComfyBtn")
        self.btn_sidebar_comfy.setToolTip("Connect to ComfyUI (host/port from Settings)")
        # Micro-fix (carried over from the unsuccessful attempt noted in
        # Session 14.5): a plain, non-flat QPushButton doesn't stretch to
        # fill a QVBoxLayout's width the way the flat SidebarNav buttons
        # do -- it sizes itself to its own text and sits with dead space
        # around it inside the footer card. Explicit Expanding policy
        # makes it match the status label's width instead of floating
        # undersized in the corner.
        self.btn_sidebar_comfy.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.btn_sidebar_comfy.clicked.connect(self._on_sidebar_comfy_clicked)
        footer_layout.addWidget(self.btn_sidebar_comfy)

        col.addWidget(footer)
        return rail

    def _build_settings_page(self) -> QWidget:
        """Session 19: real Settings page. Two sections today —
        ComfyUI connection (host/port, moved out of Builder's old
        "4. ComfyUI" panel) and Appearance (the theme toggle, which
        has had working logic since Session 14.5 with no UI attached
        until now) — plus a labeled placeholder for whatever gets added
        later, so future settings have an obvious home instead of
        landing on whichever tab is convenient at the time.

        Guide's own language setting deliberately does **not** get a
        control here — it already has one inside `GuideDialog` itself,
        and Guide's entry point is a sidebar nav action, not a page
        this settings surface owns.
        """
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(18)

        lbl_title = QLabel("🔧  Settings")
        lbl_title.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        outer.addWidget(lbl_title)

        # ---- ComfyUI connection ----
        comfy_card = QFrame()
        comfy_card.setObjectName("Card")
        comfy_card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        comfy_col = QVBoxLayout(comfy_card)
        comfy_col.setContentsMargins(16, 14, 16, 14)
        comfy_col.setSpacing(8)

        lbl_comfy_heading = QLabel("ComfyUI connection")
        lbl_comfy_heading.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        comfy_col.addWidget(lbl_comfy_heading)

        host_row = QHBoxLayout()
        host_row.addWidget(QLabel("Host:"))
        self.settings_ent_host = QLineEdit(self.settings.get("comfy_host", COMFY_DEFAULT_HOST))
        self.settings_ent_host.editingFinished.connect(self._on_settings_host_changed)
        host_row.addWidget(self.settings_ent_host, 1)
        host_row.addWidget(QLabel("Port:"))
        self.settings_ent_port = QLineEdit(str(self.settings.get("comfy_port", COMFY_DEFAULT_PORT)))
        self.settings_ent_port.setFixedWidth(70)
        self.settings_ent_port.editingFinished.connect(self._on_settings_port_changed)
        host_row.addWidget(self.settings_ent_port)
        comfy_col.addLayout(host_row)

        lbl_comfy_note = QLabel(
            "Used by the Run/Disconnect button in the sidebar footer.")
        lbl_comfy_note.setObjectName("dim")
        lbl_comfy_note.setWordWrap(True)
        comfy_col.addWidget(lbl_comfy_note)

        outer.addWidget(comfy_card)

        # ---- Appearance ----
        appearance_card = QFrame()
        appearance_card.setObjectName("Card")
        appearance_card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        appearance_col = QVBoxLayout(appearance_card)
        appearance_col.setContentsMargins(16, 14, 16, 14)
        appearance_col.setSpacing(8)

        lbl_appearance_heading = QLabel("Appearance")
        lbl_appearance_heading.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        appearance_col.addWidget(lbl_appearance_heading)

        theme_row = QHBoxLayout()
        theme_row.addWidget(QLabel("Theme:"))
        self.radio_theme_dark = QRadioButton("🌙 Dark")
        self.radio_theme_light = QRadioButton("☀️ Light")
        self.radio_theme_custom = QRadioButton("🎨 Custom")
        self._theme_radio_group = QButtonGroup(self)
        self._theme_radio_group.addButton(self.radio_theme_dark)
        self._theme_radio_group.addButton(self.radio_theme_light)
        self._theme_radio_group.addButton(self.radio_theme_custom)
        {"dark": self.radio_theme_dark, "light": self.radio_theme_light,
         "custom": self.radio_theme_custom}[self.theme_name].setChecked(True)
        self.radio_theme_dark.toggled.connect(lambda checked: checked and self._set_theme("dark"))
        self.radio_theme_light.toggled.connect(lambda checked: checked and self._set_theme("light"))
        self.radio_theme_custom.toggled.connect(lambda checked: checked and self._set_theme("custom"))
        theme_row.addWidget(self.radio_theme_dark)
        theme_row.addWidget(self.radio_theme_light)
        theme_row.addWidget(self.radio_theme_custom)
        theme_row.addStretch(1)
        appearance_col.addLayout(theme_row)

        # Session 39: Custom theme controls -- Base/Accent color swatches
        # plus a light/dark ladder-direction toggle. Always present (not
        # built only when Custom is picked), just disabled otherwise --
        # simpler than tearing the row down and rebuilding it every time
        # the radio selection changes.
        #
        # Follow-up: plain flat-colored buttons didn't read as
        # clickable at all (flagged against a screenshot) -- each swatch
        # now shows a small "✎" edit-pencil glyph (in whichever of
        # black/white contrasts against its own color, so it stays
        # legible on any pick), a pointer cursor, and a tooltip naming
        # the action, plus a visible hover/pressed state via
        # `#ColorSwatchBtn` in the QSS itself so it re-themes correctly.
        custom_row = QHBoxLayout()
        custom_row.addWidget(QLabel("  Base:"))
        self.btn_custom_base = self._build_color_swatch(
            "custom_theme_base", "Click to choose the Custom theme's Base color")
        custom_row.addWidget(self.btn_custom_base)

        custom_row.addWidget(QLabel("Accent:"))
        self.btn_custom_accent = self._build_color_swatch(
            "custom_theme_accent", "Click to choose the Custom theme's Accent color")
        custom_row.addWidget(self.btn_custom_accent)


        self.radio_custom_mode_dark = QRadioButton("Dark-leaning")
        self.radio_custom_mode_light = QRadioButton("Light-leaning")
        custom_mode_group = QButtonGroup(self)
        custom_mode_group.addButton(self.radio_custom_mode_dark)
        custom_mode_group.addButton(self.radio_custom_mode_light)
        (self.radio_custom_mode_dark if self.settings.get("custom_theme_mode", "dark") == "dark"
         else self.radio_custom_mode_light).setChecked(True)
        self.radio_custom_mode_dark.toggled.connect(
            lambda checked: checked and self._on_custom_mode_changed("dark"))
        self.radio_custom_mode_light.toggled.connect(
            lambda checked: checked and self._on_custom_mode_changed("light"))
        custom_row.addWidget(self.radio_custom_mode_dark)
        custom_row.addWidget(self.radio_custom_mode_light)
        custom_row.addStretch(1)
        appearance_col.addLayout(custom_row)

        # Session 40: optional background image, carried *by* the
        # Custom theme (not a fourth theme type) — an upload button, a
        # fit-mode combo, a Remove button, and an opacity/dimming
        # slider. Same "always present, disabled unless Custom" pattern
        # as the Base/Accent row above.
        bg_row = QHBoxLayout()
        bg_row.addWidget(QLabel("  Background:"))
        self.btn_custom_bg_upload = QPushButton("Upload image…")
        self.btn_custom_bg_upload.clicked.connect(self._pick_background_image)
        bg_row.addWidget(self.btn_custom_bg_upload)

        self.combo_custom_bg_fit = QComboBox()
        for mode in BACKGROUND_FIT_MODES:
            self.combo_custom_bg_fit.addItem(BACKGROUND_FIT_LABELS[mode], mode)
        target = self.combo_custom_bg_fit.findData(
            self.settings.get("custom_theme_bg_fit", DEFAULT_BACKGROUND_FIT))
        self.combo_custom_bg_fit.setCurrentIndex(target if target >= 0 else 0)
        self.combo_custom_bg_fit.activated.connect(self._on_bg_fit_changed)
        bg_row.addWidget(self.combo_custom_bg_fit)

        self.btn_custom_bg_clear = QPushButton("Remove")
        self.btn_custom_bg_clear.clicked.connect(self._clear_background_image)
        bg_row.addWidget(self.btn_custom_bg_clear)

        bg_row.addWidget(QLabel("Brightness:"))
        self.slider_custom_bg_opacity = QSlider(Qt.Orientation.Horizontal)
        self.slider_custom_bg_opacity.setRange(0, 100)
        self.slider_custom_bg_opacity.setFixedWidth(90)
        self.slider_custom_bg_opacity.setValue(
            self.settings.get("custom_theme_bg_opacity", DEFAULT_BACKGROUND_OPACITY))
        self.slider_custom_bg_opacity.setToolTip(
            "Optional dimming over the background image. No automatic "
            "legibility protection is applied — an unreadable pairing "
            "is on you, same as the image choice itself.")
        self.slider_custom_bg_opacity.valueChanged.connect(self._on_bg_opacity_changed)
        bg_row.addWidget(self.slider_custom_bg_opacity)
        bg_row.addStretch(1)
        appearance_col.addLayout(bg_row)

        # Session 40.1: card translucency + background blur — both are
        # cosmetic add-ons on top of the background image (no visible
        # effect without one set), kept on their own row since the
        # upload row above was already getting crowded.
        bg_row2 = QHBoxLayout()
        bg_row2.addWidget(QLabel("  Card opacity:"))
        self.slider_custom_card_alpha = QSlider(Qt.Orientation.Horizontal)
        self.slider_custom_card_alpha.setRange(20, 100)
        self.slider_custom_card_alpha.setFixedWidth(90)
        self.slider_custom_card_alpha.setValue(
            self.settings.get("custom_theme_card_alpha", DEFAULT_CARD_ALPHA))
        self.slider_custom_card_alpha.setToolTip(
            "How see-through cards/panels are over the background image. "
            "100 = fully opaque (unchanged). Text and borders always "
            "stay fully opaque for legibility — only surface fills are "
            "affected.")
        self.slider_custom_card_alpha.valueChanged.connect(self._on_card_alpha_changed)
        bg_row2.addWidget(self.slider_custom_card_alpha)

        bg_row2.addWidget(QLabel("Blur:"))
        self.slider_custom_bg_blur = QSlider(Qt.Orientation.Horizontal)
        self.slider_custom_bg_blur.setRange(0, MAX_BACKGROUND_BLUR)
        self.slider_custom_bg_blur.setFixedWidth(90)
        self.slider_custom_bg_blur.setValue(
            self.settings.get("custom_theme_bg_blur", DEFAULT_BACKGROUND_BLUR))
        self.slider_custom_bg_blur.setToolTip(
            "Blurs the background image itself (computed once per change, "
            "not per frame — pairs well with a lower Card opacity for a "
            "frosted-glass look). Recomputes ~300ms after you stop "
            "moving it, not on every tick: a 4K image can take over a "
            "second to re-blur, so applying it live would make the "
            "slider itself feel laggy.")
        self._bg_blur_debounce = QTimer(self)
        self._bg_blur_debounce.setSingleShot(True)
        self._bg_blur_debounce.setInterval(300)
        self._bg_blur_debounce.timeout.connect(self._on_bg_blur_committed)
        self.slider_custom_bg_blur.valueChanged.connect(self._on_bg_blur_dragged)
        bg_row2.addWidget(self.slider_custom_bg_blur)
        bg_row2.addStretch(1)
        appearance_col.addLayout(bg_row2)

        self._refresh_custom_theme_controls_enabled()

        outer.addWidget(appearance_card)

        # ---- Sounds (Session 37) ----
        sounds_card = QFrame()
        sounds_card.setObjectName("Card")
        sounds_card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        sounds_col = QVBoxLayout(sounds_card)
        sounds_col.setContentsMargins(16, 14, 16, 14)
        sounds_col.setSpacing(10)

        lbl_sounds_heading = QLabel("Sounds")
        lbl_sounds_heading.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        sounds_col.addWidget(lbl_sounds_heading)

        self._sound_combos = {}
        self._sound_sliders = {}
        self._sound_combo_delegates = {}
        self._sound_combo_filters = {}
        for action_key in SOUND_ACTIONS:
            row = QHBoxLayout()
            row.addWidget(QLabel(SOUND_ACTION_LABELS[action_key]), 1)

            combo = QComboBox()
            combo.setMinimumWidth(150)
            delegate = _SoundComboDelegate(combo)
            combo.setItemDelegate(delegate)
            self._sound_combos[action_key] = combo
            self._sound_combo_delegates[action_key] = delegate
            event_filter = _SoundComboDeleteFilter(combo, delegate, action_key, self)
            combo.view().viewport().installEventFilter(event_filter)
            self._sound_combo_filters[action_key] = event_filter
            row.addWidget(combo)

            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(0, 100)
            slider.setFixedWidth(90)
            self._sound_sliders[action_key] = slider
            row.addWidget(slider)

            sounds_col.addLayout(row)
            self._refresh_sound_combo(action_key)
            combo.activated.connect(lambda _i, k=action_key: self._on_sound_combo_activated(k))
            slider.valueChanged.connect(lambda v, k=action_key: self._on_sound_volume_changed(k, v))

        outer.addWidget(sounds_card)

        # ---- Placeholder for future settings ----
        placeholder_card = QFrame()
        placeholder_card.setObjectName("Card")
        placeholder_card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        placeholder_col = QVBoxLayout(placeholder_card)
        placeholder_col.setContentsMargins(16, 14, 16, 14)
        lbl_placeholder = QLabel("More settings coming later.")
        lbl_placeholder.setObjectName("dim")
        placeholder_col.addWidget(lbl_placeholder)
        outer.addWidget(placeholder_card)

        outer.addStretch(1)
        return page

    # ------------------------------------------------------------------
    # Sounds card (Session 37)
    # ------------------------------------------------------------------
    def _sound_selected(self, action_key: str) -> str:
        return self.settings.get("sounds", {}).get(action_key, {}).get("selected", "none")

    def _sound_volume(self, action_key: str, selected: str) -> int:
        from backend.constants import DEFAULT_SOUND_VOLUME
        return self.settings.get("sound_volumes", {}).get(action_key, {}).get(
            selected, DEFAULT_SOUND_VOLUME)

    def _refresh_sound_combo(self, action_key: str):
        """Rebuilds one action's dropdown from scratch: None / Default /
        every `[User N]` currently on disk / a trailing `+ Add Sound`
        row. Also syncs the volume slider's visibility+value to
        whatever ends up selected."""
        combo = self._sound_combos[action_key]
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("None", "none")
        combo.addItem("Default", "default")
        for idx, _path in sound_manager.list_custom_sounds(self.data_dir, action_key):
            combo.addItem(f"User {idx}", f"custom:{idx}")
        combo.addItem("+ Add Sound…", "__add__")

        selected = self._sound_selected(action_key)
        target_index = combo.findData(selected)
        combo.setCurrentIndex(target_index if target_index >= 0 else 0)
        combo.blockSignals(False)

        slider = self._sound_sliders[action_key]
        slider.blockSignals(True)
        slider.setEnabled(selected != "none")
        slider.setValue(self._sound_volume(action_key, selected))
        slider.blockSignals(False)

    def _on_sound_combo_activated(self, action_key: str):
        combo = self._sound_combos[action_key]
        data = combo.currentData()

        if data == "__add__":
            self._add_custom_sound(action_key)
            return

        self.settings.setdefault("sounds", {})[action_key] = {"selected": data}
        self._save_settings()
        self._refresh_sound_combo(action_key)

    def _add_custom_sound(self, action_key: str):
        """OS file picker -> copy into that action's subfolder ->
        immediately select it (no separate "select after adding"
        step, per the finalized design)."""
        path, _filter = QFileDialog.getOpenFileName(
            self, f"Choose a sound for \"{SOUND_ACTION_LABELS[action_key]}\"",
            "", "WAV files (*.wav)")
        if not path:
            self._refresh_sound_combo(action_key)  # undo the combo landing on "+ Add Sound…"
            return
        try:
            selected = sound_manager.add_custom_sound(self.data_dir, action_key, path)
        except ValueError as exc:
            QMessageBox.warning(self, "Couldn't add sound", str(exc))
            self._refresh_sound_combo(action_key)
            return

        self.settings.setdefault("sounds", {})[action_key] = {"selected": selected}
        self._save_settings()
        self._refresh_sound_combo(action_key)

    def _on_sound_volume_changed(self, action_key: str, value: int):
        selected = self._sound_selected(action_key)
        if selected == "none":
            return
        volumes = self.settings.setdefault("sound_volumes", {})
        volumes.setdefault(action_key, {})[selected] = value
        self._save_settings()

    def _delete_custom_sound_by_idx(self, action_key: str, idx: int):
        """Deletes a specific `custom:N` sound, identified by clicking
        its x inside the dropdown -- not necessarily the one currently
        selected, since the popup lets you delete any entry in the
        list without selecting it first."""
        sound_manager.delete_custom_sound(self.data_dir, action_key, idx)
        selected = self._sound_selected(action_key)
        if selected == f"custom:{idx}":
            # Removing the file it was pointing at -> falls back to
            # "none", same rule as the missing-file handling at
            # play-time.
            self.settings.setdefault("sounds", {})[action_key] = {"selected": "none"}
            self._save_settings()
        self._refresh_sound_combo(action_key)

    def _on_settings_host_changed(self):
        host = self.settings_ent_host.text().strip() or COMFY_DEFAULT_HOST
        self.settings_ent_host.setText(host)
        self.settings["comfy_host"] = host
        self._save_settings()

    def _on_settings_port_changed(self):
        text = self.settings_ent_port.text().strip()
        try:
            port = int(text) if text else COMFY_DEFAULT_PORT
        except ValueError:
            QMessageBox.warning(self, "Invalid port", "Port must be a number.")
            self.settings_ent_port.setText(str(self.settings.get("comfy_port", COMFY_DEFAULT_PORT)))
            return
        self.settings_ent_port.setText(str(port))
        self.settings["comfy_port"] = port
        self._save_settings()

    def _active_colors(self) -> dict:
        """Session 39: the colors dict actually in effect right now --
        a plain `THEMES` lookup for "dark"/"light", or a freshly derived
        palette for "custom" (never cached, since Base/Accent/mode can
        change independently of `theme_name` itself while Custom is
        already selected -- see `_preview_custom_color`)."""
        if self.theme_name == "custom":
            return derive_palette(
                self.settings.get("custom_theme_base", THEMES["dark"]["bg"]),
                self.settings.get("custom_theme_accent", THEMES["dark"]["accent"]),
                self.settings.get("custom_theme_mode", "dark"),
            )
        return THEMES[self.theme_name]

    def _apply_theme_colors(self, colors: dict = None):
        """Pushes a colors dict to every themed surface. Defaults to
        `_active_colors()` (the persisted/selected theme) but also
        accepts an explicit dict so a color-picker's live preview can
        push an in-progress pick without touching `self.settings` yet
        (see `_preview_custom_color`).

        Session 40.1: when the Custom theme has a background image
        active, cards/surfaces get run through `apply_surface_alpha`
        first so they read as translucent over it — the "Card opacity"
        slider. Title bar and the `BackgroundSurface` fallback fill
        stay fully opaque regardless (chrome, not a card; and the
        fallback fill is the bottom-most layer, translucency there
        would just show the window manager's own backdrop, not
        anything meaningful)."""
        if colors is None:
            colors = self._active_colors()
        has_bg_image = self.theme_name == "custom" and bool(
            theme_background.resolve_background_path(self.settings.get("custom_theme_bg_image")))
        card_alpha = self.settings.get("custom_theme_card_alpha", DEFAULT_CARD_ALPHA)
        qss_colors = apply_surface_alpha(colors, card_alpha) if has_bg_image else colors
        if has_bg_image:
            # See theme.py's Session 40.1 follow-up note on
            # `#PromptOutputPage`/`::pane`: those two are fully hidden
            # behind the actual `QPlainTextEdit`, so giving them a
            # translucent `bg_alt` too would stack a second alpha blend
            # underneath the text edit's own -- this key lets those two
            # specific rules opt out and stay solid.
            qss_colors["bg_alt_solid"] = colors["bg_alt"]
        apply_theme(QApplication.instance(), qss_colors)
        self.title_bar.set_colors(colors)
        self._refresh_theme_icon()
        self.tab_builder.set_colors(qss_colors)
        self.tab_library.set_colors(qss_colors)
        self.tab_gallery.set_colors(qss_colors)
        self._refresh_background_surface(colors)

    def _refresh_background_surface(self, colors: dict):
        """Session 40: the central `BackgroundSurface`'s flat fallback
        fill always tracks the active theme's `bg`, so switching
        Dark/Light/Custom (or dragging a live Base preview) never leaves
        a stale color showing through. The image itself is only ever
        shown for the Custom theme — it's a property *of* that theme,
        not a fourth mode — so Dark/Light always clear it regardless of
        what's saved in settings."""
        self.central.set_bg_color(colors.get("bg", THEMES["dark"]["bg"]))
        if self.theme_name == "custom":
            stored = theme_background.resolve_background_path(
                self.settings.get("custom_theme_bg_image"))
            self.central.set_background(
                stored,
                self.settings.get("custom_theme_bg_fit", DEFAULT_BACKGROUND_FIT),
                self.settings.get("custom_theme_bg_opacity", DEFAULT_BACKGROUND_OPACITY),
                self.settings.get("custom_theme_bg_blur", DEFAULT_BACKGROUND_BLUR),
            )
        else:
            stored = None
            self.central.set_background(None)
        # Bug found in testing: `content`/`page_col` are plain QWidgets,
        # and the app-wide `QWidget { background-color: ... }` rule in
        # theme.py paints them fully opaque with zero margin/spacing
        # between them and the sidebar/stack — so the central
        # BackgroundSurface never actually showed through anywhere, even
        # with a real image successfully loaded (it silently "worked"
        # underneath two solid layers). A widget-level `setStyleSheet`
        # naturally wins over the app-wide QSS (same precedent as
        # `#ColorSwatchBtn`), so toggle these two specific surfaces
        # transparent only when there's an actual image to show through
        # them — sidebar and every card keep their own opaque
        # backgrounds either way, only the page's own margins/gaps (and
        # the sliver around the sidebar) end up showing the image.
        transparent = "background: transparent;"
        if stored:
            self.content_surface.setStyleSheet(transparent)
            self.page_col.setStyleSheet(transparent)
        else:
            self.content_surface.setStyleSheet("")
            self.page_col.setStyleSheet("")

    def _set_theme(self, theme_name: str):
        """Sets the theme to a specific target, used by the Settings
        page's Dark/Light/Custom radio group. `toggle_theme` (still used
        nowhere else, kept intact per Session 14.5's note) now just
        calls this with the flipped value."""
        if theme_name == self.theme_name:
            return
        self.theme_name = theme_name
        self._apply_theme_colors()
        self.settings["theme"] = self.theme_name
        self._save_settings()
        self._refresh_custom_theme_controls_enabled()

    def _build_color_swatch(self, key: str, tooltip: str) -> QPushButton:
        """Builds one Base/Accent color-swatch button: filled with the
        current value of `settings[key]`, a small edit-pencil glyph in
        whichever of black/white contrasts against that fill, a pointer
        cursor, and a tooltip -- so it reads as clickable regardless of
        which color happens to be picked."""
        btn = QPushButton("✎")
        btn.setObjectName("ColorSwatchBtn")
        btn.setFixedSize(32, 24)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setToolTip(tooltip)
        self._recolor_swatch(btn, self.settings.get(key, "#7c8cff"))
        btn.clicked.connect(lambda: self._pick_custom_color(key, btn))
        return btn

    @staticmethod
    def _recolor_swatch(btn: QPushButton, hex_color: str):
        glyph_color = "#ffffff" if contrast_ratio(hex_color, "#ffffff") >= contrast_ratio(hex_color, "#000000") else "#000000"
        btn.setStyleSheet(
            f"QPushButton#ColorSwatchBtn {{ background-color: {hex_color}; color: {glyph_color}; "
            f"border: 1px solid rgba(128,128,128,0.6); border-radius: 5px; font-weight: 700; }}"
            f"QPushButton#ColorSwatchBtn:hover {{ border: 2px solid {glyph_color}; }}"
        )

    def _preview_custom_color(self, key: str, color: QColor):
        """Live-preview hook for the Base/Accent `QColorDialog`s'
        `currentColorChanged` signal. Doesn't apply immediately --
        `currentColorChanged` fires on every pixel of a wheel/slider
        drag, and a full QSS rebuild+reapply per pixel is the visible
        lag reported against the first pass of this feature. Instead
        just records the latest pick and (re)starts a short throttle
        timer; `_apply_pending_custom_preview` does the actual work, at
        most once per `_PREVIEW_THROTTLE_MS`. No-op while Custom isn't
        the active theme, so opening a picker can't flash the wrong
        colors in."""
        if self.theme_name != "custom":
            return
        self._pending_custom_preview = (key, color)
        self._custom_preview_timer.start(self._PREVIEW_THROTTLE_MS)

    def _apply_pending_custom_preview(self):
        """Timer-driven follow-up to `_preview_custom_color` -- the one
        place that actually rebuilds/reapplies the QSS during a drag.
        Doesn't write to `self.settings` yet, so canceling the dialog
        leaves the persisted theme untouched (`_apply_theme_colors()`
        with no args re-derives from the still-unmodified settings on
        cancel/accept, in `_pick_custom_color`)."""
        if self._pending_custom_preview is None or self.theme_name != "custom":
            return
        key, color = self._pending_custom_preview
        base = color.name() if key == "custom_theme_base" else self.settings.get(
            "custom_theme_base", THEMES["dark"]["bg"])
        accent = color.name() if key == "custom_theme_accent" else self.settings.get(
            "custom_theme_accent", THEMES["dark"]["accent"])
        mode = self.settings.get("custom_theme_mode", "dark")
        self._apply_theme_colors(derive_palette(base, accent, mode))

    def _pick_custom_color(self, key: str, swatch: QPushButton):
        initial = QColor(self.settings.get(key, "#7c8cff"))
        dlg = QColorDialog(initial, self)
        dlg.currentColorChanged.connect(lambda c: self._preview_custom_color(key, c))
        dlg.currentColorChanged.connect(lambda c: self._recolor_swatch(swatch, c.name()))
        result = dlg.exec()
        # The dialog is closing either way -- stop any still-pending
        # throttled preview frame from `_preview_custom_color` so it
        # can't apply a now-stale in-drag color after this method has
        # already moved on to the committed-or-reverted state below.
        self._custom_preview_timer.stop()
        self._pending_custom_preview = None
        if result:
            color = dlg.selectedColor()
            if color.isValid():
                self.settings[key] = color.name()
                self._save_settings()
        # Either accepted (re-derive from the now-saved value) or
        # canceled (re-derive from the unchanged one) -- same call
        # either way, since both cases mean "settings reflect the truth
        # again, stop showing the live preview". Also re-syncs the
        # swatch itself back to the settled value (a canceled dialog
        # otherwise leaves the swatch showing the last dragged-to color
        # via the `currentColorChanged` hookup above, not the reverted
        # one).
        if self.theme_name == "custom":
            self._apply_theme_colors()
        self._recolor_swatch(swatch, self.settings.get(key, "#7c8cff"))

    def _on_custom_mode_changed(self, mode: str):
        if self.settings.get("custom_theme_mode", "dark") == mode:
            return
        self.settings["custom_theme_mode"] = mode
        self._save_settings()
        if self.theme_name == "custom":
            self._apply_theme_colors()

    def _refresh_custom_theme_controls_enabled(self):
        is_custom = self.theme_name == "custom"
        for widget in (getattr(self, "btn_custom_base", None), getattr(self, "btn_custom_accent", None),
                       getattr(self, "radio_custom_mode_dark", None), getattr(self, "radio_custom_mode_light", None),
                       getattr(self, "btn_custom_bg_upload", None), getattr(self, "combo_custom_bg_fit", None),
                       getattr(self, "btn_custom_bg_clear", None), getattr(self, "slider_custom_bg_opacity", None),
                       getattr(self, "slider_custom_card_alpha", None), getattr(self, "slider_custom_bg_blur", None)):
            if widget is not None:
                widget.setEnabled(is_custom)

    # ------------------------------------------------------------------
    # Custom theme background image (Session 40)
    # ------------------------------------------------------------------
    def _pick_background_image(self):
        from backend.constants import BACKGROUND_IMAGE_EXTENSIONS
        exts = " ".join(f"*{e}" for e in BACKGROUND_IMAGE_EXTENSIONS)
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose a background image", "", f"Images ({exts})")
        if not path:
            return
        try:
            stored = theme_background.set_background_image(self.data_dir, path)
        except ValueError as exc:
            QMessageBox.warning(self, "Unsupported image", str(exc))
            return
        self.settings["custom_theme_bg_image"] = stored
        self._save_settings()
        if self.theme_name == "custom":
            self._apply_theme_colors()

    def _clear_background_image(self):
        if not self.settings.get("custom_theme_bg_image"):
            return
        theme_background.clear_background_image(self.data_dir)
        self.settings["custom_theme_bg_image"] = None
        self._save_settings()
        if self.theme_name == "custom":
            self._apply_theme_colors()

    def _on_bg_fit_changed(self, _index: int):
        mode = self.combo_custom_bg_fit.currentData()
        self.settings["custom_theme_bg_fit"] = mode
        self._save_settings()
        if self.theme_name == "custom":
            self._apply_theme_colors()

    def _on_bg_opacity_changed(self, value: int):
        self.settings["custom_theme_bg_opacity"] = value
        self._save_settings()
        if self.theme_name == "custom":
            self._apply_theme_colors()

    def _on_card_alpha_changed(self, value: int):
        self.settings["custom_theme_card_alpha"] = value
        self._save_settings()
        if self.theme_name == "custom":
            self._apply_theme_colors()

    def _on_bg_blur_dragged(self, value: int):
        # Cheap: just remembers the value so the slider's own position/
        # label stay in sync while dragging. The expensive Pillow blur
        # only runs in `_on_bg_blur_committed`, ~300ms after the last
        # change (restarted on every tick, including keyboard/wheel
        # steps, not just mouse drag) — a plain `sliderReleased` would
        # miss keyboard-arrow adjustments entirely.
        self.settings["custom_theme_bg_blur"] = value
        self._bg_blur_debounce.start()

    def _on_bg_blur_committed(self):
        self._save_settings()
        if self.theme_name == "custom":
            self._apply_theme_colors()

    def _on_nav_clicked(self, index: int):
        if self.stack.currentWidget() is self.tab_library and self.stack.widget(index) is not self.tab_library:
            self.tab_library.clear_lora_dependency_colors()
        self.stack.setCurrentIndex(index)

    # ------------------------------------------------------------------
    # Sidebar pipeline-mode switch (Session 48.2)
    # ------------------------------------------------------------------
    def _on_sidebar_mode_switch_clicked(self):
        """Deliberately does NOT navigate to the Builder tab — that's
        the separate 🛠 Builder nav button's own unchanged job, per
        your own clarification that this control needs to work from
        any tab (e.g. narrowing Library's category bar back down while
        Library itself is what's on screen). Just cycles
        `BuilderTab.pipeline_mode` directly; `_apply_pipeline_mode`
        (already fixed in 48.1 to actually reach Library whenever it's
        called) takes care of everything downstream, including calling
        back into `update_sidebar_mode_caption` below."""
        self.tab_builder._cycle_pipeline_mode()

    def update_sidebar_mode_caption(self, pipeline_mode: str):
        """Called by `BuilderTab._apply_pipeline_mode` every time the
        mode changes (including its very first call, during
        `BuilderTab.__init__`, before this window exists yet — guarded
        the same `hasattr`/`is not None` way `library_tab`'s own sync
        already is). Short caption under the icon (`PIPELINE_MODE_SHORT_LABELS`
        — a sidebar button has room for "T2I", not "Text → Image"); the
        long form (`PIPELINE_MODE_LABELS`) goes on the tooltip instead,
        so hovering still tells the whole story."""
        short = PIPELINE_MODE_SHORT_LABELS.get(pipeline_mode, pipeline_mode)
        long = PIPELINE_MODE_LABELS.get(pipeline_mode, pipeline_mode)
        self.btn_sidebar_mode_switch.setText(f"⚡\n{short}")
        self.btn_sidebar_mode_switch.setToolTip(f"Pipeline mode: {long}\nClick to switch")

    # Session 46.2 follow-up: `_on_builder_request_open_library_tools`
    # removed along with `BuilderTab.request_open_library_tools` -- the
    # "Browse Tools & Actions in Library" hint button that fired it is
    # gone, superseded by the real inline Actions slot list built
    # directly in Builder. (The old method body also had a latent bug
    # -- an undefined `index` -- that's moot now it's gone.)

    # ------------------------------------------------------------------
    # Sidebar <-> BuilderTab ComfyUI status mirroring (Session 14)
    # ------------------------------------------------------------------
    def _on_sidebar_comfy_clicked(self):
        self.tab_builder.sidebar_request_comfy_toggle()

    def _refresh_sidebar_comfy_status(self):
        """Single choke point for the sidebar footer's status text —
        state-driven from `comfy_connected`/`comfy_check_busy` rather
        than mirroring Builder's own `lbl_comfy_status` verbatim.
        Session 14.5 step 3: the sidebar doesn't need workflow-detail
        text ("— graph ready", warning specifics) alongside the status —
        Builder's own ComfyUI panel still shows that detail, and real
        errors already surface via `QMessageBox.critical` on failure.
        Session 15 fix: no dot glyph anymore — color alone (green text
        for Connected, dim default otherwise) reads clearly enough on
        its own without an extra bullet."""
        if self.tab_builder.comfy_check_busy:
            text, style_name = "Checking…", "dim"
        elif self.tab_builder.comfy_connected:
            text, style_name = "Connected", "success"
        else:
            text, style_name = "Disconnected", "dim"
        self.lbl_sidebar_comfy_dot.setText(text)
        if self.lbl_sidebar_comfy_dot.objectName() != style_name:
            self.lbl_sidebar_comfy_dot.setObjectName(style_name)
            style = self.lbl_sidebar_comfy_dot.style()
            style.unpolish(self.lbl_sidebar_comfy_dot)
            style.polish(self.lbl_sidebar_comfy_dot)

    def _on_comfy_connection_changed(self, connected: bool):
        self.btn_sidebar_comfy.setText("Disconnect" if connected else "Run")
        self._refresh_sidebar_comfy_status()

    def _on_comfy_status_message(self, _text: str):
        # No longer mirrored verbatim (Session 14.5 step 3) — connection
        # state and busy state alone drive the sidebar's text now. This
        # handler stays connected (rather than disconnected in main.py)
        # so a future session can reintroduce detail without re-wiring
        # signals, but it's currently a no-op beyond a state refresh.
        self._refresh_sidebar_comfy_status()

    def _on_comfy_check_busy_changed(self, busy: bool):
        self.btn_sidebar_comfy.setEnabled(not busy)
        self._refresh_sidebar_comfy_status()

    def _refresh_theme_icon(self):
        # Session 14.5: the theme button moved out of the top-right
        # strip and has no replacement UI yet — Session 19 wires a real
        # control on the Settings page to `toggle_theme()`. Guarded so
        # this stays a harmless no-op until then instead of an
        # AttributeError.
        if hasattr(self, "btn_theme"):
            is_dark = self.theme_name == "dark" or (
                self.theme_name == "custom" and self.settings.get("custom_theme_mode", "dark") == "dark")
            self.btn_theme.setText("🌙" if is_dark else "☀️")

    def toggle_theme(self):
        """Kept as a plain flip-whatever-it-is-now entry point (no
        current caller since the Settings page's Dark/Light radios call
        `_set_theme` with an explicit target instead, per Session 19) —
        `_set_theme` now owns the actual work, including the Library
        drop zone's manual color refresh."""
        self._set_theme("light" if self.theme_name == "dark" else "dark")

    def _save_settings(self):
        try:
            save_json(self.settings_file, self.settings)
        except FileManagerError as exc:
            QMessageBox.critical(self, "Error", str(exc))

    def open_guide(self):
        dlg = GuideDialog(self.settings, self.settings_file, self._active_colors(), parent=self)
        dlg.exec()

    # ------------------------------------------------------------------
    def closeEvent(self, event):
        """Session 33: `_comfy_previews/` was only ever wiped on the
        *next* startup (`init_folders`), never on the way out — so
        leftover preview files sit visible in the data folder for the
        whole gap between closing the app and relaunching it. This is
        belt-and-suspenders with that existing startup wipe, not a
        replacement for it: wipes the same disposable cache here too,
        so it reads as empty immediately on close as well. Best-effort
        only — a locked/in-use file shouldn't block shutdown, so
        failures here are swallowed the same way `init_folders`
        already swallows them."""
        previews_dir = os.path.join(self.data_dir, "_comfy_previews")
        if os.path.exists(previews_dir):
            try:
                shutil.rmtree(previews_dir)
            except OSError:
                pass

        # Session 49 audit fix: a mid-generation (or mid-connection-check)
        # app close previously left `ComfyGenerationWorker`/`ComfyCheckWorker`
        # running as an orphaned QThread. Its `run()` would keep executing
        # after the main window (and its widgets) started tearing down, and
        # its signals -- connected to BuilderTab slots that touch widgets --
        # could fire into a partially-destroyed UI. Both workers' `stop()`
        # (generation) sets a cancel flag and best-effort notifies ComfyUI;
        # for the check worker there's no cancel hook (it's a short-lived
        # HTTP round trip), so we just wait for it. Either way we block here
        # briefly rather than let Qt tear down widgets out from under a
        # still-running thread.
        self._shutdown_comfy_workers()
        super().closeEvent(event)

    def _shutdown_comfy_workers(self):
        """Best-effort, bounded wait for BuilderTab's ComfyUI worker
        threads so none are still running when this window (and its
        widgets) get destroyed. Never blocks indefinitely -- a wedged
        worker shouldn't prevent the app from closing, it should just
        stop being able to safely touch UI."""
        tab_builder = getattr(self, "tab_builder", None)
        if tab_builder is None:
            return

        gen_worker = getattr(tab_builder, "_gen_worker", None)
        if gen_worker is not None and gen_worker.isRunning():
            try:
                gen_worker.stop()
            except Exception:
                pass
            gen_worker.wait(3000)

        check_worker = getattr(tab_builder, "_check_worker", None)
        if check_worker is not None and check_worker.isRunning():
            check_worker.wait(3000)

    # ------------------------------------------------------------------
    def _apply_app_icon(self):
        """Mirrors the original's `_apply_app_icon`: look for icon.ico,
        then icon.png, next to the program; silently skip if neither
        exists.

        Session 50: also sets the icon on `QApplication` itself, not
        just this window. `setWindowIcon` on the QMainWindow is enough
        on Windows/macOS, but several Linux desktop environments (GNOME
        in particular) key taskbar/dock grouping and the alt-tab icon
        off the *application's* icon rather than each window's -- so a
        window-only icon can silently show up blank in the taskbar even
        though the titlebar/alt-tab icon looks fine. Setting both is
        cheap and correct everywhere; this doesn't change behavior on
        Windows/macOS, which were already covered by the window-level
        call alone.

        Note: only `icon.ico` is currently produced by the Windows
        build step. A same-named `icon.png` needs to be dropped next to
        it (see `BUILD_LINUX.md`) for this to actually resolve to
        something on Linux -- `.ico` is a valid Qt-loadable format in
        principle, but treating `.png` as the authoritative Linux/macOS
        asset avoids relying on Qt's ICO plugin being present in every
        build environment."""
        ico_path = os.path.join(_app_root_dir(), "icon.ico")
        png_path = os.path.join(_app_root_dir(), "icon.png")
        icon = None
        if os.path.exists(ico_path):
            icon = QIcon(ico_path)
        elif os.path.exists(png_path):
            icon = QIcon(png_path)
        if icon is not None:
            self.setWindowIcon(icon)
            app = QApplication.instance()
            if app is not None:
                app.setWindowIcon(icon)

    def _size_to_screen(self):
        """Scales the default window size to the actual screen instead
        of a fixed guess, same intent as the original's screen_w/h-based
        `good_w`/`good_h` calculation. Returns the chosen (w, h) so the
        caller can remember it as the "comfortable default" to snap back
        to on maximize->restore (see `changeEvent`)."""
        screen = QApplication.primaryScreen().availableGeometry()
        good_w = max(1040, min(1480, int(screen.width() * 0.85)))
        good_h = max(680, min(980, int(screen.height() * 0.85)))
        self.resize(good_w, good_h)
        self.setMinimumSize(1040, 680)
        pos_x = max(0, (screen.width() - good_w) // 2)
        pos_y = max(0, (screen.height() - good_h) // 2)
        self.move(pos_x, pos_y)
        return (good_w, good_h)

    def _apply_computed_minsize(self):
        """Sets the window's real floor size from what the UI actually
        needs, instead of the provisional fixed `setMinimumSize(1040,
        680)` set by `_size_to_screen` before any tab existed. Ported
        from the original's `_apply_computed_minsize`: `self.tabs`'
        `sizeHint()` (the Qt equivalent of Tk's `winfo_reqwidth`/
        `winfo_reqheight` after `update_idletasks`) reports how much
        space the widget tree wants at its natural size, independent of
        the window's current size — the right basis for a floor. A
        margin is added for window chrome (title bar, borders, the top
        bar above the tabs) so the layout isn't knife-edge tight, and
        the floor is never allowed to exceed the actual screen, so a
        4K-derived requirement run on a smaller screen is still
        shrinkable rather than stuck open.
        """
        self.stack.updateGeometry()
        QApplication.processEvents()
        hint = self.stack.sizeHint()
        req_w, req_h = hint.width(), hint.height()
        if req_w <= 1 or req_h <= 1:
            return  # widgets not realized yet; keep the provisional floor

        margin_w, margin_h = 36, 80
        min_w = max(1040, req_w + margin_w)
        min_h = max(680, req_h + margin_h)

        screen = QApplication.primaryScreen().availableGeometry()
        min_w = min(min_w, max(1040, screen.width() - 40))
        min_h = min(min_h, max(680, screen.height() - 80))

        self.setMinimumSize(min_w, min_h)

        # If the window is currently sitting smaller than its own new
        # floor (e.g. a cramped size from before every tab existed to
        # measure), grow it up to the floor right away rather than
        # leaving controls clipped until the user manually resizes.
        if self.width() < min_w or self.height() < min_h:
            new_w = max(self.width(), min_w)
            new_h = max(self.height(), min_h)
            self.resize(new_w, new_h)

    # ------------------------------------------------------------------
    # Session 38: manual edge-resize (frameless windows have no OS
    # resize border). App-wide filter so it works no matter which
    # child widget the mouse happens to be over -- see the
    # `installEventFilter` call in `__init__` for why.
    # ------------------------------------------------------------------
    def _resize_edge_at(self, local_pos) -> str | None:
        if self.isMaximized():
            return None
        w, h = self.width(), self.height()
        x, y = local_pos.x(), local_pos.y()
        if not (-RESIZE_MARGIN <= x <= w + RESIZE_MARGIN and -RESIZE_MARGIN <= y <= h + RESIZE_MARGIN):
            return None
        left = x <= RESIZE_MARGIN
        right = x >= w - RESIZE_MARGIN
        top = y <= RESIZE_MARGIN
        bottom = y >= h - RESIZE_MARGIN
        if top and left:
            return "top_left"
        if top and right:
            return "top_right"
        if bottom and left:
            return "bottom_left"
        if bottom and right:
            return "bottom_right"
        if left:
            return "left"
        if right:
            return "right"
        if top:
            return "top"
        if bottom:
            return "bottom"
        return None

    _EDGE_CURSORS = {
        "left": Qt.CursorShape.SizeHorCursor, "right": Qt.CursorShape.SizeHorCursor,
        "top": Qt.CursorShape.SizeVerCursor, "bottom": Qt.CursorShape.SizeVerCursor,
        "top_left": Qt.CursorShape.SizeFDiagCursor, "bottom_right": Qt.CursorShape.SizeFDiagCursor,
        "top_right": Qt.CursorShape.SizeBDiagCursor, "bottom_left": Qt.CursorShape.SizeBDiagCursor,
    }

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            edge = self._resize_edge_at(self.mapFromGlobal(event.globalPosition().toPoint()))
            if edge:
                self._resize_edge = edge
                self._resize_start_geo = self.geometry()
                self._resize_start_pos = event.globalPosition().toPoint()
                return True
        elif event.type() == QEvent.Type.MouseMove:
            global_pos = event.globalPosition().toPoint()
            if self._resize_edge:
                self._apply_resize(global_pos)
                return True
            if not self.isMaximized():
                edge = self._resize_edge_at(self.mapFromGlobal(global_pos))
                self.setCursor(self._EDGE_CURSORS[edge]) if edge else self.unsetCursor()
        elif event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
            if self._resize_edge:
                self._resize_edge = None
                return True
        return super().eventFilter(obj, event)

    def _apply_resize(self, global_pos):
        dx = global_pos.x() - self._resize_start_pos.x()
        dy = global_pos.y() - self._resize_start_pos.y()
        geo = QRect(self._resize_start_geo)
        min_w, min_h = self.minimumWidth(), self.minimumHeight()

        if "left" in self._resize_edge:
            new_left = min(geo.left() + dx, geo.right() - min_w)
            geo.setLeft(new_left)
        elif "right" in self._resize_edge:
            geo.setRight(max(geo.right() + dx, geo.left() + min_w))

        if "top" in self._resize_edge:
            new_top = min(geo.top() + dy, geo.bottom() - min_h)
            geo.setTop(new_top)
        elif "bottom" in self._resize_edge:
            geo.setBottom(max(geo.bottom() + dy, geo.top() + min_h))

        self.setGeometry(geo)

    def changeEvent(self, event):
        """Detects the transition out of maximized (maximized -> normal)
        and snaps the window back to the same comfortable default size
        it started at, centered on screen — instead of leaving it at
        whatever size it happened to have right before it was maximized.
        Mirrors the original's `_on_root_configure`'s "zoomed -> normal"
        check, adapted to Qt's `WindowStateChange` event instead of Tk's
        `<Configure>`."""
        super().changeEvent(event)
        if event.type() != QEvent.Type.WindowStateChange:
            return
        self.title_bar.sync_maximize_icon()
        state = self.windowState()
        previous = getattr(self, "_last_window_state", state)
        self._last_window_state = state
        was_maximized = bool(previous & Qt.WindowState.WindowMaximized)
        is_normal = state == Qt.WindowState.WindowNoState
        if was_maximized and is_normal and getattr(self, "_default_window_size", None):
            w, h = self._default_window_size
            screen = QApplication.primaryScreen().availableGeometry()
            x = max(0, (screen.width() - w) // 2)
            y = max(0, (screen.height() - h) // 2)
            self.resize(w, h)
            self.move(x, y)


def _apply_native_snap_confirmation(window, window_cls):
    """Session 42, step 1: an stderr banner confirming which window
    class actually got instantiated -- see additionalfeatures.md
    SESSION 42 for the full reasoning. Session 43 cleanup: the
    `[native-snap]` title-bar/window-title tag from the original
    debug version has been removed now that Snap is confirmed working
    on real hardware and promoted to default-on (Session 42.3) --
    the stderr line alone is enough for anyone who still wants to
    confirm which class is active, without permanently showing a
    debug label in the title bar."""
    if window_cls is MainWindow:
        return
    print(
        "[PromptForge] Native Win32 Snap ENABLED — "
        "MainWindowWinSnap is active (PROMPTFORGE_ENABLE_WIN_NATIVE_SNAP set).",
        file=sys.stderr,
    )


def main():
    # HiDPI: Qt6 already high-DPI-aware by default, but set the rounding
    # policy explicitly (PassThrough — use the OS scale factor exactly,
    # no rounding to the nearest integer) before QApplication exists,
    # matching the original's `SetProcessDpiAwareness(1)` intent without
    # the Windows-only ctypes call.
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)

    # Session 42.3: promoted from opt-in to default-on for Windows, per
    # explicit request once the crash (42.1), the button-click bug, and
    # the DPI coordinate bug (both 42.2/42.3) were found and fixed on
    # real hardware. Unset (or any value other than an explicit "0"/
    # "false"/"no") now means ENABLED -- the reverse of Session 41's
    # original opt-in default. Kept as an env var (not a stored
    # setting) purely so there's still a quick manual escape hatch
    # (`PROMPTFORGE_ENABLE_WIN_NATIVE_SNAP=0`) if a future machine hits
    # a new problem, without needing a code change to fall back to the
    # plain frameless `MainWindow`.
    window_cls = MainWindow
    native_snap_flag = os.environ.get("PROMPTFORGE_ENABLE_WIN_NATIVE_SNAP", "1").lower()
    native_snap_enabled = native_snap_flag not in ("0", "false", "no")
    if sys.platform.startswith("win") and native_snap_enabled:
        from ui.win_snap import MainWindowWinSnap
        window_cls = MainWindowWinSnap

    window = window_cls()
    _apply_native_snap_confirmation(window, window_cls)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
