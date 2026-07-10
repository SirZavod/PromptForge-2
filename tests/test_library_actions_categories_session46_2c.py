"""Session 46.2c tests — Library gets its own "image_actions"/
"video_actions" categories (instead of i2i/i2v's Actions slot sharing
t2i's generic "tools" category), and the Custom/Standard template
switch is hidden (forced to Standard) while in an image-input mode —
see additionalfeatures.md's SESSION 46.2c write-up for the design
decision this codifies.

Also covers two same-session follow-ups driven by real-screenshot
feedback:
- t2i must not show the *other* modes' categories either (it used to
  show literally everything), and the whole template panel card — not
  just the inner Standard/Custom switch — hides in image modes so it
  stops occupying screen space.
- The right-rail Tools list is its OWN category per image mode
  ("edit_tools" in i2i, "video_tools" in i2v) -- deliberately separate
  from the main column's Actions category ("image_actions"/
  "video_actions"), since an Actions entry needs prompt text and a
  Tools entry often doesn't (a LoRA-only fixer, just a stack strength).
  So each image mode shows exactly TWO Library categories, not one.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from PyQt6.QtWidgets import QApplication

from ui.tabs.builder_tab import BuilderTab
from ui.tabs.library_tab import LibraryTab
from backend.constants import (
    PIPELINE_MODE_T2I, PIPELINE_MODE_I2I, PIPELINE_MODE_I2V,
    CATEGORIES, CATEGORY_LABELS, CATEGORY_ICONS,
)
from backend.file_manager import init_folders


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


COLORS = {
    "bg": "#202020", "bg_alt": "#242424", "bg_card": "#282828",
    "bg_input": "#2c2c2c", "border": "#3a3a3a", "fg": "#f0f0f0",
    "fg_dim": "#9a9a9a", "accent": "#5b8def", "accent_text": "#ffffff",
    "accent_hover": "#6f9bf2", "success": "#4caf50", "danger": "#e05252",
    "warn": "#e0a852", "tree_bg": "#242424", "tree_alt": "#262626",
    "select_bg": "#31445e",
}


def make_builder(tmp_path, settings=None):
    init_folders(str(tmp_path), CATEGORIES)
    settings_file = str(tmp_path / "settings.json")
    return BuilderTab(str(tmp_path), COLORS, settings or {}, settings_file)


def make_library(tmp_path):
    init_folders(str(tmp_path), CATEGORIES)
    settings_file = str(tmp_path / "settings.json")
    return LibraryTab(str(tmp_path), COLORS, {}, settings_file)


# ---------------------------------------------------------------------
# Constants: new categories exist and are wired into the shared dicts
# ---------------------------------------------------------------------

def test_new_categories_registered():
    for cat in ("image_actions", "video_actions", "edit_tools", "video_tools"):
        assert cat in CATEGORIES
    assert "tools" in CATEGORIES  # untouched, still backs t2i's Tools slots

    assert CATEGORY_LABELS["image_actions"] == "Image Action"
    assert CATEGORY_LABELS["video_actions"] == "Video Action"
    assert CATEGORY_LABELS["edit_tools"] == "Edit Tools"
    assert CATEGORY_LABELS["video_tools"] == "Video Tools"
    for cat in ("image_actions", "video_actions", "edit_tools", "video_tools"):
        assert cat in CATEGORY_ICONS


# ---------------------------------------------------------------------
# LibraryTab: category bar filtering per pipeline mode
# ---------------------------------------------------------------------

def test_t2i_shows_original_five_but_not_any_image_mode_category(app, tmp_path):
    lib = make_library(tmp_path)
    lib.set_pipeline_mode_filter(PIPELINE_MODE_T2I)
    image_mode_only = ("image_actions", "video_actions", "edit_tools", "video_tools")
    for cat, box in lib.cat_boxes.items():
        expected = cat not in image_mode_only
        assert box.isVisibleTo(lib) is expected


def test_i2i_shows_exactly_image_actions_and_edit_tools(app, tmp_path):
    lib = make_library(tmp_path)
    lib.set_pipeline_mode_filter(PIPELINE_MODE_I2I)
    for cat, box in lib.cat_boxes.items():
        assert box.isVisibleTo(lib) is (cat in ("image_actions", "edit_tools"))


def test_i2v_shows_exactly_video_actions_and_video_tools(app, tmp_path):
    lib = make_library(tmp_path)
    lib.set_pipeline_mode_filter(PIPELINE_MODE_I2V)
    for cat, box in lib.cat_boxes.items():
        assert box.isVisibleTo(lib) is (cat in ("video_actions", "video_tools"))


def test_switching_to_i2i_falls_back_off_a_hidden_category(app, tmp_path):
    lib = make_library(tmp_path)
    lib.switch_library_category("tools")
    lib.set_pipeline_mode_filter(PIPELINE_MODE_I2I)
    assert lib.current_category in ("image_actions", "edit_tools")


# ---------------------------------------------------------------------
# BuilderTab: Actions slot reads from the mode-correct category
# ---------------------------------------------------------------------

def test_actions_category_helper_tracks_mode(app, tmp_path):
    b = make_builder(tmp_path)
    b.pipeline_mode = PIPELINE_MODE_I2I
    assert b._actions_category() == "image_actions"
    b.pipeline_mode = PIPELINE_MODE_I2V
    assert b._actions_category() == "video_actions"


def test_action_slot_combo_seeded_from_image_actions_in_i2i(app, tmp_path):
    init_folders(str(tmp_path), CATEGORIES)
    (tmp_path / "image_actions" / "Zoom In.txt").write_text("zoom in")
    b = make_builder(tmp_path)
    b.pipeline_mode = PIPELINE_MODE_I2I
    b._apply_pipeline_mode()
    b.add_action_slot()
    slot = b.active_actions[0]
    assert "Zoom In" in slot["action_combo"]._all_values


def test_action_slot_combo_seeded_from_video_actions_in_i2v(app, tmp_path):
    init_folders(str(tmp_path), CATEGORIES)
    (tmp_path / "video_actions" / "Pan Left.txt").write_text("pan left")
    b = make_builder(tmp_path)
    b.pipeline_mode = PIPELINE_MODE_I2V
    b._apply_pipeline_mode()
    b.add_action_slot()
    slot = b.active_actions[0]
    assert "Pan Left" in slot["action_combo"]._all_values


def test_flipping_i2i_to_i2v_reseeds_existing_action_slots(app, tmp_path):
    init_folders(str(tmp_path), CATEGORIES)
    (tmp_path / "image_actions" / "Zoom In.txt").write_text("zoom in")
    (tmp_path / "video_actions" / "Pan Left.txt").write_text("pan left")
    b = make_builder(tmp_path)
    b.pipeline_mode = PIPELINE_MODE_I2I
    b._apply_pipeline_mode()
    b.add_action_slot()
    slot = b.active_actions[0]
    assert "Zoom In" in slot["action_combo"]._all_values
    assert "Pan Left" not in slot["action_combo"]._all_values

    b.pipeline_mode = PIPELINE_MODE_I2V
    b._apply_pipeline_mode()
    assert "Pan Left" in slot["action_combo"]._all_values
    assert "Zoom In" not in slot["action_combo"]._all_values


# ---------------------------------------------------------------------
# BuilderTab: right-rail Tools slot reads from its OWN per-mode
# category -- "edit_tools"/"video_tools", distinct from Actions'
# "image_actions"/"video_actions" (46.2c follow-up #3)
# ---------------------------------------------------------------------

def test_mode_tools_category_helper_tracks_all_three_modes(app, tmp_path):
    b = make_builder(tmp_path)
    assert b.pipeline_mode == PIPELINE_MODE_T2I
    assert b._mode_tools_category() == "tools"
    b.pipeline_mode = PIPELINE_MODE_I2I
    assert b._mode_tools_category() == "edit_tools"
    b.pipeline_mode = PIPELINE_MODE_I2V
    assert b._mode_tools_category() == "video_tools"


def test_tools_and_actions_categories_are_distinct_in_image_modes(app, tmp_path):
    b = make_builder(tmp_path)
    b.pipeline_mode = PIPELINE_MODE_I2I
    assert b._mode_tools_category() != b._actions_category()
    b.pipeline_mode = PIPELINE_MODE_I2V
    assert b._mode_tools_category() != b._actions_category()


def test_tool_slot_combo_seeded_from_tools_in_t2i(app, tmp_path):
    init_folders(str(tmp_path), CATEGORIES)
    (tmp_path / "tools" / "Sharpen.txt").write_text("sharpen")
    b = make_builder(tmp_path)
    b.add_tool_slot()
    slot = b.active_tools[0]
    assert "Sharpen" in slot["tool_combo"]._all_values


def test_tool_slot_combo_seeded_from_edit_tools_in_i2i(app, tmp_path):
    init_folders(str(tmp_path), CATEGORIES)
    (tmp_path / "edit_tools" / "Anatomy Fixer.txt").write_text("")
    b = make_builder(tmp_path)
    b.pipeline_mode = PIPELINE_MODE_I2I
    b._apply_pipeline_mode()
    b.add_tool_slot()
    slot = b.active_tools[0]
    assert "Anatomy Fixer" in slot["tool_combo"]._all_values


def test_tool_slot_combo_seeded_from_video_tools_in_i2v(app, tmp_path):
    init_folders(str(tmp_path), CATEGORIES)
    (tmp_path / "video_tools" / "Frame Interpolator.txt").write_text("")
    b = make_builder(tmp_path)
    b.pipeline_mode = PIPELINE_MODE_I2V
    b._apply_pipeline_mode()
    b.add_tool_slot()
    slot = b.active_tools[0]
    assert "Frame Interpolator" in slot["tool_combo"]._all_values


def test_switching_mode_reseeds_existing_tool_slots(app, tmp_path):
    init_folders(str(tmp_path), CATEGORIES)
    (tmp_path / "tools" / "Sharpen.txt").write_text("sharpen")
    (tmp_path / "edit_tools" / "Anatomy Fixer.txt").write_text("")
    b = make_builder(tmp_path)
    b.add_tool_slot()
    slot = b.active_tools[0]
    assert "Sharpen" in slot["tool_combo"]._all_values

    b.pipeline_mode = PIPELINE_MODE_I2I
    b._apply_pipeline_mode()
    assert "Anatomy Fixer" in slot["tool_combo"]._all_values
    assert "Sharpen" not in slot["tool_combo"]._all_values

    b.pipeline_mode = PIPELINE_MODE_T2I
    b._apply_pipeline_mode()
    assert "Sharpen" in slot["tool_combo"]._all_values
    assert "Anatomy Fixer" not in slot["tool_combo"]._all_values


def test_tools_card_retitled_per_mode(app, tmp_path):
    b = make_builder(tmp_path)
    assert b.lbl_tools_heading.text() == "Tools"

    b.pipeline_mode = PIPELINE_MODE_I2I
    b._apply_pipeline_mode()
    assert b.lbl_tools_heading.text() == "Edit Tools"

    b.pipeline_mode = PIPELINE_MODE_I2V
    b._apply_pipeline_mode()
    assert b.lbl_tools_heading.text() == "Video Tools"

    b.pipeline_mode = PIPELINE_MODE_T2I
    b._apply_pipeline_mode()
    assert b.lbl_tools_heading.text() == "Tools"


def test_generate_standard_prompt_uses_mode_correct_tools_category(app, tmp_path):
    init_folders(str(tmp_path), CATEGORIES)
    (tmp_path / "edit_tools" / "Zoom In.txt").write_text("zoom in tag")
    b = make_builder(tmp_path)
    b.pipeline_mode = PIPELINE_MODE_I2I
    b._apply_pipeline_mode()
    b.add_tool_slot()
    slot = b.active_tools[0]
    slot["tool_combo"].set_value("Zoom In")

    active_tool_names = [s["tool_combo"].current_value() for s in b.active_tools]
    from backend.prompt_builder import generate_standard_prompt
    prompt = generate_standard_prompt(
        str(tmp_path), "None", [], "None", active_tool_names, b.block_order,
        tools_category=b._mode_tools_category(),
    )
    assert "zoom in tag" in prompt


# ---------------------------------------------------------------------
# BuilderTab: Custom/Standard switch hidden + forced Standard in image modes
# ---------------------------------------------------------------------

def test_custom_switch_visible_in_t2i(app, tmp_path):
    b = make_builder(tmp_path)
    b.tpl_section.set_expanded(True)
    assert b.tpl_section.isVisibleTo(b) is True
    assert b.lbl_template_type.isVisibleTo(b) is True
    assert b.combo_template_category.isVisibleTo(b) is True


def test_custom_switch_hidden_and_forced_standard_in_i2i(app, tmp_path):
    b = make_builder(tmp_path)
    b.tpl_section.set_expanded(True)
    b.combo_template_category.setCurrentText("Custom")
    assert b.combo_template_category.currentText() == "Custom"

    b.pipeline_mode = PIPELINE_MODE_I2I
    b._apply_pipeline_mode()

    # 46.2c revision: the *whole* template panel card is hidden in image
    # modes now, not just the inner Standard/Custom switch, so it stops
    # taking up screen space instead of sitting there empty-looking.
    assert b.tpl_section.isVisibleTo(b) is False
    assert b.lbl_template_type.isVisibleTo(b) is False
    assert b.combo_template_category.isVisibleTo(b) is False
    assert b.combo_template_category.currentText() == "Standard"


def test_custom_switch_restored_after_returning_to_t2i(app, tmp_path):
    b = make_builder(tmp_path)
    b.tpl_section.set_expanded(True)
    b.pipeline_mode = PIPELINE_MODE_I2I
    b._apply_pipeline_mode()
    b.pipeline_mode = PIPELINE_MODE_T2I
    b._apply_pipeline_mode()

    assert b.tpl_section.isVisibleTo(b) is True
    assert b.lbl_template_type.isVisibleTo(b) is True
    assert b.combo_template_category.isVisibleTo(b) is True
