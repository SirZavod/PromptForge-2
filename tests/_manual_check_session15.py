"""Session 15 manual smoke-test checklist — Builder column 2: Prompt
Builder declutter + resize, plus the sidebar Comfy-button micro-fix
flagged on the Session 14.5 NOW.png.

Same sandbox limitation as every UI session since Session 3: no PyQt6 /
no network here. `python -m py_compile` passes on every touched file
(`main.py`, `ui/theme.py`, `ui/tabs/builder_tab.py`) but none of this
has actually been launched.

Run with:  python main.py

--- Micro-fix: sidebar Comfy button width + status style ---
1. Bottom-of-sidebar footer: the Run/Disconnect button now fills the
   same width as the "Connected"/"Disconnected" status line above it —
   no dead gap to the right of the button inside the footer card
   (this was the bug circled in red on the Session 14.5 NOW.png).
1b. Status line has no dot/emoji glyph anymore — plain text only,
    colored green for "Connected", default dim gray for "Disconnected"
    /"Checking…" (per your note: color alone reads clearly without a
    bullet).

--- Prompt Template panel (now collapsible) ---
2. On first launch (no prior settings), the Prompt Template panel shows
   as ONE line — "📄  Template: Standard" + a chevron — not the old
   3-row always-expanded box.
3. Clicking the header expands it to reveal: Template type combo,
   Block order… button + order text, the named-template combo + save
   button (Standard), or the Custom controls row (Custom) — nothing
   from before is missing, just hidden until expanded.
4. Switching Template type (Standard ⇄ Custom) while expanded updates
   the collapsed header's text next time you collapse it (e.g. "📄
   Template: Custom").
5. Collapse/expand state persists across a relaunch
   (`settings["section_collapsed_template_panel"]`), same pattern as
   the LoRA section's own persistence.

--- Characters block (tightened) ---
6. Add 1 character, then a 2nd — at a normal window height, confirm
   the Builder column does NOT need to scroll to see Style +
   Characters (both slots) + Scenario + the Positive/Negative output +
   Generate, all at once. This is the actual test for the plan's "no
   scroll at 1-2 characters" goal — if it still scrolls, flag it back,
   this is the session responsible for fixing it.
7. Each character card (Who/Outfit rows + eye buttons + remove button)
   is visibly more compact than before — less dead padding around the
   two combo rows.
8. Add/remove still works correctly; "Character N" labels still
   renumber correctly after a removal from the middle of the list.

--- Tools removed from this column (temporary — expected) ---
9. There is currently NO "Tools" section anywhere in the Builder tab's
   Standard flow — this is intentional per Session 15 step 3. Tools
   re-appear in the new ComfyUI-advanced column in Session 17; nothing
   is deleted, `self.box_tools`/`add_tool_slot`/`remove_tool_slot` all
   still exist (explicitly `.hide()`-den, not just off-layout — see
   the "floating Tools box" bugfix note above the changelog), just not
   attached to any visible layout yet.
10. Confirm Standard prompt generation still assembles correctly with
    zero tools active (it always would have, in the "no tools added"
    case) — this just makes that case permanent until Session 17.

--- Positive/Negative output (now tabs) ---
11. "Generated prompt"/"Negative prompt" are no longer two separate
    boxes — one tabbed area with "Positive" and (conditionally)
    "Negative" tabs sits where "Generated prompt" used to be.
12. With ComfyUI NOT connected: only the "Positive" tab exists, no
    "Negative" tab at all.
13. Connect to ComfyUI (Settings/sidebar Run, or fake host/port to
    exercise the failure path first): once actually connected AND the
    Standard template type is active, a "Negative" tab appears
    alongside "Positive".
14. Switch Template type to Custom while connected: the Negative tab
    disappears again (Custom carries its own per-template negative
    prompt box inside custom_section, untouched by this session).
    Disconnect while on Custom, then reconnect while on Custom — still
    no Negative tab. Switch back to Standard while connected — it
    reappears.
15. Text typed into the Negative tab's box still round-trips through
    `settings["negative_prompt"]` even while the tab is hidden (type
    something, disconnect so the tab vanishes, reconnect — the text is
    still there).
16. "⚡ Generate prompt and copy" now sits directly under the tab pair,
    not above Characters — confirm visually.
17. A "📋 Copy" button sits under the Positive tab's output, next to
    the copy-status label. Click it with generated text present — it
    re-copies to the clipboard and updates the status label. Click it
    with an empty output — no-ops silently (no crash, no false status
    message).

--- Regression ---
18. Full "Generate prompt and copy" flow (Standard, then Custom) still
    produces correct text in the Positive tab and still auto-copies to
    clipboard on generate, exactly as before this session.
19. ComfyUI generation queue flow (🎨 Generate in ComfyUI, Stop, Clear
    queue) untouched and still functional — this session didn't touch
    `_build_comfy_panel`, the LoRA section, or the queue row.
20. Theme toggle is still unreachable from the UI (expected, per
    Session 14.5 — lands for real in Session 19); if you need to
    switch themes, still edit `"theme"` in
    `prompt_forge_data/_settings.json` directly.
"""
print(__doc__)
