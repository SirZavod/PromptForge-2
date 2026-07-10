"""Session 31 tests: restored LoRA-dependency color-coding on Library's
entry tree (Скрин 3).

Covers both halves:
- `backend.lora_deps.compute_lora_dependency_status` — the three-state
  (ok/missing/conflict) classification, per the plan's semantics:
  conflict (2+ same-basename files) wins over an exact-path match,
  ok covers both an exact match and a single unambiguous relocated
  match, missing is only "nothing anywhere shares this name".
- `LibraryTab` wiring — coloring only appears after an explicit "Check
  LoRA dependencies" click, survives a category switch/search refresh
  while on the Library page, and `clear_lora_dependency_colors()`
  (called by MainWindow on nav-away) wipes it back to nothing.

Run headless with:
    QT_QPA_PLATFORM=offscreen python -m pytest tests/test_library_tab_session31.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication, QMessageBox

from backend.constants import CATEGORIES, THEMES
from backend.file_manager import init_folders, save_library_meta
from backend.lora_deps import compute_lora_dependency_status
from ui.dialogs import themed_message_box
from ui.tabs.library_tab import LibraryTab, _KIND_ENTRY

# See test_library_tab_session30.py's own comment on this pattern —
# holding a strong reference for the whole module's lifetime avoids a
# cross-test crash from a parentless widget's deferred Qt events firing
# against an already-collected C++ object.
_keepalive = []


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture()
def tmp_data_dir():
    with tempfile.TemporaryDirectory() as d:
        init_folders(d, CATEGORIES)
        yield d


def _touch(data_dir, cat, name):
    with open(os.path.join(data_dir, cat, f"{name}.txt"), "w", encoding="utf-8") as f:
        f.write("some tags")


@pytest.fixture()
def tab(qapp, tmp_data_dir, monkeypatch):
    monkeypatch.setattr(themed_message_box, "information", lambda *a, **k: None)
    monkeypatch.setattr(themed_message_box, "critical", lambda *a, **k: None)
    monkeypatch.setattr(themed_message_box, "warning", lambda *a, **k: None)
    monkeypatch.setattr(themed_message_box, "question",
                         lambda *a, **k: QMessageBox.StandardButton.Yes)
    settings_file = os.path.join(tmp_data_dir, "_settings.json")
    t = LibraryTab(tmp_data_dir, THEMES["dark"], {}, settings_file)
    _keepalive.append(t)
    return t


def _entry_color(tab, category, base):
    tab.switch_library_category(category)
    item = tab._find_entry_item(base)
    assert item is not None
    return item.foreground(0).color()


# ------------------------------------------------------------------
# Backend: compute_lora_dependency_status
# ------------------------------------------------------------------
def test_exact_match_is_ok(tmp_data_dir):
    _touch(tmp_data_dir, "characters", "Akane")
    save_library_meta(tmp_data_dir, "characters", "Akane", lora="loras\\akane.safetensors")
    status = compute_lora_dependency_status(tmp_data_dir, CATEGORIES, ["loras\\akane.safetensors"])
    assert status[("characters", "Akane")] == "ok"


def test_nothing_anywhere_is_missing(tmp_data_dir):
    _touch(tmp_data_dir, "characters", "Akane")
    save_library_meta(tmp_data_dir, "characters", "Akane", lora="loras\\akane.safetensors")
    status = compute_lora_dependency_status(tmp_data_dir, CATEGORIES, ["loras\\other.safetensors"])
    assert status[("characters", "Akane")] == "missing"


def test_single_relocated_match_is_ok_not_conflict(tmp_data_dir):
    # Bound to "loras\\akane.safetensors" but ComfyUI only has the same
    # filename under a different folder — unambiguous, still "ok".
    _touch(tmp_data_dir, "characters", "Akane")
    save_library_meta(tmp_data_dir, "characters", "Akane", lora="loras\\akane.safetensors")
    status = compute_lora_dependency_status(
        tmp_data_dir, CATEGORIES, ["loras\\Characters\\akane.safetensors"])
    assert status[("characters", "Akane")] == "ok"


def test_two_files_same_basename_is_conflict(tmp_data_dir):
    _touch(tmp_data_dir, "characters", "Akane")
    save_library_meta(tmp_data_dir, "characters", "Akane", lora="loras\\akane.safetensors")
    status = compute_lora_dependency_status(
        tmp_data_dir, CATEGORIES,
        ["loras\\akane.safetensors", "loras\\Alt\\akane.safetensors"])
    assert status[("characters", "Akane")] == "conflict"


def test_conflict_wins_even_when_bound_path_is_the_exact_match(tmp_data_dir):
    # The bound path IS one of the two duplicates — still flagged red,
    # since the ambiguity itself (which file ComfyUI actually resolves)
    # is the risk, not just "is today's binding technically correct".
    _touch(tmp_data_dir, "characters", "Akane")
    save_library_meta(tmp_data_dir, "characters", "Akane", lora="loras\\akane.safetensors")
    status = compute_lora_dependency_status(
        tmp_data_dir, CATEGORIES,
        ["loras\\akane.safetensors", "loras\\Alt\\akane.safetensors"])
    assert status[("characters", "Akane")] == "conflict"


def test_unbound_entries_are_absent_from_the_map(tmp_data_dir):
    _touch(tmp_data_dir, "characters", "NoLora")
    status = compute_lora_dependency_status(tmp_data_dir, CATEGORIES, [])
    assert ("characters", "NoLora") not in status


def test_canon_outfit_included(tmp_data_dir):
    _touch(tmp_data_dir, "outfits", "Akane_Canon_1")
    save_library_meta(tmp_data_dir, "outfits", "Akane_Canon_1", lora="loras\\akane.safetensors")
    status = compute_lora_dependency_status(tmp_data_dir, CATEGORIES, ["loras\\akane.safetensors"])
    assert status[("outfits", "Akane_Canon_1")] == "ok"


# ------------------------------------------------------------------
# UI wiring: click-gated coloring, survives refresh, clears on nav-away
# ------------------------------------------------------------------
def test_no_coloring_before_check_is_clicked(tab, tmp_data_dir):
    _touch(tmp_data_dir, "characters", "Akane")
    _touch(tmp_data_dir, "characters", "Akane")
    save_library_meta(tmp_data_dir, "characters", "Akane", lora="loras\\akane.safetensors")
    tab.refresh_library_list()
    tab.switch_library_category("characters")
    assert tab.lora_dep_status == {}


def test_check_paints_green_for_ok_entry(tab, tmp_data_dir):
    _touch(tmp_data_dir, "characters", "Akane")
    _touch(tmp_data_dir, "characters", "Akane")
    save_library_meta(tmp_data_dir, "characters", "Akane", lora="loras\\akane.safetensors")
    tab.comfy_connected = True
    tab._update_available_loras(["loras\\akane.safetensors"])
    tab.check_library_lora_dependencies()

    assert tab.lora_dep_status[("characters", "Akane")] == "ok"
    color = _entry_color(tab, "characters", "Akane")
    assert color.name() == QColor(tab.colors["success"]).name()


def test_coloring_survives_category_switch_and_search(tab, tmp_data_dir):
    _touch(tmp_data_dir, "characters", "Akane")
    _touch(tmp_data_dir, "characters", "Akane")
    save_library_meta(tmp_data_dir, "characters", "Akane", lora="loras\\akane.safetensors")
    tab.comfy_connected = True
    tab._update_available_loras(["loras\\akane.safetensors"])
    tab.check_library_lora_dependencies()

    tab.switch_library_category("styles")
    tab.switch_library_category("characters")
    assert tab.lora_dep_status[("characters", "Akane")] == "ok"
    item = tab._find_entry_item("Akane")
    assert item.foreground(0).color().isValid()


def test_clear_lora_dependency_colors_wipes_status_and_uncolors(tab, tmp_data_dir):
    _touch(tmp_data_dir, "characters", "Akane")
    _touch(tmp_data_dir, "characters", "Akane")
    save_library_meta(tmp_data_dir, "characters", "Akane", lora="loras\\akane.safetensors")
    tab.comfy_connected = True
    tab._update_available_loras(["loras\\akane.safetensors"])
    tab.check_library_lora_dependencies()
    assert tab.lora_dep_status

    tab.clear_lora_dependency_colors()
    assert tab.lora_dep_status == {}


def test_check_disabled_without_comfy_connection_does_not_color(tab, tmp_data_dir):
    _touch(tmp_data_dir, "characters", "Akane")
    _touch(tmp_data_dir, "characters", "Akane")
    save_library_meta(tmp_data_dir, "characters", "Akane", lora="loras\\akane.safetensors")
    tab.comfy_connected = False
    tab.check_library_lora_dependencies()
    assert tab.lora_dep_status == {}
