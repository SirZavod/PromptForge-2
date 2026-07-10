"""Session 30 tests: the per-entry LoRA strength control added directly
under the Library LoRA Assign/Clear row (Скрин 2).

Covers: the backend meta round-trip for the new `lora_strength` field
(default 1.0, persists only when meaningful, survives a lora-path
rewrite via lora_deps.apply_lora_candidate), and the UI-level spin box
— default value, editing persists, reload restores it, a brand-new
entry starts at 1.0, and NoScrollDoubleSpinBox's wheel-ignoring
behavior is actually the widget in use here (Session 25.3 reuse, not a
plain QDoubleSpinBox reintroducing the wheel-scroll bug).

Run headless with:
    QT_QPA_PLATFORM=offscreen python -m pytest tests/test_library_tab_session30.py -v
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
from backend.file_manager import init_folders, load_library_meta, save_library_meta
from backend.lora_deps import apply_lora_candidate
from ui.dialogs import themed_message_box
from ui.tabs.library_tab import LibraryTab
from ui.widgets.no_scroll_spinbox import NoScrollDoubleSpinBox

# Keeps every LibraryTab this module creates alive for the whole test
# run. PyQt6 widgets built with no parent (as every tab fixture here
# does) get torn down the moment Python garbage-collects the last
# reference to them; if that happens mid-suite, a later, unrelated
# test can crash when Qt delivers a stray/deferred event to an
# AutocompleteCombobox whose underlying C++ object no longer exists.
# Explicit close()/deleteLater() was tried first and made this worse
# (it just moved the crash earlier); simply never releasing the
# reference sidesteps the problem entirely, at the cost of some
# memory that's reclaimed anyway when the test process exits.
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
def tab(qapp, tmp_data_dir, monkeypatch):
    monkeypatch.setattr(themed_message_box, "information", lambda *a, **k: None)
    monkeypatch.setattr(themed_message_box, "critical", lambda *a, **k: None)
    monkeypatch.setattr(themed_message_box, "warning", lambda *a, **k: None)
    settings_file = os.path.join(tmp_data_dir, "_settings.json")
    t = LibraryTab(tmp_data_dir, THEMES["dark"], {}, settings_file)
    _keepalive.append(t)
    return t


def _write_entry(data_dir, cat, name, content="some tags"):
    with open(os.path.join(data_dir, cat, f"{name}.txt"), "w", encoding="utf-8") as f:
        f.write(content)


# ------------------------------------------------------------------
# Backend: meta round-trip
# ------------------------------------------------------------------
def test_load_library_meta_defaults_strength_to_one(tmp_data_dir):
    meta = load_library_meta(tmp_data_dir, "characters", "NoSidecar")
    assert meta["lora_strength"] == 1.0


def test_save_library_meta_round_trips_strength(tmp_data_dir):
    save_library_meta(tmp_data_dir, "characters", "Akane",
                       lora="PromptForgeLoras\\akane.safetensors", lora_strength=0.6)
    meta = load_library_meta(tmp_data_dir, "characters", "Akane")
    assert meta["lora"] == "PromptForgeLoras\\akane.safetensors"
    assert meta["lora_strength"] == 0.6


def test_save_library_meta_keeps_sidecar_for_nondefault_strength_alone(tmp_data_dir):
    # Even with no LoRA bound, a strength moved off 1.0 is meaningful
    # enough to keep the sidecar around (mirrors force_first's own
    # "any one field alone is enough" rule).
    save_library_meta(tmp_data_dir, "characters", "Bare", lora_strength=1.5)
    path = os.path.join(tmp_data_dir, "characters", "Bare.meta.json")
    assert os.path.exists(path)
    assert load_library_meta(tmp_data_dir, "characters", "Bare")["lora_strength"] == 1.5


def test_save_library_meta_all_default_deletes_sidecar(tmp_data_dir):
    save_library_meta(tmp_data_dir, "characters", "Temp", lora="x.safetensors", lora_strength=2.0)
    path = os.path.join(tmp_data_dir, "characters", "Temp.meta.json")
    assert os.path.exists(path)
    save_library_meta(tmp_data_dir, "characters", "Temp", lora=None, lora_strength=1.0)
    assert not os.path.exists(path)


def test_apply_lora_candidate_preserves_strength(tmp_data_dir):
    save_library_meta(tmp_data_dir, "characters", "Rewrite",
                       lora="old\\path.safetensors", lora_strength=0.42)
    updated = apply_lora_candidate(
        tmp_data_dir, "old\\path.safetensors", "new\\path.safetensors",
        [("characters", "Rewrite")])
    assert updated == 1
    meta = load_library_meta(tmp_data_dir, "characters", "Rewrite")
    assert meta["lora"] == "new\\path.safetensors"
    assert meta["lora_strength"] == 0.42


# ------------------------------------------------------------------
# UI: strength control on the card
# ------------------------------------------------------------------
def test_strength_control_uses_no_scroll_spinbox(tab):
    tab.start_new_library_entry()
    assert isinstance(tab.spin_lib_lora_strength, NoScrollDoubleSpinBox)


def test_new_entry_strength_defaults_to_one(tab):
    tab.start_new_library_entry()
    assert tab.lib_entry_lora_strength == 1.0
    assert tab.spin_lib_lora_strength.value() == 1.0


def test_editing_strength_persists_and_reloads(tab, tmp_data_dir):
    _write_entry(tmp_data_dir, "characters", "Char1")
    tab.switch_library_category("characters")
    tab.on_library_select("Char1")
    tab.spin_lib_lora_strength.setValue(0.8)
    meta = load_library_meta(tmp_data_dir, "characters", "Char1")
    assert meta["lora_strength"] == 0.8

    # Reselecting elsewhere then back must reload the same strength.
    _write_entry(tmp_data_dir, "characters", "Char2")
    tab.on_library_select("Char2")
    assert tab.lib_entry_lora_strength == 1.0
    tab.on_library_select("Char1")
    assert tab.lib_entry_lora_strength == 0.8
    assert tab.spin_lib_lora_strength.value() == 0.8


def test_strength_survives_lora_assign_and_clear(tab, tmp_data_dir):
    _write_entry(tmp_data_dir, "characters", "Char3")
    tab.switch_library_category("characters")
    tab.on_library_select("Char3")
    tab.spin_lib_lora_strength.setValue(1.3)

    tab._update_available_loras(["some\\lora.safetensors"])
    tab.comfy_connected = True
    from ui.dialogs.lora_assign_dialog import LoraAssignDialog
    original = LoraAssignDialog.get_selected_lora
    LoraAssignDialog.get_selected_lora = staticmethod(lambda *a, **k: "some\\lora.safetensors")
    try:
        tab._assign_lib_lora()
    finally:
        LoraAssignDialog.get_selected_lora = original

    assert tab.lib_entry_lora == "some\\lora.safetensors"
    assert tab.lib_entry_lora_strength == 1.3
    meta = load_library_meta(tmp_data_dir, "characters", "Char3")
    assert meta["lora_strength"] == 1.3

    tab._clear_lib_lora()
    assert tab.lib_entry_lora is None
    # Clearing the binding doesn't reset the strength the user already
    # dialed in — it's still there if they re-assign a LoRA.
    assert tab.lib_entry_lora_strength == 1.3
