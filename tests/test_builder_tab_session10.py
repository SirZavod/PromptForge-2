"""Session 10 tests — Builder tab (part 1).

`list_outfit_options_for_character` (backend/file_manager.py) is pure
Python/filesystem, zero Qt — fully testable here, same pattern as
test_backend_smoke.py.

`ui/tabs/builder_tab.py` itself, `ui/dialogs/order_dialog.py`, and
`ui/dialogs/custom_template_editor.py` all import PyQt6, which is not
installed and not installable (no network) in this sandbox — same
limitation noted in every prior UI session's tests. Not exercised here;
see tests/_manual_check_session10.py for the on-screen checklist to run
manually once PyQt6 is available.

Run with: python -m pytest tests/test_builder_tab_session10.py -v
      or: python -m unittest tests.test_builder_tab_session10 -v
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.file_manager import list_outfit_options_for_character
from backend.prompt_builder import parse_custom_template, generate_custom_prompt


class TestListOutfitOptionsForCharacter(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp, "outfits"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _touch(self, name):
        open(os.path.join(self.tmp, "outfits", f"{name}.txt"), "w").close()

    def test_no_character_returns_just_none(self):
        self.assertEqual(list_outfit_options_for_character(self.tmp, ""), ["None"])
        self.assertEqual(list_outfit_options_for_character(self.tmp, "None"), ["None"])

    def test_canon_outfits_sorted_numerically_before_shared(self):
        self._touch("Alice_Canon_2")
        self._touch("Alice_Canon_10")
        self._touch("Alice_Canon_1")
        self._touch("Casual Outfit")
        self._touch("Bob_Canon_1")  # a different character's canon — must not leak in

        result = list_outfit_options_for_character(self.tmp, "Alice")
        self.assertEqual(result, ["None", "Canon 1", "Canon 2", "Canon 10", "Casual Outfit"])

    def test_character_with_no_canon_outfits_still_gets_shared(self):
        self._touch("Casual Outfit")
        result = list_outfit_options_for_character(self.tmp, "Nobody")
        self.assertEqual(result, ["None", "Casual Outfit"])


class TestCustomTemplateRoundTrip(unittest.TestCase):
    """Sanity check that the Builder tab's custom-template path still
    round-trips correctly through the Session 1 backend functions it
    calls — a light integration check that doesn't need Qt."""

    def test_parse_and_generate(self):
        text = "[Name 1] wears [Outfit 1]. Style: [Style]. Extra: [Tool]"
        parsed = parse_custom_template(text)
        self.assertEqual(parsed["name_idx"], {1})
        self.assertEqual(parsed["outfit_idx"], {1})
        self.assertTrue(parsed["use_style"])
        self.assertTrue(parsed["use_tool"])

        result = generate_custom_prompt(
            text,
            name_vals={1: "Alice"},
            desc_vals={1: ""},
            outfit_vals={1: "red dress"},
            style_val="anime style",
            scenario_val="",
            tool_val="@fixedanatomy")
        self.assertEqual(result, "Alice wears red dress. Style: anime style. Extra: @fixedanatomy")


if __name__ == "__main__":
    unittest.main()
