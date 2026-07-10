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
import json
import os
import shutil
import subprocess
import sys
import zipfile

from backend.constants import (
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
    LoRA sidebar itself has always used for a brand-new slot."""
    empty = {"source_url": None, "lora": None, "lora_strength": 1.0, "force_first": False,
             "video_ext": None}
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
        }
    except Exception:
        return empty


def save_library_meta(data_dir, category, name, source_url=None, lora=None,
                       lora_strength=1.0, force_first=False, video_ext=None):
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
    instead of two."""
    if not name:
        return
    try:
        strength = float(lora_strength) if lora_strength is not None else 1.0
    except (TypeError, ValueError):
        strength = 1.0
    if not source_url and not lora and not force_first and strength == 1.0 and not video_ext:
        delete_library_meta(data_dir, category, name)
        return
    path = library_meta_path(data_dir, category, name)
    try:
        cat_dir = os.path.join(data_dir, category)
        if not os.path.exists(cat_dir):
            os.makedirs(cat_dir)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"source_url": source_url or None, "lora": lora or None,
                       "lora_strength": strength,
                       "force_first": bool(force_first),
                       "video_ext": video_ext or None}, f, ensure_ascii=False, indent=2)
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


def get_active_file_list(data_dir, category, folder_maps, active_map):
    """Session 45: Builder-facing variant of get_file_list — same
    listing, minus anything inactive (the entry itself, or filed under
    an inactive folder). The Library tab's own browsing/search never
    calls this; it keeps using plain get_file_list so inactive entries
    stay fully visible/searchable there."""
    return [
        name for name in get_file_list(data_dir, category)
        if is_entry_active(active_map, folder_maps, category, name)
    ]


def list_active_outfit_options_for_character(data_dir, char_name, folder_maps, active_map):
    """Session 45: Builder-facing variant of
    list_outfit_options_for_character — canon outfits are filtered by
    their own (auto-filed, Canonical Outfits folder) active state, and
    shared outfits by get_active_file_list above."""
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
                if not is_entry_active(active_map, folder_maps, "outfits", base):
                    continue
                num = base[len(canon_prefix):]
                canon_nums.append(num)
    except OSError:
        canon_nums = []
    for num in sorted(canon_nums, key=natural_sort_key):
        options.append(f"Canon {num}")

    options.extend(get_active_file_list(data_dir, "outfits", folder_maps, active_map))
    return options


def list_outfit_options_for_character(data_dir, char_name):
    """Builder-tab helper (ported from the original's inline
    `update_outfit_list`): returns the outfit dropdown contents for a
    specific selected character — that character's own canon outfits
    first (as "Canon N", sorted numerically), followed by every shared
    (non-canon) outfit in the library. Always starts with "None".
    Returns just ["None"] if char_name is empty/"None"."""
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
                            active_map=None, active_file=None):
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

    Returns (imported, skipped), each a list of (category, name)."""
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
