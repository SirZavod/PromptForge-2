"""Session 5 tests: LibraryTab's image zone / Source URL / LoRA binding
logic, against a temp data dir with the real five category folders.
Covers persistence (meta sidecar round-trips), the source-URL edit/
save/cancel state machine, the LoRA assign/clear flow, duplicate's
image-carry-over, and the connected/disconnected visibility hooks. The
widgets' actual on-screen appearance is what `python main.py` itself is
for — this file covers the behavior that doesn't need eyeballs.

Run headless with:
    QT_QPA_PLATFORM=offscreen python -m pytest tests/test_library_tab_session5.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile

import pytest
from PyQt6.QtWidgets import QApplication, QMessageBox

from backend.constants import CATEGORIES, THEMES
from backend.file_manager import init_folders, load_library_meta, find_library_image
from ui.dialogs import themed_message_box
from ui.tabs.library_tab import LibraryTab
from ui.widgets.image_zone import ImageDropZone


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


def _make_test_image(path):
    from PIL import Image
    Image.new("RGB", (32, 32), (255, 0, 0)).save(path, "PNG")


# ------------------------------------------------------------------
# Image zone
# ------------------------------------------------------------------
def test_image_zone_starts_placeholder(tab):
    assert tab.image_drop_zone._has_image is False


def test_handle_image_drop_requires_name(tab):
    tab.start_new_library_entry()
    tab.ent_lib_name.setText("")
    tab.handle_image_drop("/nonexistent/path.png")  # no-op, no name
    assert tab.image_drop_zone._has_image is False


def test_handle_image_drop_attaches_and_persists(tab, tmp_data_dir):
    src = os.path.join(tmp_data_dir, "src.png")
    _make_test_image(src)
    tab.switch_library_category("styles")
    tab.ent_lib_name.setText("MyStyle")
    tab.handle_image_drop(src)
    assert tab.image_drop_zone._has_image is True
    saved = find_library_image(tmp_data_dir, "styles", "MyStyle")
    assert saved and os.path.exists(saved)


# Session 28: the "Image: Size" slider was removed (Design Code #5,
# same reasoning as Builder's own Session 17.5 removal) — the preview
# now just fills whatever space its card gives it. The old
# test_slider_percent_round_trips_through_settings test covered a
# control that no longer exists; nothing replaces it since there's no
# manual sizing behavior left to test here.


# ------------------------------------------------------------------
# Source URL
# ------------------------------------------------------------------
def test_source_url_save_rejects_bad_scheme(tab, tmp_data_dir):
    _write_entry(tmp_data_dir, "scenarios", "Scn1")
    tab.switch_library_category("scenarios")
    tab.on_library_select("Scn1")
    tab._start_lib_source_edit()
    tab.ent_lib_source_url.setText("not-a-url")
    tab._save_lib_source_url()
    assert tab.lib_source_url is None
    assert tab.lbl_lib_source_error.text()


def test_source_url_save_persists_to_meta(tab, tmp_data_dir):
    _write_entry(tmp_data_dir, "scenarios", "Scn2")
    tab.switch_library_category("scenarios")
    tab.on_library_select("Scn2")
    tab._start_lib_source_edit()
    tab.ent_lib_source_url.setText("https://example.com/x")
    tab._save_lib_source_url()
    meta = load_library_meta(tmp_data_dir, "scenarios", "Scn2")
    assert meta["source_url"] == "https://example.com/x"

    # Reselecting elsewhere then back must reload the same URL.
    _write_entry(tmp_data_dir, "scenarios", "Scn3")
    tab.on_library_select("Scn3")
    assert tab.lib_source_url is None
    tab.on_library_select("Scn2")
    assert tab.lib_source_url == "https://example.com/x"


def test_source_url_cancel_does_not_persist(tab, tmp_data_dir):
    _write_entry(tmp_data_dir, "scenarios", "Scn4")
    tab.switch_library_category("scenarios")
    tab.on_library_select("Scn4")
    tab._start_lib_source_edit()
    tab.ent_lib_source_url.setText("https://example.com/never-saved")
    tab._cancel_lib_source_edit()
    assert tab.lib_source_url is None
    meta = load_library_meta(tmp_data_dir, "scenarios", "Scn4")
    assert meta["source_url"] is None


# ------------------------------------------------------------------
# LoRA binding
# ------------------------------------------------------------------
def test_lora_visibility_hidden_when_disconnected(tab):
    # Session 28 (Design Code #4): the row itself no longer hides while
    # disconnected — only Assign/Clear disable, same pattern as
    # Builder's own action cluster (Session 22).
    tab._refresh_lib_lora_visibility(False)
    assert tab.btn_lib_lora_assign.isVisible() is True
    assert tab.btn_lib_lora_assign.isEnabled() is False
    assert tab.btn_lib_lora_clear.isEnabled() is False


def test_lora_visibility_shown_when_connected(tab):
    tab._refresh_lib_lora_visibility(True)
    assert tab.comfy_connected is True


def test_assign_lora_with_empty_list_shows_message(tab, monkeypatch):
    called = {}
    monkeypatch.setattr(themed_message_box, "information",
                         lambda *a, **k: called.setdefault("hit", True))
    tab._available_loras = []
    tab._assign_lib_lora()
    assert called.get("hit") is True


def test_clear_lora_resets_and_persists(tab, tmp_data_dir):
    _write_entry(tmp_data_dir, "scenarios", "Scn5")
    tab.switch_library_category("scenarios")
    tab.on_library_select("Scn5")
    tab.lib_entry_lora = "Loras/foo.safetensors"
    tab._persist_current_lib_meta()
    assert load_library_meta(tmp_data_dir, "scenarios", "Scn5")["lora"] == "Loras/foo.safetensors"
    tab._clear_lib_lora()
    assert tab.lib_entry_lora is None
    assert load_library_meta(tmp_data_dir, "scenarios", "Scn5")["lora"] is None


def test_update_available_loras_hook(tab):
    tab._update_available_loras(["a.safetensors", "b.safetensors"])
    assert tab._available_loras == ["a.safetensors", "b.safetensors"]


# ------------------------------------------------------------------
# Duplicate carries the image over
# ------------------------------------------------------------------
def test_duplicate_carries_image_over(tab, tmp_data_dir):
    src = os.path.join(tmp_data_dir, "src2.png")
    _make_test_image(src)
    tab.switch_library_category("styles")
    tab.ent_lib_name.setText("StyleWithImage")
    tab.txt_lib_tags.setPlainText("some tags")
    tab.save_to_library()
    tab.handle_image_drop(src)

    tab.duplicate_library_entry()
    new_name = "StyleWithImage_copy"
    saved = find_library_image(tmp_data_dir, "styles", new_name)
    assert saved and os.path.exists(saved)
