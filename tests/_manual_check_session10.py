"""Session 10 manual on-screen check — throwaway, per the migration
plan's verification rule.

Boots MainWindow (real app, real BuilderTab) so a human can walk the
Builder tab by hand. Not a bare test harness like Sessions 1/2/9's
manual-check scripts — the Builder tab needs the real Library data
(styles/characters/outfits/scenarios/tools) to be worth clicking
through, so this just runs the actual app and prints a checklist to
stdout for what to verify.

Run: python -m tests._manual_check_session10
"""
import sys

CHECKLIST = """
Session 10 manual checklist — Builder tab (part 1)
===================================================
1. Switch "Template type" between Standard/Custom — panel swaps,
   negative-prompt box only shows in Standard mode.
2. Standard: pick a Style, add 2-3 Characters (Who + Outfit), pick a
   Scenario, add a Tool. Click the eye icons — preview dialogs show
   the right file content.
3. Pick a character with real canon outfits in your library data —
   confirm the Outfit dropdown shows "Canon N" options sorted
   numerically (Canon 2 before Canon 10) ahead of shared outfits.
4. Remove a character/tool slot from the middle of the list — remaining
   slots renumber correctly (Character 1, 2, 3...).
5. "Block order..." — reorder blocks with Up/Down, Done applies; the
   summary label above updates immediately.
6. "💾" next to the template combo — save current order as a named
   template, confirm it reappears in the dropdown and reselecting it
   restores that order (including after adding a brand-new block key
   that didn't exist when the template was saved, if you have any old
   templates.json lying around).
7. Click "⚡ Generate prompt and copy" with nothing selected — see the
   "Select at least one..." message, no crash.
8. Fill in enough to generate — output box fills in, copy-status label
   appears, and check your OS clipboard actually has the text.
9. Switch to the History tab — the just-generated prompt appears at
   the top of the list (BuilderTab.prompt_generated -> HistoryTab
   connection wired in main.py).
10. Custom: "✏ Create template" — write a template with [Name 1],
    [Outfit 1], [Style], [Tool], save it. Confirm the dynamic form
    below shows exactly the sections used (no Scenario section, since
    it wasn't referenced). Fill it in and Generate.
11. "✏ Edit" on that same template — Delete button appears (only for
    edit, not create); deleting it falls back to the "no custom
    templates" placeholder if it was the only one.
12. Toggle the app's dark/light theme (top-right button) while on the
    Builder tab — everything (including the slot "Card" frames) stays
    legible in both themes.
"""


def main():
    print(CHECKLIST)
    from main import main as real_main
    return real_main()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
