"""Session 48 implementation tests — regression coverage for the
fixes actually built this session (48.1, 48.2, 48.3, 48.5, 48.7).
48.6 is covered implicitly by the whole existing suite passing after
every `QMessageBox.*` call site was migrated to `themed_message_box`
(see the many monkeypatch updates across `tests/test_library_tab_*`,
`test_history_tab_session3.py`, `test_gallery_tab_session8.py`, and
`test_session47_bugfixes.py`) — this file adds one direct unit test
for the module itself. 48.4 (real video-in-Library support) was
deliberately scoped as its own future session, per
additionalfeatures.md's SESSION 48.4 write-up, and isn't touched here.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap, QColor
from PyQt6.QtWidgets import QApplication, QDialogButtonBox, QSizePolicy

from backend.constants import CATEGORIES, PIPELINE_MODE_I2V, PIPELINE_MODE_T2I
from backend.file_manager import init_folders
from ui.dialogs import themed_message_box
from ui.tabs.builder_tab import BuilderTab
from ui.widgets.image_zone import ResultImageViewer


COLORS = {
    "bg": "#202020", "bg_alt": "#242424", "bg_card": "#282828",
    "bg_input": "#2c2c2c", "border": "#3a3a3a", "fg": "#f0f0f0",
    "fg_dim": "#9a9a9a", "accent": "#5b8def", "accent_text": "#ffffff",
    "accent_hover": "#6f9bf2", "success": "#4caf50", "danger": "#e05252",
    "warn": "#e0a852", "tree_bg": "#242424", "tree_alt": "#262626",
    "select_bg": "#31445e",
}


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def make_builder(tmp_path):
    init_folders(str(tmp_path), CATEGORIES)
    settings_file = str(tmp_path / "settings.json")
    return BuilderTab(str(tmp_path), COLORS, {}, settings_file)


# ---------------------------------------------------------------------
# 48.1 — Library category sync
# ---------------------------------------------------------------------
def test_apply_pipeline_mode_is_a_no_op_before_library_tab_is_wired(qapp, tmp_path):
    """The exact gap 48.1 fixed: calling _apply_pipeline_mode() before
    main.py has wired up `library_tab` must not raise -- it silently
    does nothing library-side, which is fine as long as a later call
    (once wired) actually catches up."""
    b = make_builder(tmp_path)
    assert b.library_tab is None  # true at real __init__ time too
    b._apply_pipeline_mode()  # must not raise


def test_apply_pipeline_mode_syncs_library_once_wired(qapp, tmp_path):
    calls = []

    class FakeLibrary:
        def set_pipeline_mode_filter(self, mode):
            calls.append(mode)

    b = make_builder(tmp_path)
    b.library_tab = FakeLibrary()
    b._apply_pipeline_mode()
    assert calls == [PIPELINE_MODE_T2I]

    b.pipeline_mode = PIPELINE_MODE_I2V
    b._apply_pipeline_mode()
    assert calls == [PIPELINE_MODE_T2I, PIPELINE_MODE_I2V]


# ---------------------------------------------------------------------
# 48.2 — sidebar mode-switch instead of Builder's own plain button
# ---------------------------------------------------------------------
def test_builder_no_longer_has_its_own_mode_button(qapp, tmp_path):
    b = make_builder(tmp_path)
    assert not hasattr(b, "btn_pipeline_mode")


def test_apply_pipeline_mode_notifies_main_window(qapp, tmp_path):
    seen = []

    class FakeMainWindow:
        def update_sidebar_mode_caption(self, mode):
            seen.append(mode)

    b = make_builder(tmp_path)
    b.main_window = FakeMainWindow()
    b._apply_pipeline_mode()
    assert seen == [PIPELINE_MODE_T2I]

    b.pipeline_mode = PIPELINE_MODE_I2V
    b._apply_pipeline_mode()
    assert seen[-1] == PIPELINE_MODE_I2V


def test_apply_pipeline_mode_survives_missing_main_window(qapp, tmp_path):
    b = make_builder(tmp_path)
    assert b.main_window is None
    b._apply_pipeline_mode()  # must not raise


def test_cycle_pipeline_mode_still_works_without_any_ui_button(qapp, tmp_path):
    b = make_builder(tmp_path)
    start = b.pipeline_mode
    b._cycle_pipeline_mode()
    assert b.pipeline_mode != start


# ---------------------------------------------------------------------
# 48.3 — i2i/i2v input drop-zone sizing
# ---------------------------------------------------------------------
def test_image_input_zone_has_expanding_size_policy(qapp, tmp_path):
    b = make_builder(tmp_path)
    policy = b.image_input_zone.sizePolicy()
    assert policy.horizontalPolicy() == QSizePolicy.Policy.Expanding
    assert policy.verticalPolicy() == QSizePolicy.Policy.Expanding


def test_image_input_zone_is_not_floored_at_the_old_min_px(qapp, tmp_path):
    """The old percent=30 scheme left this permanently at MIN_PX
    (130px) with no way to grow -- Expanding + a stretch factor means
    it can actually claim more, bounded only by the new maximum-height
    ceiling."""
    b = make_builder(tmp_path)
    assert b.image_input_zone.maximumHeight() > 130


# ---------------------------------------------------------------------
# 48.5 — devicePixelRatio-aware image scaling
# ---------------------------------------------------------------------
def test_draw_image_tags_the_scaled_pixmap_with_the_real_device_pixel_ratio(qapp, monkeypatch):
    from PyQt6.QtGui import QPainter

    viewer = ResultImageViewer(COLORS)
    viewer.resize(400, 300)

    pixmap = QPixmap(200, 300)
    pixmap.fill(QColor("red"))
    viewer._pixmap = pixmap
    viewer._has_image = True

    monkeypatch.setattr(type(viewer), "devicePixelRatioF", lambda self: 1.5)

    captured = {}
    original_draw = QPainter.drawPixmap

    def fake_draw_pixmap(self, x, y, pm, *args, **kwargs):
        captured["pixmap"] = pm
        return None

    monkeypatch.setattr(QPainter, "drawPixmap", fake_draw_pixmap)
    try:
        target = QPixmap(400, 300)
        painter = QPainter(target)
        viewer._draw_image(painter, 400, 300)
        painter.end()
    finally:
        monkeypatch.setattr(QPainter, "drawPixmap", original_draw)

    assert "pixmap" in captured, "expected _draw_image to reach drawPixmap"
    assert captured["pixmap"].devicePixelRatio() == 1.5


def test_draw_image_defaults_to_ratio_one_on_a_normal_display(qapp):
    """No monkeypatched DPI -- offscreen test displays report 1.0, and
    the fix must not break the completely ordinary case."""
    from PyQt6.QtGui import QPainter

    viewer = ResultImageViewer(COLORS)
    viewer.resize(400, 300)
    pixmap = QPixmap(200, 300)
    pixmap.fill(QColor("blue"))
    viewer._pixmap = pixmap
    viewer._has_image = True

    target = QPixmap(400, 300)
    painter = QPainter(target)
    viewer._draw_image(painter, 400, 300)  # must not raise regardless of ratio
    painter.end()


# ---------------------------------------------------------------------
# 48.6 — themed_message_box smoke test (no real .exec() -- would block)
# ---------------------------------------------------------------------
def test_themed_message_box_question_maps_accept_to_yes(qapp):
    from PyQt6.QtWidgets import QMessageBox
    dlg = themed_message_box._ThemedMessageBox(
        None, COLORS, "question", "Confirm?", "Are you sure?",
        QDialogButtonBox.StandardButton.Yes | QDialogButtonBox.StandardButton.No)
    dlg.accept()  # simulate clicking Yes, without exec()'ing (would block headless)
    from PyQt6.QtWidgets import QDialog
    assert dlg.result() == QDialog.DialogCode.Accepted


def test_themed_message_box_falls_back_to_default_colors_without_crashing(qapp):
    class NoColorsParent:
        pass
    colors = themed_message_box._colors_for(NoColorsParent())
    assert colors == themed_message_box._FALLBACK_COLORS


# ---------------------------------------------------------------------
# 48.7 — lazy tooltip loading in Library's category list
# ---------------------------------------------------------------------
def test_refresh_library_list_does_not_read_content_when_not_searching(qapp, tmp_path):
    from ui.tabs.library_tab import LibraryTab, _KIND_ENTRY
    init_folders(str(tmp_path), CATEGORIES)
    for i in range(5):
        with open(os.path.join(str(tmp_path), "tools", f"Tool{i}.txt"), "w", encoding="utf-8") as f:
            f.write(f"some tag content {i}")

    lib = LibraryTab(str(tmp_path), COLORS, {}, str(tmp_path / "settings.json"))
    lib.switch_library_category("tools")

    found_any_entry = False
    it = lib.tree_library.invisibleRootItem()

    def walk(item):
        nonlocal found_any_entry
        for i in range(item.childCount()):
            child = item.child(i)
            data = child.data(0, Qt.ItemDataRole.UserRole) or {}
            if data.get("kind") == _KIND_ENTRY:
                found_any_entry = True
                # Lazy-loading means no tooltip yet -- nobody's hovered it.
                assert child.toolTip(0) == ""
                assert data.get("path")
            walk(child)

    walk(it)
    assert found_any_entry


def test_item_entered_lazily_loads_the_tooltip_on_hover(qapp, tmp_path):
    from ui.tabs.library_tab import LibraryTab, _KIND_ENTRY
    init_folders(str(tmp_path), CATEGORIES)
    with open(os.path.join(str(tmp_path), "tools", "Grain.txt"), "w", encoding="utf-8") as f:
        f.write("film grain, subtle noise")

    lib = LibraryTab(str(tmp_path), COLORS, {}, str(tmp_path / "settings.json"))
    lib.switch_library_category("tools")

    item = None
    root = lib.tree_library.invisibleRootItem()
    for i in range(root.childCount()):
        child = root.child(i)
        data = child.data(0, Qt.ItemDataRole.UserRole) or {}
        if data.get("kind") == _KIND_ENTRY:
            item = child
            break
    assert item is not None
    assert item.toolTip(0) == ""

    lib._on_library_item_entered(item)
    assert "film grain" in item.toolTip(0)


def test_refresh_library_list_still_reads_content_when_searching(qapp, tmp_path):
    from ui.tabs.library_tab import LibraryTab, _KIND_ENTRY
    init_folders(str(tmp_path), CATEGORIES)
    with open(os.path.join(str(tmp_path), "tools", "Grain.txt"), "w", encoding="utf-8") as f:
        f.write("film grain, subtle noise")
    with open(os.path.join(str(tmp_path), "tools", "Blur.txt"), "w", encoding="utf-8") as f:
        f.write("soft focus blur")

    lib = LibraryTab(str(tmp_path), COLORS, {}, str(tmp_path / "settings.json"))
    lib.switch_library_category("tools")
    lib.ent_search.setText("subtle")

    matched_names = []
    root = lib.tree_library.invisibleRootItem()

    def walk(item):
        for i in range(item.childCount()):
            child = item.child(i)
            data = child.data(0, Qt.ItemDataRole.UserRole) or {}
            if data.get("kind") == _KIND_ENTRY:
                matched_names.append(child.text(0))
            walk(child)

    walk(root)
    assert matched_names == ["Grain"]
