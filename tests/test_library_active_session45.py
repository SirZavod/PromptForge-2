"""Session 45 — Library Active/Inactive entries.

Covers the backend active-map helpers directly (data model, ancestor
inheritance, persistence, rename/delete sync) plus a thin UI-level
smoke pass on LibraryTab (bulk-button relabeling, context-menu-driven
toggle + tree dimming, whole-library bulk actions) and BuilderTab
(dropdowns stop offering inactive entries).

Run headless with:
    QT_QPA_PLATFORM=offscreen python -m pytest tests/test_library_active_session45.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile

import pytest
from PyQt6.QtWidgets import QApplication, QMessageBox

from backend import file_manager as fm
from backend.constants import CATEGORIES, THEMES
from backend.file_manager import init_folders
from ui.dialogs import themed_message_box
from ui.tabs.library_tab import LibraryTab
from ui.tabs.builder_tab import BuilderTab


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture()
def tmp_data_dir():
    with tempfile.TemporaryDirectory() as d:
        init_folders(d, CATEGORIES)
        for name in ["Alice", "Bob", "Carol"]:
            with open(os.path.join(d, "characters", f"{name}.txt"), "w", encoding="utf-8") as f:
                f.write("tag")
        yield d


@pytest.fixture()
def tab(qapp, tmp_data_dir, monkeypatch):
    monkeypatch.setattr(themed_message_box, "information", lambda *a, **k: None)
    monkeypatch.setattr(themed_message_box, "critical", lambda *a, **k: None)
    monkeypatch.setattr(themed_message_box, "warning", lambda *a, **k: None)
    monkeypatch.setattr(
        themed_message_box, "question",
        lambda *a, **k: QMessageBox.StandardButton.Yes,
    )
    settings_file = os.path.join(tmp_data_dir, "_settings.json")
    t = LibraryTab(tmp_data_dir, THEMES["dark"], {}, settings_file)
    t.switch_library_category("characters")
    return t


# ------------------------------------------------------------------
# Backend data-model tests
# ------------------------------------------------------------------
def test_defaults_everything_active(tmp_data_dir):
    active_map = fm.load_active_map(os.path.join(tmp_data_dir, "_active.json"))
    assert fm.get_active_file_list(tmp_data_dir, "characters", {}, active_map) == [
        "Alice", "Bob", "Carol",
    ]


def test_entry_inactive_is_filtered(tmp_data_dir):
    active_file = os.path.join(tmp_data_dir, "_active.json")
    active_map = fm.load_active_map(active_file)
    fm.set_entries_active(active_map, active_file, "characters", ["Bob"], False)
    assert fm.get_active_file_list(tmp_data_dir, "characters", {}, active_map) == ["Alice", "Carol"]
    reloaded = fm.load_active_map(active_file)
    assert fm.get_active_file_list(tmp_data_dir, "characters", {}, reloaded) == ["Alice", "Carol"]


def test_inactive_folder_hides_its_children(tmp_data_dir):
    folders_file = os.path.join(tmp_data_dir, "_folders.json")
    active_file = os.path.join(tmp_data_dir, "_active.json")
    folder_maps = {}
    active_map = fm.load_active_map(active_file)
    fm.set_entry_folder(folder_maps, folders_file, "characters", "Bob", "Group A")
    fm.set_folders_active(active_map, active_file, "characters", ["Group A"], False)
    assert fm.get_active_file_list(tmp_data_dir, "characters", folder_maps, active_map) == [
        "Alice", "Carol",
    ]
    fm.set_folders_active(active_map, active_file, "characters", ["Group A"], True)
    assert fm.get_active_file_list(tmp_data_dir, "characters", folder_maps, active_map) == [
        "Alice", "Bob", "Carol",
    ]


def test_entry_and_ancestor_folder_flags_are_independent(tmp_data_dir):
    folders_file = os.path.join(tmp_data_dir, "_folders.json")
    active_file = os.path.join(tmp_data_dir, "_active.json")
    folder_maps = {}
    active_map = fm.load_active_map(active_file)
    fm.set_entry_folder(folder_maps, folders_file, "characters", "Bob", "Group A")
    fm.set_entries_active(active_map, active_file, "characters", ["Bob"], False)
    assert not fm.is_entry_active(active_map, folder_maps, "characters", "Bob")
    assert fm.is_folder_active(active_map, "characters", "Group A")
    fm.set_folders_active(active_map, active_file, "characters", ["Group A"], True)
    assert not fm.is_entry_active(active_map, folder_maps, "characters", "Bob")


def test_rename_and_delete_sync(tmp_data_dir):
    active_file = os.path.join(tmp_data_dir, "_active.json")
    active_map = fm.load_active_map(active_file)
    fm.set_entries_active(active_map, active_file, "characters", ["Bob"], False)

    fm.rename_entry_active_entry(active_map, active_file, "characters", "Bob", "Bobby")
    assert "Bob" not in active_map["characters"]["entries"]
    assert "Bobby" in active_map["characters"]["entries"]

    fm.remove_entry_active_entry(active_map, active_file, "characters", "Bobby")
    assert "Bobby" not in active_map.get("characters", {}).get("entries", set())


def test_folder_rename_and_delete_sync(tmp_data_dir):
    active_file = os.path.join(tmp_data_dir, "_active.json")
    active_map = fm.load_active_map(active_file)
    cat_active = active_map.setdefault("characters", {"entries": set(), "folders": set()})
    cat_active["folders"].add("Group A")
    cat_active["folders"].add("Group A/Nested")

    fm.rename_folder_active_entry(active_map, active_file, "characters", "Group A", "Group B")
    assert active_map["characters"]["folders"] == {"Group B", "Group B/Nested"}

    fm.delete_folder_active_entries(active_map, active_file, "characters", "Group B")
    assert active_map["characters"]["folders"] == set()


def test_missing_active_key_defaults_active():
    active_map = fm.load_active_map("/nonexistent/path/_active.json")
    assert active_map == {}
    assert fm.is_entry_active(active_map, {}, "characters", "Anyone")


# ------------------------------------------------------------------
# UI-level smoke pass
# ------------------------------------------------------------------
def test_bulk_buttons_relabel_with_selection(tab):
    assert tab.btn_inactive_all.text() == "Inactive All"
    assert tab.btn_active_all.text() == "Active All"
    item = tab._find_entry_item("Alice")
    assert item is not None
    item.setSelected(True)
    tab._on_tree_selection_changed()
    assert tab.btn_inactive_all.text() == "Set 1 Inactive"
    assert tab.btn_active_all.text() == "Set 1 Active"


def test_marking_entry_inactive_dims_the_row(tab):
    tab._set_active_and_refresh(["Alice"], [], False)
    assert not fm.is_entry_active(tab.active_map, tab.folder_maps, "characters", "Alice")
    item = tab._find_entry_item("Alice")
    assert item is not None
    assert item.foreground(0).color().alpha() < 255


def test_bulk_whole_library_inactive_then_active(tab):
    tab._bulk_set_active(False)
    assert not fm.is_entry_active(tab.active_map, tab.folder_maps, "characters", "Alice")
    assert not fm.is_entry_active(tab.active_map, tab.folder_maps, "characters", "Bob")
    tab._bulk_set_active(True)
    assert fm.is_entry_active(tab.active_map, tab.folder_maps, "characters", "Alice")
    assert fm.is_entry_active(tab.active_map, tab.folder_maps, "characters", "Bob")


def test_builder_dropdowns_stop_offering_inactive_entries(tab, tmp_data_dir):
    tab._set_active_and_refresh(["Bob"], [], False)
    settings_file = os.path.join(tmp_data_dir, "_settings.json")
    builder = BuilderTab(tmp_data_dir, THEMES["dark"], {}, settings_file)
    names = builder._lib_active_file_list("characters")
    assert "Bob" not in names
    assert "Alice" in names and "Carol" in names
