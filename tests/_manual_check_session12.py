"""Session 12 manual on-screen check — In-app multi-language Guide.

Same sandbox limitation as every UI session since Session 3: no PyQt6 /
no network here, so this has been hand-checked against the reference
and against `tests/test_guide_content_session12.py` (data-layer, runs
clean) but NOT actually launched. Run this checklist yourself with a
real PyQt6 install before starting a later session that touches
main.py or ui/dialogs/guide_dialog.py again.

Run with:  python main.py

Checklist:
1. Click "❓ Guide" in the top bar. Dialog opens, title "❓ PromptForge
   Guide", "Quick start" section selected and shown by default.
2. Left nav lists all 8 sections in order: Quick start, Library &
   Subfolders, The Tools category, Connecting to ComfyUI (or whatever
   "comfyui" is titled), LoRA Manager, Generation queue (or whatever
   "queue" is titled), History & Gallery, Known issues.
3. Click through a few sections — body text updates each time, nav
   selection follows.
4. Close the dialog, press F1 — same dialog opens (confirms the
   QShortcut wiring, not just the button).
5. Switch the Language dropdown to "Русский". Section titles switch to
   Russian. Whatever section was selected stays selected (does NOT
   jump back to "Quick start"/section 0) — pick section 5 first, then
   switch language, and confirm you're still looking at section 5's
   (now-Russian-titled) content.
6. Switch to "中文" and "日本語" — same check, section stays selected.
   Since ru/zh/ja are the three hand-translated languages in this
   build, none of their sections should show the "[translation
   pending]" marker text.
7. Close the dialog, reopen it (button or F1) — language dropdown
   remembers "日本語" (or whatever you left it on), confirming the
   settings["guide_language"] persistence round-tripped through
   `_settings.json` within the same run.
8. Quit and relaunch the app entirely — Guide still opens on the last
   chosen language. Confirms the save actually hit disk, not just an
   in-memory settings dict.
9. Resize the dialog smaller/larger — nav list and body text both stay
   usable (nav doesn't disappear, body doesn't get clipped/unreadable).
10. Click "Close" — dialog closes cleanly, no error in the console.
"""
print(__doc__)
