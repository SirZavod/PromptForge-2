"""Session 46.2 tests — Builder's i2i/i2v layout swap, corrected per
the 46.2 follow-up (Actions is a real inline slot list now, not a link
to Library; Style also hides in image mode).
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from PyQt6.QtWidgets import QApplication

from ui.tabs.builder_tab import BuilderTab
from ui.widgets.image_zone import ImageDropZone
from backend.constants import PIPELINE_MODE_T2I, PIPELINE_MODE_I2I, CATEGORIES
from backend.file_manager import init_folders


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def make_builder(app, tmp_path, settings=None):
    colors = {
        "bg": "#202020", "bg_alt": "#242424", "bg_card": "#282828",
        "bg_input": "#2c2c2c", "border": "#3a3a3a", "fg": "#f0f0f0",
        "fg_dim": "#9a9a9a", "accent": "#5b8def", "accent_text": "#ffffff",
        "accent_hover": "#6f9bf2", "success": "#4caf50", "danger": "#e05252",
        "warn": "#e0a852", "tree_bg": "#242424", "tree_alt": "#262626",
        "select_bg": "#31445e",
    }
    init_folders(str(tmp_path), CATEGORIES)
    settings_file = str(tmp_path / "settings.json")
    return BuilderTab(str(tmp_path), colors, settings or {}, settings_file)


def test_t2i_default_layout(app, tmp_path):
    b = make_builder(app, tmp_path)
    assert isinstance(b.image_input_zone, ImageDropZone)
    assert b.pipeline_mode == PIPELINE_MODE_T2I
    assert not b.image_input_zone.isVisible() or not b.isVisible()
    assert b.image_input_zone.isVisibleTo(b) is False
    assert b.box_style.isVisibleTo(b) is True
    assert b.box_chars.isVisibleTo(b) is True
    assert b.box_scenario.isVisibleTo(b) is True
    assert b.box_actions.isVisibleTo(b) is False


def test_switching_to_i2i_swaps_the_layout(app, tmp_path):
    b = make_builder(app, tmp_path)
    b.pipeline_mode = PIPELINE_MODE_I2I
    b._apply_pipeline_mode()

    assert b.image_input_zone.isVisibleTo(b) is True
    assert b.box_style.isVisibleTo(b) is False
    assert b.box_chars.isVisibleTo(b) is False
    assert b.box_scenario.isVisibleTo(b) is False
    assert b.box_actions.isVisibleTo(b) is True


def test_switching_back_to_t2i_restores_layout_and_clears_image(app, tmp_path, tmp_path_factory):
    b = make_builder(app, tmp_path)
    b.pipeline_mode = PIPELINE_MODE_I2I
    b._apply_pipeline_mode()

    fake_img = tmp_path / "in.png"
    fake_img.write_bytes(b"not-a-real-png-but-fine-for-path-tracking")
    b._on_image_input_chosen(str(fake_img))
    assert b.input_image_path == str(fake_img)

    b.pipeline_mode = PIPELINE_MODE_T2I
    b._apply_pipeline_mode()

    assert b.image_input_zone.isVisibleTo(b) is False
    assert b.box_style.isVisibleTo(b) is True
    assert b.box_chars.isVisibleTo(b) is True
    assert b.box_scenario.isVisibleTo(b) is True
    assert b.box_actions.isVisibleTo(b) is False
    assert b.input_image_path is None


def test_image_chosen_updates_path_and_preview(app, tmp_path):
    b = make_builder(app, tmp_path)
    b.pipeline_mode = PIPELINE_MODE_I2I
    b._apply_pipeline_mode()

    fake_img = tmp_path / "chosen.png"
    fake_img.write_bytes(b"still-not-a-real-png")
    b._on_image_input_chosen(str(fake_img))
    assert b.input_image_path == str(fake_img)


def test_add_action_slot_appends_and_updates_count(app, tmp_path):
    b = make_builder(app, tmp_path)
    b.pipeline_mode = PIPELINE_MODE_I2I
    b._apply_pipeline_mode()
    assert b.active_actions == []
    assert b.placeholder_actions.isVisibleTo(b) is True

    b.add_action_slot()

    assert len(b.active_actions) == 1
    assert b.lbl_actions_count.text() == "1 action(s)"
    assert b.placeholder_actions.isVisibleTo(b) is False
    slot = b.active_actions[0]
    assert slot["idx_label"].text() == "Action 1"
    assert slot["action_combo"].current_value() == "None"


def test_remove_action_slot_renumbers_remaining_slots(app, tmp_path):
    b = make_builder(app, tmp_path)
    b.add_action_slot()
    b.add_action_slot()
    first, second = b.active_actions

    b.remove_action_slot(first)

    assert b.active_actions == [second]
    assert second["idx_label"].text() == "Action 1"
    assert b.lbl_actions_count.text() == "1 action(s)"


def test_removing_all_action_slots_restores_placeholder(app, tmp_path):
    b = make_builder(app, tmp_path)
    b.pipeline_mode = PIPELINE_MODE_I2I
    b._apply_pipeline_mode()
    b.add_action_slot()
    slot = b.active_actions[0]

    b.remove_action_slot(slot)

    assert b.active_actions == []
    assert b.placeholder_actions.isVisibleTo(b) is True
    assert b.lbl_actions_count.text() == "0 action(s)"


def test_request_open_library_tools_signal_removed(app, tmp_path):
    b = make_builder(app, tmp_path)
    assert not hasattr(b, "request_open_library_tools")
    assert not hasattr(b, "_open_library_tools_category")
    assert not hasattr(b, "box_image_tools_hint")
