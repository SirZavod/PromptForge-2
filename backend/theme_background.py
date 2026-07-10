"""Session 40 — storage for the Custom theme's optional background
image. Same "copy the file in, reference it by path from settings from
then on, never bundle it" precedent Session 37 set for custom sounds
(see additionalfeatures.md, SESSION 40) — kept as its own small module
rather than piling onto `file_manager.py`, matching how `sound_manager.py`
and `theme_derive.py` already sit alongside it as focused, single-purpose
backend modules.
"""
import glob
import os
import shutil

from backend.constants import (
    BACKGROUND_IMAGE_EXTENSIONS,
    BACKGROUND_IMAGE_STEM,
    THEME_ASSETS_DIR_NAME,
)


def theme_assets_dir(data_dir: str) -> str:
    path = os.path.join(data_dir, THEME_ASSETS_DIR_NAME)
    os.makedirs(path, exist_ok=True)
    return path


def _existing_background_paths(data_dir: str):
    return glob.glob(os.path.join(theme_assets_dir(data_dir), BACKGROUND_IMAGE_STEM + ".*"))


def set_background_image(data_dir: str, source_path: str) -> str:
    """Copies `source_path` into `<data_dir>/theme/background<ext>`,
    replacing any previous background image (only one can be active at
    a time — this isn't a library like Session 37's per-action custom
    sounds, just one slot on the current Custom theme). Raises
    `ValueError` for an unrecognized extension rather than silently
    accepting something `QPixmap` can't load. Returns the stored path,
    which is what gets written into `settings["custom_theme_bg_image"]`.
    """
    ext = os.path.splitext(source_path)[1].lower()
    if ext not in BACKGROUND_IMAGE_EXTENSIONS:
        raise ValueError(
            f"Unsupported image type '{ext}'. Supported: {', '.join(BACKGROUND_IMAGE_EXTENSIONS)}")
    clear_background_image(data_dir)
    dest = os.path.join(theme_assets_dir(data_dir), BACKGROUND_IMAGE_STEM + ext)
    shutil.copyfile(source_path, dest)
    return dest


def clear_background_image(data_dir: str) -> None:
    for existing in _existing_background_paths(data_dir):
        try:
            os.remove(existing)
        except OSError:
            pass


def resolve_background_path(stored_path: str | None) -> str | None:
    """Runtime backstop for the "moved/deleted on disk after being
    set" case the plan called out — returns `stored_path` unchanged if
    it still exists, `None` otherwise, so callers fail gracefully back
    to the plain derived color instead of erroring out on launch."""
    if stored_path and os.path.isfile(stored_path):
        return stored_path
    return None
