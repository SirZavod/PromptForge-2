"""LoRA dependency scanning and candidate-finder — pure logic only.
The report text and the candidate-picker dialog are UI and belong in
Session 7 (ui/dialogs/lora_dependency_dialog.py); this module only
answers "what's missing" and "what else could it be".

Extracted from PromptForgeApp's methods in the original Tkinter
monolith (promptforgeint.py). Converted from methods to standalone
functions with explicit parameters (no `self`) per the migration plan.
`data_dir`/`categories`/`available_loras` replace what used to be
`self.DATA_DIR`/`self.CATEGORIES`/`self._available_loras`.

`_lora_path_basename` keeps its original leading underscore exactly as
the migration plan's own Session 7 text refers to it. The scan function
is exposed without the underscore here (nothing later in the plan calls
it by its old private name, and a leading underscore on a public
module-level function reads as a mistake to anyone editing this file
going forward) — an alias is kept regardless, for anyone grepping the
original name.
"""
import glob
import os

from backend.constants import natural_sort_key
from backend.file_manager import get_file_list, load_library_meta, save_library_meta


def apply_lora_candidate(data_dir, old_path, new_path, affected_entries):
    """Rewrites the 'lora' field in every affected entry's meta sidecar
    from old_path to new_path, leaving source_url/force_first on each
    entry exactly as they were — this only ever touches the one field,
    never anything else about the entry. `affected_entries` is the same
    [(category, name), ...] list the dependency scan already produced
    for old_path, so there's no need to re-derive which entries are
    involved. Returns how many entries were updated."""
    updated = 0
    for category, name in affected_entries:
        # Canon outfits are displayed as "Char — Canon N" but stored on
        # disk as "Char_Canon_N" — load_library_meta/save_library_meta
        # both key off the on-disk base name, so the display form needs
        # converting back before use here.
        if category == "outfits" and " — Canon " in name:
            char_name, num = name.split(" — Canon ")
            base = f"{char_name}_Canon_{num}"
        else:
            base = name
        meta = load_library_meta(data_dir, category, base)
        if meta.get("lora") != old_path:
            continue  # already changed by something else since the scan ran
        save_library_meta(data_dir, category, base, source_url=meta.get("source_url"),
                           lora=new_path, lora_strength=meta.get("lora_strength", 1.0),
                           force_first=meta.get("force_first", False))
        updated += 1
    return updated


def _lora_path_basename(path):
    """Extracts the filename from a LoRA path, recognizing BOTH '\\'
    and '/' as separators regardless of which OS PromptForge itself is
    running on. LoRA paths in this app are always stored Windows-style
    (e.g. "PromptForgeLoras\\Anima\\Characters\\akane.safetensors" —
    see the README's models/lora folder structure), since that's what
    ComfyUI itself reports them as on a Windows host. os.path.basename
    is platform-dependent: it only splits on the separator of whatever
    OS Python is currently running on, so on Linux/macOS it would treat
    an entire backslash-separated Windows path as a single filename
    with no split at all — quietly breaking every candidate match. This
    always treats both separators as path boundaries, independent of
    the host OS."""
    return path.replace("\\", "/").rsplit("/", 1)[-1]


def find_lora_candidates(available_loras, missing_paths):
    """For each missing LoRA path, looks for files elsewhere in
    ComfyUI's current LoRA list (`available_loras`) whose FILENAME (not
    full path) matches exactly — i.e. the user has the right file, just
    under a different folder than the one the library entry was
    originally bound to (e.g. they didn't recreate the exact
    "PromptForgeLoras\\Anima\\Characters\\..." structure from the
    original library).

    Returns {missing_path: result} where result is one of:
      - a single candidate path (str) — exactly one other file shares
        this basename; safe to suggest as a one-click fix.
      - a list of 2+ candidate paths — a genuine name collision (two
        different LoRAs, e.g. for different base models, that happen
        to share a filename). Deliberately NOT auto-picked: silently
        guessing wrong here means a generation runs with the wrong
        model's LoRA with no visible error — the only safe move is to
        show every option and let a person decide.
      - None — no other file with this basename exists anywhere;
        there's genuinely nothing to suggest.
    """
    by_basename = {}
    for path in available_loras:
        by_basename.setdefault(_lora_path_basename(path), []).append(path)

    results = {}
    for missing_path in missing_paths:
        basename = _lora_path_basename(missing_path)
        candidates = [p for p in by_basename.get(basename, []) if p != missing_path]
        if not candidates:
            results[missing_path] = None
        elif len(candidates) == 1:
            results[missing_path] = candidates[0]
        else:
            results[missing_path] = candidates
    return results


def compute_lora_dependency_status(data_dir, categories, available_loras):
    """Session 31: the restored three-state Library tree color-coding
    (Скрин 3) — {(category, base): "ok"|"missing"|"conflict"} for every
    entry (including canon outfits, via their own glob pass, same as
    `scan_library_lora_dependencies`) that has a LoRA bound to it.
    Entries with no binding at all are simply absent from the returned
    dict — no status, no row coloring.

    Per the plan's own three-state definition (not the older, unreleased
    "ok/candidate/missing" version of this feature — see UIRework.md's
    Session 31 note): only one axis matters, ambiguity, and it's judged
    purely from `available_loras`, independent of whether the entry's
    own bound path happens to be an exact match:

      "conflict" (red) — 2+ files in `available_loras` share the exact
      same basename as the bound path, regardless of folder. Checked
      FIRST and wins over an exact-path match: even a currently-correct
      binding is one ComfyUI/library reshuffle away from resolving to
      the wrong file if two candidates share a name, so it's flagged,
      not colored green.

      "ok" (green) — no basename collision (0 or 1 other file sharing
      the name), and the file exists: either the bound path matches
      `available_loras` exactly, or exactly one relocated file with the
      same basename exists elsewhere (the entry hasn't been re-pointed
      to it, but there's nothing ambiguous about which file that would
      be).

      "missing" (yellow) — no basename collision, and no file anywhere
      (exact or relocated) shares the bound path's name.
    """
    by_basename = {}
    for path in available_loras:
        by_basename.setdefault(_lora_path_basename(path), []).append(path)

    def status_for(path):
        basename = _lora_path_basename(path)
        same_name = by_basename.get(basename, [])
        if len(same_name) >= 2:
            return "conflict"
        if path in available_loras or len(same_name) == 1:
            return "ok"
        return "missing"

    result = {}
    for category in categories:
        for name in get_file_list(data_dir, category):
            lora = load_library_meta(data_dir, category, name).get("lora")
            if lora:
                result[(category, name)] = status_for(lora)

    canon_files = glob.glob(os.path.join(data_dir, "outfits", "*_Canon_*.txt"))
    for f in sorted(canon_files, key=natural_sort_key):
        base = os.path.splitext(os.path.basename(f))[0]
        lora = load_library_meta(data_dir, "outfits", base).get("lora")
        if lora:
            result[("outfits", base)] = status_for(lora)

    return result



def scan_library_lora_dependencies(data_dir, categories, available_loras):
    """Scans every entry in every Library category (plus canon outfits,
    scanned separately since get_file_list("outfits") deliberately
    excludes them) for a bound LoRA, and returns (entry_count, missing)
    where missing maps lora_path -> [(category, entry_name), ...] for
    every bound path NOT found in `available_loras`.

    Kept separate from the report-building/UI step (Session 7's
    check_library_lora_dependencies) so the candidate-suggestion dialog
    can run the exact same scan rather than duplicating it."""
    entry_count = 0
    missing = {}
    for category in categories:
        for name in get_file_list(data_dir, category):
            entry_count += 1
            lora = load_library_meta(data_dir, category, name).get("lora")
            if lora and lora not in available_loras:
                missing.setdefault(lora, []).append((category, name))

    canon_files = glob.glob(os.path.join(data_dir, "outfits", "*_Canon_*.txt"))
    for f in sorted(canon_files, key=natural_sort_key):
        base = os.path.splitext(os.path.basename(f))[0]
        entry_count += 1
        lora = load_library_meta(data_dir, "outfits", base).get("lora")
        if lora and lora not in available_loras:
            char_name, num = base.split("_Canon_")
            missing.setdefault(lora, []).append(("outfits", f"{char_name} — Canon {num}"))

    return entry_count, missing


# Alias for anyone grepping the original method name.
_scan_library_lora_dependencies = scan_library_lora_dependencies
