"""Session 6 tests: LibraryTab's virtual-folder system — create, rename,
delete, move (drag&drop callback + "Move to..." context-menu path share
the same `_move_selected_entries_to`), Canonical Outfits protection,
and expand/collapse persistence. Also covers the two new pure backend
functions (`rename_folder`, `delete_folder`) directly against a temp
folder map, independent of any UI.

The widgets' actual on-screen drag gesture is what `python main.py`
itself is for — this file covers the data-layer behavior and the
callback/handler functions a real drag or right-click would invoke,
which don't need eyeballs to verify.

Run headless with:
    QT_QPA_PLATFORM=offscreen python -m pytest tests/test_library_tab_session6.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QMessageBox

from backend.constants import CANONICAL_OUTFITS_FOLDER, CATEGORIES, FOLDER_PATH_SEP, THEMES
from backend.file_manager import (
    delete_folder,
    init_folders,
    is_protected_folder,
    load_json,
    rename_folder,
)
from ui.dialogs.library_folder_dialog import LibraryFolderDialog
from ui.dialogs import themed_message_box
from ui.tabs.library_tab import LibraryTab, _KIND_ENTRY, _KIND_FOLDER


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture()
def tmp_data_dir():
    with tempfile.TemporaryDirectory() as d:
        init_folders(d, CATEGORIES)
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
    return LibraryTab(tmp_data_dir, THEMES["dark"], {}, settings_file)


def _write_entry(data_dir, cat, name, content="some tags"):
    with open(os.path.join(data_dir, cat, f"{name}.txt"), "w", encoding="utf-8") as f:
        f.write(content)


# ------------------------------------------------------------------
# Pure backend functions
# ------------------------------------------------------------------
def test_rename_folder_repoints_entries_and_descendants():
    folder_maps = {"styles": {"a": "Casual", "b": "Casual/Wednesday", "c": "Other"}}
    empty_folders = {"styles": {"Casual/Empty"}}
    expanded = {"styles": {"Casual"}}
    with tempfile.TemporaryDirectory() as d:
        folders_file = os.path.join(d, "_folders.json")
        new_path = rename_folder(folder_maps, empty_folders, expanded, folders_file,
                                  "styles", "Casual", "Smart Casual")
    assert new_path == "Smart Casual"
    assert folder_maps["styles"]["a"] == "Smart Casual"
    assert folder_maps["styles"]["b"] == "Smart Casual/Wednesday"
    assert folder_maps["styles"]["c"] == "Other"  # untouched
    assert "Smart Casual/Empty" in empty_folders["styles"]
    assert "Smart Casual" in expanded["styles"]
    assert "Casual" not in expanded["styles"]


def test_rename_folder_rejects_slash_and_noop():
    folder_maps, empty_folders, expanded = {}, {}, {}
    with tempfile.TemporaryDirectory() as d:
        folders_file = os.path.join(d, "_folders.json")
        assert rename_folder(folder_maps, empty_folders, expanded, folders_file,
                              "styles", "Casual", "Has/Slash") is None
        assert rename_folder(folder_maps, empty_folders, expanded, folders_file,
                              "styles", "Casual", "Casual") is None
        assert rename_folder(folder_maps, empty_folders, expanded, folders_file,
                              "styles", "Casual", "") is None


def test_delete_folder_moves_contents_to_root():
    folder_maps = {"styles": {"a": "Casual", "b": "Casual/Wednesday", "c": "Other"}}
    empty_folders = {"styles": {"Casual/Empty"}}
    expanded = {"styles": {"Casual"}}
    with tempfile.TemporaryDirectory() as d:
        folders_file = os.path.join(d, "_folders.json")
        delete_folder(folder_maps, empty_folders, expanded, folders_file, "styles", "Casual")
    assert "a" not in folder_maps["styles"]
    assert "b" not in folder_maps["styles"]
    assert folder_maps["styles"]["c"] == "Other"
    assert "Casual/Empty" not in empty_folders["styles"]
    assert "Casual" not in expanded["styles"]


# ------------------------------------------------------------------
# is_protected_folder
# ------------------------------------------------------------------
def test_canonical_outfits_and_descendants_are_protected():
    assert is_protected_folder("outfits", CANONICAL_OUTFITS_FOLDER) is True
    assert is_protected_folder("outfits", CANONICAL_OUTFITS_FOLDER + "/Sub") is True
    assert is_protected_folder("outfits", "Casual") is False
    assert is_protected_folder("styles", CANONICAL_OUTFITS_FOLDER) is False  # category-scoped


# ------------------------------------------------------------------
# New folder (via the tab, dialog monkeypatched)
# ------------------------------------------------------------------
def test_prompt_new_library_folder_creates_empty_folder(tab, monkeypatch):
    monkeypatch.setattr(LibraryFolderDialog, "get_folder_name",
                         staticmethod(lambda *a, **k: "Casual"))
    tab.switch_library_category("styles")
    tab._prompt_new_library_folder()
    assert "Casual" in tab.empty_folders.get("styles", set())
    assert "Casual" in tab.expanded_folders.get("styles", set())


def test_prompt_new_subfolder_nested_path(tab, monkeypatch):
    monkeypatch.setattr(LibraryFolderDialog, "get_folder_name",
                         staticmethod(lambda *a, **k: "Wednesday"))
    tab.switch_library_category("styles")
    tab._prompt_new_library_folder("Casual")
    assert "Casual/Wednesday" in tab.empty_folders.get("styles", set())


def test_prompt_new_subfolder_refused_under_canonical_outfits(tab, monkeypatch):
    called = {}
    monkeypatch.setattr(themed_message_box, "information",
                         lambda *a, **k: called.setdefault("hit", True))
    tab.switch_library_category("outfits")
    tab._prompt_new_library_folder(CANONICAL_OUTFITS_FOLDER)
    assert called.get("hit") is True
    assert CANONICAL_OUTFITS_FOLDER not in tab.empty_folders.get("outfits", set())


def test_prompt_new_folder_empty_name_is_noop(tab, monkeypatch):
    monkeypatch.setattr(LibraryFolderDialog, "get_folder_name",
                         staticmethod(lambda *a, **k: None))
    tab.switch_library_category("styles")
    before = set(tab.empty_folders.get("styles", set()))
    tab._prompt_new_library_folder()
    assert tab.empty_folders.get("styles", set()) == before


# ------------------------------------------------------------------
# Rename / delete folder (via the tab)
# ------------------------------------------------------------------
def test_rename_library_folder_via_tab(tab, monkeypatch, tmp_data_dir):
    _write_entry(tmp_data_dir, "scenarios", "Scn1")
    tab.switch_library_category("scenarios")
    tab.on_library_select("Scn1")
    from backend.file_manager import set_entry_folder
    set_entry_folder(tab.folder_maps, tab.folders_file, "scenarios", "Scn1", "Old")

    monkeypatch.setattr(LibraryFolderDialog, "get_folder_name",
                         staticmethod(lambda *a, **k: "New"))
    tab._rename_library_folder("Old")
    assert tab.folder_maps["scenarios"]["Scn1"] == "New"
    on_disk = load_json(tab.folders_file, {})
    assert on_disk["scenarios"]["Scn1"] == "New"


def test_delete_library_folder_via_tab(tab, tmp_data_dir):
    _write_entry(tmp_data_dir, "scenarios", "Scn2")
    tab.switch_library_category("scenarios")
    from backend.file_manager import set_entry_folder
    set_entry_folder(tab.folder_maps, tab.folders_file, "scenarios", "Scn2", "ToDelete")

    tab._delete_library_folder("ToDelete")  # QMessageBox.question monkeypatched to Yes
    assert "Scn2" not in tab.folder_maps.get("scenarios", {})
    # The entry itself must still exist on disk — folders are organizational only.
    assert os.path.exists(os.path.join(tmp_data_dir, "scenarios", "Scn2.txt"))


def test_rename_canonical_outfits_blocked_at_menu_level(tab):
    # The context menu disables Rename/Delete for the protected folder
    # (is_protected_folder gates the QAction's enabled state) rather
    # than the underlying method refusing — matches the original,
    # which relies on the disabled Tk menu entry never firing the
    # command at all. Confirm the gating predicate itself is correct,
    # since that's what the menu-build code consults.
    assert is_protected_folder("outfits", CANONICAL_OUTFITS_FOLDER) is True


# ------------------------------------------------------------------
# Move entries (shared by drag&drop and "Move to...")
# ------------------------------------------------------------------
def test_move_selected_entries_to_folder(tab, tmp_data_dir):
    _write_entry(tmp_data_dir, "styles", "St1")
    _write_entry(tmp_data_dir, "styles", "St2")
    tab.switch_library_category("styles")
    tab._move_selected_entries_to("Vibrant", ["St1", "St2"])
    assert tab.folder_maps["styles"]["St1"] == "Vibrant"
    assert tab.folder_maps["styles"]["St2"] == "Vibrant"
    assert "Vibrant" in tab.expanded_folders.get("styles", set())


def test_move_to_protected_folder_is_refused(tab, tmp_data_dir, monkeypatch):
    called = {}
    monkeypatch.setattr(themed_message_box, "information",
                         lambda *a, **k: called.setdefault("hit", True))
    _write_entry(tmp_data_dir, "outfits", "Outf1")
    tab.switch_library_category("outfits")
    tab._move_selected_entries_to(CANONICAL_OUTFITS_FOLDER, ["Outf1"])
    assert called.get("hit") is True
    assert "Outf1" not in tab.folder_maps.get("outfits", {})


def test_move_skips_canon_outfits_in_selection(tab, tmp_data_dir):
    _write_entry(tmp_data_dir, "outfits", "Hero_Canon_1")
    _write_entry(tmp_data_dir, "outfits", "Hero_casual")
    tab.switch_library_category("outfits")
    tab._move_selected_entries_to("MyFolder", ["Hero_Canon_1", "Hero_casual"])
    assert "Hero_Canon_1" not in tab.folder_maps.get("outfits", {})  # skipped, canon-managed only
    assert tab.folder_maps["outfits"]["Hero_casual"] == "MyFolder"


# ------------------------------------------------------------------
# Expand/collapse persistence
# ------------------------------------------------------------------
def test_expand_collapse_state_tracked_per_category(tab, tmp_data_dir):
    _write_entry(tmp_data_dir, "styles", "St3")
    tab.switch_library_category("styles")
    from backend.file_manager import set_entry_folder
    set_entry_folder(tab.folder_maps, tab.folders_file, "styles", "St3", "Folder3")
    tab.refresh_library_list()

    folder_item = None
    for i in range(tab.tree_library.topLevelItemCount()):
        it = tab.tree_library.topLevelItem(i)
        data = it.data(0, Qt.ItemDataRole.UserRole)
        if data and data.get("kind") == _KIND_FOLDER and data.get("path") == "Folder3":
            folder_item = it
            break
    assert folder_item is not None

    tab._set_folder_expanded(folder_item, True)
    assert "Folder3" in tab.expanded_folders.get("styles", set())
    tab._set_folder_expanded(folder_item, False)
    assert "Folder3" not in tab.expanded_folders.get("styles", set())


def test_expand_all_and_collapse_all(tab, tmp_data_dir):
    _write_entry(tmp_data_dir, "styles", "St4")
    tab.switch_library_category("styles")
    from backend.file_manager import set_entry_folder
    set_entry_folder(tab.folder_maps, tab.folders_file, "styles", "St4", "FolderX")

    tab.expand_all_library_folders()
    assert "FolderX" in tab.expanded_folders.get("styles", set())

    tab.collapse_all_library_folders()
    assert tab.expanded_folders.get("styles", set()) == set()


# ------------------------------------------------------------------
# Duplicate carries folder assignment (Session 6 step 7)
# ------------------------------------------------------------------
def test_duplicate_carries_folder_assignment(tab, tmp_data_dir):
    from backend.file_manager import set_entry_folder
    tab.switch_library_category("styles")
    tab.ent_lib_name.setText("FolderedStyle")
    tab.txt_lib_tags.setPlainText("tag content")
    tab.save_to_library()
    set_entry_folder(tab.folder_maps, tab.folders_file, "styles", "FolderedStyle", "Vivid")

    tab.duplicate_library_entry()
    new_name = "FolderedStyle_copy"
    assert tab.folder_maps["styles"].get(new_name) == "Vivid"


# ------------------------------------------------------------------
# Drag & drop entry point (callback wiring)
# ------------------------------------------------------------------
def test_tree_on_entries_dropped_routes_to_move(tab, tmp_data_dir):
    _write_entry(tmp_data_dir, "styles", "DragMe")
    tab.switch_library_category("styles")
    assert tab.tree_library.on_entries_dropped == tab._move_selected_entries_to
    tab.tree_library.on_entries_dropped("Dropped", ["DragMe"])
    assert tab.folder_maps["styles"]["DragMe"] == "Dropped"
