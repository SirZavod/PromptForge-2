"""Session 39 — derives a full `THEMES[...]`-shaped color dict from just
two user-picked colors (Base, Accent) plus a light/dark ladder direction.

Reverse-engineered against `backend.constants.THEMES["dark"]` /
`THEMES["light"]`: those two dicts are the reference ladder this module's
deltas were tuned against, so a custom palette keeps the same
*relationships* between roles (bg < bg_alt < bg_card in dark mode, the
inverse in light mode, etc.) that the shipped themes have, just recolored
around whatever Base/Accent the person picked.

Only `derive_palette()` is meant to be called from outside this module;
everything else is a helper for it.
"""
import colorsys

# Fallback text colors used before the WCAG contrast check below --
# intentionally the same near-black/near-white the shipped themes already
# use for `fg`, not a fresh guess.
_NEAR_WHITE = "#f4f5f8"
_NEAR_BLACK = "#1c1d22"
_ABS_WHITE = "#ffffff"
_ABS_BLACK = "#000000"

# Minimum acceptable WCAG contrast ratio for body text against its
# background. 4.5:1 is the standard "AA, normal text" threshold.
_MIN_TEXT_CONTRAST = 4.5

# Status colors (success/danger/warn) are semantic, not derived from
# Base/Accent -- kept as the exact values the shipped dark/light themes
# already use, picked by ladder direction like every other role that
# isn't Base/Accent itself.
_STATUS_COLORS = {
    "dark": {"success": "#4caf7d", "danger": "#e5645f", "danger_hover": "#f07b76", "warn": "#e0a84e"},
    "light": {"success": "#2f9d63", "danger": "#d6453f", "danger_hover": "#c43631", "warn": "#c5860f"},
}


def _hex_to_hsl(hex_color: str):
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    return h, s, l


def _hsl_to_hex(h: float, s: float, l: float) -> str:
    h = h % 1.0
    s = _clamp01(s)
    l = _clamp01(l)
    r, g, b = colorsys.hls_to_rgb(h, l, s)
    return "#{:02x}{:02x}{:02x}".format(round(r * 255), round(g * 255), round(b * 255))


def _clamp01(x: float) -> float:
    return min(max(x, 0.0), 1.0)


def _channel_linear(c8: int) -> float:
    c = c8 / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _relative_luminance(hex_color: str) -> float:
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    r, g, b = _channel_linear(r), _channel_linear(g), _channel_linear(b)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(hex_a: str, hex_b: str) -> float:
    """WCAG relative-luminance contrast ratio between two hex colors,
    1.0 (no contrast) to 21.0 (pure black vs. pure white)."""
    la, lb = _relative_luminance(hex_a), _relative_luminance(hex_b)
    la, lb = max(la, lb), min(la, lb)
    return (la + 0.05) / (lb + 0.05)


def derive_palette(base_hex: str, accent_hex: str, mode: str = "dark") -> dict:
    """Returns a dict with the exact same keys as `THEMES["dark"]`/
    `THEMES["light"]`, derived from `base_hex` (background family),
    `accent_hex` (accent family), and `mode` ("dark" or "light", the
    ladder direction -- Base alone doesn't say whether bg should end up
    darker or lighter than the surfaces stacked on it).
    """
    if mode not in ("dark", "light"):
        mode = "dark"

    bh, bs, bl = _hex_to_hsl(base_hex)
    ah, asat, al = _hex_to_hsl(accent_hex)

    if mode == "dark":
        # Keep the background genuinely dark even if the user's "Base"
        # pick happens to be light -- mirrors THEMES["dark"]["bg"]'s own
        # lightness (~13%) rather than trusting the raw pick verbatim.
        bg_l = min(bl, 0.22)
        deltas = {"bg_input": -0.04, "bg_alt": 0.04, "bg_card": 0.06, "border": 0.13,
                  "tree_bg": -0.01, "tree_alt": 0.03}
        accent_hover_delta = 0.06
        select_delta = 0.08
    else:
        bg_l = max(bl, 0.90)
        deltas = {"bg_input": 0.035, "bg_alt": 0.035, "bg_card": 0.035, "border": -0.11,
                  "tree_bg": 0.035, "tree_alt": 0.02}
        accent_hover_delta = -0.09
        select_delta = -0.10

    def surface(delta, sat=None):
        s = bs if sat is None else sat
        return _hsl_to_hex(bh, s, bg_l + delta)

    bg = _hsl_to_hex(bh, bs, bg_l)
    bg_input = surface(deltas["bg_input"])
    bg_alt = surface(deltas["bg_alt"])
    bg_card = surface(deltas["bg_card"])
    border = surface(deltas["border"], sat=min(bs + 0.05, 1.0))
    tree_bg = surface(deltas["tree_bg"])
    tree_alt = surface(deltas["tree_alt"])

    # fg/fg_dim: pick whichever of near-black/near-white contrasts better
    # against the derived bg, then verify against the real WCAG formula --
    # an unlucky Base pick could otherwise still land under 4.5:1.
    if contrast_ratio(bg, _NEAR_WHITE) >= contrast_ratio(bg, _NEAR_BLACK):
        fg, fg_dim = _NEAR_WHITE, "#9a9cab"
        fallback_fg = _ABS_WHITE
    else:
        fg, fg_dim = _NEAR_BLACK, "#5c5e6b"
        fallback_fg = _ABS_BLACK
    if contrast_ratio(bg, fg) < _MIN_TEXT_CONTRAST:
        fg = fallback_fg

    accent = _hsl_to_hex(ah, asat, al)
    accent_hover = _hsl_to_hex(ah, asat, al + accent_hover_delta)
    select_bg = _hsl_to_hex(ah, min(asat, 0.55), bg_l + select_delta)

    status = _STATUS_COLORS[mode]

    return {
        "bg": bg,
        "bg_alt": bg_alt,
        "bg_card": bg_card,
        "bg_input": bg_input,
        "fg": fg,
        "fg_dim": fg_dim,
        "accent": accent,
        "accent_hover": accent_hover,
        "accent_text": "#ffffff",
        "border": border,
        "success": status["success"],
        "danger": status["danger"],
        "danger_hover": status["danger_hover"],
        "warn": status["warn"],
        "select_bg": select_bg,
        "tree_bg": tree_bg,
        "tree_alt": tree_alt,
    }


# Session 40.1 — surface tokens eligible for the Custom theme's "Card
# opacity" slider. Deliberately excludes `border`, `select_bg`,
# `fg`/`fg_dim`, and every accent/status color — those carry meaning
# (text legibility, the current selection, success/danger/warn) that a
# translucency slider shouldn't be allowed to wash out, whereas these
# are pure fill colors.
_ALPHA_ELIGIBLE_KEYS = ("bg", "bg_alt", "bg_card", "bg_input", "tree_bg", "tree_alt")


def hex_to_rgba(hex_color: str, alpha_pct: int) -> str:
    """`"#2b2d37"`, `60` -> `"rgba(43,45,55,153)"` — a plain hex color
    stays a valid drop-in QSS `background-color` value either way, this
    just gives it an alpha channel Qt's CSS engine understands.

    Qt's `rgba()` function takes an **integer 0-255** alpha, unlike
    standard CSS3's 0.0-1.0 float — passing a float here silently fails
    to parse as a valid value (confirmed against a real render: every
    surface using it went fully transparent, showing through to raw
    black, not a blended translucent color)."""
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    a = round(max(0, min(100, alpha_pct)) / 100 * 255)
    return f"rgba({r},{g},{b},{a})"


def apply_surface_alpha(colors: dict, alpha_pct: int) -> dict:
    """Returns a copy of `colors` with the surface-fill tokens
    (`_ALPHA_ELIGIBLE_KEYS`) converted to `rgba(...)` at `alpha_pct`
    opacity, everything else untouched. `alpha_pct >= 100` returns
    `colors` unchanged (by value, not by reference — callers are free
    to mutate the result) since there's nothing to do and it avoids an
    identical-looking but needlessly rgba-ified QSS string."""
    if alpha_pct >= 100:
        return dict(colors)
    out = dict(colors)
    for key in _ALPHA_ELIGIBLE_KEYS:
        if key in out:
            out[key] = hex_to_rgba(out[key], alpha_pct)
    return out
