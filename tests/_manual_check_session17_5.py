"""Session 17.5 manual smoke-test checklist — Rail/splitter stability
+ result-column space reclaim.

Same sandbox limitation as every UI session since Session 3: no PyQt6 /
no network here. `python -m py_compile` passes on every touched file
(`ui/tabs/builder_tab.py`, `ui/widgets/collapsible_rail.py`,
`ui/theme.py`) but none of this has actually been launched.

Run with:  python main.py

--- Arrow direction ---
1. With the ComfyUI rail expanded, the handle shows "»" (about to
   collapse rightward). Click it: rail animates closed, handle now
   shows "«" (about to expand back leftward). This is the reverse of
   Session 17's mapping — confirm it now matches the motion about to
   happen, not the motion that just happened.

--- No more drag handles ---
2. Try to drag the boundary between the Builder column and the Result
   column, and between the Result column and the ComfyUI rail — there
   should be NO draggable splitter handle anywhere across the 3
   columns anymore. Column widths only change via window resize or the
   rail's own toggle.
3. Toggle the rail open/closed several times in a row, resizing the
   window in between toggles — the animation should never "reverse"
   or jump to an unexpected width. (This was the core Session 17 bug:
   dragging the old splitter handle desynced `railWidth` from the
   `_expanded` flag.)

--- Rail width / tool name clipping ---
4. Expand the rail and add a tool with a longish name (e.g. "Add tool
   enhancer") in the Tools slot list — the name should no longer clip
   at the new 320px expanded width.
5. Collapse the rail — thin strip, handle still visible and clickable
   at the same vertical-centered position.

--- Toggle handle position ---
6. The toggle handle sits at a FIXED position on the rail's left edge,
   vertically centered, in both expanded and collapsed states — it
   should never share a row with the "ComfyUI options" title label,
   and should never shift horizontally between states.

--- Size slider removal ---
7. The old "Size" slider above the result image is completely gone —
   no slider, no leftover empty row where it used to be.
8. The preview image now fills the entire available height/width of
   the Result column's card automatically — resize the window and
   confirm the image box grows/shrinks with it, with no dead space
   below/beside it (aside from the deliberate rounded-card margin).
9. Expand/collapse the ComfyUI rail — confirm the Result column (and
   therefore the preview image) automatically grows when the rail
   collapses and shrinks when it expands, with no manual step needed.

--- Regression ---
10. Full ComfyUI generate -> progress -> result-appears -> Open
    folder/Clear queue flow still works end to end exactly as before
    this session (Session 16's action cluster untouched).
11. Builder column 2 (Session 15's tab pair, collapsed Template panel,
    tightened Characters) still looks/behaves as before — this session
    only touched columns 3+4's container/sizing plumbing.
12. Theme toggle still repaints the rail's toggle handle correctly in
    both light and dark themes (new `QToolButton#RailHandle` QSS).
"""
print(__doc__)
