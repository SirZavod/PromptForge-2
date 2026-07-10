"""Session 44: Library context menu ("New folder...", "Move to...")
was rendering with the bare Windows-native QMenu look instead of the
app's accent color -- QMenu doesn't inherit a parent's QSS the way
most other widgets do and needs its own explicit rule. This locks
down that `build_qss()` now emits a global `QMenu` block (covering
every QMenu in the app, present and future, not just the Library
one) whose `::item:selected` background is the theme's own accent
color -- not a hardcoded value -- so it stays correct across
Dark/Light/Custom.

Run with: python -m pytest tests/test_theme_qmenu_session44.py -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])

from backend.constants import THEMES  # noqa: E402
from ui.theme import build_qss  # noqa: E402


class TestQMenuAccentRule(unittest.TestCase):
    def test_qmenu_rule_present_for_every_builtin_theme(self):
        for name, c in THEMES.items():
            qss = build_qss(name)
            self.assertIn("QMenu {", qss, f"missing QMenu base rule for '{name}' theme")
            self.assertIn("QMenu::item:selected", qss,
                          f"missing QMenu::item:selected rule for '{name}' theme")

    def test_selected_item_uses_this_themes_own_accent_color(self):
        for name, c in THEMES.items():
            qss = build_qss(name)
            # Isolate the QMenu::item:selected block and confirm it
            # references *this* theme's accent tokens, not a value
            # copied from another theme or hardcoded.
            start = qss.index("QMenu::item:selected")
            block = qss[start:start + 200]
            self.assertIn(c["accent"], block)
            self.assertIn(c["accent_text"], block)

    def test_custom_derived_palette_dict_also_works(self):
        # Session 39's derived "Custom" palette is a plain colors dict,
        # not a THEMES key -- build_qss must accept that shape too.
        custom = dict(THEMES["dark"])
        custom["accent"] = "#ff6600"
        qss = build_qss(custom)
        start = qss.index("QMenu::item:selected")
        block = qss[start:start + 200]
        self.assertIn("#ff6600", block)

    def test_menu_separator_and_disabled_item_styled_too(self):
        qss = build_qss("dark")
        self.assertIn("QMenu::separator", qss)
        self.assertIn("QMenu::item:disabled", qss)


if __name__ == "__main__":
    unittest.main()
