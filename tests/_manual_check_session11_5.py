"""Session 11.5.1 + 11.5.2 manual on-screen check — throwaway, per the
migration plan's verification rule. Folded into one file since both
bugfix sessions are small and independent.

Run: python -m tests._manual_check_session11_5
"""
import sys

CHECKLIST = """
Session 11.5.1 — AutocompleteCombobox popup interaction
=========================================================
1. Click-to-open, TEXT area (not the border): on the Builder tab, click
   directly on the text inside the Style combo (e.g. on the "None"
   value) — the suggestion popup opens immediately. No text cursor /
   text-selection caret should appear instead.
2. Click-to-open, BORDER/arrow area: same combo, click the little
   dropdown-arrow edge — popup still opens the same way (no regression).
3. Type-to-filter still works once the popup is open from either click.
4. Esc closes the popup without committing a half-typed value (field
   reverts to the last committed value on next focus-out).
5. Click outside the popup, elsewhere in the app (e.g. click an empty
   area of the Builder tab) — popup closes.
6. Open a combo's popup, then switch to the Library tab via the tab
   bar — popup closes (does not float over the Library tab).
7. Open a combo's popup, then Alt+Tab to another application and back
   — popup closed while the other app was focused (check immediately
   on switching back — it should already be gone, not still open).
8. Regression pass across at least two different combos on two
   different tabs — repeat steps 1 and 4-7 on: a Builder-tab combo
   (Style/Character/Outfit/Scenario/Tool) AND a Library-tab combo
   (category/folder picker if present) AND a LoRA slot combo in the
   Builder's LoRA manager (once ComfyUI is connected). All must behave
   identically — no combo instance left on the old broken behavior.

Session 11.5.2 — History LoRA/image display + Library gating
=========================================================
9. Generate an image via "🎨 Generate in ComfyUI" with at least one
   LoRA slot filled in. Once it completes, go to History and select
   that entry — a "LoRA used: ..." line appears under the preview text
   with the LoRA name(s) (hover for the full list if truncated), and a
   "🔍 Open image" button appears below it.
10. Click "🔍 Open image" — the Gallery's own full-view dialog opens
    (in-app, scaled to ~90% of the screen), not an OS file-explorer
    window.
11. Select an older History entry that has neither `lora_used` nor
    `image_ref` (e.g. a plain "Generate prompt and copy" entry from
    before ComfyUI was ever connected) — neither the LoRA label nor the
    Open-image button appear; no crash, no empty label sitting there.
12. Restart the app, reopen History — old entries (including ones
    created before this session, if their JSON already had
    `lora_used`/`image_ref` populated) render correctly the same way.
13. Disconnect ComfyUI (or launch fresh, never connect) — go to
    Library: the "🔍 Check LoRA dependencies" button is disabled/greyed
    together with the LoRA-binding row being hidden. Connect ComfyUI —
    both become available together, in the same click.
14. Click "⚡ Generate prompt and copy" while ComfyUI IS connected —
    confirm the deliberate decision (clipboard still gets a copy) is
    what actually happens; this is a documented decision, not a bug if
    the clipboard does get the text.
"""


def main():
    print(CHECKLIST)
    print("Run the app (python main.py) and walk through the checklist above.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
