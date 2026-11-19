"""File I/O, library entry images/metadata, virtual folders, and
library export/import — extracted from PromptForgeApp's methods in the
original Tkinter monolith (promptforgeint.py).

Every function here was previously a method on PromptForgeApp that
read `self.DATA_DIR`, `self._folder_maps`, etc. Converted to standalone
functions that take that state as explicit parameters, per the
migration plan. Two state shapes recur throughout this module and the
callers that will own them in later sessions:

  - `folder_maps`: {category: {entry_name: "folder/path"}}, persisted
    as a single JSON file (LIBRARY_FOLDERS_FILE_NAME under data_dir).
    Functions that touch it (set_entry_folder, remove_entry_folder_entry,
    rename_entry_folder_entry, move_entries_to_folder,
    merge_imported_library) mutate the dict the caller passed in, in
    place, then persist it — exactly like the original mutated
    self._folder_maps in place. The owning tab (LibraryTab, Session 6)
    keeps the dict as its own instance attribute and passes it into
    every call here, the same way the monolith threaded `self` through
    every method.
  - `empty_folders`: {category: set(folder_path)}, session-only, never
    persisted — same lifecycle note as the original's self._empty_folders.

Zero Tkinter/PyQt imports anywhere in this module. Functions that
previously reported failure via `messagebox.showerror`/`showwarning`
now raise one of the exceptions defined below instead; the UI layer
(PyQt) is responsible for catching them and presenting a QMessageBox
with `str(exc)` as the body — this is the one deliberate behavioral
seam in an otherwise verbatim port, since a backend module must not
import a GUI toolkit.
"""
import glob
import json
import math
import os
import shutil
import subprocess
import sys
import uuid
import zipfile

from backend.constants import (
    ACTIVE_ENTRY_ACTIVE,
    ACTIVE_ENTRY_INACTIVE,
    CATEGORIES,
    LORA_PROFILE_DEFAULT_NAME,
    LORA_PROFILE_NAME_MAX_LEN,
    LORA_PROFILES_DEFAULT_KEY,
    LORA_PROFILES_FILE_NAME,
    LORA_SOURCE_DEFAULT,
    LORA_SOURCE_OWN,
    LIBRARY_ACTIVE_OWNER_FILE_TEMPLATE,
    MAX_LORA_PROFILES,
    MODEL_CFG_MAX,
    MODEL_CFG_MIN,
    MODEL_FIELD_CFG,
    MODEL_FIELD_CLIP_TYPE,
    MODEL_FIELD_LORA_SOURCE,
    MODEL_FIELD_SAMPLER,
    MODEL_FIELD_SCHEDULER,
    MODEL_FIELD_STEPS,
    MODEL_FILE_FIELDS,
    MODEL_PRESET_FIELDS,
    MODEL_TEXT_FIELDS,
    MODEL_STEPS_MAX,
    MODEL_STEPS_MIN,
    IMAGE_STORE_EXT,
    LIBRARY_META_EXT,
    LIBRARY_FOLDERS_FILE_NAME,
    LIBRARY_ACTIVE_FILE_NAME,
    FOLDER_PATH_SEP,
    CANONICAL_OUTFITS_FOLDER,
    SOUND_ACTIONS,
    SOUNDS_DIR_NAME,
    VIDEO_EXTENSIONS,
    natural_sort_key,
    sanitize_filename,
)

try:
    from PIL import Image
    PIL_AVAILABLE = True
except Exception:
    Image = None
    PIL_AVAILABLE = False


# ============================================================
#                         EXCEPTIONS
# ============================================================
class FileManagerError(Exception):
    """Raised where the original code called messagebox.showerror for a
    plain file I/O failure (e.g. save_json)."""


class LoraProfileError(Exception):
    """Session 65: raised for an invalid LoRA-profile operation (empty or
    duplicate name, limit reached, unknown id). `str(exc)` is a
    user-presentable sentence; the UI shows it as-is."""


class ImageProcessingError(Exception):
    """Raised where the original code called messagebox.showerror/
    showwarning around process_and_store_image (missing Pillow, no
    name given, unreadable/unsavable image). As of Session 48.4 this
    is also raised by process_and_store_video for the equivalent video
    failures (no name, unreadable/uncopyable source) — one exception
    type, since every existing call site already catches this and
    shows the message via themed_message_box.critical; a second,
    near-identical exception class would just be more to import for
    no behavioral difference."""


class LibraryExportImportError(Exception):
    """Raised for any export/import failure: a bad zip, an unsafe
    zip-slip path, or a plain I/O error while writing/reading the
    archive."""


# ============================================================
#                       APP / DATA PATHS
# ============================================================
def app_dir():
    """Folder that contains the running script, or — when packaged with
    PyInstaller — the folder that contains the .exe. Used to find files
    that must sit next to the program (the icon, the data folder, etc.)
    no matter whether the app is run as a .py file or as a compiled
    executable."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


# ============================================================
#                      PLAIN JSON LOAD/SAVE
# ============================================================
def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default
    return default


def save_json(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        raise FileManagerError(f"Failed to save data: {e}") from e


def init_folders(data_dir, categories):
    """Creates the folder structure if it doesn't exist, and wipes the
    disposable ComfyUI preview cache (_comfy_previews/) — every
    successful generation adds its own result_NNN.<ext> file there
    during a run so the Gallery can show the whole session's history;
    it must not pile up indefinitely or bleed into a fresh session's
    Gallery, hence the wipe on every startup."""
    if not os.path.exists(data_dir):
        os.makedirs(data_dir)
    for cat in categories:
        path = os.path.join(data_dir, cat)
        if not os.path.exists(path):
            os.makedirs(path)

    # Session 37: per-action custom-sound pools always exist, even
    # before the user has uploaded anything for a given action -- see
    # backend/sound_manager.py for how these get populated/resolved.
    for action_key in SOUND_ACTIONS:
        sounds_action_dir = os.path.join(data_dir, SOUNDS_DIR_NAME, action_key)
        if not os.path.exists(sounds_action_dir):
            os.makedirs(sounds_action_dir)

    previews_dir = os.path.join(data_dir, "_comfy_previews")
    if os.path.exists(previews_dir):
        try:
            shutil.rmtree(previews_dir)
        except OSError:
            pass
    try:
        os.makedirs(previews_dir, exist_ok=True)
    except OSError:
        pass


# ============================================================
#                LIBRARY ENTRY IMAGES (Pillow)
# ============================================================
def library_image_path(data_dir, category, name):
    """Path where the entry's image is expected to live, regardless of
    whether the file currently exists."""
    return os.path.join(data_dir, category, f"{name}{IMAGE_STORE_EXT}")


def find_library_image(data_dir, category, name):
    """Returns the on-disk image path for this entry, or None if it has
    no saved image."""
    if not name:
        return None
    path = library_image_path(data_dir, category, name)
    return path if os.path.exists(path) else None


def process_and_store_image(data_dir, source_path, category, name):
    """Converts/resizes the picked image and saves it next to the
    category's text entries, named after the entry itself.

    - Converts to an optimized .jpg (flattened onto white, since JPEG
      has no alpha channel).
    - Proportionally scales so the longest side is IMAGE_MAX_SIDE px;
      never upscales beyond the source resolution.
    - Returns the saved path on success; raises ImageProcessingError on
      failure (caller shows the message via QMessageBox).
    """
    from backend.constants import IMAGE_MAX_SIDE

    if not PIL_AVAILABLE:
        raise ImageProcessingError(
            "Pillow is required to process images.\nInstall it with: pip install Pillow")
    if not name:
        raise ImageProcessingError("Set a name for this entry before attaching an image.")

    try:
        src_img = Image.open(source_path)
        src_img.load()
    except Exception as e:
        raise ImageProcessingError(f"Could not open image:\n{e}") from e

    # Session 49 audit fix: `source_path`'s file handle (`src_img.fp`)
    # was never explicitly closed. `.load()` closes it for most
    # formats once decoding is done, but that's a per-plugin decision,
    # not a guarantee -- and even where it does hold, everything below
    # used to run inside a *second* bare try/except with no `finally`,
    # so an exception on the resize/save path (bad dest permissions,
    # disk full, an odd source mode `.convert()` chokes on) left
    # whatever handle-equivalent state the source image still held
    # dangling on that error path specifically, exactly the case this
    # audit was asked to check for. `with Image.open(...)` isn't used
    # up front because the error message for a failed *open* needs to
    # stay distinct from a failed *save* (existing behavior, kept) --
    # this `finally` gets the same guarantee without merging those.
    try:
        if src_img.mode in ("RGBA", "LA", "P"):
            background = Image.new("RGB", src_img.size, (255, 255, 255))
            rgba = src_img.convert("RGBA")
            background.paste(rgba, mask=rgba.split()[-1])
            img = background
        else:
            img = src_img.convert("RGB")

        w, h = img.size
        longest = max(w, h)
        if longest > IMAGE_MAX_SIDE:
            scale = IMAGE_MAX_SIDE / float(longest)
            new_w = max(int(round(w * scale)), 1)
            new_h = max(int(round(h * scale)), 1)
            img = img.resize((new_w, new_h), Image.LANCZOS)

        cat_dir = os.path.join(data_dir, category)
        if not os.path.exists(cat_dir):
            os.makedirs(cat_dir)

        dest_path = library_image_path(data_dir, category, name)
        img.save(dest_path, "JPEG", quality=90, optimize=True)
        return dest_path
    except Exception as e:
        raise ImageProcessingError(f"Could not save image:\n{e}") from e
    finally:
        src_img.close()


def delete_library_image(data_dir, category, name):
    """Removes the on-disk image for this entry, if any. Silent no-op
    if there isn't one."""
    if not name:
        return
    path = library_image_path(data_dir, category, name)
    if os.path.exists(path):
        try:
            os.remove(path)
        except Exception:
            pass


def rename_library_image(data_dir, category, old_name, new_name):
    """Keeps the image file in sync when an entry is renamed on save."""
    if not old_name or old_name == new_name:
        return
    old_path = library_image_path(data_dir, category, old_name)
    if os.path.exists(old_path):
        new_path = library_image_path(data_dir, category, new_name)
        try:
            if os.path.exists(new_path):
                os.remove(new_path)
            shutil.move(old_path, new_path)
        except Exception:
            pass


# ============================================================
#         LIBRARY ENTRY VIDEOS (Session 48.4)
# ============================================================
# A Library entry can now have a real video attached (not just a
# poster-frame cosmetic fix — see additionalfeatures.md SESSION 48.4
# for the full direction-(a)-vs-(b) writeup). Storage model: the
# video file lives next to the entry's existing {name}.jpg poster,
# named "{name}{ext}" (ext is whatever the source file's own
# extension was — .mp4/.webm/.mov/.mkv/.avi, no re-encoding), and the
# poster .jpg keeps being written through the exact same
# library_image_path()/find_library_image() path every other display
# site (quick-preview, export, duplicate) already uses — so a video
# entry looks, to every one of those call sites, exactly like an
# image entry that happens to also have a video sidecar. Only the
# sites that need to *play* the video (LibraryTab's preview zone) have
# to know videos exist at all; everything else keeps working
# unchanged, per scope item 4 in the additionalfeatures.md writeup.
# The sidecar meta JSON's "video_ext" field (see save_library_meta
# above) is the single source of truth for "does this entry have a
# video, and what's its extension" — not a directory scan, so a
# leftover video file from a deleted/renamed entry is never
# accidentally picked up for a different one.
def library_video_path(data_dir, category, name, ext):
    """Path where the entry's video is expected to live, given the
    extension recorded in its meta sidecar. Regardless of whether the
    file currently exists, same contract as library_image_path()."""
    return os.path.join(data_dir, category, f"{name}{ext}")


def find_library_video(data_dir, category, name):
    """Returns the on-disk video path for this entry, or None if it has
    no attached video (or the meta sidecar points at a file that isn't
    actually there anymore). Mirrors find_library_image()'s contract."""
    if not name:
        return None
    meta = load_library_meta(data_dir, category, name)
    ext = meta.get("video_ext")
    if not ext:
        return None
    path = library_video_path(data_dir, category, name, ext)
    return path if os.path.exists(path) else None


def process_and_store_video(data_dir, source_path, category, name):
    """Copies the picked/dropped video file next to the category's
    text entries, named after the entry itself (same naming scheme as
    process_and_store_image, just with the source's own extension
    instead of a forced .jpg re-encode — there's no equivalent-quality
    reason to transcode a video the way a resize/re-compress makes
    sense for a still image).

    Does NOT touch the meta sidecar or generate the poster frame —
    those are the caller's job (LibraryTab), since the poster grab
    needs a live Qt event loop (PosterFrameGrabber/QMediaPlayer) that
    has no business living in this Qt-free backend module.

    Returns (dest_path, ext) on success; raises ImageProcessingError
    on failure (missing name, unrecognized extension, or a plain
    copy failure), same as process_and_store_image."""
    if not name:
        raise ImageProcessingError("Set a name for this entry before attaching a video.")
    if not source_path or not os.path.exists(source_path):
        raise ImageProcessingError(f"Could not open video:\n{source_path}")

    ext = os.path.splitext(source_path)[1].lower()
    if ext not in VIDEO_EXTENSIONS:
        raise ImageProcessingError(
            f"\"{os.path.basename(source_path)}\" isn't a supported video type.")

    try:
        cat_dir = os.path.join(data_dir, category)
        if not os.path.exists(cat_dir):
            os.makedirs(cat_dir)

        # Drop any previously-attached video for this entry first, in
        # case it had a different extension than the new one (e.g.
        # swapping a .mp4 attachment for a .webm one) -- otherwise
        # both would sit on disk with only the meta sidecar's video_ext
        # pointing at the new one, leaking the old file forever.
        delete_library_video(data_dir, category, name)

        dest_path = library_video_path(data_dir, category, name, ext)
        shutil.copyfile(source_path, dest_path)
        return dest_path, ext
    except ImageProcessingError:
        raise
    except Exception as e:
        raise ImageProcessingError(f"Could not save video:\n{e}") from e


def delete_library_video(data_dir, category, name):
    """Removes the on-disk video for this entry, if any -- looked up
    via the meta sidecar's video_ext (not a directory scan), so this
    is a silent no-op for an entry that never had one. Does NOT touch
    the meta sidecar itself or the poster .jpg -- callers that mean
    "detach the video entirely" should also clear video_ext via
    save_library_meta; callers that mean "about to replace it with a
    different one" (process_and_store_video above) don't."""
    if not name:
        return
    path = find_library_video(data_dir, category, name)
    if path and os.path.exists(path):
        try:
            os.remove(path)
        except Exception:
            pass


def rename_library_video(data_dir, category, old_name, new_name):
    """Keeps the video file in sync when an entry is renamed on save --
    mirrors rename_library_image()/rename_library_meta(). Must be
    called before rename_library_meta() moves the sidecar (it reads
    the *old* name's meta to find the video's current extension)."""
    if not old_name or old_name == new_name:
        return
    old_video = find_library_video(data_dir, category, old_name)
    if not old_video:
        return
    ext = os.path.splitext(old_video)[1]
    new_path = library_video_path(data_dir, category, new_name, ext)
    try:
        if os.path.exists(new_path):
            os.remove(new_path)
        shutil.move(old_video, new_path)
    except Exception:
        pass


# ============================================================
#         LIBRARY ENTRY METADATA (source_url / lora / force_first)
# ============================================================
# Stored as a small sidecar JSON file named after the entry, exactly
# like the image sidecar above ({name}{IMAGE_STORE_EXT}), so it follows
# the same rename/duplicate/delete lifecycle without needing a separate
# top-level JSON file to keep in sync with the on-disk .txt files.
def library_meta_path(data_dir, category, name):
    return os.path.join(data_dir, category, f"{name}{LIBRARY_META_EXT}")


def load_library_meta(data_dir, category, name):
    """Returns {"source_url": str|None, "lora": str|None,
    "lora_strength": float, "force_first": bool} for this entry.
    Missing/corrupt sidecar -> no link, no binding, strength 1.0,
    force_first=False.

    force_first only has any effect for the "tools" category (see
    backend.prompt_builder._build_tools_block) — a Tool entry with this
    set and a non-empty tags/content is pulled out of the normal
    block_order position and always placed at the very start of the
    assembled prompt, ahead of Style/Characters/Scenario, so a tag like
    "@fixedanatomy" reaches the model before anything else can be
    conditioned around it. It's stored generically here rather than
    gated to "tools" at the sidecar level, same as source_url/lora
    already are, since nothing stops some future category from wanting
    the same knob.

    lora_strength (Session 30): the entry's own per-LoRA strength,
    editable directly on the Library card next to Assign/Clear. This is
    the entry's stored preference, independent from whatever value a
    Builder LoRA slot currently shows — Builder's autofill
    (backend.prompt_builder.compute_lora_autofill) reads this as the
    *initial* value for a freshly-created auto slot, but once that slot
    exists in Builder its strength is edited there like any other slot
    and isn't written back here. Defaults to 1.0, same default the
    LoRA sidebar itself has always used for a brand-new slot.

    display_alias (Session 56): an optional human-readable label for a
    canon outfit, or None. It is display-only — the real
    "Character_Canon_N" name stays the key. Legacy sidecars without the
    key load as None.

    variation_of / variation_label (Session 58): a character variation
    stores the parent character's entry name and an optional display
    label here. Both are None for a normal entry, so every legacy
    sidecar keeps loading exactly as before. The link is the key; the
    file name stays "<Parent>__V<n>" and the label never renames it."""
    # loras (Session 65): extra per-profile bindings,
    # {profile_id: {"lora": path, "strength": float}}. {} for a legacy
    # sidecar. The Default profile is NOT in here: it is the `lora` /
    # `lora_strength` pair above.
    empty = {"source_url": None, "lora": None, "lora_strength": 1.0, "force_first": False,
             "video_ext": None, "display_alias": None,
             "variation_of": None, "variation_label": None, "loras": {}}
    if not name:
        return empty
    path = library_meta_path(data_dir, category, name)
    if not os.path.exists(path):
        return empty
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return empty
        try:
            strength = float(data.get("lora_strength", 1.0))
        except (TypeError, ValueError):
            strength = 1.0
        display_alias = data.get("display_alias")
        if display_alias is not None:
            # Tolerate a hand-edited sidecar: an alias is always text or
            # nothing, never a number/bool leaking into QLineEdit.
            display_alias = str(display_alias).strip() or None
        variation_of = data.get("variation_of")
        if variation_of is not None:
            variation_of = str(variation_of).strip() or None
        variation_label = data.get("variation_label")
        if variation_label is not None:
            variation_label = str(variation_label).strip() or None
        video_ext = data.get("video_ext") or None
        if video_ext and video_ext not in VIDEO_EXTENSIONS:
            # Sidecar edited by hand or from a future version with a
            # format we don't recognize -- ignore rather than trust it
            # blindly, same "don't crash on a weird file" spirit as
            # process_and_store_video's own extension check below.
            video_ext = None
        return {
            "source_url": data.get("source_url") or None,
            "lora": data.get("lora") or None,
            "lora_strength": strength,
            "force_first": bool(data.get("force_first", False)),
            "video_ext": video_ext,
            "display_alias": display_alias,
            "variation_of": variation_of,
            "variation_label": variation_label,
            "loras": _normalize_loras(data.get("loras")),
        }
    except Exception:
        return empty


_META_ALIAS_UNSET = object()
_META_VARIATION_UNSET = object()
_META_LORAS_UNSET = object()


def _normalize_loras(raw):
    """Session 65: tolerant parse of the sidecar's `loras` value.

    Anything malformed (not a dict, blank id, non-dict payload, missing
    or non-text path) is dropped; a bad strength becomes 1.0. Unknown
    profile ids are KEPT here (they may belong to a profile that has not
    been imported yet) and are ignored by the resolvers instead."""
    result = {}
    if not isinstance(raw, dict):
        return result
    for pid, payload in raw.items():
        if not isinstance(pid, str) or not pid.strip():
            continue
        if not isinstance(payload, dict):
            continue
        path = payload.get("lora")
        if not isinstance(path, str) or not path.strip():
            continue
        try:
            strength = float(payload.get("strength", 1.0))
        except (TypeError, ValueError):
            strength = 1.0
        if not math.isfinite(strength):
            strength = 1.0
        result[pid.strip()] = {"lora": path, "strength": strength}
    return result


def save_library_meta(data_dir, category, name, source_url=None, lora=None,
                       lora_strength=1.0, force_first=False, video_ext=None,
                       display_alias=_META_ALIAS_UNSET,
                       variation_of=_META_VARIATION_UNSET,
                       variation_label=_META_VARIATION_UNSET,
                       loras=_META_LORAS_UNSET):
    """Writes the sidecar JSON, or removes it if every field ends up
    empty/default (so entries with nothing special don't grow a stray
    file). lora_strength only keeps the sidecar alive on its own if it's
    been moved off the 1.0 default while a LoRA is actually bound —
    an un-bound entry's leftover strength number isn't worth a file.

    video_ext (Session 48.4): the extension (e.g. ".mp4") of the video
    file stored alongside this entry's poster .jpg at
    library_video_path(), or None for an entry with no video attached.
    Kept in the same sidecar as source_url/lora rather than a separate
    file, for the same reason those already live here — one JSON per
    entry to keep in sync through rename/duplicate/delete/export,
    instead of two.

    display_alias (Session 56): an optional human-readable label for a
    canon outfit (e.g. "Office Suit") shown in Library/Builder while
    the real "Character_Canon_N" name stays the key. It never renames
    the file. This parameter uses a sentinel default on purpose: every
    existing caller that saves source_url/lora/video_ext without
    mentioning the alias must PRESERVE whatever alias is already
    stored. Passing display_alias="" (or None) explicitly clears it.

    variation_of / variation_label (Session 58): the character variation
    link and its display label. Both use the same sentinel rule as
    display_alias — omitting a parameter preserves the stored value,
    while passing ""/None clears it. A variation keeps the real file
    name "<Parent>__V<n>"; the label is display-only.

    loras (Session 65): the extra per-profile LoRA bindings,
    {profile_id: {"lora": path, "strength": float}}. Same sentinel rule:
    OMITTING it preserves what is stored (so every pre-existing caller
    that only knows lora/lora_strength cannot erase it), passing {} or
    None clears it. The Default profile is not stored here."""
    if not name:
        return
    try:
        strength = float(lora_strength) if lora_strength is not None else 1.0
    except (TypeError, ValueError):
        strength = 1.0
    preserve_alias = display_alias is _META_ALIAS_UNSET
    preserve_variation_of = variation_of is _META_VARIATION_UNSET
    preserve_variation_label = variation_label is _META_VARIATION_UNSET
    preserve_loras = loras is _META_LORAS_UNSET
    if (preserve_alias or preserve_variation_of or preserve_variation_label
            or preserve_loras):
        existing = load_library_meta(data_dir, category, name)
    else:
        existing = {}
    if preserve_alias:
        display_alias = existing.get("display_alias")
    else:
        display_alias = str(display_alias).strip() if display_alias else None
    if preserve_variation_of:
        variation_of = existing.get("variation_of")
    else:
        variation_of = str(variation_of).strip() if variation_of else None
    if preserve_variation_label:
        variation_label = existing.get("variation_label")
    else:
        variation_label = str(variation_label).strip() if variation_label else None
    if preserve_loras:
        loras = existing.get("loras") or {}
    else:
        loras = _normalize_loras(loras)
    if (not source_url and not lora and not force_first and strength == 1.0
            and not video_ext and not display_alias
            and not variation_of and not variation_label and not loras):
        delete_library_meta(data_dir, category, name)
        return
    path = library_meta_path(data_dir, category, name)
    try:
        cat_dir = os.path.join(data_dir, category)
        if not os.path.exists(cat_dir):
            os.makedirs(cat_dir)
        with open(path, "w", encoding="utf-8") as f:
            payload = {"source_url": source_url or None, "lora": lora or None,
                       "lora_strength": strength,
                       "force_first": bool(force_first),
                       "video_ext": video_ext or None,
                       "display_alias": display_alias or None,
                       "variation_of": variation_of or None,
                       "variation_label": variation_label or None}
            if loras:
                # Written only when present, so a library that never uses
                # profiles keeps byte-identical sidecars.
                payload["loras"] = loras
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def delete_library_meta(data_dir, category, name):
    if not name:
        return
    path = library_meta_path(data_dir, category, name)
    if os.path.exists(path):
        try:
            os.remove(path)
        except Exception:
            pass


def rename_library_meta(data_dir, category, old_name, new_name):
    """Keeps the metadata sidecar in sync when an entry is renamed,
    mirroring rename_library_image above."""
    if not old_name or old_name == new_name:
        return
    old_path = library_meta_path(data_dir, category, old_name)
    if os.path.exists(old_path):
        new_path = library_meta_path(data_dir, category, new_name)
        try:
            if os.path.exists(new_path):
                os.remove(new_path)
            shutil.move(old_path, new_path)
        except Exception:
            pass


def update_library_meta(data_dir, category, name, **changes):
    """Session 58: read-modify-write the sidecar for a single field
    change without having to restate every other field. `save_library_meta`
    defaults most parameters to None, so calling it directly to change
    one key would silently clear the rest; this helper loads the full
    record first and passes every field back explicitly.

    Only known meta keys are accepted; unknown keyword names are
    ignored so a typo cannot create a stray key on disk."""
    meta = load_library_meta(data_dir, category, name)
    known = ("source_url", "lora", "lora_strength", "force_first",
             "video_ext", "display_alias", "variation_of", "variation_label",
             "loras")
    for key, value in changes.items():
        if key in known:
            meta[key] = value
    save_library_meta(
        data_dir, category, name,
        source_url=meta.get("source_url"),
        lora=meta.get("lora"),
        lora_strength=meta.get("lora_strength", 1.0),
        force_first=meta.get("force_first", False),
        video_ext=meta.get("video_ext"),
        display_alias=meta.get("display_alias"),
        variation_of=meta.get("variation_of"),
        variation_label=meta.get("variation_label"),
        loras=meta.get("loras") or {},
    )


# ============================================================
#         LORA PROFILES (Session 65)
# ============================================================
# Design (see Plan_Sessions_65-68): the implicit Default profile is the
# entry's original `lora`/`lora_strength`; each extra profile is a
# stable-id key in the sidecar's `loras` dict. Resolution is STRICT:
# asking for profile P never falls back to Default (a LoRA trained for
# another base model is worse than a visible gap). Variations resolve per
# profile: own binding for P, else the parent's binding for P.
def lora_profiles_path(data_dir):
    return os.path.join(data_dir, LORA_PROFILES_FILE_NAME)


def _clean_profile_name(name):
    return " ".join(str(name or "").split())


def _sanitize_model_text(value):
    """Model file fields are ComfyUI names (str). Anything else loads as
    empty so a hand-edited file cannot leak a number into a combo."""
    return value.strip() if isinstance(value, str) else ""


def _sanitize_steps(value):
    """Session 69: tolerant Steps parser. None/invalid -> None (empty =
    "from workflow", D15/D29); numeric values are clamped to the sane
    range. Booleans are not numbers here (JSON `true` is not a step
    count)."""
    if value is None or isinstance(value, bool):
        return None
    try:
        num = float(value.strip() if isinstance(value, str) else value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(num) or not num.is_integer():
        return None
    return max(MODEL_STEPS_MIN, min(MODEL_STEPS_MAX, int(num)))


def _sanitize_cfg(value):
    """Session 69: tolerant CFG parser. None/invalid -> None; values are
    clamped. CFG may be fractional (D29)."""
    if value is None or isinstance(value, bool):
        return None
    try:
        num = float(value.strip() if isinstance(value, str) else value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(num):
        return None
    return max(MODEL_CFG_MIN, min(MODEL_CFG_MAX, num))


def _sanitize_lora_source(value, own_id=None):
    """"own"/"default" (case-insensitive) or a model id. ""/garbage ->
    "own". A self-reference is normalised to "own" (no cycles, D16)."""
    text = value.strip() if isinstance(value, str) else ""
    if not text:
        return LORA_SOURCE_OWN
    lowered = text.casefold()
    if lowered == LORA_SOURCE_OWN:
        return LORA_SOURCE_OWN
    if lowered == LORA_SOURCE_DEFAULT:
        return LORA_SOURCE_DEFAULT
    if own_id is not None and text == own_id:
        return LORA_SOURCE_OWN
    return text


def _normalize_default_preset(raw):
    """Session 69 (D14): the Default preset stores only the shared preset
    fields. Unknown keys are kept (they may belong to a future version)."""
    record = dict(raw) if isinstance(raw, dict) else {}
    record.pop("id", None)
    record.pop("name", None)
    record.pop(MODEL_FIELD_LORA_SOURCE, None)
    for field in MODEL_TEXT_FIELDS:
        record[field] = _sanitize_model_text(record.get(field))
    record[MODEL_FIELD_STEPS] = _sanitize_steps(record.get(MODEL_FIELD_STEPS))
    record[MODEL_FIELD_CFG] = _sanitize_cfg(record.get(MODEL_FIELD_CFG))
    return record


def _preset_fields_payload(record):
    """Only the meaningful preset keys of `record`, in a deterministic
    order. Empty/None fields are omitted so a library that never uses
    presets keeps a byte-identical _lora_profiles.json."""
    payload = {}
    for key, value in record.items():
        if key in ("id", "name") or key in MODEL_PRESET_FIELDS:
            continue
        if key == MODEL_FIELD_LORA_SOURCE:
            continue
        payload[key] = value
    for field in MODEL_TEXT_FIELDS:
        text = _sanitize_model_text(record.get(field))
        if text:
            payload[field] = text
    steps = _sanitize_steps(record.get(MODEL_FIELD_STEPS))
    if steps is not None:
        payload[MODEL_FIELD_STEPS] = steps
    cfg = _sanitize_cfg(record.get(MODEL_FIELD_CFG))
    if cfg is not None:
        payload[MODEL_FIELD_CFG] = cfg
    return payload


def _normalize_profile_record(item):
    """One tolerant profile record (id/name + preset fields + unknown
    keys preserved). Returns None for an unusable row."""
    if not isinstance(item, dict):
        return None
    pid = item.get("id")
    name = _clean_profile_name(item.get("name"))
    if not isinstance(pid, str) or not pid.strip() or not name:
        return None
    pid = pid.strip()
    record = dict(item)
    record["id"] = pid
    record["name"] = name
    for field in MODEL_TEXT_FIELDS:
        record[field] = _sanitize_model_text(item.get(field))
    record[MODEL_FIELD_STEPS] = _sanitize_steps(item.get(MODEL_FIELD_STEPS))
    record[MODEL_FIELD_CFG] = _sanitize_cfg(item.get(MODEL_FIELD_CFG))
    record[MODEL_FIELD_LORA_SOURCE] = _sanitize_lora_source(
        item.get(MODEL_FIELD_LORA_SOURCE), own_id=pid)
    return record


def _read_model_document(path):
    """Session 69: the full tolerant read of _lora_profiles.json.

    Returns (records, default_preset, extra_top_level_keys). Accepts the
    bare-list file written by Session 65-68 and the {"profiles": [...],
    "default": {...}} shape. Malformed rows/values are dropped or
    clamped; unknown keys (per model and top-level) are preserved so a
    newer version's data survives an older build."""
    raw = load_json(path, [])
    if isinstance(raw, dict):
        items = raw.get("profiles")
        default_raw = raw.get(LORA_PROFILES_DEFAULT_KEY)
        extra_top = {key: value for key, value in raw.items()
                     if key not in ("profiles", LORA_PROFILES_DEFAULT_KEY)}
    else:
        items = raw
        default_raw = None
        extra_top = {}
    records = []
    seen = set()
    if not isinstance(items, list):
        items = []
    for item in items:
        record = _normalize_profile_record(item)
        if record is None or record["id"] in seen:
            continue
        seen.add(record["id"])
        records.append(record)
    return records, _normalize_default_preset(default_raw), extra_top


def _write_model_document(path, records, default_preset, extra_top):
    """Writes the document, omitting empty preset fields and removing
    the file entirely when nothing is stored (the pre-Session-69
    behaviour for a library without models)."""
    items = []
    for record in records:
        item = {"id": record["id"], "name": record["name"]}
        item.update(_preset_fields_payload(record))
        source = record.get(MODEL_FIELD_LORA_SOURCE) or LORA_SOURCE_OWN
        if source != LORA_SOURCE_OWN:
            item[MODEL_FIELD_LORA_SOURCE] = source
        items.append(item)
    default_payload = _preset_fields_payload(default_preset or {})
    if not items and not default_payload and not extra_top:
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            pass
        return
    document = dict(extra_top)
    document["profiles"] = items
    if default_payload:
        document[LORA_PROFILES_DEFAULT_KEY] = default_payload
    save_json(path, document)


def _read_lora_profiles_file(path):
    """Tolerant read of a profiles file: accepts a bare list or
    {"profiles": [...]}, skips malformed rows and duplicate ids.
    Returns just the id/name pairs (the long-standing public shape)."""
    records, _default, _extra = _read_model_document(path)
    return [{"id": record["id"], "name": record["name"]} for record in records]


def load_lora_profiles(data_dir):
    """Ordered list of {"id", "name"} for the EXTRA profiles (the
    implicit Default is never in this list). Missing/corrupt file -> []."""
    return _read_lora_profiles_file(lora_profiles_path(data_dir))


def save_lora_profiles(data_dir, profiles):
    """Persists the list, preserving each existing model's preset fields
    and any unknown keys. An empty list removes the file only when there
    is no Default preset either, so a library that never uses models
    stays exactly as it was.

    Callers may pass plain {"id", "name"} rows (the pre-Session-69 shape)
    or full records; whatever a row carries is merged over what is
    already stored."""
    path = lora_profiles_path(data_dir)
    existing_records, default_preset, extra_top = _read_model_document(path)
    existing = {record["id"]: record for record in existing_records}
    merged = []
    for profile in profiles or []:
        if not isinstance(profile, dict):
            continue
        pid = profile.get("id")
        if not isinstance(pid, str) or not pid.strip():
            continue
        pid = pid.strip()
        record = dict(existing.get(pid, {}))
        record.update(profile)
        record["id"] = pid
        name = _clean_profile_name(record.get("name"))
        if not name:
            continue
        record["name"] = name
        for field in MODEL_TEXT_FIELDS:
            record[field] = _sanitize_model_text(record.get(field))
        record[MODEL_FIELD_STEPS] = _sanitize_steps(record.get(MODEL_FIELD_STEPS))
        record[MODEL_FIELD_CFG] = _sanitize_cfg(record.get(MODEL_FIELD_CFG))
        record[MODEL_FIELD_LORA_SOURCE] = _sanitize_lora_source(
            record.get(MODEL_FIELD_LORA_SOURCE), own_id=pid)
        merged.append(record)
    _write_model_document(path, merged, default_preset, extra_top)


def _load_model_records(data_dir):
    return _read_model_document(lora_profiles_path(data_dir))


def _find_model_record(records, profile_id):
    return next((record for record in records if record["id"] == profile_id), None)


def _resolve_owner_from_records(records, record):
    """Session 69 (D16/D17): the id of the list `record` uses, or None
    for Default. No chains: a source must itself be "own", otherwise
    (unknown id, dangling import, hand-edited chain) it falls back to
    Default instead of looping."""
    source = record.get(MODEL_FIELD_LORA_SOURCE) or LORA_SOURCE_OWN
    if source == LORA_SOURCE_OWN:
        return record["id"]
    if source == LORA_SOURCE_DEFAULT:
        return None
    target = _find_model_record(records, source)
    if target is None:
        return None
    if (target.get(MODEL_FIELD_LORA_SOURCE) or LORA_SOURCE_OWN) != LORA_SOURCE_OWN:
        return None
    return target["id"]


def resolve_list_owner(data_dir, profile_id):
    """Session 69 (D17): which list — Default (None) or an own-list model
    id — `profile_id` stores and reads its LoRA bindings and Active map
    at. Default/unknown -> None, so a deleted or never-imported model
    degrades to Default instead of erroring during a generation."""
    if not profile_id:
        return None
    records, _default, _extra = _load_model_records(data_dir)
    record = _find_model_record(records, profile_id)
    if record is None:
        return None
    return _resolve_owner_from_records(records, record)


def list_dependents(data_dir, profile_id):
    """Models whose LoRA list is `profile_id` (Default when None), as
    [{"id", "name"}]. Used by the D16 guard ("a source cannot switch
    away from own") and by delete confirmation counts."""
    records, _default, _extra = _load_model_records(data_dir)
    pid = profile_id or None
    if pid is not None and _find_model_record(records, pid) is None:
        return []
    return [{"id": record["id"], "name": record["name"]}
            for record in records
            if record["id"] != pid and _resolve_owner_from_records(records, record) == pid]


def own_list_profile_ids(data_dir):
    """Session 69 (D9): ids of the models that have their own LoRA list.
    Together with Default (None) these are the lists "in use"; a model
    sharing another list is dormant (D18) and is not included."""
    records, _default, _extra = _load_model_records(data_dir)
    return [record["id"] for record in records
            if (record.get(MODEL_FIELD_LORA_SOURCE) or LORA_SOURCE_OWN)
            == LORA_SOURCE_OWN]


def _canonical_source_choice(records, profile_id, source):
    """Validates a lora_source value for a model and returns the
    canonical form ("own", "default" or an own-list model id). Raises
    LoraProfileError with a user-presentable sentence."""
    if profile_id is None:
        raise LoraProfileError("Default is always its own list.")
    if source is None:
        return LORA_SOURCE_OWN
    text = source.strip() if isinstance(source, str) else ""
    lowered = text.casefold()
    if not text or lowered == LORA_SOURCE_OWN:
        return LORA_SOURCE_OWN
    if lowered == LORA_SOURCE_DEFAULT:
        return LORA_SOURCE_DEFAULT
    if text == profile_id:
        raise LoraProfileError("A model cannot share its own list.")
    target = _find_model_record(records, text)
    if target is None:
        raise LoraProfileError("That model no longer exists.")
    if (target.get(MODEL_FIELD_LORA_SOURCE) or LORA_SOURCE_OWN) != LORA_SOURCE_OWN:
        raise LoraProfileError(
            "A model can only share the list of Default or of a model that has its own list.")
    return target["id"]


def _ensure_can_leave_own(records, profile_id, new_source):
    """D16: a model other models share cannot switch away from "own"."""
    if new_source == LORA_SOURCE_OWN:
        return
    record = _find_model_record(records, profile_id)
    if record is None:
        return
    if (record.get(MODEL_FIELD_LORA_SOURCE) or LORA_SOURCE_OWN) != LORA_SOURCE_OWN:
        return
    dependents = [other["name"] for other in records
                  if other["id"] != profile_id
                  and _resolve_owner_from_records(records, other) == profile_id]
    if dependents:
        names = ", ".join(f'"{name}"' for name in dependents)
        raise LoraProfileError(
            f'"{record["name"]}" is used as the LoRA list source by {names}. '
            "Switch those models to another list first.")


def get_model_preset(data_dir, profile_id=None):
    """Session 69 (D13/D14): one model as a fully-resolved preset dict.

    `profile_id` None/"" is Default. Unknown ids raise LoraProfileError.
    `list_owner` is the id whose LoRA list and Active map apply (None =
    Default), `list_owner_name` its display name."""
    records, default_preset, _extra = _load_model_records(data_dir)
    if not profile_id:
        return {
            "id": None, "name": LORA_PROFILE_DEFAULT_NAME, "is_default": True,
            "diffusion_model": default_preset.get(MODEL_FILE_FIELDS[0], ""),
            "clip": default_preset.get(MODEL_FILE_FIELDS[1], ""),
            "vae": default_preset.get(MODEL_FILE_FIELDS[2], ""),
            "clip_type": default_preset.get(MODEL_FIELD_CLIP_TYPE, ""),
            "sampler": default_preset.get(MODEL_FIELD_SAMPLER, ""),
            "scheduler": default_preset.get(MODEL_FIELD_SCHEDULER, ""),
            "steps": default_preset.get(MODEL_FIELD_STEPS),
            "cfg": default_preset.get(MODEL_FIELD_CFG),
            "lora_source": LORA_SOURCE_OWN,
            "list_owner": None,
            "list_owner_name": LORA_PROFILE_DEFAULT_NAME,
        }
    record = _find_model_record(records, profile_id)
    if record is None:
        raise LoraProfileError("That model no longer exists.")
    owner_id = _resolve_owner_from_records(records, record)
    owner_name = LORA_PROFILE_DEFAULT_NAME
    if owner_id is not None:
        owner = _find_model_record(records, owner_id)
        owner_name = owner["name"] if owner else LORA_PROFILE_DEFAULT_NAME
    return {
        "id": record["id"], "name": record["name"], "is_default": False,
        "diffusion_model": record.get(MODEL_FILE_FIELDS[0], ""),
        "clip": record.get(MODEL_FILE_FIELDS[1], ""),
        "vae": record.get(MODEL_FILE_FIELDS[2], ""),
        "clip_type": record.get(MODEL_FIELD_CLIP_TYPE, ""),
        "sampler": record.get(MODEL_FIELD_SAMPLER, ""),
        "scheduler": record.get(MODEL_FIELD_SCHEDULER, ""),
        "steps": record.get(MODEL_FIELD_STEPS),
        "cfg": record.get(MODEL_FIELD_CFG),
        "lora_source": record.get(MODEL_FIELD_LORA_SOURCE) or LORA_SOURCE_OWN,
        "list_owner": owner_id,
        "list_owner_name": owner_name,
    }


def update_lora_profile_fields(data_dir, profile_id, **fields):
    """Session 69: sets any of the preset fields on one model (or on the
    Default preset when `profile_id` is None) and returns the resolved
    preset. Unknown keyword names are ignored; values are sanitised by
    the same tolerant parser the loader uses. `lora_source` goes through
    the D16 rules and raises LoraProfileError when invalid."""
    path = lora_profiles_path(data_dir)
    records, default_preset, extra_top = _read_model_document(path)
    if profile_id:
        record = _find_model_record(records, profile_id)
        if record is None:
            raise LoraProfileError("That model no longer exists.")
        target = record
    else:
        target = default_preset
    if MODEL_FIELD_LORA_SOURCE in fields:
        if profile_id is None:
            raise LoraProfileError("Default is always its own list.")
        new_source = _canonical_source_choice(
            records, profile_id, fields[MODEL_FIELD_LORA_SOURCE])
        _ensure_can_leave_own(records, profile_id, new_source)
        target[MODEL_FIELD_LORA_SOURCE] = new_source
    for field in MODEL_TEXT_FIELDS:
        if field in fields:
            target[field] = _sanitize_model_text(fields[field])
    if MODEL_FIELD_STEPS in fields:
        target[MODEL_FIELD_STEPS] = _sanitize_steps(fields[MODEL_FIELD_STEPS])
    if MODEL_FIELD_CFG in fields:
        target[MODEL_FIELD_CFG] = _sanitize_cfg(fields[MODEL_FIELD_CFG])
    _write_model_document(path, records, default_preset, extra_top)
    return get_model_preset(data_dir, profile_id)


def set_lora_source(data_dir, profile_id, source):
    """Session 69 (D16/D18): points a model's LoRA list at "own",
    "default" or another own-list model and returns the counts the
    confirmation needs:

        {"lora_source", "list_owner", "entries_with_bindings", "active_entries"}

    Bindings and the per-list Active map are never deleted, so switching
    back to "own" restores both (D18). Leaving "own" while other models
    depend on this list is refused."""
    path = lora_profiles_path(data_dir)
    records, default_preset, extra_top = _read_model_document(path)
    target = _find_model_record(records, profile_id)
    if target is None:
        raise LoraProfileError("That model no longer exists.")
    new_source = _canonical_source_choice(records, profile_id, source)
    _ensure_can_leave_own(records, profile_id, new_source)
    entries_with_bindings = len(lora_profile_binding_entries(data_dir, profile_id))
    active_entries = _count_explicit_active_states(data_dir, profile_id)
    target[MODEL_FIELD_LORA_SOURCE] = new_source
    _write_model_document(path, records, default_preset, extra_top)
    if new_source == LORA_SOURCE_OWN:
        owner_id = profile_id
    elif new_source == LORA_SOURCE_DEFAULT:
        owner_id = None
    else:
        owner_id = new_source
    return {
        "lora_source": new_source,
        "list_owner": owner_id,
        "entries_with_bindings": entries_with_bindings,
        "active_entries": active_entries,
    }


def duplicate_lora_profile(data_dir, profile_id):
    """Session 69 (D31): copies a model's preset fields and lora_source
    under a unique "<name> copy" name. Bindings and the Active map are
    per-list data and are deliberately not copied."""
    path = lora_profiles_path(data_dir)
    records, default_preset, extra_top = _read_model_document(path)
    target = _find_model_record(records, profile_id)
    if target is None:
        raise LoraProfileError("That model no longer exists.")
    if len(records) >= MAX_LORA_PROFILES:
        raise LoraProfileError(
            f"At most {MAX_LORA_PROFILES} models can be added.")
    taken = {record["name"].casefold() for record in records}
    taken.add(LORA_PROFILE_DEFAULT_NAME.casefold())
    base_name = f'{target["name"]} copy'
    name = base_name
    n = 2
    while name.casefold() in taken:
        name = f"{base_name} {n}"
        n += 1
    record = dict(target)
    record["id"] = new_lora_profile_id(record["id"] for record in records)
    record["name"] = name
    records.append(record)
    _write_model_document(path, records, default_preset, extra_top)
    return {"id": record["id"], "name": name}


def new_lora_profile_id(existing_ids=()):
    """Short random hex id, unique among `existing_ids`."""
    taken = set(existing_ids)
    while True:
        pid = uuid.uuid4().hex[:6]
        if pid not in taken:
            return pid


def _validate_profile_name(name, profiles, default_name, own_id=None):
    name = _clean_profile_name(name)
    if not name:
        raise LoraProfileError("Enter a name for the model.")
    if len(name) > LORA_PROFILE_NAME_MAX_LEN:
        raise LoraProfileError(
            f"The model name is too long (max {LORA_PROFILE_NAME_MAX_LEN} characters).")
    taken = {_clean_profile_name(default_name or LORA_PROFILE_DEFAULT_NAME).casefold()}
    taken.update(p["name"].casefold() for p in profiles if p["id"] != own_id)
    if name.casefold() in taken:
        raise LoraProfileError(f'A model named "{name}" already exists.')
    return name


def add_lora_profile(data_dir, name, default_name=LORA_PROFILE_DEFAULT_NAME):
    """Adds a profile and returns {"id", "name"}. Raises LoraProfileError
    for an empty/duplicate/too-long name or when MAX_LORA_PROFILES is
    reached. `default_name` is the Default profile's display name, which
    new names may not clash with."""
    profiles = load_lora_profiles(data_dir)
    if len(profiles) >= MAX_LORA_PROFILES:
        raise LoraProfileError(
            f"At most {MAX_LORA_PROFILES} models can be added.")
    name = _validate_profile_name(name, profiles, default_name)
    profile = {"id": new_lora_profile_id(p["id"] for p in profiles), "name": name}
    profiles.append(profile)
    save_lora_profiles(data_dir, profiles)
    return profile


def rename_lora_profile(data_dir, profile_id, new_name, default_name=LORA_PROFILE_DEFAULT_NAME):
    """Display-name change only; no entry is touched."""
    profiles = load_lora_profiles(data_dir)
    target = next((p for p in profiles if p["id"] == profile_id), None)
    if target is None:
        raise LoraProfileError("That model no longer exists.")
    target["name"] = _validate_profile_name(new_name, profiles, default_name, own_id=profile_id)
    save_lora_profiles(data_dir, profiles)
    return dict(target)


def _iter_sidecar_entries(data_dir):
    """Yields (category, entry_base_name) for every metadata sidecar on
    disk, canon outfits included (they are ordinary files in outfits/)."""
    for category in CATEGORIES:
        pattern = os.path.join(data_dir, category, f"*{LIBRARY_META_EXT}")
        for path in sorted(glob.glob(pattern)):
            base = os.path.basename(path)[:-len(LIBRARY_META_EXT)]
            if base:
                yield category, base


def lora_profile_binding_entries(data_dir, profile_id):
    """[(category, name)] of every entry that has a binding for the
    profile — what a delete would prune (shown in the confirmation)."""
    found = []
    for category, name in _iter_sidecar_entries(data_dir):
        if profile_id in load_library_meta(data_dir, category, name).get("loras", {}):
            found.append((category, name))
    return found


def delete_lora_profile(data_dir, profile_id, report=None):
    """Removes the profile, re-points models that shared its list to
    Default (D16), drops its per-list Active map and prunes its bindings
    from every entry. Returns how many entries' bindings were changed
    (unchanged pre-Session-69 contract). Other fields of those sidecars
    (video link, alias, variation link...) are preserved.

    `report` (optional dict, same pattern as merge_imported_library)
    receives "bindings", "dependents" (the re-pointed models) and
    "active_entries" (explicit states dropped with the map), for the
    delete confirmation."""
    path = lora_profiles_path(data_dir)
    records, default_preset, extra_top = _read_model_document(path)
    if _find_model_record(records, profile_id) is None:
        raise LoraProfileError("That model no longer exists.")
    dependents = list_dependents(data_dir, profile_id)
    dependent_ids = {dependent["id"] for dependent in dependents}
    for record in records:
        if record["id"] in dependent_ids:
            record[MODEL_FIELD_LORA_SOURCE] = LORA_SOURCE_DEFAULT
    active_entries = _count_explicit_active_states(data_dir, profile_id)
    changed = 0
    for category, name in lora_profile_binding_entries(data_dir, profile_id):
        loras = dict(load_library_meta(data_dir, category, name).get("loras", {}))
        loras.pop(profile_id, None)
        update_library_meta(data_dir, category, name, loras=loras)
        changed += 1
    records = [record for record in records if record["id"] != profile_id]
    _write_model_document(path, records, default_preset, extra_top)
    try:
        active_path = owner_active_map_path(data_dir, profile_id)
        if os.path.exists(active_path):
            os.remove(active_path)
    except OSError:
        pass
    if isinstance(report, dict):
        report["bindings"] = changed
        report["dependents"] = dependents
        report["active_entries"] = active_entries
    return changed


def merge_imported_lora_profiles(data_dir, extracted_dir, imported):
    """Import step: for the entries that were just imported, makes sure
    every profile id their sidecars reference exists locally.

    Profiles are matched by ID, never by name. A referenced id that is
    unknown here is added with the imported name (suffixed " (2)", "(3)"
    on a clash with a different local profile or the Default name). A
    referenced id with no definition in the zip stays an ignored
    binding. The add ignores MAX_LORA_PROFILES on purpose: dropping a
    referenced profile would silently orphan its bindings.

    Session 69: a newly added model also brings its preset fields and
    `lora_source`; an already existing id keeps all local data (only the
    name is never touched). A shared source that is not present locally
    falls back to "Same as Default" (D16). The model's
    `_active_<id>.json` is copied for newly added ids, and an imported
    Default preset is adopted only when the local one is still empty.
    Returns the list of profiles that were added."""
    referenced = set()
    for category, name in imported:
        referenced.update(load_library_meta(data_dir, category, name).get("loras", {}))
    path = lora_profiles_path(data_dir)
    records, default_preset, extra_top = _read_model_document(path)
    src_records, src_default, _src_extra = _read_model_document(
        os.path.join(extracted_dir, LORA_PROFILES_FILE_NAME))
    source = {record["id"]: record for record in src_records}
    local_ids = {record["id"] for record in records}
    taken = {record["name"].casefold() for record in records}
    taken.add(LORA_PROFILE_DEFAULT_NAME.casefold())
    added = []
    for pid in sorted(referenced - local_ids):
        src = source.get(pid)
        if src is None:
            continue
        base_name = src["name"]
        name, n = base_name, 2
        while name.casefold() in taken:
            name = f"{base_name} ({n})"
            n += 1
        record = dict(src)
        record["id"] = pid
        record["name"] = name
        records.append(record)
        taken.add(name.casefold())
        added.append({"id": pid, "name": name})

    adopted_default = False
    if (not _preset_fields_payload(default_preset)
            and _preset_fields_payload(src_default)):
        default_preset = dict(src_default)
        adopted_default = True

    if added:
        added_ids = {profile["id"] for profile in added}
        valid_ids = {record["id"] for record in records}
        for record in records:
            if record["id"] not in added_ids:
                continue
            src_value = record.get(MODEL_FIELD_LORA_SOURCE) or LORA_SOURCE_OWN
            if src_value in (LORA_SOURCE_OWN, LORA_SOURCE_DEFAULT):
                continue
            target = _find_model_record(records, src_value)
            if (src_value not in valid_ids or target is None
                    or (target.get(MODEL_FIELD_LORA_SOURCE) or LORA_SOURCE_OWN)
                    != LORA_SOURCE_OWN):
                record[MODEL_FIELD_LORA_SOURCE] = LORA_SOURCE_DEFAULT
        for profile in added:
            src_active = os.path.join(
                extracted_dir,
                LIBRARY_ACTIVE_OWNER_FILE_TEMPLATE.format(owner_id=profile["id"]))
            if not os.path.exists(src_active):
                continue
            try:
                shutil.copyfile(src_active,
                                owner_active_map_path(data_dir, profile["id"]))
            except OSError:
                pass

    if added or adopted_default:
        _write_model_document(path, records, default_preset, extra_top)
    return added


def list_lora_bindings(meta, known_profile_ids=None):
    """[(profile_id_or_None, path, strength)] for one entry's meta dict:
    Default first (profile_id None), then the extra profiles. When
    `known_profile_ids` is given, bindings of unknown profile ids are
    skipped (D8: unknown ids are ignored)."""
    rows = []
    if meta.get("lora"):
        rows.append((None, meta["lora"], meta.get("lora_strength", 1.0)))
    for pid, payload in (meta.get("loras") or {}).items():
        if known_profile_ids is not None and pid not in known_profile_ids:
            continue
        rows.append((pid, payload["lora"], payload["strength"]))
    return rows


def get_lora_binding(meta, profile_id=None):
    """(lora_path, strength) for one profile of one entry's meta dict;
    (None, 1.0) when it has none. `profile_id` None/"" = Default. No
    fallback between profiles (strict)."""
    if not profile_id:
        lora = meta.get("lora")
        return (lora, meta.get("lora_strength", 1.0)) if lora else (None, 1.0)
    payload = (meta.get("loras") or {}).get(profile_id)
    if payload and payload.get("lora"):
        return payload["lora"], payload["strength"]
    return None, 1.0


def set_lora_binding(data_dir, category, name, profile_id, lora, strength=1.0):
    """Sets or (when `lora` is falsy) clears one profile's binding on an
    entry, leaving every other field and profile untouched.

    Session 69: assigning a LoRA under an own-list model is the single
    write path for D21's wake-once, so it is hooked here (an entry in
    auto state becomes explicitly Active; an explicit state is never
    touched automatically)."""
    if not profile_id:
        update_library_meta(data_dir, category, name,
                            lora=lora or None, lora_strength=strength)
        return
    loras = dict(load_library_meta(data_dir, category, name).get("loras", {}))
    if lora:
        loras[profile_id] = {"lora": lora, "strength": strength}
    else:
        loras.pop(profile_id, None)
    update_library_meta(data_dir, category, name, loras=loras)
    if lora:
        note_lora_assigned(data_dir, profile_id, category, name)


def resolve_entry_lora(data_dir, category, name, profile_id=None):
    """(lora_path_or_None, strength) the entry contributes under the
    given profile. A character VARIATION with no binding of its own for
    that profile uses its parent's binding for the same profile (S58
    inheritance, now per profile); a variation's own binding wins."""
    lora, strength = get_lora_binding(load_library_meta(data_dir, category, name), profile_id)
    if not lora and category == "characters":
        parent = variation_parent(data_dir, name)
        if parent:
            lora, strength = get_lora_binding(
                load_library_meta(data_dir, category, parent), profile_id)
    return (lora or None), (strength if lora else 1.0)


# ============================================================
#         LIBRARY VIRTUAL FOLDERS (subfolder organization)
# ============================================================
# Folders here are a pure UI/organization layer on top of the existing
# flat-per-category storage. An entry's name stays the single,
# globally-unique-within-its-category identifier it always was —
# get_file_list, the Builder's dropdowns, history, and the LoRA
# auto-fill logic never need to know folders exist at all. Only the
# Library tab's tree view, its search box, and its move/organize
# actions consult `folder_maps`.
#
# Persisted as {category: {entry_name: "Folder/Sub Folder"}} in the
# caller's `folders_file` (LIBRARY_FOLDERS_FILE_NAME under data_dir). A
# missing key simply means "lives at the root of the category" — there
# is no need to ever write an explicit "" value.
def save_folder_map(folders_file, folder_maps):
    save_json(folders_file, folder_maps)


def get_entry_folder(folder_maps, category, name):
    """Returns the folder path string an entry is filed under, or ""
    if it lives at the root of the category."""
    return folder_maps.get(category, {}).get(name, "") or ""


def set_entry_folder(folder_maps, folders_file, category, name, folder_path):
    """Files `name` under `folder_path` ("" = root of the category).
    Does not touch any file on disk — folders are virtual. Mutates
    `folder_maps` in place and persists it, mirroring the original's
    in-place mutation of self._folder_maps."""
    cat_map = folder_maps.setdefault(category, {})
    folder_path = (folder_path or "").strip("/")
    if folder_path:
        cat_map[name] = folder_path
    else:
        cat_map.pop(name, None)
    save_folder_map(folders_file, folder_maps)


def remove_entry_folder_entry(folder_maps, folders_file, category, name):
    """Drops any folder assignment for `name` (used when an entry is
    deleted, so the manifest doesn't accumulate references to files
    that no longer exist)."""
    cat_map = folder_maps.get(category)
    if cat_map and name in cat_map:
        del cat_map[name]
        save_folder_map(folders_file, folder_maps)


def rename_entry_folder_entry(folder_maps, folders_file, category, old_name, new_name):
    """Carries an entry's folder assignment over on rename/duplicate,
    mirroring rename_library_image/rename_library_meta above."""
    if not old_name or old_name == new_name:
        return
    cat_map = folder_maps.get(category)
    if cat_map and old_name in cat_map:
        cat_map[new_name] = cat_map.pop(old_name)
        save_folder_map(folders_file, folder_maps)


def list_all_folders(folder_maps, empty_folders, category):
    """Returns every distinct folder path used in this category
    (including ancestors of nested paths, even if nothing is filed
    directly in them, and including freshly-created empty folders),
    sorted alphabetically depth-first. Used to populate the "Move
    to..." submenu and the folder picker."""
    paths = set(empty_folders.get(category, set()))
    for folder_path in folder_maps.get(category, {}).values():
        if not folder_path:
            continue
        parts = folder_path.split(FOLDER_PATH_SEP)
        for depth in range(1, len(parts) + 1):
            paths.add(FOLDER_PATH_SEP.join(parts[:depth]))
    return sorted(paths, key=natural_sort_key)


def is_protected_folder(category, folder_path):
    """Canonical Outfits (outfits category only) is auto-managed: users
    cannot rename it, delete it, or hand-drop ordinary entries into it.
    Returns True if `folder_path` IS that folder or a path nested under
    it.

    Named without the original's leading underscore would be more
    idiomatic for a public module function, but the leading underscore
    is kept here (and on _file_canon_outfit_into_folder below) to match
    the exact names later sessions in the migration plan refer to —
    see Session 6/7's steps, which call these out by these names."""
    if category != "outfits":
        return False
    return (folder_path == CANONICAL_OUTFITS_FOLDER
            or folder_path.startswith(CANONICAL_OUTFITS_FOLDER + FOLDER_PATH_SEP))


# Alias kept for traceability with the original method name / the
# migration plan's own references to "_is_protected_folder".
_is_protected_folder = is_protected_folder


def is_canon_outfit_name(base):
    return "_Canon_" in base


def _file_canon_outfit_into_folder(folder_maps, folders_file, char_name, num):
    """Auto-files a canon outfit into the Canonical Outfits folder the
    moment it's created/saved as canon. Called from save_to_library
    (Library tab, later session)."""
    base = f"{char_name}_Canon_{num}"
    set_entry_folder(folder_maps, folders_file, "outfits", base, CANONICAL_OUTFITS_FOLDER)


def move_entries_to_folder(folder_maps, folders_file, category, names, folder_path):
    """Moves a batch of entries (e.g. a multi-selection) into
    folder_path in one go. Refuses to drop ordinary outfits into the
    protected Canonical Outfits folder, and silently skips canon
    outfits if a non-protected target was requested by mistake (canon
    outfits are only ever moved automatically, never by hand) — see
    is_canon_outfit_name(). Returns the number of entries actually
    moved."""
    moved = 0
    for name in names:
        is_canon = category == "outfits" and is_canon_outfit_name(name)
        if is_canon:
            continue  # canon outfits' folder is managed automatically only
        if is_protected_folder(category, folder_path):
            continue  # users can't manually file ordinary entries in here
        set_entry_folder(folder_maps, folders_file, category, name, folder_path)
        moved += 1
    return moved


# ============================================================
#       LIBRARY ACTIVE/INACTIVE ENTRIES & FOLDERS (Session 45)
# ============================================================
# {category: {"entries": set(name), "folders": set(folder_path)}} of
# everything currently marked INACTIVE (absence = active, additively —
# see LIBRARY_ACTIVE_FILE_NAME's own note). Persisted on disk as plain
# lists (JSON has no set type), converted to sets the moment it's
# loaded, mirroring the empty_folders/expanded_folders in-memory shape
# used elsewhere in this module.
def load_active_map(active_file):
    raw = load_json(active_file, {})
    active_map = {}
    if isinstance(raw, dict):
        for category, payload in raw.items():
            if not isinstance(payload, dict):
                continue
            active_map[category] = {
                "entries": set(payload.get("entries", []) or []),
                "folders": set(payload.get("folders", []) or []),
            }
    return active_map


def save_active_map(active_file, active_map):
    serializable = {
        category: {
            "entries": sorted(payload.get("entries", set())),
            "folders": sorted(payload.get("folders", set())),
        }
        for category, payload in active_map.items()
        if payload.get("entries") or payload.get("folders")
    }
    save_json(active_file, serializable)


def _active_cat(active_map, category):
    return active_map.setdefault(category, {"entries": set(), "folders": set()})


def is_folder_active(active_map, category, folder_path):
    """A folder is inactive if it, or any ancestor of it, is in the
    inactive-folders set for this category."""
    if not folder_path:
        return True
    inactive_folders = active_map.get(category, {}).get("folders", set())
    if not inactive_folders:
        return True
    parts = folder_path.split(FOLDER_PATH_SEP)
    for depth in range(1, len(parts) + 1):
        if FOLDER_PATH_SEP.join(parts[:depth]) in inactive_folders:
            return False
    return True


def is_entry_active(active_map, folder_maps, category, name):
    """An entry is active only if it isn't itself marked inactive AND no
    ancestor folder it's filed under is inactive — matches the spec's
    "is this entry inactive, or is any ancestor folder inactive" rule,
    checked live rather than propagated/stored down the tree."""
    cat_active = active_map.get(category, {})
    if name in cat_active.get("entries", set()):
        return False
    folder_path = get_entry_folder(folder_maps, category, name)
    return is_folder_active(active_map, category, folder_path)


def set_entries_active(active_map, active_file, category, names, active: bool):
    """Bulk-sets active/inactive for a batch of entry names in one
    category, persisting once."""
    cat_active = _active_cat(active_map, category)
    for name in names:
        if active:
            cat_active["entries"].discard(name)
        else:
            cat_active["entries"].add(name)
    save_active_map(active_file, active_map)


def set_folders_active(active_map, active_file, category, folder_paths, active: bool):
    """Bulk-sets active/inactive for a batch of folder paths in one
    category, persisting once. Only ever affects the folder path
    itself (not its descendants individually) — is_folder_active/
    is_entry_active already treat "any ancestor inactive" as inactive,
    so a descendant never needs its own flag flipped for this to work."""
    cat_active = _active_cat(active_map, category)
    for folder_path in folder_paths:
        if active:
            cat_active["folders"].discard(folder_path)
        else:
            cat_active["folders"].add(folder_path)
    save_active_map(active_file, active_map)


def remove_entry_active_entry(active_map, active_file, category, name):
    """Drops any inactive-flag for `name` (used when an entry is
    deleted, mirroring remove_entry_folder_entry above so the active
    map doesn't accumulate references to files that no longer exist)."""
    cat_active = active_map.get(category)
    if cat_active and name in cat_active.get("entries", set()):
        cat_active["entries"].discard(name)
        save_active_map(active_file, active_map)


def rename_entry_active_entry(active_map, active_file, category, old_name, new_name):
    """Carries an entry's inactive-flag over on rename/duplicate,
    mirroring rename_entry_folder_entry above."""
    if not old_name or old_name == new_name:
        return
    cat_active = active_map.get(category)
    if cat_active and old_name in cat_active.get("entries", set()):
        cat_active["entries"].discard(old_name)
        cat_active["entries"].add(new_name)
        save_active_map(active_file, active_map)


def rename_folder_active_entry(active_map, active_file, category, old_folder_path, new_folder_path):
    """Carries a folder's (and any nested folder's) inactive-flag over
    on rename, mirroring rename_folder's own re-pointing logic."""
    cat_active = active_map.get(category)
    if not cat_active:
        return
    changed = False
    for p in list(cat_active.get("folders", set())):
        if p == old_folder_path:
            cat_active["folders"].discard(p)
            cat_active["folders"].add(new_folder_path)
            changed = True
        elif p.startswith(old_folder_path + FOLDER_PATH_SEP):
            cat_active["folders"].discard(p)
            cat_active["folders"].add(new_folder_path + p[len(old_folder_path):])
            changed = True
    if changed:
        save_active_map(active_file, active_map)


def delete_folder_active_entries(active_map, active_file, category, folder_path):
    """Drops the inactive-flag for `folder_path` (and any nested
    subfolders) when the folder itself is deleted as an organizational
    construct, mirroring delete_folder's own cleanup."""
    cat_active = active_map.get(category)
    if not cat_active:
        return
    changed = False
    for p in list(cat_active.get("folders", set())):
        if p == folder_path or p.startswith(folder_path + FOLDER_PATH_SEP):
            cat_active["folders"].discard(p)
            changed = True
    if changed:
        save_active_map(active_file, active_map)


def owner_active_map_path(data_dir, owner_id):
    """Session 69 (D20): where one LoRA list's Active map lives.
    Default (None/"") keeps the untouched `_active.json`; every model
    with its own list gets `_active_<owner_id>.json` next to it."""
    if not owner_id:
        return os.path.join(data_dir, LIBRARY_ACTIVE_FILE_NAME)
    safe_id = sanitize_filename(str(owner_id)) or "model"
    return os.path.join(
        data_dir, LIBRARY_ACTIVE_OWNER_FILE_TEMPLATE.format(owner_id=safe_id))


def load_active_map_for(data_dir, owner_id):
    """Session 69 (D20/D21): the Active map of one list.

    Default (owner_id None/"") returns exactly the old two-valued map
    from `_active.json`. An own-list model returns the three-valued
    shape `{category: {"entries": {name: "active"|"inactive"},
    "folders": set()}}`; a name absent from `entries` is in *auto* state
    (judged live by `is_entry_active_for`). Folders stay two-valued.
    Missing/corrupt file -> {} (everything auto/active)."""
    if not owner_id:
        return load_active_map(owner_active_map_path(data_dir, None))
    raw = load_json(owner_active_map_path(data_dir, owner_id), {})
    active_map = {}
    if not isinstance(raw, dict):
        return active_map
    for category, payload in raw.items():
        if not isinstance(payload, dict):
            continue
        entries = {}
        raw_entries = payload.get("entries")
        if isinstance(raw_entries, dict):
            for name, state in raw_entries.items():
                if not isinstance(name, str) or not name:
                    continue
                state = str(state or "").strip().casefold()
                if state in (ACTIVE_ENTRY_ACTIVE, ACTIVE_ENTRY_INACTIVE):
                    entries[name] = state
        elif isinstance(raw_entries, list):
            # A Default-shaped file copied by hand: listed names are
            # explicit inactive, exactly like _active.json would mean.
            for name in raw_entries:
                if isinstance(name, str) and name:
                    entries[name] = ACTIVE_ENTRY_INACTIVE
        folders = set()
        if isinstance(payload.get("folders"), list):
            folders = {folder for folder in payload["folders"]
                       if isinstance(folder, str) and folder}
        if entries or folders:
            active_map[category] = {"entries": entries, "folders": folders}
    return active_map


def save_active_map_for(data_dir, owner_id, active_map):
    """Session 69: persists one list's Active map. Default delegates to
    the untouched `save_active_map`; an own-list model writes only
    categories that actually hold an explicit state or an inactive
    folder, and removes the file when nothing is left (so a library that
    never toggles anything gains no stray files)."""
    path = owner_active_map_path(data_dir, owner_id)
    if not owner_id:
        save_active_map(path, active_map)
        return
    serializable = {}
    for category, payload in (active_map or {}).items():
        if not isinstance(payload, dict):
            continue
        raw_entries = payload.get("entries") or {}
        if isinstance(raw_entries, (set, list, tuple)):
            entries = {name: ACTIVE_ENTRY_INACTIVE for name in raw_entries
                       if isinstance(name, str) and name}
        elif isinstance(raw_entries, dict):
            entries = {name: state for name, state in raw_entries.items()
                       if isinstance(name, str) and name
                       and state in (ACTIVE_ENTRY_ACTIVE, ACTIVE_ENTRY_INACTIVE)}
        else:
            entries = {}
        folders = sorted(folder for folder in (payload.get("folders") or set())
                         if isinstance(folder, str) and folder)
        if entries or folders:
            serializable[category] = {"entries": dict(sorted(entries.items())),
                                      "folders": folders}
    if not serializable:
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            pass
        return
    save_json(path, serializable)


def _count_explicit_active_states(data_dir, owner_id):
    """How many entries carry an explicit three-valued state for this
    own-list model (used for the D18 confirmation before switching its
    list away or deleting it)."""
    if not owner_id:
        return 0
    active_map = load_active_map_for(data_dir, owner_id)
    return sum(len(payload.get("entries") or {})
               for payload in active_map.values())


def _other_list_owner_ids(data_dir, owner_id):
    """Every other LoRA list currently in use: Default plus each model
    that has its own list. Dormant lists (models sharing another list)
    are deliberately excluded (D18/D9)."""
    owners = [None]
    records, _default, _extra = _load_model_records(data_dir)
    for record in records:
        if record["id"] == owner_id:
            continue
        if (record.get(MODEL_FIELD_LORA_SOURCE) or LORA_SOURCE_OWN) == LORA_SOURCE_OWN:
            owners.append(record["id"])
    return owners


def is_entry_active_for(data_dir, owner_id, active_map, folder_maps, category, name):
    """Session 69 (D20/D21): is `name` active in the list of `owner_id`?

    Default (or an id resolving to Default) delegates to the untouched
    `is_entry_active`, so today's behaviour is byte-for-byte preserved.
    For an own-list model:
      - an inactive folder (or ancestor) wins, as today;
      - an explicit "inactive" / "active" entry state wins;
      - otherwise the D21 auto rule: Inactive when the entry carries a
        LoRA under any OTHER list and none under this one, otherwise
        Active (styles, scenarios, plain characters and new entries are
        never auto-inactive). Variations use the D5 inheritance through
        resolve_entry_lora."""
    owner = resolve_list_owner(data_dir, owner_id)
    if owner is None:
        return is_entry_active(active_map, folder_maps, category, name)
    if not is_folder_active(active_map, category,
                            get_entry_folder(folder_maps, category, name)):
        return False
    cat_active = active_map.get(category, {}) if active_map else {}
    state = (cat_active.get("entries") or {}).get(name)
    if state == ACTIVE_ENTRY_INACTIVE:
        return False
    if state == ACTIVE_ENTRY_ACTIVE:
        return True
    if resolve_entry_lora(data_dir, category, name, owner)[0]:
        return True
    for other_owner in _other_list_owner_ids(data_dir, owner):
        if resolve_entry_lora(data_dir, category, name, other_owner)[0]:
            return False
    return True


def note_lora_assigned(data_dir, owner_id, category, name):
    """Session 69 (D21 wake-once): called from the single LoRA write path
    right after a binding is assigned. For an own-list model, an entry
    still in *auto* state becomes explicitly Active; an explicit Active
    or Inactive state is never changed automatically, so a user who set
    it Inactive again keeps it Inactive. Default has no auto rule.
    Returns True when a state was written."""
    owner = resolve_list_owner(data_dir, owner_id)
    if owner is None:
        return False
    active_map = load_active_map_for(data_dir, owner)
    cat_active = active_map.setdefault(
        category, {"entries": {}, "folders": set()})
    entries = cat_active.setdefault("entries", {})
    if name in entries:
        return False
    entries[name] = ACTIVE_ENTRY_ACTIVE
    save_active_map_for(data_dir, owner, active_map)
    return True


def set_entries_active_for(data_dir, owner_id, category, names, active):
    """Session 69: bulk toggle in a list's context. Default delegates to
    `set_entries_active` (unchanged); an own-list model writes an
    explicit "active"/"inactive" state for every name, which is exactly
    what stops the D21 auto rule from moving it later."""
    owner = resolve_list_owner(data_dir, owner_id)
    path = owner_active_map_path(data_dir, owner)
    if owner is None:
        active_map = load_active_map(path)
        set_entries_active(active_map, path, category, names, active)
        return
    active_map = load_active_map_for(data_dir, owner)
    cat_active = active_map.setdefault(
        category, {"entries": {}, "folders": set()})
    state = ACTIVE_ENTRY_ACTIVE if active else ACTIVE_ENTRY_INACTIVE
    for name in names:
        cat_active.setdefault("entries", {})[name] = state
    save_active_map_for(data_dir, owner, active_map)


def remove_entry_active_entry_for(data_dir, owner_id, category, name):
    """Session 69: entry-delete carry-over for one model's map. The
    literal `owner_id` file is maintained (so dormant data of a model
    that currently shares another list stays consistent too)."""
    if not owner_id:
        path = owner_active_map_path(data_dir, None)
        active_map = load_active_map(path)
        remove_entry_active_entry(active_map, path, category, name)
        return
    active_map = load_active_map_for(data_dir, owner_id)
    cat_active = active_map.get(category)
    if cat_active and name in (cat_active.get("entries") or {}):
        del cat_active["entries"][name]
        save_active_map_for(data_dir, owner_id, active_map)


def rename_entry_active_entry_for(data_dir, owner_id, category, old_name, new_name):
    """Session 69: entry rename/duplicate carry-over for one model's map."""
    if not old_name or old_name == new_name:
        return
    if not owner_id:
        path = owner_active_map_path(data_dir, None)
        active_map = load_active_map(path)
        rename_entry_active_entry(active_map, path, category, old_name, new_name)
        return
    active_map = load_active_map_for(data_dir, owner_id)
    cat_active = active_map.get(category)
    if cat_active and old_name in (cat_active.get("entries") or {}):
        cat_active["entries"][new_name] = cat_active["entries"].pop(old_name)
        save_active_map_for(data_dir, owner_id, active_map)


def rename_folder_active_entries_for(data_dir, owner_id, category,
                                     old_folder_path, new_folder_path):
    """Session 69: folder-rename carry-over for one model's map."""
    if not owner_id:
        path = owner_active_map_path(data_dir, None)
        active_map = load_active_map(path)
        rename_folder_active_entry(
            active_map, path, category, old_folder_path, new_folder_path)
        return
    active_map = load_active_map_for(data_dir, owner_id)
    cat_active = active_map.get(category)
    if not cat_active:
        return
    changed = False
    for folder_path in list(cat_active.get("folders") or set()):
        if folder_path == old_folder_path:
            cat_active["folders"].discard(folder_path)
            cat_active["folders"].add(new_folder_path)
            changed = True
        elif folder_path.startswith(old_folder_path + FOLDER_PATH_SEP):
            cat_active["folders"].discard(folder_path)
            cat_active["folders"].add(
                new_folder_path + folder_path[len(old_folder_path):])
            changed = True
    if changed:
        save_active_map_for(data_dir, owner_id, active_map)


def delete_folder_active_entries_for(data_dir, owner_id, category, folder_path):
    """Session 69: folder-delete carry-over for one model's map."""
    if not owner_id:
        path = owner_active_map_path(data_dir, None)
        active_map = load_active_map(path)
        delete_folder_active_entries(active_map, path, category, folder_path)
        return
    active_map = load_active_map_for(data_dir, owner_id)
    cat_active = active_map.get(category)
    if not cat_active:
        return
    changed = False
    for folder in list(cat_active.get("folders") or set()):
        if folder == folder_path or folder.startswith(folder_path + FOLDER_PATH_SEP):
            cat_active["folders"].discard(folder)
            changed = True
    if changed:
        save_active_map_for(data_dir, owner_id, active_map)


# ---- Session 72: per-list Active / Inactive for Library + Builder ----------
def owner_active_file_ids(data_dir):
    """Session 72: ids of every model that currently has an
    `_active_<id>.json` on disk (Default's `_active.json` is not one).
    Dormant lists are included on purpose: their files must follow entry
    renames / deletes too, or the data would be stale when the model is
    switched back to Own (D18)."""
    prefix, suffix = "_active_", ".json"
    ids = []
    try:
        names = os.listdir(data_dir)
    except OSError:
        return ids
    for file_name in sorted(names):
        if (file_name.startswith(prefix) and file_name.endswith(suffix)
                and file_name != LIBRARY_ACTIVE_FILE_NAME
                and len(file_name) > len(prefix) + len(suffix)):
            ids.append(file_name[len(prefix):-len(suffix)])
    return ids


def rename_entry_active_all_owners(data_dir, category, old_name, new_name):
    """Carries an entry's explicit state over a rename in EVERY model
    file (Default's map is handled by its caller, as before)."""
    for owner_id in owner_active_file_ids(data_dir):
        rename_entry_active_entry_for(data_dir, owner_id, category, old_name, new_name)


def remove_entry_active_all_owners(data_dir, category, name):
    """Drops a deleted entry's explicit state from every model file."""
    for owner_id in owner_active_file_ids(data_dir):
        remove_entry_active_entry_for(data_dir, owner_id, category, name)


def rename_folder_active_all_owners(data_dir, category, old_folder_path, new_folder_path):
    for owner_id in owner_active_file_ids(data_dir):
        rename_folder_active_entries_for(
            data_dir, owner_id, category, old_folder_path, new_folder_path)


def delete_folder_active_all_owners(data_dir, category, folder_path):
    for owner_id in owner_active_file_ids(data_dir):
        delete_folder_active_entries_for(data_dir, owner_id, category, folder_path)


def set_folders_active_for(data_dir, owner_id, category, folder_paths, active):
    """Session 72: folder toggle in a list's context (folders stay
    two-valued: present = inactive). Default delegates to the unchanged
    `set_folders_active`."""
    owner = resolve_list_owner(data_dir, owner_id)
    path = owner_active_map_path(data_dir, owner)
    if owner is None:
        active_map = load_active_map(path)
        set_folders_active(active_map, path, category, folder_paths, active)
        return
    active_map = load_active_map_for(data_dir, owner)
    cat_active = active_map.setdefault(
        category, {"entries": {}, "folders": set()})
    for folder_path in folder_paths:
        if active:
            cat_active["folders"].discard(folder_path)
        else:
            cat_active["folders"].add(folder_path)
    save_active_map_for(data_dir, owner, active_map)


def set_whole_library_active_for(data_dir, owner_id, names_by_category,
                                 folders_by_category, active):
    """Session 72: "Active All" / "Inactive All" for one list.

    Default keeps today's behaviour exactly (Active All wipes the
    category's inactive sets; Inactive All marks every given name and
    folder). An own-list model writes an explicit state for every given
    entry (a deliberate bulk choice must not be undone by the auto rule
    later) and sets / clears every given folder."""
    owner = resolve_list_owner(data_dir, owner_id)
    path = owner_active_map_path(data_dir, owner)
    if owner is None:
        active_map = load_active_map(path)
        for category in set(names_by_category) | set(folders_by_category):
            if active:
                active_map[category] = {"entries": set(), "folders": set()}
            else:
                cat_active = active_map.setdefault(
                    category, {"entries": set(), "folders": set()})
                cat_active["entries"].update(names_by_category.get(category, []))
                cat_active["folders"].update(folders_by_category.get(category, []))
        save_active_map(path, active_map)
        return
    active_map = load_active_map_for(data_dir, owner)
    state = ACTIVE_ENTRY_ACTIVE if active else ACTIVE_ENTRY_INACTIVE
    for category in set(names_by_category) | set(folders_by_category):
        cat_active = active_map.setdefault(
            category, {"entries": {}, "folders": set()})
        for name in names_by_category.get(category, []):
            cat_active.setdefault("entries", {})[name] = state
        if active:
            cat_active["folders"] = set()
        else:
            cat_active["folders"] = set(cat_active.get("folders") or set()) | set(
                folders_by_category.get(category, []))
    save_active_map_for(data_dir, owner, active_map)


def note_lora_assigned_for_bindings(data_dir, category, name, loras):
    """Session 72: wake-once for an entry that was just written with a
    set of extra bindings (new entry saved, duplicate). Calls
    `note_lora_assigned` for every non-empty binding; Default and
    sharing models are no-ops there. Returns the owner ids that wrote a
    state."""
    woken = []
    for profile_id, payload in (loras or {}).items():
        if not profile_id or not isinstance(payload, dict) or not payload.get("lora"):
            continue
        owner = resolve_list_owner(data_dir, profile_id)
        if owner and owner not in woken and note_lora_assigned(
                data_dir, owner, category, name):
            woken.append(owner)
    return woken


def load_active_context(data_dir, profile_id):
    """Session 72: (owner_id, active_map) for the model `profile_id`
    (None/unknown = Default). The map is the OWNER's (D17), so a model
    sharing Default's list gets Default's unchanged two-valued map."""
    owner = resolve_list_owner(data_dir, profile_id)
    return owner, load_active_map_for(data_dir, owner)


class ActiveChecker:
    """Session 72: fast, memoising version of `is_entry_active_for` for
    loops over many entries (Library tree, Builder combos).

    One instance is meant for one pass. It resolves the list owner and
    the other lists in use once, and reads each sidecar at most once,
    instead of re-reading the models file and sidecars per entry. For
    Default it is a thin wrapper over the unchanged `is_entry_active`.
    Its answers equal `is_entry_active_for` (tested)."""

    def __init__(self, data_dir, owner_id, active_map, folder_maps):
        self.data_dir = data_dir
        self.active_map = active_map or {}
        self.folder_maps = folder_maps or {}
        self.owner = resolve_list_owner(data_dir, owner_id)
        self._others = (_other_list_owner_ids(data_dir, self.owner)
                        if self.owner is not None else [])
        self._meta = {}

    def _meta_of(self, category, name):
        key = (category, name)
        if key not in self._meta:
            self._meta[key] = load_library_meta(self.data_dir, category, name)
        return self._meta[key]

    def _carries(self, category, name, profile_id):
        meta = self._meta_of(category, name)
        if get_lora_binding(meta, profile_id)[0]:
            return True
        if category == "characters":
            parent = meta.get("variation_of")
            if (parent and parent != name and os.path.exists(
                    os.path.join(self.data_dir, category, f"{parent}.txt"))):
                return bool(get_lora_binding(
                    self._meta_of(category, parent), profile_id)[0])
        return False

    def entry_state(self, category, name):
        """The entry's OWN state ignoring folders: False = inactive
        (explicit, or auto-inactive), True = active."""
        if self.owner is None:
            return name not in self.active_map.get(category, {}).get("entries", set())
        state = (self.active_map.get(category, {}).get("entries") or {}).get(name)
        if state == ACTIVE_ENTRY_INACTIVE:
            return False
        if state == ACTIVE_ENTRY_ACTIVE:
            return True
        if self._carries(category, name, self.owner):
            return True
        for other in self._others:
            if self._carries(category, name, other):
                return False
        return True

    def is_auto(self, category, name):
        """True while the entry has no explicit state in an own list."""
        if self.owner is None:
            return False
        return name not in (self.active_map.get(category, {}).get("entries") or {})

    def __call__(self, category, name):
        if self.owner is None:
            return is_entry_active(self.active_map, self.folder_maps, category, name)
        if not is_folder_active(self.active_map, category,
                                get_entry_folder(self.folder_maps, category, name)):
            return False
        return self.entry_state(category, name)


def make_active_checker(data_dir, owner_id, active_map, folder_maps):
    return ActiveChecker(data_dir, owner_id, active_map, folder_maps)


def rename_folder(folder_maps, empty_folders, expanded_folders, folders_file, category, folder_path, new_name):
    """Renames `folder_path`'s final path component to `new_name`,
    re-pointing every entry and nested subfolder whose path starts with
    the old folder path onto the new one (and likewise for any
    in-memory empty folders and persisted expand state) — ported from
    `_rename_library_folder`, minus the dialog/validation/messagebox
    half, which is the UI layer's job (Session 6).

    Returns the new full folder path on success. Returns None if
    `new_name` is empty, contains FOLDER_PATH_SEP, or is unchanged
    (i.e. nothing to do) — the caller decides what (if anything) to
    tell the user about a no-op vs an actual rename."""
    old_name = folder_path.split(FOLDER_PATH_SEP)[-1]
    new_name = (new_name or "").strip()
    if not new_name or new_name == old_name or FOLDER_PATH_SEP in new_name:
        return None
    parent = FOLDER_PATH_SEP.join(folder_path.split(FOLDER_PATH_SEP)[:-1])
    new_path = f"{parent}{FOLDER_PATH_SEP}{new_name}" if parent else new_name

    cat_map = folder_maps.get(category, {})
    for entry_name, entry_folder in list(cat_map.items()):
        if entry_folder == folder_path:
            cat_map[entry_name] = new_path
        elif entry_folder.startswith(folder_path + FOLDER_PATH_SEP):
            cat_map[entry_name] = new_path + entry_folder[len(folder_path):]

    empty_set = empty_folders.get(category, set())
    for p in list(empty_set):
        if p == folder_path:
            empty_set.discard(p)
            empty_set.add(new_path)
        elif p.startswith(folder_path + FOLDER_PATH_SEP):
            empty_set.discard(p)
            empty_set.add(new_path + p[len(folder_path):])

    expanded = expanded_folders.get(category, set())
    if folder_path in expanded:
        expanded.discard(folder_path)
        expanded.add(new_path)

    save_folder_map(folders_file, folder_maps)
    return new_path


def delete_folder(folder_maps, empty_folders, expanded_folders, folders_file, category, folder_path):
    """Deletes `folder_path` (and any nested subfolders) as an
    organizational construct only — every entry that was filed under it
    moves back to the category root; nothing is deleted on disk. Ported
    from `_delete_library_folder`, minus the confirmation dialog, which
    is the UI layer's job (Session 6)."""
    cat_map = folder_maps.get(category, {})
    for entry_name, entry_folder in list(cat_map.items()):
        if entry_folder == folder_path or entry_folder.startswith(folder_path + FOLDER_PATH_SEP):
            del cat_map[entry_name]

    empty_set = empty_folders.get(category, set())
    for p in list(empty_set):
        if p == folder_path or p.startswith(folder_path + FOLDER_PATH_SEP):
            empty_set.discard(p)

    expanded_folders.get(category, set()).discard(folder_path)

    save_folder_map(folders_file, folder_maps)


def create_new_folder(empty_folders, category, parent_path, folder_name):
    """Registers a brand-new (initially empty) folder so it shows up in
    the tree immediately, without requiring an entry to be moved into
    it first. Empty folders are remembered for the session via
    `empty_folders` (not persisted standalone — they become "real" the
    moment an entry is filed into them; until then they'd otherwise
    vanish on the next refresh since list_all_folders only derives
    paths from entries that exist)."""
    folder_name = (folder_name or "").strip()
    if not folder_name or FOLDER_PATH_SEP in folder_name:
        return None
    full_path = f"{parent_path}{FOLDER_PATH_SEP}{folder_name}" if parent_path else folder_name
    empty_folders.setdefault(category, set()).add(full_path)
    return full_path


# ============================================================
#                  LIBRARY FILE LISTING / READING
# ============================================================
def get_file_list(data_dir, category):
    path = os.path.join(data_dir, category)
    files = os.listdir(path)
    result = []
    for f in files:
        if f.endswith(".txt"):
            base = os.path.splitext(f)[0]
            if category == "outfits" and "_Canon_" in base:
                continue  # canon outfits are not shown as standalone shared outfits
            result.append(base)
    return sorted(result, key=natural_sort_key)


def _is_active_in_list(data_dir, owner_id, active_map, folder_maps, category, name):
    """Session 69: one dispatch point for the Builder-facing helpers, so
    every one of them reads the same map it was handed — Default's
    unchanged map when `owner_id` is None, the owner's three-valued map
    otherwise."""
    if not owner_id:
        return is_entry_active(active_map, folder_maps, category, name)
    return is_entry_active_for(
        data_dir, owner_id, active_map, folder_maps, category, name)


def get_active_file_list(data_dir, category, folder_maps, active_map, owner_id=None):
    """Session 45: Builder-facing variant of get_file_list — same
    listing, minus anything inactive (the entry itself, or filed under
    an inactive folder). The Library tab's own browsing/search never
    calls this; it keeps using plain get_file_list so inactive entries
    stay fully visible/searchable there.

    Session 69: pass the active model's `owner_id` together with that
    owner's map to apply the per-list D21 rule; leaving both out keeps
    today's Default behaviour exactly."""
    check = make_active_checker(data_dir, owner_id, active_map, folder_maps)
    return [name for name in get_file_list(data_dir, category)
            if check(category, name)]


def list_active_outfit_options_for_character(data_dir, char_name, folder_maps, active_map,
                                             owner_id=None):
    """Session 45: Builder-facing variant of
    list_outfit_options_for_character — canon outfits are filtered by
    their own (auto-filed, Canonical Outfits folder) active state, and
    shared outfits by get_active_file_list above.

    Session 58: a variation resolves to its parent for the canon-outfit
    lookup, because variations inherit the parent's canon outfits (Q6).

    Session 69: optional `owner_id` (and that owner's map) applies the
    per-list Active rule."""
    char_name = resolve_outfit_owner(data_dir, char_name)
    if not char_name or char_name == "None":
        return ["None"]

    options = ["None"]
    check = make_active_checker(data_dir, owner_id, active_map, folder_maps)
    outfits_dir = os.path.join(data_dir, "outfits")
    canon_prefix = f"{char_name}_Canon_"
    canon_nums = []
    try:
        for f in os.listdir(outfits_dir):
            if f.endswith(".txt") and f.startswith(canon_prefix):
                base = os.path.splitext(f)[0]
                if not check("outfits", base):
                    continue
                num = base[len(canon_prefix):]
                canon_nums.append(num)
    except OSError:
        canon_nums = []
    for num in sorted(canon_nums, key=natural_sort_key):
        options.append(f"Canon {num}")

    options.extend(get_active_file_list(
        data_dir, "outfits", folder_maps, active_map, owner_id=owner_id))
    return options


def list_active_outfit_display_options_for_character(data_dir, char_name, folder_maps, active_map,
                                                     owner_id=None):
    """Session 56: Builder-facing variant of
    list_active_outfit_options_for_character that returns
    (display, real_value) pairs.

    `real_value` is always what the rest of the app stores and looks up
    ("Canon N" for canon outfits, the entry name for shared outfits).
    `display` is what the outfit selector should show: a canon outfit's
    optional display_alias when it has one, otherwise the same real
    value. Duplicate aliases within one character's canon outfits — and
    aliases that collide with a shared outfit name — are disambiguated
    as "alias (Canon N)" rather than silently collapsing into one row.

    Inactive canon/shared outfits are filtered out exactly like the
    plain active variant, and "None" is the first identity pair.

    Session 58: a variation resolves to its parent first, so its canon
    outfit options (and aliases) are the parent's own (Q6)."""
    char_name = resolve_outfit_owner(data_dir, char_name)
    if not char_name or char_name == "None":
        return [("None", "None")]

    check = make_active_checker(data_dir, owner_id, active_map, folder_maps)
    outfits_dir = os.path.join(data_dir, "outfits")
    canon_prefix = f"{char_name}_Canon_"
    canon_entries = []  # (num, base, alias)
    try:
        for f in os.listdir(outfits_dir):
            if not (f.endswith(".txt") and f.startswith(canon_prefix)):
                continue
            base = os.path.splitext(f)[0]
            if not check("outfits", base):
                continue
            num = base[len(canon_prefix):]
            alias = load_library_meta(data_dir, "outfits", base).get("display_alias")
            canon_entries.append((num, base, alias))
    except OSError:
        canon_entries = []
    canon_entries.sort(key=lambda entry: natural_sort_key(entry[0]))

    shared = get_active_file_list(
        data_dir, "outfits", folder_maps, active_map, owner_id=owner_id)
    shared_by_fold = {name.casefold(): name for name in shared}
    real_values = {f"Canon {num}".casefold() for num, _base, _alias in canon_entries}
    real_values.update(shared_by_fold)

    alias_counts = {}
    for _num, _base, alias in canon_entries:
        if alias:
            key = alias.casefold()
            alias_counts[key] = alias_counts.get(key, 0) + 1

    options = [("None", "None")]
    for num, _base, alias in canon_entries:
        real = f"Canon {num}"
        if not alias:
            display = real
        else:
            needs_suffix = alias_counts.get(alias.casefold(), 0) > 1
            # A label that collides with any other row's real value
            # (another canon's "Canon N" or a shared outfit name) also
            # needs the real number appended, otherwise two different
            # rows would map to the same display text.
            if not needs_suffix:
                needs_suffix = (
                    alias.casefold() != real.casefold()
                    and alias.casefold() in real_values
                )
            display = f"{alias} (Canon {num})" if needs_suffix else alias
        options.append((display, real))

    options.extend((name, name) for name in shared)
    return options


def list_outfit_options_for_character(data_dir, char_name):
    """Builder-tab helper (ported from the original's inline
    `update_outfit_list`): returns the outfit dropdown contents for a
    specific selected character — that character's own canon outfits
    first (as "Canon N", sorted numerically), followed by every shared
    (non-canon) outfit in the library. Always starts with "None".
    Returns just ["None"] if char_name is empty/"None".

    Session 58: a variation resolves to its parent for the canon list
    (variations inherit the parent's canon outfits, Q6)."""
    char_name = resolve_outfit_owner(data_dir, char_name)
    if not char_name or char_name == "None":
        return ["None"]

    options = ["None"]
    outfits_dir = os.path.join(data_dir, "outfits")
    canon_prefix = f"{char_name}_Canon_"
    canon_nums = []
    try:
        for f in os.listdir(outfits_dir):
            if f.endswith(".txt") and f.startswith(canon_prefix):
                base = os.path.splitext(f)[0]
                num = base[len(canon_prefix):]
                canon_nums.append(num)
    except OSError:
        canon_nums = []
    for num in sorted(canon_nums, key=natural_sort_key):
        options.append(f"Canon {num}")

    options.extend(get_file_list(data_dir, "outfits"))
    return options


def read_file_content(data_dir, category, filename):
    if not filename or filename == "None":
        return ""
    filepath = os.path.join(data_dir, category, f"{filename}.txt")
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read().strip()
    return ""


# ============================================================
#        CHARACTER VARIATIONS (Session 58, backend only)
# ============================================================
# A variation is an ordinary character entry whose sidecar says
# `variation_of: <parent entry name>`. The file name is stable
# "<Parent>__V<n>" (smallest free n), and `variation_label` is a
# display-only label — editing it never renames the file (the same
# split Session 56 uses for canon-outfit aliases). Only one level is
# allowed: a variation cannot own variations.
#
# Everything below is pure data/file logic with no Qt dependency, so
# the Library and Builder UI sessions can share the same rules.
VARIATION_NAME_SEP = "__V"


def _character_entry_exists(data_dir, name):
    return bool(name) and os.path.exists(
        os.path.join(data_dir, "characters", f"{name}.txt"))


def variation_parent(data_dir, name, category="characters"):
    """Returns the parent entry name when `name` is a variation whose
    parent still exists, otherwise None.

    A missing parent is treated as "not a variation" on purpose: an
    orphaned link must never make the entry unreachable or crash the
    listing. `promote_orphan_variations` below cleans such sidecars
    explicitly (used by import)."""
    if not name:
        return None
    parent = load_library_meta(data_dir, category, name).get("variation_of")
    if not parent or parent == name:
        return None
    if not os.path.exists(os.path.join(data_dir, category, f"{parent}.txt")):
        return None
    return parent


def is_variation(data_dir, name, category="characters"):
    return variation_parent(data_dir, name, category) is not None


def get_variation_label(data_dir, name, category="characters"):
    """Display label for a variation, falling back to the entry name
    when the sidecar has none (hand-edited/legacy data)."""
    label = load_library_meta(data_dir, category, name).get("variation_label")
    return label or name


def resolve_outfit_owner(data_dir, name, category="characters"):
    """The entry whose canon outfits apply to `name`: the parent for a
    variation, otherwise the entry itself. Callers use this for the
    `f"{owner}_Canon_N"` lookup while `name` still supplies the text."""
    return variation_parent(data_dir, name, category) or name


def get_character_parent_list(data_dir):
    """Every character entry that is not a variation, naturally sorted.
    Orphans count as parents (see variation_parent), so a manually
    deleted parent file cannot hide the entry from Builder."""
    return [name for name in get_file_list(data_dir, "characters")
            if not is_variation(data_dir, name)]


def get_active_character_parent_list(data_dir, folder_maps, active_map, owner_id=None):
    """Builder-facing parent list: same as get_character_parent_list,
    minus parents marked inactive (directly or via an inactive folder).
    An inactive parent makes its variations unreachable from Builder,
    which is the confirmed Session 57 decision Q8.

    Session 69: optional `owner_id` applies the active model's list rule."""
    check = make_active_checker(data_dir, owner_id, active_map, folder_maps)
    return [name for name in get_character_parent_list(data_dir)
            if check("characters", name)]


def _variation_suffix(name, parent):
    prefix = f"{parent}{VARIATION_NAME_SEP}"
    if name and name.startswith(prefix):
        return name[len(prefix):]
    return ""


def list_active_character_variations(data_dir, parent, folder_maps, active_map, owner_id=None):
    """Returns [(display_label, entry_name)] for the active variations
    of `parent`, ready for the Builder Variant combo.

    Labels are free-form and may repeat (Q5). When two active variations
    of the same parent share a label, both are shown as
    "label (V<n>)" using the stable file suffix, so the combo never
    collapses two different entries into one row. Sorted by label, then
    naturally by entry name.

    Session 69: optional `owner_id` applies the active list's rule."""
    if not parent or parent == "None":
        return []
    check = make_active_checker(data_dir, owner_id, active_map, folder_maps)
    if not check("characters", parent):
        # Q8: an inactive parent makes its variations unreachable from
        # Builder. Guard here too, so a stale UI call cannot bypass the
        # parents-only list.
        return []
    rows = []
    for name in get_file_list(data_dir, "characters"):
        if variation_parent(data_dir, name) != parent:
            continue
        if not check("characters", name):
            continue
        rows.append((name, get_variation_label(data_dir, name)))
    counts = {}
    for _name, label in rows:
        key = label.casefold()
        counts[key] = counts.get(key, 0) + 1
    result = []
    for name, label in rows:
        if counts.get(label.casefold(), 0) > 1:
            suffix = _variation_suffix(name, parent)
            display = f"{label} (V{suffix})" if suffix else label
        else:
            display = label
        result.append((display, name))
    result.sort(key=lambda row: (row[0].casefold(), natural_sort_key(row[1])))
    return result


def next_variation_name(data_dir, parent):
    """Smallest free stable file base "<Parent>__V<n>" (n >= 1)."""
    if not parent:
        return None
    chars_dir = os.path.join(data_dir, "characters")
    try:
        existing = {os.path.splitext(f)[0] for f in os.listdir(chars_dir)
                    if f.endswith(".txt")}
    except OSError:
        existing = set()
    prefix = f"{parent}{VARIATION_NAME_SEP}"
    n = 1
    while f"{prefix}{n}" in existing:
        n += 1
    return f"{prefix}{n}"


def _variation_sibling_labels(data_dir, parent, exclude=None):
    labels = set()
    for name in get_file_list(data_dir, "characters"):
        if name == exclude:
            continue
        if variation_parent(data_dir, name) != parent:
            continue
        labels.add(get_variation_label(data_dir, name).casefold())
    return labels


def unique_variation_label(data_dir, parent, label, exclude=None):
    """Returns `label` if it is free among this parent's variations,
    otherwise "<label> copy", "<label> copy 2", ... (Q4). An empty
    label becomes "Variation" before uniquifying."""
    base = (label or "").strip() or "Variation"
    siblings = _variation_sibling_labels(data_dir, parent, exclude=exclude)
    if base.casefold() not in siblings:
        return base
    candidate = f"{base} copy"
    if candidate.casefold() not in siblings:
        return candidate
    n = 2
    while f"{base} copy {n}".casefold() in siblings:
        n += 1
    return f"{base} copy {n}"


def create_character_variation(data_dir, parent, folder_maps=None, folders_file=None,
                               active_map=None, active_file=None, label=None):
    """Creates a new variation of `parent`, copying the parent's current
    text as a snapshot (B1: copy, not delta). Returns the new entry name,
    or None when the parent is missing / is itself a variation.

    The new entry is active by default and inherits the parent's virtual
    folder. The label defaults to "Variation <n>"; the file name stays
    stable and independent of it."""
    parent = (parent or "").strip()
    if not parent or not _character_entry_exists(data_dir, parent):
        return None
    if is_variation(data_dir, parent):
        return None  # one level only
    new_name = next_variation_name(data_dir, parent)
    if not new_name:
        return None
    suffix = _variation_suffix(new_name, parent)
    new_label = (label or "").strip() or f"Variation {suffix}"
    content = read_file_content(data_dir, "characters", parent)
    chars_dir = os.path.join(data_dir, "characters")
    try:
        os.makedirs(chars_dir, exist_ok=True)
        with open(os.path.join(chars_dir, f"{new_name}.txt"), "w", encoding="utf-8") as f:
            f.write(content)
    except OSError:
        return None
    save_library_meta(data_dir, "characters", new_name,
                      variation_of=parent, variation_label=new_label)
    if folder_maps is not None and folders_file:
        parent_folder = get_entry_folder(folder_maps, "characters", parent)
        if parent_folder:
            set_entry_folder(folder_maps, folders_file, "characters", new_name, parent_folder)
    # New entries are active by default; absence of an inactive flag is
    # exactly that. active_map/active_file are accepted for signature
    # symmetry with the other lifecycle helpers.
    return new_name


def duplicate_character_variation(data_dir, name, folder_maps=None, folders_file=None,
                                  active_map=None, active_file=None):
    """Copies a variation, keeping the same parent and giving the copy
    the next "<label> copy", "<label> copy 2" label (Q4). Text, image
    and video are copied; the sidecar keeps the parent link but clears
    any canon-outfit alias. Returns the new entry name or None."""
    parent = variation_parent(data_dir, name)
    if not parent:
        return None
    new_name = next_variation_name(data_dir, parent)
    if not new_name:
        return None
    try:
        content = read_file_content(data_dir, "characters", name)
        with open(os.path.join(data_dir, "characters", f"{new_name}.txt"),
                  "w", encoding="utf-8") as f:
            f.write(content)
    except OSError:
        return None

    src_image = find_library_image(data_dir, "characters", name)
    if src_image:
        try:
            shutil.copyfile(src_image, library_image_path(data_dir, "characters", new_name))
        except OSError:
            pass
    old_meta = load_library_meta(data_dir, "characters", name)
    src_video = find_library_video(data_dir, "characters", name)
    if src_video:
        try:
            shutil.copyfile(
                src_video,
                library_video_path(data_dir, "characters", new_name, old_meta.get("video_ext")))
        except OSError:
            pass

    original_label = get_variation_label(data_dir, name)
    siblings = _variation_sibling_labels(data_dir, parent, exclude=name)
    new_label = f"{original_label} copy"
    if new_label.casefold() in siblings:
        n = 2
        while f"{original_label} copy {n}".casefold() in siblings:
            n += 1
        new_label = f"{original_label} copy {n}"

    save_library_meta(
        data_dir, "characters", new_name,
        source_url=old_meta.get("source_url"),
        lora=old_meta.get("lora"),
        lora_strength=old_meta.get("lora_strength", 1.0),
        force_first=old_meta.get("force_first", False),
        video_ext=old_meta.get("video_ext") if src_video else None,
        display_alias="",
        variation_of=parent,
        variation_label=new_label,
        loras=old_meta.get("loras") or {},
    )
    if folder_maps is not None and folders_file:
        old_folder = get_entry_folder(folder_maps, "characters", name)
        if old_folder:
            set_entry_folder(folder_maps, folders_file, "characters", new_name, old_folder)
    # Session 72: the copy carries the original's extra bindings, which
    # counts as assigning them (wake-once, D21).
    note_lora_assigned_for_bindings(
        data_dir, "characters", new_name, old_meta.get("loras") or {})
    return new_name


def get_character_dependents(data_dir, char_name):
    """Returns {"canon_outfits": [...], "variations": [...]} — the
    entries a rename/delete cascade must carry along. Used by the UI to
    build the confirmation text before calling the cascade helper."""
    result = {"canon_outfits": [], "variations": []}
    if not char_name:
        return result
    canon_prefix = f"{char_name}_Canon_"
    try:
        for f in os.listdir(os.path.join(data_dir, "outfits")):
            if f.endswith(".txt") and f.startswith(canon_prefix):
                result["canon_outfits"].append(os.path.splitext(f)[0])
    except OSError:
        pass
    result["canon_outfits"].sort(key=natural_sort_key)
    result["variations"] = [
        name for name in get_file_list(data_dir, "characters")
        if variation_parent(data_dir, name) == char_name
    ]
    return result


def _rename_library_entry_artifacts(data_dir, category, old_name, new_name):
    """Moves .txt/image/video/meta together. Video must move before the
    meta sidecar (rename_library_video reads the old sidecar to learn
    the video's extension)."""
    if not old_name or not new_name or old_name == new_name:
        return
    rename_library_video(data_dir, category, old_name, new_name)
    rename_library_image(data_dir, category, old_name, new_name)
    rename_library_meta(data_dir, category, old_name, new_name)
    old_txt = os.path.join(data_dir, category, f"{old_name}.txt")
    if os.path.exists(old_txt):
        try:
            cat_dir = os.path.join(data_dir, category)
            os.makedirs(cat_dir, exist_ok=True)
            new_txt = os.path.join(cat_dir, f"{new_name}.txt")
            if os.path.exists(new_txt):
                os.remove(new_txt)
            shutil.move(old_txt, new_txt)
        except OSError:
            pass


def _delete_library_entry_artifacts(data_dir, category, name):
    if not name:
        return
    try:
        path = os.path.join(data_dir, category, f"{name}.txt")
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass
    delete_library_image(data_dir, category, name)
    delete_library_video(data_dir, category, name)
    delete_library_meta(data_dir, category, name)


def rename_character_with_dependents(data_dir, old_name, new_name,
                                     folder_maps=None, folders_file=None,
                                     active_map=None, active_file=None):
    """Session 57 Q2 cascade: rename a character together with its canon
    outfits ("<old>_Canon_N") and variations ("<old>__V<n>"), including
    image/video/meta/folder/active entries and each variation's
    `variation_of` link. Returns a summary dict with the new names.

    This also closes the pre-existing gap where renaming a character
    left its canon outfits under the old prefix. No-op (and
    `renamed: False`) when the old entry is missing, the new name is
    empty/identical, or the target already exists."""
    result = {"canon_outfits": [], "variations": [], "renamed": False}
    old_name = (old_name or "").strip()
    new_name = (new_name or "").strip()
    if not old_name or not new_name or old_name == new_name:
        return result
    if not _character_entry_exists(data_dir, old_name):
        return result
    if _character_entry_exists(data_dir, new_name):
        return result

    dependents = get_character_dependents(data_dir, old_name)

    for old_base in dependents["canon_outfits"]:
        rest = old_base[len(old_name) + len("_Canon_"):]
        new_base = f"{new_name}_Canon_{rest}"
        _rename_library_entry_artifacts(data_dir, "outfits", old_base, new_base)
        if folder_maps is not None and folders_file:
            rename_entry_folder_entry(folder_maps, folders_file, "outfits", old_base, new_base)
        if active_map is not None and active_file:
            rename_entry_active_entry(active_map, active_file, "outfits", old_base, new_base)
        rename_entry_active_all_owners(data_dir, "outfits", old_base, new_base)
        result["canon_outfits"].append(new_base)

    for old_var in dependents["variations"]:
        suffix = _variation_suffix(old_var, old_name)
        target = f"{new_name}{VARIATION_NAME_SEP}{suffix}" if suffix else None
        if not target or _character_entry_exists(data_dir, target):
            target = next_variation_name(data_dir, new_name)
        if not target:
            continue
        _rename_library_entry_artifacts(data_dir, "characters", old_var, target)
        update_library_meta(data_dir, "characters", target, variation_of=new_name)
        if folder_maps is not None and folders_file:
            rename_entry_folder_entry(folder_maps, folders_file, "characters", old_var, target)
        if active_map is not None and active_file:
            rename_entry_active_entry(active_map, active_file, "characters", old_var, target)
        rename_entry_active_all_owners(data_dir, "characters", old_var, target)
        result["variations"].append(target)

    _rename_library_entry_artifacts(data_dir, "characters", old_name, new_name)
    if folder_maps is not None and folders_file:
        rename_entry_folder_entry(folder_maps, folders_file, "characters", old_name, new_name)
    if active_map is not None and active_file:
        rename_entry_active_entry(active_map, active_file, "characters", old_name, new_name)
    rename_entry_active_all_owners(data_dir, "characters", old_name, new_name)
    result["renamed"] = True
    return result


def delete_character_with_dependents(data_dir, char_name,
                                     folder_maps=None, folders_file=None,
                                     active_map=None, active_file=None):
    """Session 57 Q1 cascade: delete a character plus its canon outfits
    and variations (with all their artifacts/folder/active entries).
    Deleting a variation only removes that variation; its parent stays.
    Returns {"canon_outfits": [...], "variations": [...], "deleted": bool}."""
    result = {"canon_outfits": [], "variations": [], "deleted": False}
    if not char_name or not _character_entry_exists(data_dir, char_name):
        return result
    dependents = get_character_dependents(data_dir, char_name)

    for name in dependents["variations"]:
        _delete_library_entry_artifacts(data_dir, "characters", name)
        if folder_maps is not None and folders_file:
            remove_entry_folder_entry(folder_maps, folders_file, "characters", name)
        if active_map is not None and active_file:
            remove_entry_active_entry(active_map, active_file, "characters", name)
        remove_entry_active_all_owners(data_dir, "characters", name)
    result["variations"] = dependents["variations"]

    for name in dependents["canon_outfits"]:
        _delete_library_entry_artifacts(data_dir, "outfits", name)
        if folder_maps is not None and folders_file:
            remove_entry_folder_entry(folder_maps, folders_file, "outfits", name)
        if active_map is not None and active_file:
            remove_entry_active_entry(active_map, active_file, "outfits", name)
        remove_entry_active_all_owners(data_dir, "outfits", name)
    result["canon_outfits"] = dependents["canon_outfits"]

    _delete_library_entry_artifacts(data_dir, "characters", char_name)
    if folder_maps is not None and folders_file:
        remove_entry_folder_entry(folder_maps, folders_file, "characters", char_name)
    if active_map is not None and active_file:
        remove_entry_active_entry(active_map, active_file, "characters", char_name)
    remove_entry_active_all_owners(data_dir, "characters", char_name)
    result["deleted"] = True
    return result


def promote_orphan_variations(data_dir, names=None):
    """Clears variation_of/variation_label on character entries whose
    parent no longer exists, turning them back into ordinary parents.
    `names` limits the scan (import passes only what it just copied).
    Returns the list of promoted entry names.

    The sidecar is rewritten through update_library_meta, so unrelated
    fields (source_url/LoRA/video/alias) survive; if nothing else is
    stored, save_library_meta removes the now-empty sidecar."""
    if names is None:
        candidates = get_file_list(data_dir, "characters")
    else:
        candidates = list(names)
    promoted = []
    for name in candidates:
        meta = load_library_meta(data_dir, "characters", name)
        parent = meta.get("variation_of")
        if not parent:
            continue
        if parent == name or not _character_entry_exists(data_dir, parent):
            update_library_meta(data_dir, "characters", name,
                                variation_of="", variation_label="")
            promoted.append(name)
    return promoted


# ============================================================
#                  LIBRARY EXPORT / IMPORT (zip)
# ============================================================
def export_library(data_dir, dest_path):
    """'📦 Export library' — zips the whole data_dir tree (every
    category's .txt/.jpg/.meta.json triplets, _folders.json, templates,
    settings, history) EXCEPT _comfy_previews/, which is a disposable
    session-only cache (see init_folders) that has no business in a
    library backup or a bundle meant to be shared with someone else.

    Relative paths inside the zip exactly mirror data_dir's own layout
    (e.g. "characters/Megumin.txt") — that's what lets
    merge_imported_library() below just walk the archive by category
    without any special-casing, and lets someone unzip it by hand and
    get back the exact folder structure if they ever need to.

    Raises LibraryExportImportError on failure. Returns dest_path on
    success — the UI layer (Session 7) is responsible for the
    QFileDialog save-path picker and the success/failure QMessageBox."""
    try:
        with zipfile.ZipFile(dest_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(data_dir):
                dirs[:] = [d for d in dirs
                           if d != "_comfy_previews" and not d.startswith("_import_tmp_")]
                for fname in files:
                    full_path = os.path.join(root, fname)
                    rel_path = os.path.relpath(full_path, data_dir)
                    zf.write(full_path, arcname=rel_path)
    except Exception as e:
        raise LibraryExportImportError(f"Failed to create the zip file:\n{e}") from e
    return dest_path


def extract_library_zip(zip_path, tmp_dir):
    """Extracts zip_path into tmp_dir with a zip-slip guard: any member
    whose resolved path would land outside tmp_dir (e.g. "../../etc/
    passwd" or an absolute path baked into the archive) is rejected and
    the whole extraction is aborted before anything is written — a
    malformed or hostile zip must never be able to write outside the
    sandbox tmp_dir is meant to be.

    Raises LibraryExportImportError for a bad zip, an unsafe path, or
    any other read failure. Caller is responsible for creating and
    later cleaning up tmp_dir (shutil.rmtree in a finally block, same
    as the original)."""
    os.makedirs(tmp_dir, exist_ok=True)
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            tmp_dir_real = os.path.realpath(tmp_dir)
            for member in zf.namelist():
                member_path = os.path.realpath(os.path.join(tmp_dir, member))
                if not (member_path == tmp_dir_real
                        or member_path.startswith(tmp_dir_real + os.sep)):
                    raise LibraryExportImportError(
                        f"This zip file contains an unsafe path and was rejected:\n{member}")
            zf.extractall(tmp_dir)
    except zipfile.BadZipFile as e:
        raise LibraryExportImportError("That file isn't a valid zip archive.") from e
    except LibraryExportImportError:
        raise
    except Exception as e:
        raise LibraryExportImportError(f"Failed to read the zip file:\n{e}") from e


def merge_imported_library(data_dir, extracted_dir, categories, folder_maps, folders_file,
                            active_map=None, active_file=None, report=None):
    """Walks an already-extracted, already-zip-slip-checked library tree
    and copies in only the entries that don't already exist (by name)
    in the corresponding category — strict skip-on-collision: an
    existing entry is left completely untouched (not overwritten, not
    renamed, not merged); the incoming one is skipped. Canon outfits
    ride along with their owning character's category scan
    automatically, since they're just .txt files in outfits/ with
    "_Canon_" in the name — no special-casing needed here, the same
    skip-on-collision rule protects them exactly like any other outfit
    entry.

    Also merges per-category folder placement (_folders.json) for
    whatever just got imported, WITHOUT touching the placement of any
    entry that already existed (those were never touched above
    either).

    Returns (imported, skipped), each a list of (category, name).

    Session 58: after copying, an imported character whose
    `variation_of` points to a parent that does not exist in the merged
    library is promoted to an ordinary parent (both variation keys are
    cleared) instead of remaining an unreachable orphan. The optional
    `report` dict receives `report["orphan_variations"]` with the
    promoted names; leaving it out keeps the old return contract
    unchanged. A link whose parent does exist is kept as-is, because
    entry names are the identity even when an import collided with an
    existing same-named character."""
    imported = []
    skipped = []
    for category in categories:
        src_cat_dir = os.path.join(extracted_dir, category)
        if not os.path.isdir(src_cat_dir):
            continue
        dest_cat_dir = os.path.join(data_dir, category)
        os.makedirs(dest_cat_dir, exist_ok=True)
        for fname in sorted(os.listdir(src_cat_dir), key=natural_sort_key):
            if not fname.endswith(".txt"):
                continue  # the matching .jpg/.meta.json (if any) ride along below
            name = os.path.splitext(fname)[0]
            dest_txt = os.path.join(dest_cat_dir, fname)
            if os.path.exists(dest_txt):
                skipped.append((category, name))
                continue
            try:
                shutil.copyfile(os.path.join(src_cat_dir, fname), dest_txt)
                for ext in (".jpg", LIBRARY_META_EXT):
                    src_sidecar = os.path.join(src_cat_dir, f"{name}{ext}")
                    if os.path.exists(src_sidecar):
                        shutil.copyfile(src_sidecar, os.path.join(dest_cat_dir, f"{name}{ext}"))
                # Session 48.4: a video sidecar's extension isn't one of
                # the fixed ones above -- it's whatever VIDEO_EXTENSIONS
                # member the meta JSON we just copied says it is. An
                # older, pre-48.4 exported library simply has no
                # "video_ext" key (load_library_meta already defaults
                # that to None), so this is a no-op for those --
                # exactly the "old exports must keep importing cleanly"
                # requirement the additionalfeatures.md writeup called
                # out up front.
                src_meta = load_library_meta(extracted_dir, category, name)
                video_ext = src_meta.get("video_ext")
                if video_ext:
                    src_video = os.path.join(src_cat_dir, f"{name}{video_ext}")
                    if os.path.exists(src_video):
                        shutil.copyfile(src_video, os.path.join(dest_cat_dir, f"{name}{video_ext}"))
                imported.append((category, name))
            except Exception:
                skipped.append((category, name))

    src_folders_path = os.path.join(extracted_dir, LIBRARY_FOLDERS_FILE_NAME)
    if os.path.exists(src_folders_path):
        try:
            with open(src_folders_path, "r", encoding="utf-8") as f:
                src_folder_maps = json.load(f)
            if isinstance(src_folder_maps, dict):
                for category, name in imported:
                    folder_path = src_folder_maps.get(category, {}).get(name)
                    if folder_path:
                        set_entry_folder(folder_maps, folders_file, category, name, folder_path)
        except Exception:
            pass  # folder placement is cosmetic — never worth failing the whole import over

    # Session 45: carry over inactive state (entries + folders) for
    # whatever just got imported — same "missing key defaults to
    # active" rule as everywhere else, so an older export with no
    # _active.json at all just leaves everything active (a no-op here).
    if active_map is not None and active_file is not None:
        src_active_path = os.path.join(extracted_dir, LIBRARY_ACTIVE_FILE_NAME)
        if os.path.exists(src_active_path):
            try:
                with open(src_active_path, "r", encoding="utf-8") as f:
                    src_active_raw = json.load(f)
                if isinstance(src_active_raw, dict):
                    for category, name in imported:
                        src_entries = set(src_active_raw.get(category, {}).get("entries", []) or [])
                        if name in src_entries:
                            set_entries_active(active_map, active_file, category, [name], False)
                    for category in categories:
                        src_folders = set(src_active_raw.get(category, {}).get("folders", []) or [])
                        for folder_path in src_folders:
                            # Only carry over inactive-folder flags for
                            # folders that actually exist in the merged
                            # result (either pre-existing or just
                            # created by the folder-placement merge
                            # above) — an inactive flag for a folder
                            # with nothing in it either way is harmless
                            # to add, so no extra existence check here.
                            set_folders_active(active_map, active_file, category, [folder_path], False)
            except Exception:
                pass  # same "cosmetic, never worth failing the import" rule as folder placement

    # Session 65: LoRA profiles referenced by the imported sidecars are
    # matched by id and added when missing (see merge_imported_lora_profiles).
    added_profiles = merge_imported_lora_profiles(data_dir, extracted_dir, imported)
    if isinstance(report, dict):
        report["added_lora_profiles"] = added_profiles

    # Session 58: orphan-variation policy. Parent names are identities,
    # so a link is kept whenever the parent exists after the merge; if
    # it does not, clear the keys and report the promotion instead of
    # leaving an entry that no Builder list can reach.
    imported_characters = [name for category, name in imported
                           if category == "characters"]
    promoted = promote_orphan_variations(data_dir, imported_characters)
    if isinstance(report, dict):
        report["orphan_variations"] = promoted

    return imported, skipped


# ============================================================
#          GALLERY (Session 8) — output-folder resolution
#          and cross-platform "reveal in explorer"
# ============================================================
# These two are pure OS-interaction helpers with zero PyQt dependency,
# ported from the original's `_resolve_output_folder_for` /
# `_reveal_file_in_explorer` / `_win_bring_explorer_to_front` (all
# plain PromptForgeApp methods in the monolith, none of which actually
# touched Tkinter widgets). Homed in file_manager.py rather than a new
# module since they're "file/OS" concerns, not image/metadata ones —
# and because the Builder tab's own "📂 Open output folder" button
# (Session 10/11) will call the exact same two functions, so this is
# their one shared home rather than something gallery_tab.py would
# otherwise have to duplicate or the Builder tab would have to import
# from a UI-layer module.
def save_comfy_preview_image(data_dir, img_bytes, seq_num, ext=".png"):
    """Writes one freshly-generated image's bytes to
    `<data_dir>/_comfy_previews/result_NNN<ext>` and returns the path.
    Each result gets its own numbered file rather than overwriting a
    single "last result" file — this is what backs the Gallery tab,
    letting it show every image generated this session, not just the
    most recent one. The whole `_comfy_previews/` folder is wiped on
    every startup (see `init_folders`), so these never pile up across
    sessions. `seq_num` is the caller's own per-session counter (the
    Builder tab's `_comfy_session_image_counter`) — kept as a plain
    parameter rather than state in this module, since this is a pure
    file-write helper, not something that should be tracking session
    state of its own.

    Raises FileManagerError on failure — same messagebox-turned-
    exception pattern as everywhere else in this module."""
    previews_dir = os.path.join(data_dir, "_comfy_previews")
    try:
        os.makedirs(previews_dir, exist_ok=True)
        path = os.path.join(previews_dir, f"result_{seq_num:03d}{ext}")
        with open(path, "wb") as f:
            f.write(img_bytes)
    except OSError as e:
        raise FileManagerError(f"Could not save preview image: {e}") from e
    return path


def resolve_output_folder_for(out_dir, remote_subfolder):
    """Resolves `out_dir/remote_subfolder` (or just `out_dir` if no
    subfolder) to a real, existing directory. Returns None if `out_dir`
    is falsy or the resolved path doesn't exist — callers fall back to
    a local preview-cache copy in that case.

    Unlike the original's `_resolve_output_folder_for`, this does not
    itself go fetch `out_dir` from a live ComfyUI connection — that's a
    network call and belongs on the caller's side (the tab/worker that
    actually owns a `ComfyUIClient`), not in this pure file-system
    helper. Callers pass in whatever `out_dir` they already have (or
    None if it hasn't been discovered yet)."""
    if not out_dir:
        return None
    folder = os.path.join(out_dir, remote_subfolder) if remote_subfolder else out_dir
    return folder if os.path.isdir(folder) else None


def win_bring_explorer_to_front(pid):
    """Best-effort: lets a freshly-launched Windows Explorer window
    foreground itself over the app, via the same narrow
    AllowSetForegroundWindow exception the original used. Silently
    does nothing on non-Windows platforms or if ctypes/the call fails —
    harmless either way, purely cosmetic."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.user32.AllowSetForegroundWindow(pid)
    except Exception:
        pass


def reveal_file_in_explorer(target_file, folder):
    """Opens `folder` in the OS file explorer with `target_file`
    selected/highlighted if possible (Windows "Show in folder" / macOS
    Finder "Reveal"). Falls back to just opening the folder when the
    file can't be located there, or on Linux, which has no universal
    cross-desktop-environment way to highlight a single file.

    Raises FileManagerError on failure (own OS-call seam, same pattern
    as every other messagebox-turned-exception in this module) — the
    UI layer catches it and shows a QMessageBox with str(exc)."""
    try:
        if sys.platform == "win32":
            if os.path.isfile(target_file):
                proc = subprocess.Popen(["explorer", "/select,", os.path.normpath(target_file)])
                win_bring_explorer_to_front(proc.pid)
            else:
                os.startfile(folder)
        elif sys.platform == "darwin":
            if os.path.isfile(target_file):
                subprocess.Popen(["open", "-R", target_file])
            else:
                subprocess.Popen(["open", folder])
        else:
            subprocess.Popen(["xdg-open", folder])
    except Exception as e:
        raise FileManagerError(f"Could not open folder:\n{e}") from e
