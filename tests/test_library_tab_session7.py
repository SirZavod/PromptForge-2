"""Session 7 tests: the "🔍 Check LoRA dependencies" flow (scan, missing
report, candidate finder/apply) and the "📦 Export library" / "📥 Import
library" flow, on top of LibraryTab.

Run headless with:
    QT_QPA_PLATFORM=offscreen python -m pytest tests/test_library_tab_session7.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import zipfile

import pytest
from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox

from backend.constants import CATEGORIES, THEMES
from backend.file_manager import (
    init_folders,
    load_library_meta,
    save_library_meta,
)
from ui.dialogs.lora_dependency_dialog import LoraCandidatesDialog, LoraDependencyReportDialog
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


# ------------------------------------------------------------------
# LoRA dependency button gating
# ------------------------------------------------------------------
def test_lora_deps_button_disabled_until_connected(tab):
    assert tab.btn_check_lora_deps.isEnabled() is False
    tab._refresh_lib_lora_visibility(True)
    assert tab.btn_check_lora_deps.isEnabled() is True
    tab._refresh_lib_lora_visibility(False)
    assert tab.btn_check_lora_deps.isEnabled() is False


def test_check_deps_requires_connection(tab, monkeypatch):
    called = {}
    monkeypatch.setattr(themed_message_box, "information",
                         lambda *a, **k: called.setdefault("hit", True))
    tab.check_library_lora_dependencies()
    assert called.get("hit") is True


# ------------------------------------------------------------------
# Scan + report + apply candidate (end to end through the tab)
# ------------------------------------------------------------------
def test_check_deps_all_clear(tab, tmp_data_dir, monkeypatch):
    _write_entry(tmp_data_dir, "styles", "S1")
    save_library_meta(tmp_data_dir, "styles", "S1", lora="Loras/found.safetensors")
    tab._refresh_lib_lora_visibility(True)
    tab._update_available_loras(["Loras/found.safetensors"])

    called = {}
    monkeypatch.setattr(themed_message_box, "information",
                         lambda *a, **k: called.setdefault("msg", args_text(a)))
    tab.check_library_lora_dependencies()
    assert "All LoRAs" in called.get("msg", "") or "Nothing missing" in called.get("msg", "")


def args_text(args):
    return " ".join(str(a) for a in args)


def test_check_deps_reports_missing_and_opens_dialog(tab, tmp_data_dir, monkeypatch):
    _write_entry(tmp_data_dir, "styles", "S2")
    save_library_meta(tmp_data_dir, "styles", "S2", lora="Loras/missing.safetensors")
    tab._refresh_lib_lora_visibility(True)
    tab._update_available_loras(["Loras/elsewhere/missing.safetensors"])

    opened = {}

    def fake_exec(self):
        opened["dlg"] = self
        return 0

    monkeypatch.setattr(LoraDependencyReportDialog, "exec", fake_exec)
    tab.check_library_lora_dependencies()
    assert "dlg" in opened
    assert "Loras/missing.safetensors" in opened["dlg"]._missing


def test_apply_lora_candidate_updates_meta_and_refreshes(tab, tmp_data_dir):
    _write_entry(tmp_data_dir, "styles", "S3")
    save_library_meta(tmp_data_dir, "styles", "S3", lora="Loras/old.safetensors")

    updated = tab._apply_lora_candidate_and_refresh(
        "Loras/old.safetensors", "Loras/new.safetensors", [("styles", "S3")])
    assert updated == 1
    meta = load_library_meta(tmp_data_dir, "styles", "S3")
    assert meta["lora"] == "Loras/new.safetensors"


def test_candidates_dialog_single_and_collision(tmp_data_dir, qapp):
    missing = {
        "Loras/a.safetensors": [("styles", "S1")],
        "Loras/b.safetensors": [("styles", "S2")],
        "Loras/c.safetensors": [("styles", "S3")],
    }
    available = [
        "Loras/other/a.safetensors",  # single match for a
        "Loras/x/b.safetensors", "Loras/y/b.safetensors",  # collision for b
        # nothing matches c
    ]
    applied = []

    def on_apply(old, new, affected):
        applied.append((old, new, affected))
        return len(affected)

    dlg = LoraCandidatesDialog(missing, available, on_apply)
    assert "Loras/a.safetensors" in dlg._row_use_this
    assert "Loras/b.safetensors" not in dlg._row_use_this  # collision, never auto-eligible
    assert "Loras/c.safetensors" not in dlg._row_use_this  # no match at all

    dlg._use_all_single_matches()
    assert applied == [("Loras/a.safetensors", "Loras/other/a.safetensors", [("styles", "S1")])]


# ------------------------------------------------------------------
# Export / import
# ------------------------------------------------------------------
def test_export_then_import_into_fresh_library(tab, tmp_data_dir, monkeypatch):
    _write_entry(tmp_data_dir, "styles", "ExportMe")
    tab.refresh_library_list()

    with tempfile.TemporaryDirectory() as export_dir:
        zip_path = os.path.join(export_dir, "lib.zip")
        monkeypatch.setattr(QFileDialog, "getSaveFileName",
                             staticmethod(lambda *a, **k: (zip_path, "")))
        info_calls = []
        monkeypatch.setattr(themed_message_box, "information",
                             lambda *a, **k: info_calls.append(args_text(a)))
        tab.export_library()
        assert os.path.exists(zip_path)
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
        assert any("ExportMe.txt" in n for n in names)
        assert not any("_comfy_previews" in n for n in names)

        with tempfile.TemporaryDirectory() as fresh_dir:
            init_folders(fresh_dir, CATEGORIES)
            fresh_settings_file = os.path.join(fresh_dir, "_settings.json")
            fresh_tab = LibraryTab(fresh_dir, tab.colors, {}, fresh_settings_file)

            monkeypatch.setattr(QFileDialog, "getOpenFileName",
                                 staticmethod(lambda *a, **k: (zip_path, "")))
            report_calls = []
            import ui.dialogs.library_export_import_dialog as report_mod
            monkeypatch.setattr(report_mod.LibraryExportImportDialog, "show_report",
                                 staticmethod(lambda *a, **k: report_calls.append(a)))
            fresh_tab.import_library()
            assert os.path.exists(os.path.join(fresh_dir, "styles", "ExportMe.txt"))
            assert len(report_calls) == 1


def test_import_skips_existing_entry(tab, tmp_data_dir, monkeypatch):
    _write_entry(tmp_data_dir, "styles", "Dup", content="original content")

    with tempfile.TemporaryDirectory() as export_dir:
        zip_path = os.path.join(export_dir, "lib.zip")
        monkeypatch.setattr(QFileDialog, "getSaveFileName",
                             staticmethod(lambda *a, **k: (zip_path, "")))
        monkeypatch.setattr(themed_message_box, "information", lambda *a, **k: None)
        tab.export_library()

        # Now change the same-named entry locally and re-import — the
        # existing (changed) file must survive untouched.
        _write_entry(tmp_data_dir, "styles", "Dup", content="changed after export")
        monkeypatch.setattr(QFileDialog, "getOpenFileName",
                             staticmethod(lambda *a, **k: (zip_path, "")))
        reports = []
        import ui.dialogs.library_export_import_dialog as report_mod
        monkeypatch.setattr(report_mod.LibraryExportImportDialog, "show_report",
                             staticmethod(lambda parent, title, content: reports.append(content)))
        tab.import_library()

        with open(os.path.join(tmp_data_dir, "styles", "Dup.txt"), encoding="utf-8") as f:
            assert f.read() == "changed after export"
        assert reports and "Skipped 1" in reports[0]
