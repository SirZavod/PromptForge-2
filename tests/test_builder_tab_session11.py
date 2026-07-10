"""Session 11 tests — LoRA autofill backend functions.

`collect_active_library_loras` / `compute_lora_autofill`
(`backend/prompt_builder.py`) are pure Python — no Qt — but had no
test coverage yet (added in Session 1, first actually *called* from
`BuilderTab._lora_autofill_from_library` in this session). Covered
here.

Session 30.2: `collect_active_library_loras` now returns
(lora_name, strength) tuples instead of bare names, and
`compute_lora_autofill` seeds each auto slot with that stored strength
instead of a hardcoded 1.0 — the Library-side strength control added in
Session 30 was otherwise dead weight, never actually reaching Builder's
LoRA autofill. Updated here accordingly.

`ui/tabs/builder_tab.py`'s ComfyUI panel/LoRA-manager widgets/queue
themselves need PyQt6, not available in this sandbox — same
limitation as every prior UI session; see
tests/_manual_check_session11.py for the on-screen checklist.

Run with: python -m pytest tests/test_builder_tab_session11.py -v
      or: python -m unittest tests.test_builder_tab_session11 -v
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.prompt_builder import collect_active_library_loras, compute_lora_autofill


class TestCollectActiveLibraryLoras(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        for cat in ("styles", "characters", "outfits", "scenarios", "tools"):
            os.makedirs(os.path.join(self.tmp, cat))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_meta(self, category, name, lora, lora_strength=1.0):
        path = os.path.join(self.tmp, category, f"{name}.meta.json")
        with open(path, "w") as f:
            json.dump({"lora": lora, "lora_strength": lora_strength}, f)

    def test_dedup_preserves_first_mention_order(self):
        self._write_meta("styles", "Anime", "animeLora.safetensors")
        self._write_meta("characters", "Alice", "aliceLora.safetensors")
        self._write_meta("characters", "Bob", "animeLora.safetensors")  # duplicate of style's

        entries = [("styles", "Anime"), ("characters", "Alice"), ("characters", "Bob")]
        result = collect_active_library_loras(self.tmp, entries)
        self.assertEqual(result, [("animeLora.safetensors", 1.0), ("aliceLora.safetensors", 1.0)])

    def test_entries_with_no_bound_lora_are_skipped(self):
        # No meta.json at all for "Casual" — load_library_meta should
        # default to {} and .get("lora") to None, not raise.
        entries = [("outfits", "Casual")]
        result = collect_active_library_loras(self.tmp, entries)
        self.assertEqual(result, [])

    def test_carries_stored_strength(self):
        self._write_meta("characters", "Akane", "akaneLora.safetensors", lora_strength=2.0)
        entries = [("characters", "Akane")]
        result = collect_active_library_loras(self.tmp, entries)
        self.assertEqual(result, [("akaneLora.safetensors", 2.0)])


class TestComputeLoraAutofill(unittest.TestCase):
    def test_empty_everything_falls_back_to_one_none_slot(self):
        result = compute_lora_autofill([], [], "None")
        self.assertEqual(result, [{"name": "None", "strength": 1.0, "auto": False}])

    def test_manual_slots_preserved_verbatim(self):
        current = [{"name": "manualLora.safetensors", "strength": 0.7, "auto": False}]
        result = compute_lora_autofill(current, [], "None")
        self.assertEqual(result, current)

    def test_auto_slots_rebuilt_from_scratch_each_time(self):
        current = [{"name": "oldAuto.safetensors", "strength": 1.0, "auto": True}]
        result = compute_lora_autofill(current, [("newAuto.safetensors", 1.0)], "None")
        self.assertEqual(result, [{"name": "newAuto.safetensors", "strength": 1.0, "auto": True}])

    def test_auto_slots_seeded_with_stored_strength(self):
        # Session 30.2: the Library's own lora_strength, not a
        # hardcoded 1.0, is what a freshly-created auto slot starts at.
        current = []
        result = compute_lora_autofill(current, [("newAuto.safetensors", 2.0)], "None")
        self.assertEqual(result, [{"name": "newAuto.safetensors", "strength": 2.0, "auto": True}])

    def test_manual_slot_wins_over_same_name_autofill(self):
        current = [{"name": "shared.safetensors", "strength": 0.5, "auto": False}]
        result = compute_lora_autofill(current, [("shared.safetensors", 1.0)], "None")
        # The manual entry must survive unchanged, and no duplicate
        # auto entry for the same name should be added alongside it.
        self.assertEqual(result, [{"name": "shared.safetensors", "strength": 0.5, "auto": False}])

    def test_manual_and_auto_slots_coexist(self):
        current = [
            {"name": "manual.safetensors", "strength": 0.8, "auto": False},
            {"name": "staleAuto.safetensors", "strength": 1.0, "auto": True},
        ]
        result = compute_lora_autofill(current, [("freshAuto.safetensors", 1.5)], "None")
        names = {(e["name"], e["auto"], e["strength"]) for e in result}
        self.assertEqual(names, {("manual.safetensors", False, 0.8), ("freshAuto.safetensors", True, 1.5)})


if __name__ == "__main__":
    unittest.main()
