"""Session 14.5 manual smoke-test checklist — sidebar polish:
icon-over-label nav, compact Comfy footer, Guide relocation.

Same sandbox limitation as every UI session since Session 3: no PyQt6 /
no network here. `python -m py_compile` passes on every touched file
(`main.py`, `ui/theme.py`) but none of this has actually been launched.

Run with:  python main.py

--- Sidebar nav (icon-over-label) ---
1. The six page rows (Builder/Library/History/Gallery/LoRA/Settings)
   now show icon on one line, label on the line below, centered — not
   the old single-line "icon   label" row.
2. Sidebar rail is visibly narrower than the Session 14 screenshot
   (icon-over-label needs far less horizontal room) — confirm nothing
   inside a nav button is clipped/wrapped awkwardly at this width.
3. Clicking each row still switches pages correctly, same as before
   (this session didn't touch `_on_nav_clicked`'s logic, only the
   button's own text/layout).

--- Guide relocation ---
4. Guide is no longer top-right — it's now its own row at the BOTTOM of
   the sidebar, below Settings, separated by a thin horizontal divider
   so it doesn't look like a 7th page destination.
5. Guide still opens via clicking it AND via F1 from any page.
6. Guide is NOT part of the page-switching highlight group — clicking
   it should never show as "selected" the way Builder/Library/etc. do
   when active (it's an action button, not a checkable nav row).

--- Theme toggle (temporarily unavailable — expected) ---
7. There is currently NO visible way to toggle the theme anywhere in
   the UI — this is intentional per the Session 14.5 plan (theme moves
   into Settings for real in Session 19). If you need to switch themes
   before then, edit `"theme"` directly in
   `prompt_forge_data/_settings.json` and relaunch.

--- ComfyUI footer (shrunk) ---
8. The Run/Disconnect button at the very bottom is visibly smaller/
   quieter than before — not a big accent-colored button anymore, a
   small bordered control under the status line.
9. Status line only ever reads one of: "● Disconnected",
   "…  Checking", "🟢  Connected" — no "— graph ready" or warning-detail
   suffix here (that detail still shows inside Builder's own "4.
   ComfyUI" panel, unchanged, until Session 19 removes that panel).
10. Click Run with ComfyUI actually reachable (or fake host/port to
    exercise the failure path) — button disables + "…  Checking" while
    in flight, then settles to "🟢  Connected"/"Disconnect" or back to
    "●  Disconnected"/"Run" on failure (with the existing
    QMessageBox.critical error dialog still appearing on failure,
    unchanged from Session 14).
11. Toggle connect/disconnect a few times in a row — footer never gets
    stuck mid-state (always ends on a consistent dot+button pairing).

--- Regression ---
12. Top area above the page content is now empty (no strip at all) —
    confirm no leftover margin/gap that looks like an empty top bar;
    if the page content starts flush enough that it looks intentional,
    this passes.
13. Resize/maximize/restore-snap (Session 13) still fine with the
    narrower sidebar.
14. Full click-through of Builder/Library/History/Gallery — content
    identical to before this session (only shell chrome changed).
"""
print(__doc__)
