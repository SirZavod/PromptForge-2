"""Session 45.1 tests: Active/Inactive bulk buttons moved onto the
count/LoRA-check row, and the cross-tab staleness bug where toggling
Active/Inactive in Library didn't reach Builder's dropdowns without an
app restart.

Covers:
- `_set_active_and_refresh()` and `_bulk_set_active()` both emit
  `library_changed` (reusing the exact Session 30.3 signal/pipeline).
- End-to-end: with the two tabs wired together the same way `main.py`
  does, marking an entry Inactive makes it disappear from Builder's
  filtered dropdown list with no manual refresh call.
- Layout: the two bulk buttons and the count/LoRA-check row all end up
  as children of the same parent layout.

Run headless with:
    QT_QPA_PLATFORM=offscreen python -m pytest tests/test_library_active_session45_1.py -v
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

_keepalive = []


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
def library(qapp, tmp_data_dir, monkeypatch):
    monkeypatch.setattr(themed_message_box, "information", lambda *a, **k: None)
    monkeypatch.setattr(themed_message_box, "critical", lambda *a, **k: None)
    monkeypatch.setattr(themed_message_box, "warning", lambda *a, **k: None)
    monkeypatch.setattr(themed_message_box, "question",
                         lambda *a, **k: QMessageBox.StandardButton.Yes)
    settings_file = os.path.join(tmp_data_dir, "_settings.json")
    tab = LibraryTab(tmp_data_dir, THEMES["dark"], {}, settings_file)
    tab.switch_library_category("characters")
    _keepalive.append(tab)
    return tab


@pytest.fixture()
def builder(qapp, tmp_data_dir):
    settings_file = os.path.join(tmp_data_dir, "_settings.json")
    tab = BuilderTab(tmp_data_dir, THEMES["dark"], {}, settings_file)
    _keepalive.append(tab)
    return tab


# ------------------------------------------------------------------
# Part B: library_changed fires on Active/Inactive changes
# ------------------------------------------------------------------
def test_set_active_and_refresh_emits_library_changed_for_entry(library):
    spy = MagicMock()
    library.library_changed.connect(spy)
    library._set_active_and_refresh(["Alice"], [], False)
    spy.assert_called_once()


def test_set_active_and_refresh_emits_library_changed_for_folder(library):
    library.set_entry_folder = None  # not used, just guarding against accidental use
    spy = MagicMock()
    library.library_changed.connect(spy)
    library._set_active_and_refresh([], ["SomeFolder"], False)
    spy.assert_called_once()


def test_bulk_set_active_selection_scoped_emits_library_changed(library):
    item = library._find_entry_item("Alice")
    assert item is not None
    item.setSelected(True)

    spy = MagicMock()
    library.library_changed.connect(spy)
    library._bulk_set_active(False)
    spy.assert_called_once()


def test_bulk_set_active_whole_library_emits_library_changed(library):
    spy = MagicMock()
    library.library_changed.connect(spy)
    library._bulk_set_active(False)  # nothing selected -> whole-library branch
    spy.assert_called_once()


# ------------------------------------------------------------------
# End-to-end: wired the same way main.py wires the two tabs
# ------------------------------------------------------------------
def test_marking_inactive_reaches_builder_live_via_signal(library, builder):
    library.library_changed.connect(builder.refresh_library_backed_combos)

    assert "Alice" in builder._lib_active_file_list("characters")
    library._set_active_and_refresh(["Alice"], [], False)
    # No manual refresh_library_backed_combos() call here — the
    # connected signal alone must be sufficient.
    assert "Alice" not in builder._lib_active_file_list("characters")

    library._set_active_and_refresh(["Alice"], [], True)
    assert "Alice" in builder._lib_active_file_list("characters")


def test_bulk_inactive_all_reaches_builder_live_via_signal(library, builder):
    library.library_changed.connect(builder.refresh_library_backed_combos)
    library._bulk_set_active(False)  # whole-library
    assert builder._lib_active_file_list("characters") == []
    library._bulk_set_active(True)
    assert set(builder._lib_active_file_list("characters")) == {"Alice", "Bob", "Carol"}


# ------------------------------------------------------------------
# Part A: bulk buttons now share the count/LoRA-check row
# ------------------------------------------------------------------
def test_bulk_buttons_share_the_count_row(library):
    count_parent = library.lbl_lib_count.parentWidget()
    deps_parent = library.btn_check_lora_deps.parentWidget()
    inactive_parent = library.btn_inactive_all.parentWidget()
    active_parent = library.btn_active_all.parentWidget()

    # Each button/label sits inside its own small "card" (per
    # _build_card), but all four cards must be siblings under the very
    # same row container.
    def _row_container(w):
        return w.parentWidget()

    assert _row_container(count_parent) is _row_container(deps_parent)
    assert _row_container(count_parent) is _row_container(inactive_parent)
    assert _row_container(count_parent) is _row_container(active_parent)
