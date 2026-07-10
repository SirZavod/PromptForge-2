"""Prompt assembly logic: Standard template block-builders, Custom
template parsing/substitution, and the pure-data half of the
library-driven LoRA autofill.

Extracted from PromptForgeApp's methods in the original Tkinter
monolith (promptforgeint.py). Converted from methods to standalone
functions with explicit parameters (no `self`) per the migration plan.

IMPORTANT — a real seam, not a verbatim copy, and worth reading before
wiring this up in later sessions:

The originals mixed three different concerns in every one of these
methods: (1) reading current values out of Tkinter widgets
(`self.selected_style.get()`, `slot["char_var"].get()`, ...), (2) pure
string-assembly logic, and (3) UI side-effects at the very end
(`messagebox.showinfo` for "nothing to generate", rebuilding LoRA slot
widgets, persisting settings). Only (2) belongs in a backend module
with zero GUI-toolkit imports. So every function below takes
already-resolved plain values (strings, lists of plain dicts, tuples)
instead of widget references, and returns a value instead of mutating
UI state or popping a message box — the UI layer (BuilderTab, Sessions
10-11) is responsible for gathering those plain values from its own
widgets, calling these functions, and deciding what an empty/falsy
result means for the user (the original's "Select at least one style,
character, scenario, or tool." / "Fill in at least one template
variable." messages move there).

Two of the original methods get a deliberately different name here
because the pure-data half is genuinely a different function than the
original (which also rebuilt widgets and persisted settings):
`_collect_active_library_loras` -> `collect_active_library_loras` (now
takes the active-entry list as a parameter instead of walking
`self.active_characters` etc. itself), and `_lora_autofill_from_library`
-> `compute_lora_autofill` (now returns the new slots list instead of
also calling `_build_lora_slots`/`_lora_persist`). The UI-layer method
that wires these up in Session 11 keeps the original names as thin
wrappers around these backend functions — see that session's notes.
"""
import re

from backend.constants import CUSTOM_VAR_PATTERN, PREFIXES
from backend.file_manager import read_file_content, load_library_meta


# ============================================================
#                  CUSTOM TEMPLATE PARSING
# ============================================================
def parse_custom_template(text):
    """Finds [Name N]/[Description N]/[Outfit N]/[Style]/[Scenario]/
    [Tool] variables in the template text."""
    name_idx, desc_idx, outfit_idx = set(), set(), set()
    use_style = use_scenario = use_tool = False
    for m in CUSTOM_VAR_PATTERN.finditer(text or ""):
        kind, idx, style_kw, scen_kw, tool_kw = m.groups()
        if kind == "Name":
            name_idx.add(int(idx))
        elif kind == "Description":
            desc_idx.add(int(idx))
        elif kind == "Outfit":
            outfit_idx.add(int(idx))
        elif style_kw:
            use_style = True
        elif scen_kw:
            use_scenario = True
        elif tool_kw:
            use_tool = True
    return {
        "name_idx": name_idx, "desc_idx": desc_idx, "outfit_idx": outfit_idx,
        "use_style": use_style, "use_scenario": use_scenario, "use_tool": use_tool,
    }


def generate_custom_prompt(text, name_vals, desc_vals, outfit_vals, style_val, scenario_val, tool_val):
    """Pure substitution + cleanup for the Custom template builder.

    `text` is the raw custom-template text (with [Name N] etc. variables
    still in place). `name_vals`/`desc_vals`/`outfit_vals` are
    {slot_index: str} — the UI layer resolves each active custom slot's
    character name / description tags / outfit tags (including the
    "Canon N" -> f"{char_name}_Canon_{n}" lookup the original did
    inline) before calling this. `style_val`/`scenario_val`/`tool_val`
    are the already-resolved tag strings for those single (non-indexed)
    variables.

    Returns the assembled, cleaned-up prompt string — possibly empty,
    which the original treated as "Fill in at least one template
    variable." (the UI layer's job to surface now)."""
    def repl(m):
        kind, idx, style_kw, scen_kw, tool_kw = m.groups()
        if kind == "Name":
            return name_vals.get(int(idx), "")
        if kind == "Description":
            return desc_vals.get(int(idx), "")
        if kind == "Outfit":
            return outfit_vals.get(int(idx), "")
        if style_kw:
            return style_val
        if scen_kw:
            return scenario_val
        if tool_kw:
            return tool_val
        return ""

    final_prompt = CUSTOM_VAR_PATTERN.sub(repl, text)
    # light cleanup of extra spaces/empty lines left behind by empty variables
    final_prompt = re.sub(r"[ \t]{2,}", " ", final_prompt)
    final_prompt = "\n".join(line.strip() for line in final_prompt.split("\n"))
    final_prompt = re.sub(r"\n{3,}", "\n\n", final_prompt).strip()
    return final_prompt


# ============================================================
#               STANDARD TEMPLATE BLOCK BUILDERS
# ============================================================
def build_style_block(data_dir, style_name, valid_chars_count):
    """Builds the Style block for the Default Template.

    Rule (Default Template only): when exactly 1 character is selected,
    the "a scene of N characters" count prefix is dropped — only the
    literal "a scene of 1 characters" phrase is removed, any joining
    punctuation that was already glued to the style tags stays as-is.
    For 0 or 2+ characters the original behavior is unchanged.
    """
    style_tags = read_file_content(data_dir, "styles", style_name)
    if style_tags:
        block = f"{style_tags}, a scene of {valid_chars_count} characters" if valid_chars_count > 0 else style_tags
    else:
        block = f"a scene of {valid_chars_count} characters" if valid_chars_count > 0 else ""

    if valid_chars_count == 1:
        block = block.replace(f"a scene of {valid_chars_count} characters", "").rstrip()

    return block


def build_characters_block(data_dir, valid_chars):
    """`valid_chars`: list of {"char_name": str, "outfit_selection": str}
    in display order — already filtered to slots where char_name is
    neither empty nor "None" (the UI layer's job, since that filtering
    reads `slot["char_var"].get()` on the original's widgets).
    `outfit_selection` follows the original combobox value convention:
    "" / "None" (no outfit), "Canon N" (this character's canon outfit
    number N), or a plain shared-outfit entry name."""
    char_lines = []
    valid_chars_count = len(valid_chars)
    for idx, slot in enumerate(valid_chars):
        c_name = slot["char_name"]
        c_tags = read_file_content(data_dir, "characters", c_name)

        o_selection = slot.get("outfit_selection", "")
        o_tags = ""
        if o_selection and o_selection != "None":
            if o_selection.startswith("Canon "):
                c_num = o_selection.split(" ")[1]
                o_tags = read_file_content(data_dir, "outfits", f"{c_name}_Canon_{c_num}")
            else:
                o_tags = read_file_content(data_dir, "outfits", o_selection)

        full_char_prompt = f"{c_tags}, {o_tags}" if o_tags else c_tags

        # Default Template rule: force a trailing period at the end of
        # each character's paragraph (character tags + outfit tags),
        # without duplicating one that's already there.
        full_char_prompt = full_char_prompt.rstrip()
        if full_char_prompt and not full_char_prompt.endswith("."):
            full_char_prompt += "."

        if valid_chars_count > 1:
            prefix = PREFIXES[idx] if idx < len(PREFIXES) else f"Character {idx + 1}:"
            char_lines.append(f"{prefix} {full_char_prompt}")
        else:
            char_lines.append(full_char_prompt)
    return "\n".join(char_lines)


def build_scenario_block(data_dir, scenario_name):
    return read_file_content(data_dir, "scenarios", scenario_name)


def build_tools_block(data_dir, active_tool_names, tools_category="tools"):
    """Returns (force_first_text, regular_text) for the active Tools
    slots. `active_tool_names` is the list of tool-name strings selected
    in each active Tool slot (the UI layer's job to gather, since it
    reads `slot["tool_var"].get()` on the original's widgets — entries
    that are empty or "None" are simply skipped below, same as the
    original, so the caller doesn't need to pre-filter).

    `tools_category` (added in the 46.2c follow-up) is which Library
    category to actually read those tool names from — "tools" by
    default (t2i's own, and every pre-46.2c caller's only option), but
    the caller now passes "image_actions"/"video_actions" when the
    Tools rail itself is scoped to i2i/i2v (see BuilderTab's
    `_mode_tools_category`). Kept as a defaulted trailing parameter
    rather than a required one so this stays a drop-in for any existing
    caller that only ever dealt with t2i's Tools.

    Tools marked "force to start of prompt" in the Library (see
    load_library_meta's force_first) are pulled out into their own
    string, joined and returned separately so generate_standard_prompt
    can place them at the very front of the assembled prompt, ahead of
    block_order entirely — a tag like "@fixedanatomy" needs to reach
    the model before anything else, regardless of whatever order the
    user has Style/Characters/Scenario in. Every other active Tool's
    tags go into regular_text instead, which slots into block_order
    exactly like Style/Characters/Scenario do.

    A Tool entry with empty tags (pure LoRA binding, no text component
    at all) contributes an empty string to whichever bucket it would
    have landed in, which simply drops out when the pieces are joined —
    its LoRA still gets pulled in separately via the existing
    library-LoRA auto-fill machinery, this function only ever deals
    with prompt text."""
    force_first_parts = []
    regular_parts = []
    for tool_name in active_tool_names:
        if not tool_name or tool_name == "None":
            continue
        tags = read_file_content(data_dir, tools_category, tool_name)
        if not tags:
            continue
        if load_library_meta(data_dir, tools_category, tool_name)["force_first"]:
            force_first_parts.append(tags)
        else:
            regular_parts.append(tags)
    return ", ".join(force_first_parts), ", ".join(regular_parts)


def generate_standard_prompt(data_dir, style_name, valid_chars, scenario_name, active_tool_names, block_order,
                              tools_category="tools", active_action_names=None, actions_category=None):
    """Pure assembly for the Standard template — mirrors the original
    generate_standard_prompt exactly, minus the UI tail
    (_finalize_generated_prompt: clipboard/history/live-preview, a
    Session 10/11 concern) and the "nothing to generate" messagebox.

    `valid_chars` / `active_tool_names` / `style_name` / `scenario_name`
    are already-resolved plain values — see build_characters_block and
    build_tools_block above for the exact shapes expected. `tools_category`
    (46.2c follow-up) passes straight through to build_tools_block —
    see its docstring for why this defaults to "tools".

    Session 47.2 fix: `active_action_names`/`actions_category` are the
    i2i/i2v "Actions" slot's equivalent of `active_tool_names`/
    `tools_category` — before this fix, `self.active_actions` (the
    Actions card) was populated correctly in the UI but never actually
    read by any prompt-assembly code, so Action entries never reached
    the prompt at all and i2i/i2v generations fell back to whatever
    the (conceptually unrelated) Tools rail had, if anything. Both
    default to falsy so every existing t2i-only caller keeps working
    unchanged — reuses `build_tools_block` itself rather than
    duplicating its force-first/empty-tags logic, since an Actions
    entry is read from the Library exactly the same shape a Tools
    entry is (name -> tags + optional force_first flag), just from a
    different category. Actions text is placed ahead of Tools text
    within the combined block (both still land in block_order's single
    "tools" slot) since Actions is the primary instruction in i2i/i2v
    mode and Tools there is closer to a LoRA-carrying supplement.

    Returns the assembled prompt string, which may be "" (or whitespace
    -only) if style/characters/scenario/tools/actions were all empty —
    the original showed "Select at least one style, character,
    scenario, or tool." in that case; checking `.strip()` on the result
    and surfacing that message (now pipeline-mode-aware, see BuilderTab
    `_generate_standard_prompt`) is still the UI layer's job."""
    valid_chars_count = len(valid_chars)
    force_first_tools, regular_tools = build_tools_block(data_dir, active_tool_names, tools_category)

    force_first_actions, regular_actions = "", ""
    if actions_category:
        force_first_actions, regular_actions = build_tools_block(
            data_dir, active_action_names or [], actions_category)

    combined_regular = ", ".join(p for p in (regular_actions, regular_tools) if p.strip())
    combined_force_first = ", ".join(p for p in (force_first_actions, force_first_tools) if p.strip())

    blocks = {
        "style": build_style_block(data_dir, style_name, valid_chars_count),
        "characters": build_characters_block(data_dir, valid_chars),
        "scenario": build_scenario_block(data_dir, scenario_name),
        "tools": combined_regular,
    }

    paragraphs = [blocks[key] for key in block_order if blocks.get(key, "").strip()]
    # combined_force_first bypasses block_order entirely — see
    # build_tools_block's docstring. Always the very first paragraph of
    # the assembled prompt, no matter how Style/Characters/Scenario/
    # Tools are ordered, since a tag like "@fixedanatomy" needs to reach
    # the model before anything else does.
    if combined_force_first.strip():
        paragraphs.insert(0, combined_force_first)
    return "\n\n".join(paragraphs)


# ============================================================
#         LIBRARY-DRIVEN LORA AUTOFILL (pure-data half)
# ============================================================
def collect_active_library_loras(data_dir, ordered_active_entries):
    """Returns a de-duplicated, order-preserving list of (lora_name,
    strength) tuples bound (load_library_meta) to whichever library
    entries are currently active in the Builder.

    Session 30.2: also carries each entry's stored `lora_strength`
    (Session 30) — previously this only returned bare names and
    compute_lora_autofill hardcoded 1.0 for every auto slot, silently
    ignoring whatever strength was set on the Library card. First
    mention wins if the same LoRA is bound at two different strengths
    across active entries (same "first mention" rule the old dedup
    already used for the name itself).

    `ordered_active_entries` is a list of (category, name) tuples in
    mention order — the UI layer (Builder tab) is responsible for
    walking its own active widgets (Standard or Custom path, in either
    case skipping empty/"None" slots) and producing this list,
    including the same "Canon N" -> f"{char_name}_Canon_{n}" outfit-
    name resolution build_characters_block/generate_custom_prompt use,
    so the lookup always hits the entry actually shown to the user."""
    result = []
    seen = set()
    for category, name in ordered_active_entries:
        meta = load_library_meta(data_dir, category, name)
        lora = meta.get("lora")
        if lora and lora not in seen:
            seen.add(lora)
            result.append((lora, meta.get("lora_strength", 1.0)))
    return result


def compute_lora_autofill(current_slots_data, auto_loras, lora_none_value="None"):
    """The pure-data half of the original's _lora_autofill_from_library:
    given the *current* lora_slots_data list and the de-duplicated
    auto_loras list (from collect_active_library_loras — a list of
    (lora_name, strength) tuples as of Session 30.2), returns the new
    combined slots list using the agreed smart-merge rule:

      1. Keep all current manual slots (auto flag False/absent) as-is
         — a manual slot always wins over an autofill for the same
         LoRA.
      2. Drop the old auto slots and rebuild them from auto_loras, each
         seeded with its Library-stored strength rather than a
         hardcoded 1.0, skipping any name already covered by a manual
         slot.
      3. If nothing is left at all, fall back to a single empty slot.

    The caller (LoRA manager UI, Session 11) still owns step 0
    (gathering auto_loras via collect_active_library_loras) and the
    UI-side tail the original also did inline — rebuilding the slot
    widgets and persisting to settings.json. Safe to call often (every
    generation): it's a no-op in terms of the returned list when there
    are no active library->LoRA bindings or when the result doesn't
    change."""
    manual_entries = [e for e in current_slots_data
                       if not e.get("auto") and e.get("name", lora_none_value) != lora_none_value]
    manual_names = {e["name"] for e in manual_entries}

    new_auto_entries = [
        {"name": lora, "strength": float(strength), "auto": True}
        for lora, strength in auto_loras
        if lora not in manual_names
    ]

    combined = manual_entries + new_auto_entries
    if not combined:
        combined = [{"name": lora_none_value, "strength": 1.0, "auto": False}]
    return combined
