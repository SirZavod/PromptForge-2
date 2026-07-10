# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for PromptForge (PyQt6 build).

Build with:
    pyinstaller PromptForge.spec

Produces a single-file, windowed (no console) executable. `icon.ico`
is bundled if present next to this spec file (same lookup MainWindow's
own `_apply_app_icon` does at runtime via `_app_root_dir()` — that
function's `sys.frozen`/`sys.executable` branch is exactly what
resolves correctly inside a --onefile build, which is why main.py has
its own root-dir helper instead of reusing `backend.file_manager.
app_dir()` — see main.py's own docstring on that).

`prompt_forge_data/` is intentionally NOT bundled as a datas entry —
it's the user's actual library/history/settings, created fresh via
`init_folders()` next to the running executable on first launch (or
already present there from a previous run/copy). Bundling it would
freeze a snapshot of dev-machine data inside the .exe itself, which is
never what's wanted for an end-user build.
"""
import os

block_cipher = None

SPEC_DIR = os.path.dirname(os.path.abspath(SPEC))
ICON_PATH = os.path.join(SPEC_DIR, "icon.ico")

a = Analysis(
    ["main.py"],
    pathex=[SPEC_DIR],
    binaries=[],
    datas=[("assets/sounds", "assets/sounds")],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter"],  # the whole point of this migration
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="PromptForge",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON_PATH if os.path.exists(ICON_PATH) else None,
)
