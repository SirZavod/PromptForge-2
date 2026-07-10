"""Session 16 manual smoke-test checklist — Builder column 3:
Result/generation panel tighten.

Same sandbox limitation as every UI session since Session 3: no PyQt6 /
no network here. `python -m py_compile` passes on every touched file
(`ui/tabs/builder_tab.py`) but none of this has actually been launched.

Run with:  python main.py

--- Result column chrome ---
1. No "Latest image" title/box-label anywhere above the preview image —
   it's a plain lightly-bordered card now, not a titled group box.
2. "Size" row is a compact single line (label + slider), no box of its
   own — same as before, just confirm it survived the surrounding
   refactor.
3. Visibly more vertical room for the actual preview image than the
   Session 15 NOW.png showed for this column (tighter margins around
   it, no reserved title strip eating space at the top).

--- Progress bar ---
4. Trigger a ComfyUI generation (or fake progress if that's easier to
   exercise) — the progress bar is now a compact bar, NOT spanning the
   column's full width, with the "N/Total" counter sitting right next
   to it (not below, not overlapping).
5. Bar + counter are left-aligned as a unit, with empty space to their
   right rather than the bar stretching to fill it.

--- Unified action cluster ---
6. "🎨 Generate in ComfyUI" now lives in THIS column (bottom of the
   Result panel), not column 2 anymore — confirm it's gone from column
   2 entirely.
7. Below Generate: Stop / queue-count text / Clear queue / Open folder
   all share one row, grouped together — not Stop floating alone in a
   corner like before.
8. Queue-count text appears in that row (not a separate label
   elsewhere) and correctly distinguishes "generating + N queued" from
   "N queued" from blank — same logic as before, just relocated.
9. Trigger a generation, then queue a couple more behind it — Stop
   stays enabled/visible correctly, Clear queue enables once something
   is actually queued, Generate correctly disables/hides per the
   existing busy-state rules (this session didn't touch any of that
   logic, only where the buttons live).
10. Open folder appears once a result actually exists (same rule as
    before) and doesn't fight Stop for space now that they're in a
    4-item row instead of a 2-item one.
11. At the column's normal ~260-300px width, confirm the secondary row
    (Stop/count/Clear queue/Open folder) doesn't visually overflow or
    wrap awkwardly — if it's cramped at your actual window size, flag
    it back; this is exactly the kind of thing I can't verify without
    a real PyQt6 render.

--- Regression ---
12. Result-zone resize slider still works (drag it, image area
    actually resizes) and still persists across relaunch
    (`settings["comfy_result_zone_percent"]`) — untouched logic, only
    the container around it changed.
13. Full ComfyUI generate → progress → result-appears → Open
    folder/Clear queue flow still works end to end exactly as before
    this session.
14. Builder column 2 (Session 15's tab pair, collapsed Template panel,
    tightened Characters) still looks/behaves as it did last session —
    this session only touched column 3 plus removing the one row that
    moved out of column 2.
"""
print(__doc__)
