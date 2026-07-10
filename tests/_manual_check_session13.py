"""Session 13 manual smoke-test checklist — integration/polish pass.

Same sandbox limitation as every UI session since Session 3: no PyQt6 /
no network here (confirmed again this session:
`pip install PyQt6 --break-system-packages` -> "No matching
distribution found"). Every change was hand-checked against the
reference (`_apply_computed_minsize`, `_on_root_configure`,
`_apply_app_icon`, `SetProcessDpiAwareness`) and `python -m py_compile`
passes on every touched file, but none of this has actually been
launched. Run this checklist yourself with a real PyQt6 install before
calling the migration done.

Run with:  python main.py

--- Window chrome (new this session) ---
1. Launch on a normal-size monitor — window opens centered, sized to
   ~85% of the screen (same as before), no visible jump/resize flash
   after the tabs finish building.
2. Shrink the window by dragging a corner as small as it'll go — it
   should stop at a floor that still shows every control in the
   current tab without anything clipped (this floor is now
   content-derived, not the flat 1040x680 guess from Session 3 — it
   may end up slightly bigger than 1040x680 depending on your system
   font/DPI).
3. Maximize the window, then restore it (un-maximize) — it should snap
   back to the same centered "comfortable default" size from step 1,
   not stay at whatever size it happened to be at right before you
   maximized it.
4. Repeat step 3 a second time in the same run — should behave
   identically (this isn't a one-shot state).
5. On a HiDPI display/scaled-desktop setup if you have one: text and
   icons render crisp, not blurry/pixelated, and controls aren't
   oddly mis-sized relative to each other.

--- Full-feature regression (every prior session, one pass) ---
6. Library: create/rename/delete/duplicate entry, attach image, set
   source URL, set LoRA binding, for all five categories including
   Tools.
7. Library folders: create a folder, drag an entry into it, rename the
   folder, try (and fail) to rename/delete "Canonical Outfits", mark
   an outfit canon and confirm it auto-files there.
8. Library LoRA dependencies: bind a LoRA that doesn't exist in
   ComfyUI's current list, run the check, confirm it's reported, find
   a same-name candidate elsewhere and apply it.
9. Library export/import: export, then import into a copy with one
   overlapping entry name — confirm the overlap is skipped and
   reported, not overwritten.
10. Builder Standard: add 2 characters, add a tool, generate prompt,
    verify clipboard content includes the Tools block in the
    configured order.
11. Builder Custom: create template with [Name 1], [Style], [Tool],
    generate.
12. ComfyUI: connect, verify LoRA list populates, click Generate three
    times quickly — confirm a queue count appears, all three
    eventually complete in order, Stop only cancels the active one,
    Clear queue only drops the pending ones.
13. Guide: open via button and via F1, switch language (ru/zh/ja),
    confirm the selected section stays selected, confirm the choice
    persists after restart.
14. History: copy, restore to Forge, favorite, delete, "LoRA used"
    label + "Open image" button on a Comfy-generated entry.
15. Gallery: resize window -> columns reflow; click reveal -> Explorer
    opens correct folder; click full view -> image opens.
16. Theme toggle -> all widgets repaint correctly in both dark and
    light, including the collapsible LoRA section and the folder tree.
17. Quit and relaunch — theme, window size/position behavior, guide
    language, LoRA slots, negative prompt, block order, and comfy
    host/port all restored exactly as left.

--- Packaging (optional, only if you actually build the .exe) ---
18. `pip install -r requirements.txt` then
    `pyinstaller PromptForge.spec` from the `promptforge/` folder.
19. Run the produced `dist/PromptForge/PromptForge.exe` (or platform
    equivalent) from a folder with NO `prompt_forge_data/` yet —
    confirm it creates one fresh and launches cleanly, no console
    window flashes, icon appears in the taskbar if `icon.ico` is
    present next to the .exe.
"""
print(__doc__)
