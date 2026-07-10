"""Session 13 — data-compatibility regression guard.

Zero Qt dependency (runs in this sandbox). Confirms the on-disk file
naming this build's `backend/constants.py` uses still matches the
original monolith's exactly — this is the one thing the migration plan
calls out as never allowed to drift ("Never break data compatibility
... Users must be able to switch between old and new builds without
data migration"), so it gets an explicit pinned-value test rather than
relying on every session's author remembering not to touch it.
"""
import unittest

from backend.constants import (
    CUSTOM_TEMPLATES_FILE_NAME,
    DATA_DIR_NAME,
    HISTORY_FILE_NAME,
    LIBRARY_FOLDERS_FILE_NAME,
    SETTINGS_FILE_NAME,
    TEMPLATES_FILE_NAME,
)


class DataFileNamingTests(unittest.TestCase):
    def test_file_names_match_the_original_monolith(self):
        self.assertEqual(DATA_DIR_NAME, "prompt_forge_data")
        self.assertEqual(SETTINGS_FILE_NAME, "_settings.json")
        self.assertEqual(HISTORY_FILE_NAME, "_history.json")
        self.assertEqual(TEMPLATES_FILE_NAME, "_templates.json")
        self.assertEqual(CUSTOM_TEMPLATES_FILE_NAME, "_custom_templates.json")
        self.assertEqual(LIBRARY_FOLDERS_FILE_NAME, "_folders.json")


if __name__ == "__main__":
    unittest.main()
