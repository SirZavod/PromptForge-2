"""Session 2 tests: ui/theme.py's QSS generator, and the commit-rule /
geometry logic of the four widgets that has nothing to do with actually
being on screen (the on-screen part is what
tests/_manual_check_session2.py is for).

Requires a QApplication instance to exist before any QWidget is
constructed — `qapp` fixture below handles that once for the whole
module. Run headless with:
    QT_QPA_PLATFORM=offscreen python -m pytest tests/test_ui_widgets_session2.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication

import backend
from ui.theme import build_qss, apply_theme
from ui.widgets.image_zone import ImageDropZone, ResultImageViewer
from ui.widgets.autocomplete import AutocompleteCombobox
from ui.widgets.collapsible_section import CollapsibleSection


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


class TestBuildQss:
    def test_builds_for_every_theme_in_backend(self):
        for name in backend.THEMES:
            qss = build_qss(name)
            assert isinstance(qss, str)
            assert len(qss) > 500
            assert "QPushButton" in qss
            assert "QToolButton#CollapsibleHeader" in qss

    def test_unknown_theme_raises_keyerror(self):
        with pytest.raises(KeyError):
            build_qss("does-not-exist")

    def test_apply_theme_sets_app_stylesheet(self, qapp):
        apply_theme(qapp, "dark")
        assert "QMainWindow" in qapp.styleSheet()
        apply_theme(qapp, "light")
        assert qapp.styleSheet() == build_qss("light")


class TestImageZonePanelHeight:
    def test_apply_panel_height_clamps_to_min_px(self, qapp):
        zone = ImageDropZone(backend.THEMES["dark"])
        zone.apply_panel_height(50)  # smaller than MIN_PX=130, also smaller budget
        # ceiling = min(MAX_PX, max(50,1)) = 50; target = max(min(130,50), min(target,50)) = 50
        assert zone.height() == 50

    def test_apply_panel_height_normal_case(self, qapp):
        zone = ImageDropZone(backend.THEMES["dark"])
        zone.apply_panel_height(1000)
        # DEFAULT_PERCENT interpolates between MIN_PX (at MIN_PERCENT) and
        # the full 1000px budget (at MAX_PERCENT) — not a flat fraction of
        # the budget, so that MAX_PERCENT actually means "fill the budget".
        span = zone.MAX_PERCENT - zone.MIN_PERCENT
        frac = (zone.DEFAULT_PERCENT - zone.MIN_PERCENT) / span
        expected = int(zone.MIN_PX + frac * (1000 - zone.MIN_PX))
        assert zone.height() == expected

    def test_apply_panel_height_max_percent_fills_budget(self, qapp):
        zone = ImageDropZone(backend.THEMES["dark"])
        zone.set_percent(zone.MAX_PERCENT)
        zone.apply_panel_height(1000)
        assert zone.height() == 1000

    def test_apply_panel_height_never_exceeds_max_px(self, qapp):
        zone = ImageDropZone(backend.THEMES["dark"])
        zone.set_percent(65)  # ImageDropZone's own MAX_PERCENT
        zone.apply_panel_height(100000)
        assert zone.height() == zone.MAX_PX

    def test_set_percent_clamps_to_widget_range(self, qapp):
        zone = ImageDropZone(backend.THEMES["dark"])
        zone.set_percent(999)
        assert zone.percent == zone.MAX_PERCENT
        zone.set_percent(-5)
        assert zone.percent == zone.MIN_PERCENT

    def test_result_viewer_has_its_own_wider_range(self, qapp):
        viewer = ResultImageViewer(backend.THEMES["dark"])
        assert viewer.MIN_PERCENT == 15
        assert viewer.MAX_PERCENT == 68
        assert viewer.DEFAULT_PERCENT == 45

    def test_show_image_bytes_with_garbage_does_not_crash_or_clear(self, qapp):
        zone = ImageDropZone(backend.THEMES["dark"])
        zone.show_image_bytes(b"not a real image")
        # deliberately does NOT fall back to placeholder on bad bytes
        assert zone._has_image is False

    def test_show_placeholder_resets_state(self, qapp):
        zone = ImageDropZone(backend.THEMES["dark"])
        zone._has_image = True
        zone.show_placeholder()
        assert zone._has_image is False
        assert zone._pixmap is None

    def test_show_video_placeholder_sets_state_and_clears_image(self, qapp):
        """Session 46.3/46.4: a video result has no pixmap at all --
        it's a distinct third state, not just 'show_image_path with a
        file QPixmap can't decode' (which would just fall back to the
        plain empty placeholder, losing the filename)."""
        viewer = ResultImageViewer(backend.THEMES["dark"])
        viewer._has_image = True
        viewer._pixmap = object()  # sentinel, must get cleared
        viewer.show_video_placeholder("clip_00001.mp4")
        assert viewer._has_image is False
        assert viewer._pixmap is None
        assert viewer._video_filename == "clip_00001.mp4"

    def test_show_placeholder_also_clears_video_state(self, qapp):
        viewer = ResultImageViewer(backend.THEMES["dark"])
        viewer.show_video_placeholder("clip.mp4")
        assert viewer._video_filename == "clip.mp4"
        viewer.show_placeholder()
        assert viewer._video_filename is None

    def test_show_image_path_clears_stale_video_state(self, qapp, tmp_path):
        """A fresh image result after a previous video one (e.g. i2v
        run followed by a t2i run in the same session) must not leave
        the old video's filename lingering and drawn over the image."""
        from PIL import Image
        img_path = tmp_path / "fresh.png"
        Image.new("RGB", (4, 4), "red").save(img_path)

        viewer = ResultImageViewer(backend.THEMES["dark"])
        viewer.show_video_placeholder("old_clip.mp4")
        viewer.show_image_path(str(img_path))
        assert viewer._video_filename is None
        assert viewer._has_image is True


class TestAutocompleteCombobox:
    def test_set_items_populates_all_values(self, qapp):
        combo = AutocompleteCombobox()
        combo.set_items(["Alpha", "Beta", "Gamma"])
        assert combo._all_values == ["Alpha", "Beta", "Gamma"]
        assert combo.count() == 3

    def test_pick_commits_value_and_emits_signal(self, qapp):
        combo = AutocompleteCombobox()
        combo.set_items(["Megumin", "Akane"])
        picked = []
        combo.item_selected.connect(picked.append)
        combo._pick("Akane")
        assert combo.current_value() == "Akane"
        assert picked == ["Akane"]

    def test_finalize_normalizes_case_on_exact_match(self, qapp):
        combo = AutocompleteCombobox()
        combo.set_items(["Megumin", "Akane"])
        combo.lineEdit().setText("megumin")
        combo._finalize()
        assert combo.current_value() == "Megumin"

    def test_finalize_empty_resolves_to_none_literal(self, qapp):
        combo = AutocompleteCombobox()
        combo.set_items(["Megumin"])
        combo.lineEdit().setText("")
        combo._finalize()
        assert combo.current_value() == "None"

    def test_finalize_unrecognized_text_falls_back_to_last_committed(self, qapp):
        combo = AutocompleteCombobox()
        combo.set_items(["Megumin", "Akane"])
        combo.lineEdit().setText("Megumin")
        combo._finalize()
        combo.lineEdit().setText("TotallyUnknown")
        combo._finalize()
        assert combo.current_value() == "Megumin"

    def test_open_popup_filters_by_substring_case_insensitive(self, qapp):
        combo = AutocompleteCombobox()
        combo.set_items(["Megumin", "Akane", "Aqua", "Kazuma", "Darkness", "Wiz", "Yunyun"])
        combo._on_text_edited("A")
        assert combo._popup_values == ["Akane", "Aqua", "Kazuma", "Darkness"]
        combo._close_popup()

    def test_arrow_navigation_wraps_around(self, qapp):
        combo = AutocompleteCombobox()
        combo.set_items(["A", "B", "C"])
        combo._open_popup(["A", "B", "C"])
        combo._listbox.setCurrentRow(0)
        from PyQt6.QtCore import Qt
        combo._on_arrow(Qt.Key.Key_Up)  # wraps from 0 to last
        assert combo._listbox.currentRow() == 2
        combo._close_popup()


class TestCollapsibleSection:
    def test_default_expanded_state(self, qapp):
        section = CollapsibleSection("Title", "key1", default_expanded=True)
        assert section.is_expanded() is True
        assert section.body.isHidden() is False

    def test_default_collapsed_state(self, qapp):
        section = CollapsibleSection("Title", "key2", default_expanded=False)
        assert section.is_expanded() is False
        assert section.body.isHidden() is True

    def test_toggle_emits_signal_with_new_state(self, qapp):
        section = CollapsibleSection("Title", "key3", default_expanded=True)
        seen = []
        section.toggled.connect(seen.append)
        section.header.setChecked(False)
        assert seen == [False]
        assert section.body.isHidden() is True

    def test_set_expanded_does_not_reemit_toggled(self, qapp):
        section = CollapsibleSection("Title", "key4", default_expanded=True)
        seen = []
        section.toggled.connect(seen.append)
        section.set_expanded(False)
        assert seen == []  # programmatic restore must not re-trigger persistence
        assert section.body.isHidden() is True

    def test_settings_key_is_exposed_for_owner_to_persist(self, qapp):
        section = CollapsibleSection("Title", "my_settings_key")
        assert section.settings_key == "my_settings_key"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
