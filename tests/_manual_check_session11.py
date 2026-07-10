"""Session 11 manual on-screen check — throwaway, per the migration
plan's verification rule.

Same approach as Session 10's: boots the real MainWindow so a human can
walk the ComfyUI panel by hand against a real running ComfyUI instance
(with a PromptForgeConnection node open in the graph, and optionally a
PromptForgeMultiLoraLoader node too).

Run: python -m tests._manual_check_session11
"""
import sys

CHECKLIST = """
Session 11 manual checklist — Builder tab (part 2, ComfyUI)
=============================================================
1. Check "ComfyUI connected?" with a wrong port — see the "Could not
   connect" error dialog, checkbox un-checks itself, host/port fields
   re-enable.
2. Check it again with the right host/port, no PromptForgeConnection
   node in the open graph — status label shows the "No PromptForgeConnection
   node was found..." warning, options/LoRA manager/Generate-in-ComfyUI
   stay hidden.
3. Add the node to the graph, re-check — "✓ Connected — graph ready",
   seed/resolution options + LoRA manager + "🎨 Generate in ComfyUI"
   all appear. Switch to the Library tab — the LoRA-binding row is now
   visible there too (comfy_connection_changed wiring).
4. LoRA manager: add/remove slots, pick a real LoRA name, adjust
   strength — [M] tag. Fill in a Style/Character/Scenario/Tool that has
   a LoRA bound in Library, click "⚡ Generate prompt and copy" — that
   LoRA appears in the manager as an [A] slot automatically
   (_lora_autofill_from_library). Manually edit that slot's strength —
   tag flips to [M] and stays that way on the next autofill.
5. Seed: leave on Random, submit a job, confirm the seed field fills in
   with the actual seed used after submission. Switch to Fixed, type a
   seed, submit again — same seed reused.
6. Resolution: switch between presets — width/height fields update and
   lock; switch to "Custom…" — fields unlock for manual entry.
7. Click "🎨 Generate in ComfyUI" — progress bar appears and updates,
   preview thumbnail updates live in "Latest image", status label
   updates through Submitting -> (progress) -> final. Confirm a new
   entry appeared in History immediately at submit time (not after
   completion) with a LoRA snapshot.
8. While it's generating, click "🎨 Generate in ComfyUI" again 2-3
   times — queue label shows "generating + N queued", each additional
   click doesn't start a second generation until the first finishes.
9. "🗑 Clear queue" — removes only the pending ones, the one currently
   running keeps going.
10. Click "⏹ Stop" mid-generation — button shows "Stopping…", the
    ComfyUI job actually aborts (check ComfyUI's own console/queue),
    status shows "⏹ Generation stopped." with no error popup, and the
    next queued item (if any) starts automatically.
11. After a successful generation, "📂 Open folder" opens the real OS
    file explorer with the actual output file selected/highlighted —
    not just the local preview cache. Switch to the Gallery tab — the
    same image appears there too (gallery_result_ready wiring).
12. Resize the window / drag the splitter between left and right
    columns — the result image panel's height/size-slider still behave
    sensibly, no crash.
13. Toggle dark/light theme while connected — LoRA [A]/[M] tag colors
    and the result-image placeholder stay legible in both themes.
14. Uncheck "ComfyUI connected?" — panel collapses back down, Library's
    LoRA-binding row hides again, queue is cleared, Generate-in-ComfyUI
    button hides.
"""


def main():
    print(CHECKLIST)
    from main import main as real_main
    return real_main()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
