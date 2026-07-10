"""Session 40 smoke tests: `backend/theme_background.py`'s file-copy /
replace / clear / missing-file-resolve logic, against a temp data dir.
No display needed — this is the same "drive the code paths headless"
verification every prior no-runtime session in additionalfeatures.md
used; live-click verification (resize, real image aspect ratios) still
needs a real display, per that file's own note.

Run with: python -m pytest tests/test_theme_background_session40.py -v
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import theme_background


def _make_image(path: str):
    # Not a real image — theme_background only cares about extension +
    # copying bytes; QPixmap-load correctness is exercised by
    # BackgroundSurface itself, which needs a real QApplication/display.
    with open(path, "wb") as f:
        f.write(b"not-a-real-image-but-thats-fine-here")


class TestThemeBackground(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.src_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.src_dir, ignore_errors=True)

    def test_set_background_image_copies_and_returns_path(self):
        src = os.path.join(self.src_dir, "wallpaper.png")
        _make_image(src)
        stored = theme_background.set_background_image(self.tmp, src)
        self.assertTrue(os.path.isfile(stored))
        self.assertNotEqual(stored, src)
        self.assertTrue(stored.endswith(".png"))

    def test_set_background_image_rejects_bad_extension(self):
        src = os.path.join(self.src_dir, "not_an_image.txt")
        _make_image(src)
        with self.assertRaises(ValueError):
            theme_background.set_background_image(self.tmp, src)

    def test_set_background_image_replaces_previous_one(self):
        src1 = os.path.join(self.src_dir, "one.png")
        src2 = os.path.join(self.src_dir, "two.jpg")
        _make_image(src1)
        _make_image(src2)
        first = theme_background.set_background_image(self.tmp, src1)
        second = theme_background.set_background_image(self.tmp, src2)
        self.assertFalse(os.path.isfile(first))
        self.assertTrue(os.path.isfile(second))
        # Only one background file should ever exist under theme/.
        remaining = os.listdir(theme_background.theme_assets_dir(self.tmp))
        self.assertEqual(len(remaining), 1)

    def test_clear_background_image_removes_file(self):
        src = os.path.join(self.src_dir, "wallpaper.webp")
        _make_image(src)
        stored = theme_background.set_background_image(self.tmp, src)
        theme_background.clear_background_image(self.tmp)
        self.assertFalse(os.path.isfile(stored))

    def test_resolve_background_path_missing_file_returns_none(self):
        self.assertIsNone(theme_background.resolve_background_path(
            os.path.join(self.tmp, "theme", "background.png")))

    def test_resolve_background_path_existing_file_returns_path(self):
        src = os.path.join(self.src_dir, "wallpaper.bmp")
        _make_image(src)
        stored = theme_background.set_background_image(self.tmp, src)
        self.assertEqual(theme_background.resolve_background_path(stored), stored)

    def test_resolve_background_path_none_input(self):
        self.assertIsNone(theme_background.resolve_background_path(None))


if __name__ == "__main__":
    unittest.main()
