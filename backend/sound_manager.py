"""Sound notifications (Session 37) — resolving *which* file should
play for a given action key, and actually playing it via
`PyQt6.QtMultimedia.QSoundEffect`.

Deliberately reads `settings.json` fresh off disk on every call rather
than taking an in-memory `settings` dict from the caller: the three
trigger points that need this (`BuilderTab`, `HistoryTab`, `LibraryTab`)
don't all currently hold a live reference to `MainWindow`'s settings
dict, and threading one through everywhere just for this would be a
bigger change than the feature warrants. The Settings page's own
`_save_settings()` already writes synchronously on every change, so a
fresh read here is never stale by more than the current call.

See `additionalfeatures.md`'s SESSION 37 for the full design writeup
(storage layout, per-sound volume keying, missing-file handling).
"""
import glob
import os
import sys

from backend.constants import (
    BUNDLED_SOUNDS_SUBDIR,
    DEFAULT_SOUND_VOLUME,
    SETTINGS_FILE_NAME,
    SOUND_ACTIONS,
    SOUNDS_DIR_NAME,
)
from backend.file_manager import load_json, save_json

try:
    from PyQt6.QtCore import QUrl
    from PyQt6.QtMultimedia import QSoundEffect
    _QSOUND_AVAILABLE = True
except Exception:
    QUrl = None
    QSoundEffect = None
    _QSOUND_AVAILABLE = False

# Kept alive here so a fire-and-forget `play()` isn't garbage-collected
# mid-playback -- QSoundEffect objects are removed from this list once
# their own `playingChanged` signal reports they're done.
_ACTIVE_EFFECTS = []


def _settings_path(data_dir: str) -> str:
    return os.path.join(data_dir, SETTINGS_FILE_NAME)


def bundled_assets_dir() -> str:
    """Where bundled ("Default") assets live. Deliberately its own
    tiny standalone resolver rather than importing `main._app_root_dir`
    (that one resolves to **the folder next to the .exe** -- the right
    rule for user-editable things, but wrong for assets baked *inside*
    a PyInstaller bundle, which live under `sys._MEIPASS` instead).
    Kept self-contained here so every call site (Builder/History/
    Library) can resolve it without a dependency on `main.py`."""
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _bundled_default_path(action_key: str) -> str:
    return os.path.join(bundled_assets_dir(), BUNDLED_SOUNDS_SUBDIR, f"{action_key}.wav")


def _find_custom_file(data_dir: str, action_key: str, idx: str):
    """Custom sounds are stored as `<idx>.<original-ext>` -- the
    extension isn't known ahead of time, so glob for it."""
    action_dir = os.path.join(data_dir, SOUNDS_DIR_NAME, action_key)
    matches = glob.glob(os.path.join(action_dir, f"{idx}.*"))
    return matches[0] if matches else None


def list_custom_sounds(data_dir: str, action_key: str) -> list:
    """Returns sorted (idx: int, path: str) tuples for every custom
    sound currently on disk for this action -- drives the "[User N]"
    entries in the Settings dropdown."""
    action_dir = os.path.join(data_dir, SOUNDS_DIR_NAME, action_key)
    if not os.path.isdir(action_dir):
        return []
    out = []
    for path in glob.glob(os.path.join(action_dir, "*")):
        stem = os.path.splitext(os.path.basename(path))[0]
        if stem.isdigit():
            out.append((int(stem), path))
    out.sort(key=lambda pair: pair[0])
    return out


def next_custom_slot(data_dir: str, action_key: str) -> int:
    existing = list_custom_sounds(data_dir, action_key)
    return (existing[-1][0] + 1) if existing else 1


def add_custom_sound(data_dir: str, action_key: str, source_path: str) -> str:
    """Copies `source_path` into that action's subfolder under the next
    free integer name, validates it actually loads, and returns the
    `"custom:N"` selector string. Raises `ValueError` if the file
    doesn't load as a real sound -- validated by attempting a real
    load, not by trusting the extension (a user can pick literally
    anything through the OS file picker)."""
    import shutil

    ext = os.path.splitext(source_path)[1] or ".wav"
    if ext.lower() != ".wav":
        raise ValueError(
            "Only .wav files are supported for sound notifications. "
            "QSoundEffect (the low-latency audio engine PromptForge uses "
            "for these short notification blips) only reliably decodes "
            "uncompressed WAV -- compressed formats like MP3/OGG may "
            "silently fail to play depending on the system's codecs. "
            "Convert the file to .wav (e.g. with ffmpeg: "
            "`ffmpeg -i input.mp3 output.wav`) and try again.")

    idx = next_custom_slot(data_dir, action_key)
    action_dir = os.path.join(data_dir, SOUNDS_DIR_NAME, action_key)
    os.makedirs(action_dir, exist_ok=True)
    dest_path = os.path.join(action_dir, f"{idx}{ext}")
    shutil.copyfile(source_path, dest_path)

    if not _validate_loads(dest_path):
        try:
            os.remove(dest_path)
        except OSError:
            pass
        raise ValueError(
            "That file couldn't be loaded as a sound. Try a different file "
            "(WAV works everywhere; MP3/OGG depend on your system's codecs).")

    return f"custom:{idx}"


def delete_custom_sound(data_dir: str, action_key: str, idx: int) -> None:
    path = _find_custom_file(data_dir, action_key, str(idx))
    if path and os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass


def _validate_loads(path: str) -> bool:
    """Best-effort load check. Without a running QApplication event
    loop `status()` may not have settled the instant after `setSource`,
    so this treats an immediately-reported Error status as a hard
    rejection but otherwise gives the file the benefit of the doubt --
    the real backstop is `resolve_sound_path`'s missing-file handling,
    which catches anything that still won't actually play later."""
    if not _QSOUND_AVAILABLE:
        return os.path.exists(path)
    effect = QSoundEffect()
    effect.setSource(QUrl.fromLocalFile(path))
    status = effect.status()
    # QSoundEffect.Status: Null=0, Loading=1, Ready=2, Error=3
    return status != 3


def resolve_sound_path(data_dir: str, action_key: str):
    """Returns (path_or_None, volume_0_to_1). Encodes the
    none/default/custom:N priority and the missing-file -> reset-to-
    none fallback (persisted immediately, same as the startup check)."""
    settings_path = _settings_path(data_dir)
    settings = load_json(settings_path, {})
    sounds_cfg = settings.get("sounds", {})
    action_cfg = sounds_cfg.get(action_key, {})
    selected = action_cfg.get("selected", "none")

    if selected == "none":
        return None, 0.0

    if selected == "default":
        path = _bundled_default_path(action_key)
        if not os.path.exists(path):
            return None, 0.0
        volume = settings.get("sound_volumes", {}).get(action_key, {}).get("default", DEFAULT_SOUND_VOLUME)
        return path, max(0.0, min(1.0, volume / 100.0))

    if selected.startswith("custom:"):
        idx = selected.split(":", 1)[1]
        path = _find_custom_file(data_dir, action_key, idx)
        if not path:
            # Missing-file handling: deliberately reset to "none", not
            # "default" -- the user picking a specific file was a
            # deliberate choice; silently substituting a different
            # sound they never chose would be worse than going silent.
            sounds_cfg[action_key] = {"selected": "none"}
            settings["sounds"] = sounds_cfg
            save_json(settings_path, settings)
            return None, 0.0
        volume = settings.get("sound_volumes", {}).get(action_key, {}).get(selected, DEFAULT_SOUND_VOLUME)
        return path, max(0.0, min(1.0, volume / 100.0))

    return None, 0.0


def play(data_dir: str, action_key: str) -> None:
    """Fire-and-forget playback for `action_key`. A no-op if the
    action's resolved choice is "none", the file is missing, or
    QtMultimedia isn't available (headless test environments)."""
    if not _QSOUND_AVAILABLE:
        return
    path, volume = resolve_sound_path(data_dir, action_key)
    if not path:
        return

    effect = QSoundEffect()
    effect.setSource(QUrl.fromLocalFile(path))
    effect.setVolume(volume)
    _ACTIVE_EFFECTS.append(effect)

    def _discard():
        if effect in _ACTIVE_EFFECTS:
            _ACTIVE_EFFECTS.remove(effect)

    def _on_playing_changed():
        if not effect.isPlaying():
            _discard()

    # Session 49 audit fix: `playingChanged` only fires on an actual
    # play->stop transition. If `setSource`/`play()` fails outright
    # (bad file, no audio device, decode error -- `status()` reports
    # QSoundEffect.Status.Error), the effect never starts playing in
    # the first place, so `playingChanged` never fires at all and the
    # object sat in `_ACTIVE_EFFECTS` for the rest of the app's life --
    # a small but unbounded leak (one per failed play() call). Cover
    # that path via `statusChanged` too: once status settles on Error,
    # discard immediately instead of waiting for a playingChanged that
    # is never coming.
    def _on_status_changed():
        if effect.status() == QSoundEffect.Status.Error:
            _discard()

    effect.playingChanged.connect(_on_playing_changed)
    effect.statusChanged.connect(_on_status_changed)
    effect.play()


def startup_check(data_dir: str) -> list:
    """Scans all three actions' `"selected"` values for a dangling
    `custom:N` once at app startup (not waited-for at the next matching
    event, so a deleted file surfaces as a single one-time notice
    instead of unexplained silence mid-session). Resets any dangling
    selection to "none" and returns the list of action keys that were
    reset, for the caller to show a notice about."""
    settings_path = _settings_path(data_dir)
    settings = load_json(settings_path, {})
    sounds_cfg = settings.get("sounds", {})
    reset_actions = []

    for action_key in SOUND_ACTIONS:
        action_cfg = sounds_cfg.get(action_key, {})
        selected = action_cfg.get("selected", "none")
        if not selected.startswith("custom:"):
            continue
        idx = selected.split(":", 1)[1]
        if _find_custom_file(data_dir, action_key, idx) is None:
            sounds_cfg[action_key] = {"selected": "none"}
            reset_actions.append(action_key)

    if reset_actions:
        settings["sounds"] = sounds_cfg
        save_json(settings_path, settings)

    return reset_actions
