"""Shared constants, color themes, and small pure-Python helpers.

Ported verbatim from the original Tkinter monolith (promptforgeint.py).
Zero Tkinter/UI dependencies — safe to import from anywhere, including
tests and worker threads.
"""
import os
import re

# ===================== Data folder & top-level file names =====================
# These were inline string literals built in PromptForgeApp.__init__
# (e.g. `self.DATA_DIR = "prompt_forge_data"`) in the original monolith.
# Pulled out here so file_manager.py (and anything else that needs a
# data-file path) has one canonical source — see IMPORTANT NOTES in the
# migration plan: "Never break data compatibility." These exact string
# values must never change.
DATA_DIR_NAME = "prompt_forge_data"
# Session 46.2c: "image_actions"/"video_actions" are purpose-built
# Library categories for the i2i/i2v "Actions" slot (Session 46.2
# follow-up), replacing the generic "tools" category that slot used to
# share with t2i's own Tools slots. "tools" itself is untouched and
# still backs t2i's Tools slots exactly as before -- this is additive,
# not a rename, so no existing data/category ever needs migrating.
#
# 46.2c follow-up #3: "edit_tools"/"video_tools" are a SEPARATE pair of
# categories for the right-rail Tools list in i2i/i2v -- deliberately
# not the same category as "image_actions"/"video_actions". Actions
# entries need a prompt/instruction (an edit or camera-move
# description); Tools entries often don't (a LoRA-only "Anatomy Fixer"
# has no text at all, just a stack strength) and, per-author, carry a
# strength that's tuned for a specific scenario -- the same LoRA at the
# wrong strength can under- or over-correct. Those are two genuinely
# different kinds of entries even within one pipeline mode, so each
# mode gets its own Tools category *and* its own Actions category,
# never one standing in for the other.
CATEGORIES = ["styles", "characters", "outfits", "scenarios", "tools",
              "image_actions", "video_actions", "edit_tools", "video_tools"]
# Session 47.1 fix: which categories are allowed to save with an empty
# tags/content field — the three "Tools-style" categories (a LoRA-only
# entry like "Anatomy Fixer" is just a stack strength, no prompt text
# at all; see the "edit_tools"/"video_tools" comment above for the full
# reasoning). "image_actions"/"video_actions" are deliberately NOT in
# this list — an Action entry needs a real edit/camera-move
# instruction, so an empty one stays a validation error there. Kept as
# a real constant (not a per-callsite string check) so LibraryTab's
# save_to_library and anything else that needs the same distinction
# share one source of truth instead of each hardcoding "tools" and
# forgetting to update it the way save_to_library originally did when
# edit_tools/video_tools were added.
TOOLS_LIKE_CATEGORIES = ("tools", "edit_tools", "video_tools")
TEMPLATES_FILE_NAME = "_templates.json"
CUSTOM_TEMPLATES_FILE_NAME = "_custom_templates.json"
HISTORY_FILE_NAME = "_history.json"
SETTINGS_FILE_NAME = "_settings.json"

# Image files we accept for upload / drag'n'drop.
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif")
# Session 46.3/46.4: which extensions a ComfyUI /history output entry
# is classified as "video" by (see ComfyUIClient.extract_output_info).
# Deliberately NOT tied to any particular node's class_type -- see
# SESSION 46.3's decision write-up for why: there is no fixed list of
# "the" video-output nodes to search for, dozens of community nodes
# (VHS_VideoCombine, various *_SaveVideo variants, etc.) all write a
# video file into a "gifs"/"videos"/whatever-named key of the same
# /history outputs dict images already come from -- classification by
# the file's own extension is the only approach that doesn't silently
# miss whichever node happens to not be on some hardcoded list.
VIDEO_EXTENSIONS = (".mp4", ".webm", ".mov", ".mkv", ".avi")
# Optimized storage format/extension for converted library images.
IMAGE_STORE_EXT = ".jpg"
# Library images are scaled so their longest side equals this many pixels.
IMAGE_MAX_SIDE = 1024
# Sidecar JSON file (named after the entry, like the image file) that holds
# per-entry metadata not suited to the plain-text tags file: Source URL
# (Task 6) and LoRA binding (Task 7.1).
LIBRARY_META_EXT = ".meta.json"

# ===================== Library folders (virtual subfolders) =====================
# Per-category mapping of {entry_name: "folder/path"} persisted in a single
# JSON file. Folders here are PURE UI/organization metadata: they never
# change where a .txt/.jpg/.meta.json actually lives on disk, and the
# Builder/get_file_list/history/lora-binding code never has to know they
# exist — they keep working off the same flat, globally-unique-per-category
# entry name as before. See _folders.json / load_folder_map / etc.
LIBRARY_FOLDERS_FILE_NAME = "_folders.json"
# Path separator used INSIDE a folder path value (e.g. "Casual Clothes/Wednesday").
# Never a literal OS path — purely a display hierarchy.
FOLDER_PATH_SEP = "/"
# Auto-managed virtual folder that canon outfits are filed into automatically
# the moment they're marked "Is this a character's canon outfit?". Users
# cannot rename it, delete it, or drop ordinary (non-canon) outfits into it
# manually — see _is_protected_folder().
CANONICAL_OUTFITS_FOLDER = "Canonical Outfits"

# ===================== Library Active/Inactive (Session 45) =====================
# Per-category record of which entries and which folders are currently
# marked Inactive (everything defaults to active, additively -- a missing
# key/file means "nothing is inactive", so this never breaks a library
# saved before this feature existed). Kept in its own sibling file next to
# _folders.json rather than folded into that file's existing flat shape,
# so the pre-Session-45 folder-map format on disk never has to change --
# see backend/file_manager.py's active-map helpers.
LIBRARY_ACTIVE_FILE_NAME = "_active.json"

# ===================== LoRA profiles / Models (Session 65+) =====================
# A "profile" is one base-model flavour of the LoRA bindings an entry
# carries (e.g. "Anima 2.9b"). The implicit DEFAULT profile is the
# entry's original `lora` / `lora_strength` sidecar fields; extra
# profiles live in the sidecar's additive `loras` key, keyed by a stable
# profile id. The profile list itself is stored next to _folders.json /
# _active.json so Library export/import carries it. Names are display-
# only: renaming a profile never touches entries.
LORA_PROFILES_FILE_NAME = "_lora_profiles.json"
# Added profiles only; the implicit Default does not count.
MAX_LORA_PROFILES = 8
LORA_PROFILE_NAME_MAX_LEN = 40
LORA_PROFILE_DEFAULT_NAME = "Default"
# _settings.json keys (used by the Settings page / Builder, Session 66+).
# LORA_PROFILE_DEFAULT_NAME_SETTING is kept only so old settings and the
# pre-Session-71 UI keep loading; from Session 69 on nothing in the
# backend reads it (D1: Default is always called "Default").
LORA_PROFILE_DEFAULT_NAME_SETTING = "lora_profile_default_name"
ACTIVE_LORA_PROFILE_SETTING = "active_lora_profile"

# ----- Models are presets (Session 69 / D13-D21) -----
# The same _lora_profiles.json also carries the optional preset fields
# per model, plus a "default" object for the Default preset (D14).
# Every field is optional: a file written by Session 65-68 loads
# unchanged (missing = empty) and is written back unchanged until one
# of the new fields is actually set.
LORA_PROFILES_DEFAULT_KEY = "default"
MODEL_FIELD_DIFFUSION = "diffusion_model"
MODEL_FIELD_CLIP = "clip"
MODEL_FIELD_VAE = "vae"
MODEL_FIELD_STEPS = "steps"
MODEL_FIELD_CFG = "cfg"
MODEL_FIELD_LORA_SOURCE = "lora_source"
# Session 73 extra (D34 / D35): the text encoder's `type` and the
# sampler / scheduler names. Plain strings; "" = leave the workflow alone.
MODEL_FIELD_CLIP_TYPE = "clip_type"
MODEL_FIELD_SAMPLER = "sampler"
MODEL_FIELD_SCHEDULER = "scheduler"
# File-valued preset fields (a ComfyUI name exactly as folder_paths
# reports it; "" = leave that loader alone, D15).
MODEL_FILE_FIELDS = (MODEL_FIELD_DIFFUSION, MODEL_FIELD_CLIP, MODEL_FIELD_VAE)
# Sampling fields: int or None / float or None (D29).
MODEL_SAMPLING_FIELDS = (MODEL_FIELD_STEPS, MODEL_FIELD_CFG)
# Choice-valued preset fields: a value ComfyUI reports for a combo widget
# (never typed by hand), "" = leave that widget alone (D15).
MODEL_CHOICE_FIELDS = (MODEL_FIELD_CLIP_TYPE, MODEL_FIELD_SAMPLER,
                       MODEL_FIELD_SCHEDULER)
# Every string-valued preset field (files + choices): one tolerant reader.
MODEL_TEXT_FIELDS = MODEL_FILE_FIELDS + MODEL_CHOICE_FIELDS
MODEL_PRESET_FIELDS = MODEL_TEXT_FIELDS + MODEL_SAMPLING_FIELDS
# "Sane" ranges used by the tolerant loader: garbage and out-of-range
# values are clamped instead of rejected, so a hand-edited file never
# makes Settings unopenable. ComfyUI's own widgets accept wider ranges;
# these only guard the stored preset.
MODEL_STEPS_MIN = 1
MODEL_STEPS_MAX = 10000
MODEL_CFG_MIN = 0.0
MODEL_CFG_MAX = 100.0
# LoRA list source of a model (D16). "own" = its own list; "default" =
# share Default's; any other value is the id of a model with its own
# list (never a chain).
LORA_SOURCE_OWN = "own"
LORA_SOURCE_DEFAULT = "default"

# ----- Per-list Active / Inactive (Session 69 / D20-D21) -----
# Default keeps _active.json exactly as before. Every model with its own
# list stores its three-valued entry state in a sibling file named from
# this template; folders stay two-valued (explicit inactive), as today.
LIBRARY_ACTIVE_OWNER_FILE_TEMPLATE = "_active_{owner_id}.json"
# Entry states stored in a per-owner file. "auto" is never written: an
# entry absent from the file is in auto state and is judged by the D21
# rule on every read.
ACTIVE_ENTRY_AUTO = "auto"
ACTIVE_ENTRY_ACTIVE = "active"
ACTIVE_ENTRY_INACTIVE = "inactive"

# ===================== ComfyUI integration constants =====================
# Contract between Prompt Forge and the companion custom node
# (promptforgeconnection.py). The node's class_type in any workflow graph
# MUST match this string — that's the only thing the two sides agree on.
# ===================== Sound notifications (Session 37) =====================
# Folder (under data_dir) holding per-action custom-sound subfolders --
# see backend/sound_manager.py for the full resolver.
SOUNDS_DIR_NAME = "sounds"
# The three trigger points wired in Session 37, in the order they appear
# on the Settings page's "Sounds" card. Keys are also the subfolder names
# under `<data_dir>/sounds/` and the bundled-default filename stems under
# `assets/sounds/`.
SOUND_ACTIONS = ("gen_ready", "image_saved", "entry_added")
SOUND_ACTION_LABELS = {
    "gen_ready": "Generation ready",
    "image_saved": "Image saved",
    "entry_added": "Entry added",
}
# Bundled ("Default") sound files live here relative to the repo root /
# PyInstaller bundle root -- see main.py's `_bundled_assets_dir()`.
BUNDLED_SOUNDS_SUBDIR = os.path.join("assets", "sounds")
DEFAULT_SOUND_VOLUME = 80  # 0-100, matches the Settings slider's own scale

# ===================== Custom theme background image (Session 40) =====================
# Subfolder (under data_dir) the uploaded background image is copied
# into — never bundled into the compiled app, it's inherently a
# per-user asset (same "copy in, reference by path from settings"
# precedent as Session 37's custom sounds).
THEME_ASSETS_DIR_NAME = "theme"
BACKGROUND_IMAGE_STEM = "background"  # actual filename is this + the original extension
BACKGROUND_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".bmp")
BACKGROUND_FIT_MODES = ("stretch", "fit_crop", "tile")
BACKGROUND_FIT_LABELS = {
    "stretch": "Stretch to fill",
    "fit_crop": "Fit + crop",
    "tile": "Tile",
}
DEFAULT_BACKGROUND_FIT = "stretch"
DEFAULT_BACKGROUND_OPACITY = 100  # 0-100, no dimming by default
# Session 40.1: how translucent the Custom theme's cards/surfaces are
# (100 = fully opaque, unchanged behavior) and how much the background
# image itself is pre-blurred (0 = sharp) — both purely cosmetic knobs
# on top of Session 40's background image, no effect without one set.
DEFAULT_CARD_ALPHA = 100
DEFAULT_BACKGROUND_BLUR = 0
MAX_BACKGROUND_BLUR = 30

COMFY_NODE_CLASS_TYPE = "PromptForgeConnection"
COMFY_DEFAULT_HOST = "127.0.0.1"
COMFY_DEFAULT_PORT = 8188
COMFY_HTTP_TIMEOUT = 6          # seconds, for quick calls (health check, /prompt submit)
COMFY_POLL_INTERVAL = 1.0       # seconds between /history polls while a job runs
COMFY_POLL_TIMEOUT = 300        # seconds — give up waiting on a single t2i/i2i generation after this
# Session 47.4 fix: t2i/i2i generations realistically finish well within
# COMFY_POLL_TIMEOUT's 300s on most setups, but that value predates i2v
# entirely and was never revisited when Session 46.3/46.4 added it — a
# real video generation (Wan/AnimateDiff/etc.) can legitimately run
# 10-30 minutes depending on model, resolution, and frame count, so
# every video generation was inheriting a 5-minute ceiling sized for a
# much faster job. i2v gets its own, much larger ceiling instead of
# just raising the flat constant, specifically so a genuinely stuck/
# crashed t2i or i2i job (queue never advances, ComfyUI hung) still
# reports failure in a reasonable ~5 minutes rather than taking 40 —
# see ComfyGenerationWorker.run in workers/comfy_worker.py, which picks
# between the two based on the queue item's own "pipeline_mode".
COMFY_VIDEO_POLL_TIMEOUT = 2400  # seconds (40 min) — i2v only
COMFY_GRAPH_PATH = "/promptforge/graph"  # served by the node's Python bridge
COMFY_LORAS_PATH = "/promptforge/loras"  # returns available LoRA file list
# Session 70 (D24-D26): the model loaders and the two new bridge routes.
COMFY_NODE_CLASS_TYPE_DIFFUSION_LOADER = "PromptForgeDiffusionLoader"
COMFY_NODE_CLASS_TYPE_CLIP_LOADER = "PromptForgeClipLoader"
COMFY_NODE_CLASS_TYPE_VAE_LOADER = "PromptForgeVaeLoader"
COMFY_MODEL_KINDS = ("diffusion", "clip", "vae")
COMFY_MODELS_PATH = "/promptforge/models"  # ?kind=diffusion|clip|vae[&refresh=1]
COMFY_INFO_PATH = "/promptforge/info"      # pack version + class list (D25)
# Session 73 extra (D34 / D35 / D37): ComfyUI's own node definitions. Stock
# ComfyUI, not a pack route: the combo values of a widget come from here.
COMFY_OBJECT_INFO_PATH = "/object_info"
COMFY_NODE_CLASS_TYPE_KSAMPLER = "KSampler"
COMFY_NODE_CLASS_TYPE_KSAMPLER_ADVANCED = "KSamplerAdvanced"
# Sampler classes in the order PromptForge reads their lists from and
# counts them for patching (D35: both classes are counted together).
COMFY_SAMPLER_CLASS_TYPES = (COMFY_NODE_CLASS_TYPE_KSAMPLER,
                             COMFY_NODE_CLASS_TYPE_KSAMPLER_ADVANCED)

# ===================== Image Edit / Img2Video pipeline modes (Session 46.1) =====================
# No separate image-input node/class_type: PromptForgeConnection itself
# grew an optional `image` (+ derived `mask`) input/output pair, the
# same "always passes through, nobody's forced to wire it" contract
# negative_prompt already had -- so the existing COMFY_NODE_CLASS_TYPE
# lookup patches `image` directly alongside prompt/seed/width/height/
# negative_prompt. See workers/comfy_worker.py's patch_graph_for_generation.
# Stock ComfyUI endpoint -- the same one its own browser-side LoadImage
# "choose file" button calls. No custom bridge route needed for this.
COMFY_UPLOAD_IMAGE_PATH = "/upload/image"

# Pipeline modes, in the order they appear in the (46.1 bare-minimum)
# mode-switch control: t2i -> i2i -> i2v. Session 46.2 replaces the plain
# button/label with the lightning-bolt-icon + text design; the identifiers
# themselves are the stable, code-facing contract other modules key off.
PIPELINE_MODE_T2I = "t2i"
PIPELINE_MODE_I2I = "i2i"
PIPELINE_MODE_I2V = "i2v"
PIPELINE_MODES = (PIPELINE_MODE_T2I, PIPELINE_MODE_I2I, PIPELINE_MODE_I2V)
PIPELINE_MODE_LABELS = {
    PIPELINE_MODE_T2I: "Text \u2192 Image",
    PIPELINE_MODE_I2I: "Image \u2192 Image",
    PIPELINE_MODE_I2V: "Image \u2192 Video",
}
# Session 48.2: the sidebar mode-switch (replacing Builder's own plain
# "Mode: Text → Image" button) has room for a caption under its icon,
# not a full sentence -- PIPELINE_MODE_LABELS' long form doesn't fit.
PIPELINE_MODE_SHORT_LABELS = {
    PIPELINE_MODE_T2I: "T2I",
    PIPELINE_MODE_I2I: "I2I",
    PIPELINE_MODE_I2V: "I2V",
}
# Session 46.1's library filter: which categories stay visible per
# pipeline mode. i2i/i2v are "editing/animating an uploaded image" --
# none of styles/characters/outfits/scenarios (prompt-construction
# vocabulary for building a scene from scratch) apply once the
# "content" is already an image, only that mode's own Actions and
# Tools categories do. 46.2c split this into a real per-mode mapping
# (i2i -> Image Actions, i2v -> Video Actions instead of both sharing
# "tools"), a revision added an explicit t2i entry (every OTHER
# category, but *not* the other mode's Actions category -- meaningless
# without an input image), and follow-up #3 added each image mode's
# own Tools category alongside its Actions category -- "edit_tools" for
# i2i, "video_tools" for i2v -- since Actions (needs a text instruction)
# and Tools (often just a LoRA + strength, no text at all) are
# genuinely different kinds of entries even within one mode. Every
# mode's set is listed out explicitly rather than computed (e.g.
# "CATEGORIES minus X") so a future unrelated category never silently
# opts itself into a mode's view just by existing.
PIPELINE_MODE_VISIBLE_CATEGORIES = {
    PIPELINE_MODE_T2I: ("styles", "characters", "outfits", "scenarios", "tools"),
    PIPELINE_MODE_I2I: ("image_actions", "edit_tools"),
    PIPELINE_MODE_I2V: ("video_actions", "video_tools"),
}
# How long "🎨 Generate in ComfyUI" briefly disables itself after a click,
# purely to absorb panic double/triple-clicking — NOT related to comfy_busy
# (the button stays usable while a generation is in flight; this only
# guards against the same click landing in the queue several times).
COMFY_QUEUE_DEBOUNCE_MS = 450
# Minimum seconds between live TAESD/latent2rgb preview-frame redraws —
# throttles how often ComfyGenerationWorker emits preview_ready so a fast
# stream of WS preview frames doesn't flood the UI thread with decodes.
COMFY_PREVIEW_MIN_INTERVAL = 0.12
# No app-side cap on how many items can sit in the local queue — ComfyUI's
# own server-side queue has no hard limit either, and is the thing that
# would actually choke first if someone queued an unreasonable number of
# jobs. That's accepted as the user's own problem (see the queue feature
# discussion) rather than something this app second-guesses with an
# arbitrary number.

# Maximum LoRA slots the app UI exposes — must be ≤ LORA_SLOTS in nodes.py.
MAX_LORA_SLOTS = 30
# Sentinel value meaning "slot empty / skip" — must match LORA_NONE in nodes.py.
LORA_NONE_VALUE = "None"
# Allowed strength range — must match LORA_STRENGTH_MIN/MAX in nodes.py.
LORA_STRENGTH_MIN = -16.0
LORA_STRENGTH_MAX = 16.0
# Common resolutions offered in the Builder's ComfyUI panel (width, height).
COMFY_RESOLUTION_PRESETS = [
    ("Square (1024x1024)", 1024, 1024),
    ("Portrait (832x1216)", 832, 1216),
    ("Landscape (1216x832)", 1216, 832),
    ("Portrait (896x1152)", 896, 1152),
    ("Landscape (1152x896)", 1152, 896),
    ("Custom…", None, None),
]

# ===================== Gallery (Task 3) constants =====================
# Square thumbnail budget for each Gallery cell — actual images are fit
# inside this box via Pillow's thumbnail() (aspect ratio preserved, no
# cropping/distortion).
GALLERY_THUMB_SIZE = 256
# Outer footprint of one cell (thumbnail + its own padding) used to work
# out how many columns fit in the current canvas width when the Gallery
# tab is resized.
GALLERY_CELL_OUTER_WIDTH = GALLERY_THUMB_SIZE + 36

# ==========================================================
#                        COLOR THEMES
# ==========================================================
THEMES = {
    "dark": {
        "bg":            "#1e1f26",
        "bg_alt":        "#262830",
        "bg_card":       "#2b2d37",
        "bg_input":      "#1a1b21",
        "fg":            "#e8e9ed",
        "fg_dim":        "#9a9cab",
        "accent":        "#7c8cff",
        "accent_hover":  "#919fff",
        "accent_text":   "#ffffff",
        "border":        "#3a3c48",
        "success":       "#4caf7d",
        "danger":        "#e5645f",
        "danger_hover":  "#f07b76",
        "warn":          "#e0a84e",
        "select_bg":     "#3a3d52",
        "tree_bg":       "#21222a",
        "tree_alt":      "#262832",
    },
    "light": {
        "bg":            "#f4f5f8",
        "bg_alt":        "#ffffff",
        "bg_card":       "#ffffff",
        "bg_input":      "#ffffff",
        "fg":            "#21222b",
        "fg_dim":        "#6b6d7a",
        "accent":        "#5566e8",
        "accent_hover":  "#4453d4",
        "accent_text":   "#ffffff",
        "border":        "#d8dae2",
        "success":       "#2f9d63",
        "danger":        "#d6453f",
        "danger_hover":  "#c43631",
        "warn":          "#c5860f",
        "select_bg":     "#e2e5fb",
        "tree_bg":       "#ffffff",
        "tree_alt":      "#f3f4fa",
    },
}

_NATURAL_SORT_RE = re.compile(r'(\d+)')


def natural_sort_key(s):
    """Sort key that compares embedded numbers numerically instead of
    character-by-character — "Canon 2" before "Canon 10" before
    "Canon 21", not "Canon 1" < "Canon 10" < "Canon 11" ... < "Canon 2"
    the way plain string sorting would put them (see the Canonical
    Outfits sort-order bug report this fixes). Splits the string into
    alternating digit/non-digit runs; digit runs become int for
    comparison, everything else is lowercased for a case-insensitive
    compare exactly like every sort site here already wanted via
    str.lower()/.lower(). Used by every sort of a human-readable library/
    folder/LoRA-path name in the app — not just Canonical Outfits, since
    "Pose 2" vs "Pose 10" in any ordinary category dropdown has the
    identical bug otherwise."""
    return [int(chunk) if chunk.isdigit() else chunk.lower()
            for chunk in _NATURAL_SORT_RE.split(s)]

CATEGORY_LABELS = {
    "styles": "Style",
    "scenarios": "Scenario",
    "characters": "Character",
    "outfits": "Outfit",
    "tools": "Tool",
    "image_actions": "Image Action",
    "video_actions": "Video Action",
    "edit_tools": "Edit Tools",
    "video_tools": "Video Tools",
}

CATEGORY_ICONS = {
    "styles": "🎨",
    "scenarios": "🎬",
    "characters": "🧑",
    "outfits": "👕",
    "tools": "🔧",
    "image_actions": "🖼️",
    "edit_tools": "🛠️",
    "video_tools": "📹",
    "video_actions": "🎞️",
}

PREFIXES = ["First:", "Second:", "Third:", "Fourth:", "Fifth:", "Sixth:", "Seventh:", "Eighth:"]

# Session 55: optional multi-character wrapper for the Standard template.
# One pair per character, around that character's tags + outfit, applied
# only when 2+ characters are selected. `custom` resolves from the two
# string settings instead of a fixed pair; a missing half means "off".
# Kept here (not in main.py) so the Settings combo and the prompt
# assembler cannot drift apart.
CHARACTER_WRAPPER_SETTING = "multi_char_wrapper"
CHARACTER_WRAPPER_PREFIX_SETTING = "multi_char_wrapper_prefix"
CHARACTER_WRAPPER_SUFFIX_SETTING = "multi_char_wrapper_suffix"
CHARACTER_WRAPPER_LABELS = {
    "none": "Off",
    "round": "( … )",
    "square": "[ … ]",
    "pipe": "| … |",
    "custom": "Custom…",
}
CHARACTER_WRAPPER_PRESETS = {
    "none": ("", ""),
    "round": ("(", ")"),
    "square": ("[", "]"),
    "pipe": ("|", "|"),
}


# Display names for the Standard builder's block_order ("Style →
# Characters → Scenario → Tools", and the "Block order..." reorder
# dialog's listbox). Deliberately separate from CATEGORY_LABELS (which
# says "Character"/"Tool", singular, for the Library tab's per-entry
# labels) — block_order keys name a whole SECTION of the builder, where
# the plural "Characters"/"Tools" reads better. Kept as one shared
# constant rather than copy-pasted per use site, since a third copy is
# exactly the kind of thing that quietly goes stale (this used to be two
# separate inline dicts in open_order_dialog and _order_to_text — adding
# "tools" to only one of them would have been an easy, silent mistake).
BLOCK_ORDER_LABELS = {
    "style": "Style",
    "characters": "Characters",
    "scenario": "Scenario",
    "tools": "Tools",
}

INVALID_FS_CHARS = r'[\\/:*?"<>|]'

# Custom template variables are written directly in the template text as
# "[Name 1]", "[Description 2]", "[Outfit 1]", "[Style]", "[Scenario]".
# The number after "Name"/"Description"/"Outfit" ties the variable to a
# specific "template character" (slot) — the same one for all three variable types.
CUSTOM_VAR_PATTERN = re.compile(
    r"\[(Name|Description|Outfit)\s+(\d+)\]|\[(Style)\]|\[(Scenario)\]|\[(Tool)\]")


def sanitize_filename(name: str) -> str:
    """Strips characters that are invalid in file names."""
    return re.sub(INVALID_FS_CHARS, "_", name).strip()
