"""Session 4 tests: LibraryTab's data logic (category switch, tree
folder-grouping, save/duplicate/delete, canon outfit handling), against
a temp data dir with the real five category folders. The tree's visual
rendering is what `python main.py` itself is for — this file covers the
behavior that doesn't need eyeballs.

Run headless with:
    QT_QPA_PLATFORM=offscreen python -m pytest tests/test_library_tab_session4.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QMessageBox

from backend.constants import CATEGORIES, THEMES
from backend.file_manager import init_folders
from ui.dialogs import themed_message_box
from ui.tabs.library_tab import LibraryTab


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


class TestCategorySwitch:
    def test_defaults_to_styles(self, tab):
        assert tab.current_category == "styles"

    def test_switch_updates_category_and_clears_editor(self, tab):
        tab.ent_lib_name.setText("leftover")
        tab.switch_library_category("scenarios")
        assert tab.current_category == "scenarios"
        assert tab.ent_lib_name.text() == ""

    def test_canon_block_only_visible_for_outfits(self, tab):
        tab.switch_library_category("outfits")
        assert tab.frame_canon_binding.isVisible()
        tab.switch_library_category("characters")
        assert not tab.frame_canon_binding.isVisible()


class TestSave:
    def test_save_new_plain_entry(self, tab, tmp_data_dir):
        tab.ent_lib_name.setText("my style")
        tab.txt_lib_tags.setPlainText("masterpiece, best quality")
        tab.save_to_library()
        assert os.path.exists(os.path.join(tmp_data_dir, "styles", "my style.txt"))
        assert tab.selected_file == "my style"

    def test_save_sanitizes_invalid_filename_chars(self, tab, monkeypatch, tmp_data_dir):
        monkeypatch.setattr(themed_message_box, "question",
                             lambda *a, **k: QMessageBox.StandardButton.Yes)
        tab.ent_lib_name.setText("weird:name?")
        tab.txt_lib_tags.setPlainText("content")
        tab.save_to_library()
        assert tab.selected_file != "weird:name?"
        assert ":" not in tab.selected_file

    def test_save_empty_tags_blocked_for_non_tools(self, tab, tmp_data_dir):
        tab.ent_lib_name.setText("empty one")
        tab.txt_lib_tags.setPlainText("")
        tab.save_to_library()
        assert not os.path.exists(os.path.join(tmp_data_dir, "styles", "empty one.txt"))

    def test_save_empty_tags_allowed_for_tools(self, tab, tmp_data_dir):
        tab.switch_library_category("tools")
        tab.ent_lib_name.setText("empty tool")
        tab.txt_lib_tags.setPlainText("")
        tab.save_to_library()
        assert os.path.exists(os.path.join(tmp_data_dir, "tools", "empty tool.txt"))

    def test_rename_existing_entry(self, tab, tmp_data_dir):
        _write_entry(tmp_data_dir, "styles", "old name", "abc")
        tab.refresh_library_list()
        item = tab._find_entry_item("old name")
        tab.on_library_select("old name")
        tab.ent_lib_name.setText("new name")
        tab.save_to_library()
        assert not os.path.exists(os.path.join(tmp_data_dir, "styles", "old name.txt"))
        assert os.path.exists(os.path.join(tmp_data_dir, "styles", "new name.txt"))


class TestCanonOutfits:
    def test_save_canon_outfit_creates_canon_named_file(self, tab, tmp_data_dir):
        _write_entry(tmp_data_dir, "characters", "Alice", "alice tags")
        tab.switch_library_category("outfits")
        tab.combo_canon_char.set_items(["Alice"])
        tab.chk_canon.setChecked(True)
        tab.combo_canon_char.set_value("Alice")
        tab.txt_lib_tags.setPlainText("school uniform")
        tab.save_to_library()
        assert os.path.exists(os.path.join(tmp_data_dir, "outfits", "Alice_Canon_1.txt"))

    def test_canon_outfit_filed_under_canonical_folder(self, tab, tmp_data_dir):
        _write_entry(tmp_data_dir, "characters", "Bob", "bob tags")
        tab.switch_library_category("outfits")
        tab.combo_canon_char.set_items(["Bob"])
        tab.chk_canon.setChecked(True)
        tab.combo_canon_char.set_value("Bob")
        tab.txt_lib_tags.setPlainText("casual wear")
        tab.save_to_library()
        from backend.constants import CANONICAL_OUTFITS_FOLDER
        assert tab.folder_maps["outfits"]["Bob_Canon_1"] == CANONICAL_OUTFITS_FOLDER

    def test_second_canon_outfit_increments_index(self, tab, tmp_data_dir):
        _write_entry(tmp_data_dir, "characters", "Carl", "carl tags")
        tab.switch_library_category("outfits")
        for _ in range(2):
            tab.start_new_library_entry()
            tab.combo_canon_char.set_items(["Carl"])
            tab.chk_canon.setChecked(True)
            tab.combo_canon_char.set_value("Carl")
            tab.txt_lib_tags.setPlainText("an outfit")
            tab.save_to_library()
        assert os.path.exists(os.path.join(tmp_data_dir, "outfits", "Carl_Canon_1.txt"))
        assert os.path.exists(os.path.join(tmp_data_dir, "outfits", "Carl_Canon_2.txt"))


class TestDuplicate:
    def test_duplicate_creates_copy_with_suffix(self, tab, tmp_data_dir):
        _write_entry(tmp_data_dir, "styles", "base style", "abc")
        tab.refresh_library_list()
        tab.on_library_select("base style")
        tab.duplicate_library_entry()
        assert os.path.exists(os.path.join(tmp_data_dir, "styles", "base style_copy.txt"))

    def test_duplicate_carries_folder_assignment(self, tab, tmp_data_dir):
        from backend.file_manager import set_entry_folder
        _write_entry(tmp_data_dir, "styles", "foldered", "abc")
        set_entry_folder(tab.folder_maps, tab.folders_file, "styles", "foldered", "MyFolder")
        tab.refresh_library_list()
        tab.on_library_select("foldered")
        tab.duplicate_library_entry()
        assert tab.folder_maps["styles"]["foldered_copy"] == "MyFolder"


class TestDelete:
    def test_delete_removes_file(self, tab, tmp_data_dir):
        _write_entry(tmp_data_dir, "styles", "to delete", "abc")
        tab.refresh_library_list()
        tab.on_library_select("to delete")
        tab.delete_library_entry()
        assert not os.path.exists(os.path.join(tmp_data_dir, "styles", "to delete.txt"))
        assert tab.selected_file is None

    def test_delete_character_cascades_to_canon_outfits(self, tab, tmp_data_dir):
        _write_entry(tmp_data_dir, "characters", "Dana", "dana tags")
        _write_entry(tmp_data_dir, "outfits", "Dana_Canon_1", "outfit tags")
        tab.switch_library_category("characters")
        tab.on_library_select("Dana")
        tab.delete_library_entry()
        assert not os.path.exists(os.path.join(tmp_data_dir, "characters", "Dana.txt"))
        assert not os.path.exists(os.path.join(tmp_data_dir, "outfits", "Dana_Canon_1.txt"))


class TestTreeGrouping:
    def test_entries_grouped_under_folder_rows(self, tab, tmp_data_dir):
        from backend.file_manager import set_entry_folder
        _write_entry(tmp_data_dir, "styles", "rooted", "x")
        _write_entry(tmp_data_dir, "styles", "in folder", "y")
        set_entry_folder(tab.folder_maps, tab.folders_file, "styles", "in folder", "Casual")
        tab.refresh_library_list()
        top_level_texts = [tab.tree_library.topLevelItem(i).text(0)
                            for i in range(tab.tree_library.topLevelItemCount())]
        assert any("📁 Casual" in t for t in top_level_texts)
        assert any(t == "rooted" for t in top_level_texts)

    def test_search_filters_entries(self, tab, tmp_data_dir):
        _write_entry(tmp_data_dir, "styles", "apple pie", "x")
        _write_entry(tmp_data_dir, "styles", "banana split", "y")
        tab.refresh_library_list()
        tab.ent_search.setText("apple")
        assert tab.lbl_lib_count.text() == "1 entry"
