"""Session 40.1 follow-up: `qcolor_from_token` -- the fix for the
"image preview placeholders render solid black" bug found from a real
screenshot. `QColor(str)` only understands hex/named colors; handing
it a CSS `rgba(r,g,b,a)` string (what `apply_surface_alpha` emits for
Card-opacity-affected tokens) silently produces an invalid color that
paints as solid black instead of raising -- these lock the fix down.

Run with: python -m pytest tests/test_color_utils_session40_1.py -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])

from ui.color_utils import qcolor_from_token  # noqa: E402


class TestQColorFromToken(unittest.TestCase):
    def test_plain_hex_behaves_like_qcolor_directly(self):
        c = qcolor_from_token("#2b2d37")
        self.assertTrue(c.isValid())
        self.assertEqual(c.getRgb(), (43, 45, 55, 255))

    def test_named_color_still_works(self):
        c = qcolor_from_token("red")
        self.assertTrue(c.isValid())
        self.assertEqual(c.getRgb(), (255, 0, 0, 255))

    def test_rgba_string_parses_correctly_not_black(self):
        c = qcolor_from_token("rgba(44,45,55,102)")
        self.assertTrue(c.isValid())
        self.assertEqual(c.getRgb(), (44, 45, 55, 102))
        # The historical bug: plain QColor("rgba(...)") silently becomes
        # solid black instead of this.
        self.assertNotEqual(c.getRgb(), (0, 0, 0, 255))

    def test_rgba_zero_alpha(self):
        c = qcolor_from_token("rgba(0,0,0,0)")
        self.assertTrue(c.isValid())
        self.assertEqual(c.getRgb(), (0, 0, 0, 0))

    def test_matches_apply_surface_alpha_output_end_to_end(self):
        from backend.theme_derive import apply_surface_alpha
        colors = {"bg_card": "#2c2e38"}
        transformed = apply_surface_alpha(colors, 40)
        c = qcolor_from_token(transformed["bg_card"])
        self.assertTrue(c.isValid())
        self.assertEqual(c.getRgb(), (44, 46, 56, 102))


if __name__ == "__main__":
    unittest.main()
