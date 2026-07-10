"""Session 8 tests: GalleryTab (ui/tabs/gallery_tab.py) — grid registration,
count label, relayout column math, resolve/reveal target logic, and the
placeholder-glyph regression this session's own on-screen check caught
(see GalleryCell._style_thumb_placeholder's docstring).

Requires a QApplication instance — `qapp` fixture handles that once for
the whole module. Run headless with:
    QT_QPA_PLATFORM=offscreen python -m pytest tests/test_gallery_tab_session8.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtGui import QColor, QImage
from PyQt6.QtWidgets import QApplication

from backend.constants import GALLERY_CELL_OUTER_WIDTH, THEMES
from backend.file_manager import FileManagerError, resolve_output_folder_for
from ui.tabs.gallery_tab import GalleryTab


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


@pytest.fixture
def real_image(tmp_path):
    path = str(tmp_path / "sample.png")
    img = QImage(200, 150, QImage.Format.Format_RGB32)
    img.fill(QColor("blue"))
    img.save(path)
    return path


class TestPlaceholder:
    def test_placeholder_shown_before_any_result(self, qapp):
        tab = GalleryTab(THEMES["dark"])
        assert tab._placeholder_hidden is False
        assert tab.lbl_placeholder.isHidden() is False

    def test_placeholder_hidden_after_first_result(self, qapp, real_image):
        tab = GalleryTab(THEMES["dark"])
        tab._gallery_register_result(real_image, None, None, "First")
        assert tab._placeholder_hidden is True
        assert tab.lbl_placeholder.isHidden() is True


class TestCellPlaceholderGlyph:
    def test_new_cell_shows_placeholder_glyph_before_thumbnail_decodes(self, qapp):
        # Regression test for the setPixmap(QPixmap())-wipes-setText bug
        # caught during this session's on-screen check: immediately
        # after construction (before the QThreadPool runnable has had a
        # chance to run), the cell must show the 🖼 glyph, not blank.
        tab = GalleryTab(THEMES["dark"])
        tab._gallery_register_result("/does/not/exist.png", None, None, "Missing")
        cell = tab.gallery_cells[0]
        assert cell.thumb.text() == "🖼"
        assert cell.thumb.pixmap() is None or cell.thumb.pixmap().isNull()


class TestRegisterAndCount:
    def test_register_appends_entry_and_cell_1to1(self, qapp, real_image):
        tab = GalleryTab(THEMES["dark"])
        for i in range(3):
            tab._gallery_register_result(real_image, f"remote_{i}.png", "sub", f"Entry {i}")
        assert len(tab.gallery_entries) == 3
        assert len(tab.gallery_cells) == 3
        assert tab.gallery_entries[1]["remote_filename"] == "remote_1.png"

    def test_count_label_pluralizes_correctly(self, qapp, real_image):
        tab = GalleryTab(THEMES["dark"])
        assert tab.lbl_count.text() == ""
        tab._gallery_register_result(real_image, None, None, "One")
        assert tab.lbl_count.text() == "1 image"
        tab._gallery_register_result(real_image, None, None, "Two")
        assert tab.lbl_count.text() == "2 images"

    def test_thumbnail_decodes_off_thread_and_lands_on_cell(self, qapp, real_image):
        tab = GalleryTab(THEMES["dark"])
        tab._gallery_register_result(real_image, None, None, "Real")
        tab._threadpool.waitForDone(2000)
        qapp.processEvents()
        cell = tab.gallery_cells[0]
        assert cell.thumb.text() == ""
        assert cell.thumb.pixmap() is not None
        assert not cell.thumb.pixmap().isNull()


class TestRelayout:
    def test_column_count_matches_available_width(self, qapp, real_image):
        tab = GalleryTab(THEMES["dark"])
        for i in range(5):
            tab._gallery_register_result(real_image, None, None, f"E{i}")
        tab.scroll.resize(GALLERY_CELL_OUTER_WIDTH * 2 + 10, 400)
        tab._gallery_relayout_now()
        positions = [
            tab.grid_layout.getItemPosition(tab.grid_layout.indexOf(c))[:2]
            for c in tab.gallery_cells
        ]
        # 2 columns fit -> row/col pairs 0,0 0,1 1,0 1,1 2,0
        assert positions == [(0, 0), (0, 1), (1, 0), (1, 1), (2, 0)]

    def test_relayout_is_a_noop_with_no_cells(self, qapp):
        tab = GalleryTab(THEMES["dark"])
        tab._gallery_relayout_now()  # must not raise


class TestResolveTarget:
    def test_falls_back_to_local_path_when_no_output_dir(self, qapp, real_image):
        tab = GalleryTab(THEMES["dark"])
        entry = {"local_path": real_image, "remote_filename": "r.png", "remote_subfolder": ""}
        target, folder = tab._gallery_resolve_target(entry)
        assert target == os.path.abspath(real_image)
        assert folder == os.path.dirname(os.path.abspath(real_image))

    def test_prefers_comfy_output_dir_when_set_and_resolvable(self, qapp, real_image, tmp_path):
        out_dir = tmp_path / "comfy_output"
        (out_dir / "sub").mkdir(parents=True)
        tab = GalleryTab(THEMES["dark"])
        tab.comfy_output_dir = str(out_dir)
        entry = {"local_path": real_image, "remote_filename": "r.png", "remote_subfolder": "sub"}
        target, folder = tab._gallery_resolve_target(entry)
        assert folder == str(out_dir / "sub")
        assert target == str(out_dir / "sub" / "r.png")

    def test_falls_back_when_comfy_output_dir_does_not_exist(self, qapp, real_image):
        tab = GalleryTab(THEMES["dark"])
        tab.comfy_output_dir = "/nonexistent_output_dir_xyz"
        entry = {"local_path": real_image, "remote_filename": "r.png", "remote_subfolder": ""}
        target, folder = tab._gallery_resolve_target(entry)
        assert target == os.path.abspath(real_image)


class TestRevealAndFullView:
    def test_reveal_shows_warning_on_failure_instead_of_raising(self, qapp, real_image, monkeypatch):
        tab = GalleryTab(THEMES["dark"])
        entry = {"local_path": real_image, "remote_filename": None, "remote_subfolder": ""}

        def _boom(target_file, folder):
            raise FileManagerError("boom")

        monkeypatch.setattr("ui.tabs.gallery_tab.reveal_file_in_explorer", _boom)
        warned = {}

        def _fake_warning(parent, title, text):
            warned["title"] = title
            warned["text"] = text

        monkeypatch.setattr("ui.tabs.gallery_tab.themed_message_box.warning", _fake_warning)
        tab._gallery_reveal_in_explorer(entry)
        assert warned.get("text") == "boom"

    def test_full_view_warns_when_file_missing(self, qapp, monkeypatch):
        tab = GalleryTab(THEMES["dark"])
        entry = {"local_path": "/does/not/exist.png", "remote_filename": None, "remote_subfolder": ""}
        warned = {}

        def _fake_warning(parent, title, text):
            warned["text"] = text

        monkeypatch.setattr("ui.tabs.gallery_tab.themed_message_box.warning", _fake_warning)
        tab._gallery_open_full_view(entry)
        assert "no longer available" in warned.get("text", "")


class TestThemeToggle:
    def test_set_colors_updates_tab_and_existing_cells_without_error(self, qapp, real_image):
        tab = GalleryTab(THEMES["dark"])
        tab._gallery_register_result(real_image, None, None, "E")
        tab.set_colors(THEMES["light"])
        assert tab.colors == THEMES["light"]
        assert tab.gallery_cells[0]._colors == THEMES["light"]


class TestResolveOutputFolderForPure:
    def test_none_out_dir_returns_none(self):
        assert resolve_output_folder_for(None, None) is None

    def test_nonexistent_dir_returns_none(self):
        assert resolve_output_folder_for("/nonexistent_dir_xyz_abc", None) is None

    def test_existing_dir_with_subfolder(self, tmp_path):
        (tmp_path / "sub").mkdir()
        assert resolve_output_folder_for(str(tmp_path), "sub") == str(tmp_path / "sub")

    def test_existing_dir_without_subfolder(self, tmp_path):
        assert resolve_output_folder_for(str(tmp_path), "") == str(tmp_path)
