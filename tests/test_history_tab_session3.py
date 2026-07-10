"""Session 3 tests: HistoryTab's data logic (filtering, CRUD, favoriting),
exercised through the real widget against a temp data dir. The visual
shell (MainWindow, top bar, theme toggle, tab order) is what
`tests/_manual_check_session3.py` is for — this file only covers logic
that doesn't need eyeballs.

Run headless with:
    QT_QPA_PLATFORM=offscreen python -m pytest tests/test_history_tab_session3.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json
import tempfile

import pytest
from PyQt6.QtWidgets import QApplication, QMessageBox

from ui.dialogs import themed_message_box
from ui.tabs.history_tab import HistoryTab


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture()
def tmp_data_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture()
def tab(qapp, tmp_data_dir, monkeypatch):
    # Silence themed_message_box popups during tests — they'd block
    # forever under offscreen/headless pytest otherwise.
    monkeypatch.setattr(themed_message_box, "information", lambda *a, **k: None)
    monkeypatch.setattr(themed_message_box, "critical", lambda *a, **k: None)
    monkeypatch.setattr(
        themed_message_box, "question",
        lambda *a, **k: QMessageBox.StandardButton.Yes,
    )
    return HistoryTab(tmp_data_dir)


class TestAddToHistory:
    def test_returns_id_and_prepends(self, tab):
        id1 = tab.add_to_history("first")
        id2 = tab.add_to_history("second")
        assert tab.history[0]["text"] == "second"
        assert tab.history[1]["text"] == "first"
        assert id1 != id2

    def test_persists_to_disk(self, tab, tmp_data_dir):
        tab.add_to_history("persisted entry")
        on_disk = json.load(open(tab.history_file, encoding="utf-8"))
        assert on_disk[0]["text"] == "persisted entry"

    def test_caps_at_200(self, tab):
        for i in range(205):
            tab.history.insert(0, {"id": str(i), "text": f"e{i}", "timestamp": "", "favorite": False})
        tab.add_to_history("one more")
        assert len(tab.history) == 200

    def test_lora_used_and_image_ref_round_trip(self, tab):
        tab.add_to_history("with extras", lora_used=[{"name": "x", "strength": 1.0, "auto": True}],
                            image_ref={"local_path": "p", "remote_filename": "f", "remote_subfolder": ""})
        assert tab.history[0]["lora_used"][0]["name"] == "x"
        assert tab.history[0]["image_ref"]["local_path"] == "p"

    def test_plain_entry_has_no_extra_keys(self, tab):
        tab.add_to_history("plain")
        assert "lora_used" not in tab.history[0]
        assert "image_ref" not in tab.history[0]


class TestAddComfyHistoryEntry:
    def test_filters_out_none_slots(self, tab):
        slots = [
            {"name": "loraA.safetensors", "strength": 0.8, "auto": False},
            {"name": "None", "strength": 1.0, "auto": False},
        ]
        tab.add_comfy_history_entry("prompt text", slots)
        assert len(tab.history[0]["lora_used"]) == 1
        assert tab.history[0]["lora_used"][0]["name"] == "loraA.safetensors"

    def test_all_none_slots_yields_no_lora_used_key(self, tab):
        slots = [{"name": "None", "strength": 1.0, "auto": False}]
        tab.add_comfy_history_entry("prompt text", slots)
        assert "lora_used" not in tab.history[0]


class TestFilterAndSelection:
    def test_favorites_filter_hides_non_favorites(self, tab):
        tab.add_to_history("not fav")
        tab.add_to_history("is fav", favorite=True)
        tab.radio_fav.setChecked(True)
        assert tab.list_history.count() == 1
        assert "is fav" in tab.list_history.item(0).text()

    def test_index_map_maps_back_to_real_history(self, tab):
        tab.add_to_history("a")
        tab.add_to_history("b", favorite=True)
        tab.add_to_history("c")
        tab.radio_fav.setChecked(True)
        # Only "b" (index 1 in self.history) should be displayed at row 0.
        assert tab._history_index_map == [1]

    def test_select_updates_preview_and_fav_button(self, tab):
        tab.add_to_history("hello world")
        tab.list_history.setCurrentRow(0)
        assert tab.txt_preview.toPlainText() == "hello world"
        assert tab.btn_fav.text() == "⭐ Favorite"


class TestMutations:
    def test_toggle_favorite(self, tab):
        tab.add_to_history("toggle me")
        tab.list_history.setCurrentRow(0)
        tab.toggle_selected_favorite()
        assert tab.history[0]["favorite"] is True
        tab.list_history.setCurrentRow(0)
        tab.toggle_selected_favorite()
        assert tab.history[0]["favorite"] is False

    def test_delete_removes_entry(self, tab):
        tab.add_to_history("keep")
        tab.add_to_history("delete me")
        tab.list_history.setCurrentRow(0)
        tab.delete_selected_history()
        assert len(tab.history) == 1
        assert tab.history[0]["text"] == "keep"

    def test_restore_emits_signal_with_text(self, tab, qtbot=None):
        received = []
        tab.restore_requested.connect(received.append)
        tab.add_to_history("restore this")
        tab.list_history.setCurrentRow(0)
        tab.restore_history_to_forge()
        assert received == ["restore this"]


class TestFavoriteLast:
    def test_matches_top_entry_marks_favorite_in_place(self, tab):
        tab.add_to_history("just generated")
        tab.favorite_last("just generated")
        assert len(tab.history) == 1
        assert tab.history[0]["favorite"] is True

    def test_no_match_creates_new_entry(self, tab):
        tab.add_to_history("something else")
        tab.favorite_last("a different prompt")
        assert len(tab.history) == 2
        assert tab.history[0]["text"] == "a different prompt"
        assert tab.history[0]["favorite"] is True


class TestLoadsExistingFile:
    def test_loads_pre_existing_history_json(self, qapp, tmp_data_dir, monkeypatch):
        os.makedirs(tmp_data_dir, exist_ok=True)
        path = os.path.join(tmp_data_dir, "_history.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump([{"id": "x", "text": "preexisting", "timestamp": "t", "favorite": False}], f)
        tab2 = HistoryTab(tmp_data_dir)
        assert tab2.history[0]["text"] == "preexisting"
        assert tab2.list_history.count() == 1
