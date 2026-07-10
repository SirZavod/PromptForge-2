"""Session 30.3 tests: new/edited/imported Library entries reaching
Builder's Who/Style/Scenario/Tool combos without an app restart.

Covers two halves of the fix:
- `LibraryTab.library_changed` actually fires on save/duplicate/delete/
  import (and does NOT fire on a plain `refresh_library_list()` call
  such as a search keystroke or category switch — those don't touch
  disk, firing there would just be wasted work on every keystroke).
- `BuilderTab.refresh_library_backed_combos()` pushes the fresh file
  list into every already-built combo (Standard's style/scenario/
  character/tool slots, a character slot's outfit list, and Custom
  Template's equivalents) without disturbing whatever the person
  currently has selected/typed.

Run headless with:
    QT_QPA_PLATFORM=offscreen python -m pytest tests/test_builder_tab_session30_3.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
from unittest.mock import MagicMock

import pytest
from PyQt6.QtWidgets import QApplication, QMessageBox

from backend.constants import CATEGORIES, THEMES
from backend.file_manager import init_folders
from ui.dialogs import themed_message_box
from ui.tabs.builder_tab import BuilderTab
from ui.tabs.library_tab import LibraryTab

# See test_library_tab_session30.py's own comment on this pattern.
_keepalive = []


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture()
def tmp_data_dir():
    with tempfile.TemporaryDirectory() as d:
        init_folders(d, CATEGORIES)
        yield d


@pytest.fixture()
def builder(qapp, tmp_data_dir):
    settings_file = os.path.join(tmp_data_dir, "_settings.json")
    tab = BuilderTab(tmp_data_dir, THEMES["dark"], {}, settings_file)
    _keepalive.append(tab)
    return tab


@pytest.fixture()
def library(qapp, tmp_data_dir, monkeypatch):
    monkeypatch.setattr(themed_message_box, "information", lambda *a, **k: None)
    monkeypatch.setattr(themed_message_box, "critical", lambda *a, **k: None)
    monkeypatch.setattr(themed_message_box, "warning", lambda *a, **k: None)
    monkeypatch.setattr(themed_message_box, "question",
                         lambda *a, **k: QMessageBox.StandardButton.Yes)
    settings_file = os.path.join(tmp_data_dir, "_settings.json")
    tab = LibraryTab(tmp_data_dir, THEMES["dark"], {}, settings_file)
    _keepalive.append(tab)
    return tab


def _touch(data_dir, cat, name):
    with open(os.path.join(data_dir, cat, f"{name}.txt"), "w", encoding="utf-8") as f:
        f.write("some tags")


# ------------------------------------------------------------------
# LibraryTab.library_changed firing
# ------------------------------------------------------------------
def test_save_to_library_emits_library_changed(library):
    spy = MagicMock()
    library.library_changed.connect(spy)
    library.switch_library_category("characters")
    library.start_new_library_entry(keep_category=True)
    library.ent_lib_name.setText("Akane")
    library.txt_lib_tags.setPlainText("black hair, red eyes")
    library.save_to_library()
    spy.assert_called_once()


def test_delete_library_entry_emits_library_changed(library, tmp_data_dir):
    _touch(tmp_data_dir, "characters", "Akane")
    library.refresh_library_list()
    library.switch_library_category("characters")
    item = library._find_entry_item("Akane")
    library.tree_library.setCurrentItem(item)
    library.on_library_select("Akane")

    spy = MagicMock()
    library.library_changed.connect(spy)
    library.delete_library_entry()
    spy.assert_called_once()


def test_duplicate_library_entry_emits_library_changed(library, tmp_data_dir):
    _touch(tmp_data_dir, "characters", "Akane")
    library.refresh_library_list()
    library.switch_library_category("characters")
    item = library._find_entry_item("Akane")
    library.tree_library.setCurrentItem(item)
    library.on_library_select("Akane")

    spy = MagicMock()
    library.library_changed.connect(spy)
    library.duplicate_library_entry()
    spy.assert_called_once()


def test_plain_refresh_library_list_does_not_emit(library, tmp_data_dir):
    # Category switches / search keystrokes call refresh_library_list()
    # directly and touch nothing on disk — must stay silent, or every
    # keystroke in Library's search box would trigger a Builder-wide
    # combo repopulation for nothing.
    spy = MagicMock()
    library.library_changed.connect(spy)
    library.refresh_library_list()
    library.switch_library_category("styles")
    spy.assert_not_called()


# ------------------------------------------------------------------
# BuilderTab.refresh_library_backed_combos
# ------------------------------------------------------------------
def test_refresh_pulls_in_new_character_without_losing_current_pick(builder, tmp_data_dir):
    _touch(tmp_data_dir, "characters", "Akane")
    builder.add_character_slot()
    slot = builder.active_characters[0]
    slot["char_combo"].set_value("Akane")

    # New entry appears on disk *after* the slot was already built —
    # exactly the "created a new entry while Builder tab is open" case.
    _touch(tmp_data_dir, "characters", "Bob")
    builder.refresh_library_backed_combos()

    assert "Bob" in slot["char_combo"]._all_values
    assert slot["char_combo"].current_value() == "Akane"  # untouched


def test_refresh_pulls_in_new_style_and_scenario(builder, tmp_data_dir):
    builder.combo_style.set_value("None")
    _touch(tmp_data_dir, "styles", "Anime")
    _touch(tmp_data_dir, "scenarios", "Beach")
    builder.refresh_library_backed_combos()

    assert "Anime" in builder.combo_style._all_values
    assert "Beach" in builder.combo_scenario._all_values


def test_refresh_pulls_in_new_tool(builder, tmp_data_dir):
    builder.add_tool_slot()
    slot = builder.active_tools[0]
    _touch(tmp_data_dir, "tools", "Sword")
    builder.refresh_library_backed_combos()
    assert "Sword" in slot["tool_combo"]._all_values


def test_refresh_pulls_in_new_outfit_for_already_selected_character(builder, tmp_data_dir):
    _touch(tmp_data_dir, "characters", "Akane")
    builder.add_character_slot()
    slot = builder.active_characters[0]
    slot["char_combo"].set_value("Akane")
    builder._update_outfit_list(slot["char_combo"], slot["outfit_combo"])

    _touch(tmp_data_dir, "outfits", "Akane_Casual")
    builder.refresh_library_backed_combos()

    assert "Akane_Casual" in slot["outfit_combo"]._all_values


def test_refresh_is_a_noop_before_any_custom_template_rendered(builder, tmp_data_dir):
    # custom_style_combo/custom_scenario_combo don't exist until a
    # Custom template has actually been rendered once — must not raise.
    builder.refresh_library_backed_combos()
