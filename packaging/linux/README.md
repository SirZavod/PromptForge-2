# Linux desktop integration (optional)

The onefile binary runs fine without this — `promptforge.desktop` is
only for users who want PromptForge to show up in their applications
menu / app launcher (GNOME Activities, KDE menu, etc.) instead of
being run by double-clicking the binary directly.

This is **not** wired into the automated build — it's a handful of
files a user (or a future packaging step) copies into place, because
a bare downloaded binary has no fixed install location for the
`.desktop` spec's `Exec=`/`Icon=` paths to point at reliably.

## Manual install (per-user, no root needed)

```bash
mkdir -p ~/.local/share/applications ~/.local/share/icons/hicolor/256x256/apps
cp promptforge.desktop ~/.local/share/applications/
cp icon.png ~/.local/share/icons/hicolor/256x256/apps/promptforge.png
# Edit Exec= in the copied .desktop file to the actual full path
# to wherever PromptForge's binary was extracted/placed, e.g.:
#   Exec=/home/youruser/Apps/PromptForge/PromptForge %F
update-desktop-database ~/.local/share/applications 2>/dev/null || true
```

After that, PromptForge shows up searchable in the applications menu
with its own icon, same as a normally-installed app.

## Why this isn't automated yet

Doing this automatically would mean either shipping an installer
script that writes to `~/.local/share/...` on first run, or switching
distribution format entirely (AppImage, .deb, Flatpak all handle this
themselves). That's the "Distribution format" decision flagged in
`additionalfeatures.md` Session 50 — deliberately left as a manual
step for now rather than building installer infrastructure around a
distribution format decision that hasn't been made yet.
