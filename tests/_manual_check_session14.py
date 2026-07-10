"""Session 14 manual smoke-test checklist — App shell: sidebar nav +
bottom ComfyUI status.

Same sandbox limitation as every UI session since Session 3: no PyQt6 /
no network here (confirmed again this session:
`pip install PyQt6 --break-system-packages` -> "No matching
distribution found"). Every change was hand-checked against the plan
(UIRework.md Session 14) and `python -m py_compile` passes on every
touched file, but none of this has actually been launched. Run this
checklist yourself with a real PyQt6 install.

Run with:  python main.py

--- Sidebar shell (new this session) ---
1. Launch: window opens with a left sidebar rail (icon-only ⚡ brand at
   top, no more "⚡ PromptForge / prompt builder & generation workspace"
   title+subtitle row anywhere) and six nav rows: Builder, Library,
   History, Gallery, LoRA, Settings.
2. Builder is selected by default (highlighted nav row, accent left
   edge) and its content is exactly what Builder looked like before
   this session — no Builder-internals changes yet, only the shell
   around it changed.
3. Click each of Library/History/Gallery — same content/behavior as
   before, just reached via the sidebar instead of a top tab.
4. Click LoRA and Settings — each shows a simple placeholder page
   ("... moves here in a later session"), not a crash, not an empty
   blank widget.
5. Click into Gallery specifically after a fresh launch (first click,
   not a re-click) — thumbnails should lay out correctly immediately
   (this is the `currentChanged`-equivalent relayout-on-first-view fix
   from the old top-tab shell, now wired through `_on_nav_clicked`).
6. Guide button (❓) and theme toggle (🌙/☀️) still live top-right above
   the page content, still work (Guide opens via button and F1, theme
   toggle repaints the whole app including the new sidebar and footer).

--- ComfyUI status/connect (moved to sidebar footer) ---
7. Sidebar footer (bottom of the rail) shows a status line
   ("● Disconnected" at launch) and a "Run" button.
8. Click Builder, confirm host/port fields are UNCHANGED there for now
   (Session 19 moves them to Settings) — enter a real ComfyUI
   host/port if you have one running, or leave the defaults.
9. Click "Run" in the sidebar footer — button disables while checking,
   status line shows "Checking connection…", then on success flips to
   "🟢 Connected — graph ready" (or the workflow-warning variant) and
   the button relabels to "Disconnect"; on failure shows "✗ <error>"
   and a QMessageBox, button relabels back to "Run".
10. With ComfyUI connected via the sidebar button, confirm Builder's
    own ComfyUI-gated UI (Tools/LoRA-visible-once-connected sections,
    Generate-in-ComfyUI button, seed/resolution options) all still
    appear exactly as before — the sidebar button is driving the exact
    same `chk_comfy_enabled` checkbox/boolean under the hood, so
    nothing downstream should behave differently.
11. Click "Disconnect" in the sidebar footer — status flips back to
    "● Disconnected", Builder's connected-only sections hide again,
    same as unchecking the old in-Builder checkbox used to do.
12. Reconnect, then switch to Library/Gallery/LoRA/Settings pages while
    connected — sidebar footer status should stay accurate regardless
    of which page is currently showing (it's not Builder-page-scoped).

--- Regression (quick pass) ---
13. Resize/maximize/restore-snap behavior (Session 13) still works with
    the new sidebar taking up its own fixed-width column.
14. Quit and relaunch — theme, window size, and comfy host/port
    (still Builder-local this session) all restore as before.
"""
print(__doc__)
