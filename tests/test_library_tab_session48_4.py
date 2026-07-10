"""Session 48.4 tests: real video attachment for Library entries —
detection on drop, per-entry video storage alongside a generated
poster JPG, LibraryTab's image zone showing video-or-image, and every
other read/write call site (delete, rename, duplicate, import) staying
correct about "or it's a video".

Run headless with:
    QT_QPA_PLATFORM=offscreen python -m pytest tests/test_library_tab_session48_4.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile

import pytest
from PyQt6.QtWidgets import QApplication, QMessageBox

from backend.constants import CATEGORIES, THEMES
from backend.file_manager import (
    ImageProcessingError,
    delete_library_video,
    find_library_video,
    init_folders,
    library_video_path,
    load_library_meta,
    process_and_store_video,
    rename_library_video,
    save_library_meta,
)
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


def _fake_video(tmp_data_dir, name="clip.mp4"):
    path = os.path.join(tmp_data_dir, name)
    with open(path, "wb") as f:
        f.write(b"not a real mp4, just bytes for a copy test")
    return path


def _write_entry(data_dir, cat, name, content="some tags"):
    with open(os.path.join(data_dir, cat, f"{name}.txt"), "w", encoding="utf-8") as f:
        f.write(content)


# ------------------------------------------------------------------
# Pure backend functions
# ------------------------------------------------------------------
def test_process_and_store_video_copies_and_returns_ext(tmp_data_dir):
    src = _fake_video(tmp_data_dir)
    dest, ext = process_and_store_video(tmp_data_dir, src, "styles", "MyClip")
    assert ext == ".mp4"
    assert dest == library_video_path(tmp_data_dir, "styles", "MyClip", ".mp4")
    assert os.path.exists(dest)
    with open(dest, "rb") as f:
        assert f.read() == b"not a real mp4, just bytes for a copy test"


def test_process_and_store_video_rejects_non_video_extension(tmp_data_dir):
    src = os.path.join(tmp_data_dir, "not_a_video.txt")
    with open(src, "w") as f:
        f.write("hi")
    with pytest.raises(ImageProcessingError):
        process_and_store_video(tmp_data_dir, src, "styles", "Bad")


def test_process_and_store_video_requires_name(tmp_data_dir):
    src = _fake_video(tmp_data_dir)
    with pytest.raises(ImageProcessingError):
        process_and_store_video(tmp_data_dir, src, "styles", "")


def test_process_and_store_video_replaces_previous_extension(tmp_data_dir):
    src_mp4 = _fake_video(tmp_data_dir, "a.mp4")
    process_and_store_video(tmp_data_dir, src_mp4, "styles", "Swap")
    save_library_meta(tmp_data_dir, "styles", "Swap", video_ext=".mp4")
    old_path = library_video_path(tmp_data_dir, "styles", "Swap", ".mp4")
    assert os.path.exists(old_path)

    src_webm = _fake_video(tmp_data_dir, "b.webm")
    dest, ext = process_and_store_video(tmp_data_dir, src_webm, "styles", "Swap")
    assert ext == ".webm"
    assert not os.path.exists(old_path)
    assert os.path.exists(dest)


def test_find_library_video_uses_meta_not_directory_scan(tmp_data_dir):
    src = _fake_video(tmp_data_dir)
    process_and_store_video(tmp_data_dir, src, "styles", "Linked")
    # No meta written yet -> not "found" even though the file is there,
    # since video_ext is the single source of truth (see file_manager.py).
    assert find_library_video(tmp_data_dir, "styles", "Linked") is None
    save_library_meta(tmp_data_dir, "styles", "Linked", video_ext=".mp4")
    found = find_library_video(tmp_data_dir, "styles", "Linked")
    assert found == library_video_path(tmp_data_dir, "styles", "Linked", ".mp4")


def test_delete_library_video_removes_file(tmp_data_dir):
    src = _fake_video(tmp_data_dir)
    process_and_store_video(tmp_data_dir, src, "styles", "Del")
    save_library_meta(tmp_data_dir, "styles", "Del", video_ext=".mp4")
    path = find_library_video(tmp_data_dir, "styles", "Del")
    assert os.path.exists(path)
    delete_library_video(tmp_data_dir, "styles", "Del")
    assert not os.path.exists(path)


def test_rename_library_video_moves_file_using_old_meta(tmp_data_dir):
    src = _fake_video(tmp_data_dir)
    process_and_store_video(tmp_data_dir, src, "styles", "Old")
    save_library_meta(tmp_data_dir, "styles", "Old", video_ext=".mp4")
    rename_library_video(tmp_data_dir, "styles", "Old", "New")
    assert not os.path.exists(library_video_path(tmp_data_dir, "styles", "Old", ".mp4"))
    assert os.path.exists(library_video_path(tmp_data_dir, "styles", "New", ".mp4"))


def test_meta_video_ext_round_trips(tmp_data_dir):
    save_library_meta(tmp_data_dir, "styles", "M", source_url="http://x", video_ext=".mov")
    meta = load_library_meta(tmp_data_dir, "styles", "M")
    assert meta["video_ext"] == ".mov"
    assert meta["source_url"] == "http://x"


def test_meta_ignores_unrecognized_video_ext(tmp_data_dir):
    # Simulates a hand-edited or future-format sidecar.
    import json
    path = os.path.join(tmp_data_dir, "styles", "Weird.meta.json")
    with open(path, "w") as f:
        json.dump({"video_ext": ".exe"}, f)
    meta = load_library_meta(tmp_data_dir, "styles", "Weird")
    assert meta["video_ext"] is None


# ------------------------------------------------------------------
# LibraryTab integration
# ------------------------------------------------------------------
def test_handle_image_drop_routes_video_to_video_storage(tab, tmp_data_dir):
    tab.switch_library_category("styles")
    tab.start_new_library_entry()
    tab.ent_lib_name.setText("VidEntry")
    src = _fake_video(tmp_data_dir)

    tab.handle_image_drop(src)

    assert find_library_video(tmp_data_dir, "styles", "VidEntry") is not None
    meta = load_library_meta(tmp_data_dir, "styles", "VidEntry")
    assert meta["video_ext"] == ".mp4"


def test_handle_image_drop_still_handles_plain_images(tab, tmp_data_dir):
    tab.switch_library_category("styles")
    tab.start_new_library_entry()
    tab.ent_lib_name.setText("ImgEntry")
    src = os.path.join(tmp_data_dir, "pic.png")
    from PIL import Image
    Image.new("RGB", (8, 8), "red").save(src)

    tab.handle_image_drop(src)

    meta = load_library_meta(tmp_data_dir, "styles", "ImgEntry")
    assert meta["video_ext"] is None
    from backend.file_manager import find_library_image
    assert find_library_image(tmp_data_dir, "styles", "ImgEntry") is not None


def test_video_attach_shows_embedded_player_not_static_pixmap(tab, tmp_data_dir):
    tab.switch_library_category("styles")
    tab.start_new_library_entry()
    tab.ent_lib_name.setText("PlayerEntry")
    src = _fake_video(tmp_data_dir)

    tab.handle_image_drop(src)

    # show_video_path is what actually sets _video_filename (video
    # state), distinct from _has_image/_pixmap (see image_zone.py).
    assert tab.image_drop_zone._video_filename is not None
    assert tab.image_drop_zone._has_image is False


def test_delete_library_entry_also_removes_its_video(tab, tmp_data_dir):
    tab.switch_library_category("styles")
    tab.start_new_library_entry()
    tab.ent_lib_name.setText("ToDelete")
    tab.txt_lib_tags.setPlainText("tags")
    src = _fake_video(tmp_data_dir)
    tab.handle_image_drop(src)
    tab.save_to_library()
    video_path = find_library_video(tmp_data_dir, "styles", "ToDelete")
    assert video_path and os.path.exists(video_path)

    tab.selected_file = "ToDelete"
    tab.delete_library_entry()

    assert not os.path.exists(video_path)


def test_duplicate_library_entry_carries_video_over(tab, tmp_data_dir):
    tab.switch_library_category("styles")
    tab.start_new_library_entry()
    tab.ent_lib_name.setText("DupSrc")
    tab.txt_lib_tags.setPlainText("tags")
    src = _fake_video(tmp_data_dir)
    tab.handle_image_drop(src)
    tab.save_to_library()

    tab.selected_file = "DupSrc"
    tab.duplicate_library_entry()

    assert find_library_video(tmp_data_dir, "styles", "DupSrc_copy") is not None


def test_on_library_select_prefers_video_over_image(tab, tmp_data_dir):
    _write_entry(tmp_data_dir, "styles", "Both")
    src = _fake_video(tmp_data_dir)
    process_and_store_video(tmp_data_dir, src, "styles", "Both")
    save_library_meta(tmp_data_dir, "styles", "Both", video_ext=".mp4")
    from backend.file_manager import library_image_path
    with open(library_image_path(tmp_data_dir, "styles", "Both"), "wb") as f:
        f.write(b"fake jpg bytes")

    tab.switch_library_category("styles")
    tab.on_library_select("Both")

    assert tab.image_drop_zone._video_filename is not None
