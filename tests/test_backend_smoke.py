"""Session 1 smoke tests: backend modules import cleanly with zero
Tkinter dependency, and the two trickiest pieces of pure logic
(parse_custom_template's regex-driven variable detection, and
find_lora_candidates' three-way exact/collision/no-match branching)
behave correctly.

Run with: python -m pytest tests/test_backend_smoke.py -v
      or: python -m unittest tests.test_backend_smoke -v
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import backend


class TestImports(unittest.TestCase):
    def test_backend_package_imports(self):
        """The backend package (and therefore every submodule it
        re-exports from) imports without error."""
        self.assertTrue(hasattr(backend, "CATEGORIES"))
        # Session 46.2c: "image_actions"/"video_actions" added as their
        # own purpose-built categories alongside the original five, and
        # a follow-up added "edit_tools"/"video_tools" as their OWN
        # per-mode Tools categories, distinct from the Actions ones.
        self.assertEqual(backend.CATEGORIES, ["styles", "characters", "outfits", "scenarios", "tools",
                                               "image_actions", "video_actions",
                                               "edit_tools", "video_tools"])

    def test_zero_tkinter_dependency(self):
        """No backend module imports tkinter, directly or transitively.
        (sys.modules check — if any backend module had `import tkinter`
        at module scope, it would already be loaded by the time we get
        here, since backend.__init__ imports every submodule.)"""
        self.assertNotIn("tkinter", sys.modules)

    def test_all_submodules_importable_standalone(self):
        import backend.constants
        import backend.comfy_client
        import backend.file_manager
        import backend.prompt_builder
        import backend.lora_deps
        import backend.guide_content


class TestLoadSaveJsonRoundTrip(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_round_trip(self):
        path = os.path.join(self.tmp, "data.json")
        payload = {"theme": "dark", "lora_slots": [{"name": "x.safetensors", "strength": 1.2}]}
        backend.save_json(path, payload)
        loaded = backend.load_json(path, default={})
        self.assertEqual(loaded, payload)

    def test_missing_file_returns_default(self):
        loaded = backend.load_json(os.path.join(self.tmp, "nope.json"), default={"theme": "light"})
        self.assertEqual(loaded, {"theme": "light"})

    def test_corrupt_file_returns_default(self):
        path = os.path.join(self.tmp, "corrupt.json")
        with open(path, "w") as f:
            f.write("{not valid json")
        loaded = backend.load_json(path, default=[])
        self.assertEqual(loaded, [])


class TestParseCustomTemplate(unittest.TestCase):
    def test_name_description_outfit_indices(self):
        text = "[Name 1] ([Description 1]) wearing [Outfit 1], with [Name 2] nearby."
        parsed = backend.parse_custom_template(text)
        self.assertEqual(parsed["name_idx"], {1, 2})
        self.assertEqual(parsed["desc_idx"], {1})
        self.assertEqual(parsed["outfit_idx"], {1})
        self.assertFalse(parsed["use_style"])
        self.assertFalse(parsed["use_scenario"])
        self.assertFalse(parsed["use_tool"])

    def test_style_and_scenario_flags(self):
        parsed = backend.parse_custom_template("Style: [Style]. Scenario: [Scenario].")
        self.assertTrue(parsed["use_style"])
        self.assertTrue(parsed["use_scenario"])
        self.assertFalse(parsed["use_tool"])

    def test_tool_variable_case(self):
        """[Tool] is the new variable added alongside [Style]/[Scenario]
        for the Tools feature — must be detected just like the others."""
        parsed = backend.parse_custom_template("[Name 1] uses [Tool] while wearing [Outfit 1].")
        self.assertTrue(parsed["use_tool"])
        self.assertEqual(parsed["name_idx"], {1})
        self.assertEqual(parsed["outfit_idx"], {1})

    def test_empty_text(self):
        parsed = backend.parse_custom_template("")
        self.assertEqual(parsed["name_idx"], set())
        self.assertFalse(parsed["use_style"])
        self.assertFalse(parsed["use_tool"])

    def test_none_text(self):
        """Original guarded with `text or ""` — must not raise on None."""
        parsed = backend.parse_custom_template(None)
        self.assertEqual(parsed["name_idx"], set())


class TestGenerateCustomPrompt(unittest.TestCase):
    def test_substitution_and_cleanup(self):
        text = "[Name 1] ([Description 1]) wearing [Outfit 1].\n\nStyle: [Style]. Tool: [Tool]"
        result = backend.generate_custom_prompt(
            text,
            name_vals={1: "Megumin"}, desc_vals={1: "red eyes"}, outfit_vals={1: "casual wear"},
            style_val="anime style", scenario_val="", tool_val="@fixedanatomy")
        self.assertIn("Megumin (red eyes) wearing casual wear.", result)
        self.assertIn("Style: anime style. Tool: @fixedanatomy", result)

    def test_collapses_triple_blank_lines(self):
        text = "[Name 1]\n\n\n\n[Style]"
        result = backend.generate_custom_prompt(
            text, name_vals={1: "X"}, desc_vals={}, outfit_vals={},
            style_val="", scenario_val="", tool_val="")
        self.assertNotIn("\n\n\n", result)


class TestFindLoraCandidates(unittest.TestCase):
    """Exercises all three branches of find_lora_candidates: exact
    single match, name collision (2+ matches), and no match at all."""

    def setUp(self):
        self.available = [
            "Anima/Characters/megumin_v2.safetensors",   # different folder, same basename as below
            "Other/megumin.safetensors",                  # exact basename match candidate
            "Yet/Another/megumin.safetensors",             # second candidate -> collision case
            "Anima/Characters/akane.safetensors",
        ]

    def test_single_candidate_match(self):
        missing = ["Old/Path/akane.safetensors"]
        results = backend.find_lora_candidates(self.available, missing)
        self.assertEqual(results["Old/Path/akane.safetensors"], "Anima/Characters/akane.safetensors")

    def test_collision_returns_list_of_all_candidates(self):
        missing = ["Stale/Path/megumin.safetensors"]
        results = backend.find_lora_candidates(self.available, missing)
        result = results["Stale/Path/megumin.safetensors"]
        self.assertIsInstance(result, list)
        self.assertEqual(set(result), {"Other/megumin.safetensors", "Yet/Another/megumin.safetensors"})

    def test_no_match_returns_none(self):
        missing = ["Nowhere/nonexistent.safetensors"]
        results = backend.find_lora_candidates(self.available, missing)
        self.assertIsNone(results["Nowhere/nonexistent.safetensors"])

    def test_does_not_suggest_itself_as_a_candidate(self):
        """A missing path that happens to already be present verbatim
        in `available` must not be offered as its own candidate."""
        available = ["Anima/Characters/akane.safetensors"]
        missing = ["Anima/Characters/akane.safetensors"]
        results = backend.find_lora_candidates(available, missing)
        self.assertIsNone(results["Anima/Characters/akane.safetensors"])

    def test_windows_and_unix_separators_both_handled(self):
        """LoRA paths are always Windows-style backslash-separated in
        practice, but the basename extraction must not depend on the
        host OS's own path separator."""
        available = ["SomeFolder/akane.safetensors"]
        missing = ["PromptForgeLoras\\Anima\\Characters\\akane.safetensors"]
        results = backend.find_lora_candidates(available, missing)
        self.assertEqual(results[missing[0]], "SomeFolder/akane.safetensors")


class TestLibraryFoldersLogic(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.folders_file = os.path.join(self.tmp, "_folders.json")
        self.folder_maps = {cat: {} for cat in backend.CATEGORIES}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_canonical_outfits_is_protected(self):
        self.assertTrue(backend.is_protected_folder("outfits", "Canonical Outfits"))
        self.assertTrue(backend.is_protected_folder("outfits", "Canonical Outfits/Nested"))
        self.assertFalse(backend.is_protected_folder("outfits", "Casual"))
        self.assertFalse(backend.is_protected_folder("characters", "Canonical Outfits"))

    def test_move_entries_skips_canon_and_protected_target(self):
        moved = backend.move_entries_to_folder(
            self.folder_maps, self.folders_file, "outfits",
            ["Casual", "Megumin_Canon_1"], "Canonical Outfits")
        self.assertEqual(moved, 0)

    def test_move_entries_normal_case(self):
        moved = backend.move_entries_to_folder(
            self.folder_maps, self.folders_file, "outfits", ["Casual"], "Weekday Wear")
        self.assertEqual(moved, 1)
        self.assertEqual(self.folder_maps["outfits"]["Casual"], "Weekday Wear")
        # persisted to disk too
        on_disk = backend.load_json(self.folders_file, {})
        self.assertEqual(on_disk["outfits"]["Casual"], "Weekday Wear")

    def test_list_all_folders_includes_ancestors_and_empty_folders(self):
        backend.set_entry_folder(self.folder_maps, self.folders_file, "outfits", "X", "A/B/C")
        empty_folders = {cat: set() for cat in backend.CATEGORIES}
        backend.create_new_folder(empty_folders, "outfits", "", "EmptyOne")
        all_folders = backend.list_all_folders(self.folder_maps, empty_folders, "outfits")
        self.assertIn("A", all_folders)
        self.assertIn("A/B", all_folders)
        self.assertIn("A/B/C", all_folders)
        self.assertIn("EmptyOne", all_folders)

    def test_rename_folder_repoints_descendants(self):
        backend.set_entry_folder(self.folder_maps, self.folders_file, "outfits", "X", "A")
        backend.set_entry_folder(self.folder_maps, self.folders_file, "outfits", "Y", "A/B")
        empty_folders = {cat: set() for cat in backend.CATEGORIES}
        expanded = {cat: set() for cat in backend.CATEGORIES}
        new_path = backend.rename_folder(
            self.folder_maps, empty_folders, expanded, self.folders_file, "outfits", "A", "Renamed")
        self.assertEqual(new_path, "Renamed")
        self.assertEqual(self.folder_maps["outfits"]["X"], "Renamed")
        self.assertEqual(self.folder_maps["outfits"]["Y"], "Renamed/B")
        on_disk = backend.load_json(self.folders_file, {})
        self.assertEqual(on_disk["outfits"]["X"], "Renamed")

    def test_rename_folder_rejects_slash(self):
        empty_folders = {cat: set() for cat in backend.CATEGORIES}
        expanded = {cat: set() for cat in backend.CATEGORIES}
        result = backend.rename_folder(
            self.folder_maps, empty_folders, expanded, self.folders_file, "outfits", "A", "Has/Slash")
        self.assertIsNone(result)

    def test_delete_folder_moves_contents_to_root(self):
        backend.set_entry_folder(self.folder_maps, self.folders_file, "outfits", "X", "A")
        backend.set_entry_folder(self.folder_maps, self.folders_file, "outfits", "Y", "A/B")
        backend.set_entry_folder(self.folder_maps, self.folders_file, "outfits", "Z", "Other")
        empty_folders = {cat: set() for cat in backend.CATEGORIES}
        expanded = {"outfits": {"A"}}
        backend.delete_folder(self.folder_maps, empty_folders, expanded, self.folders_file, "outfits", "A")
        self.assertNotIn("X", self.folder_maps["outfits"])
        self.assertNotIn("Y", self.folder_maps["outfits"])
        self.assertEqual(self.folder_maps["outfits"]["Z"], "Other")
        self.assertNotIn("A", expanded["outfits"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
