"""Session 12 — logic tests for `backend/guide_content.py` (data only,
zero Qt dependency, so unlike `ui/dialogs/guide_dialog.py` this actually
runs in this sandbox). These are the checks the GuideDialog's own
fallback logic (`GUIDE_CONTENT.get(lang, GUIDE_CONTENT["en"])` plus a
per-key `.get(...)`) relies on being true; if any of them ever went
false, the dialog would render an empty section instead of falling back
to English text, silently.
"""
import unittest

from backend.guide_content import (
    GUIDE_CONTENT,
    GUIDE_LANGUAGES,
    GUIDE_SECTION_ORDER,
)


class GuideContentTests(unittest.TestCase):
    def test_every_declared_language_has_an_entry(self):
        for code in GUIDE_LANGUAGES:
            self.assertIn(code, GUIDE_CONTENT, f"missing GUIDE_CONTENT entry for {code!r}")

    def test_every_language_has_every_section(self):
        for code, content in GUIDE_CONTENT.items():
            for key in GUIDE_SECTION_ORDER:
                self.assertIn(key, content, f"{code!r} is missing section {key!r}")

    def test_every_section_is_a_title_body_pair_of_nonempty_strings(self):
        for code, content in GUIDE_CONTENT.items():
            for key in GUIDE_SECTION_ORDER:
                title, body = content[key]
                self.assertIsInstance(title, str)
                self.assertIsInstance(body, str)
                self.assertTrue(title.strip(), f"{code!r}/{key!r} has an empty title")
                self.assertTrue(body.strip(), f"{code!r}/{key!r} has an empty body")

    def test_non_english_untranslated_sections_are_explicitly_marked_pending(self):
        # Every language other than "en" that GUIDE_CONTENT actually
        # defines was generated as an explicit "translation pending"
        # placeholder for languages not in the hand-written set (ru/zh/
        # ja have real translations in this build) — this just confirms
        # the marker text convention holds, not that every language is
        # translated.
        hand_translated = {"en", "ru", "zh", "ja"}
        for code, content in GUIDE_CONTENT.items():
            if code in hand_translated:
                continue
            for key in GUIDE_SECTION_ORDER:
                _title, body = content[key]
                self.assertTrue(
                    body.startswith("["),
                    f"{code!r}/{key!r} should open with an explicit pending-translation marker",
                )

    def test_section_order_has_no_duplicates_and_matches_english_keys(self):
        self.assertEqual(len(GUIDE_SECTION_ORDER), len(set(GUIDE_SECTION_ORDER)))
        self.assertEqual(set(GUIDE_SECTION_ORDER), set(GUIDE_CONTENT["en"].keys()))

    def test_display_name_lookup_round_trips(self):
        # GuideDialog builds `{v: k for k, v in GUIDE_LANGUAGES.items()}`
        # to resolve a combobox's display text back to the language code
        # GUIDE_CONTENT is keyed by — confirms that mapping is lossless
        # (no two codes sharing a display name).
        code_by_display = {v: k for k, v in GUIDE_LANGUAGES.items()}
        self.assertEqual(len(code_by_display), len(GUIDE_LANGUAGES))
        for code, display in GUIDE_LANGUAGES.items():
            self.assertEqual(code_by_display[display], code)


if __name__ == "__main__":
    unittest.main()
