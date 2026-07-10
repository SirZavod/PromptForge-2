"""Session 40.1 follow-up — a couple of raw-`QPainter` widgets (the
Builder/Library image preview cards, `ui/widgets/image_zone.py`) build
their own `QColor` objects directly from the active theme's colors
dict, rather than going through QSS. `apply_surface_alpha` (Session
40.1's Card opacity slider) can turn a colors-dict entry like `bg_card`
into a CSS `rgba(r,g,b,a)` string instead of a plain hex string —
that's a valid value for Qt *style sheets*, but plain `QColor(str)`
only understands hex (`#RRGGBB`/`#AARRGGBB`) and SVG color names, not
CSS's `rgba()` function syntax. Handing it an `rgba(...)` string
silently produces an invalid (black) QColor instead of raising, which
is exactly what turned the preview widgets' card fill solid black
once Card opacity went below 100 — this was found from a real
screenshot, not caught in this environment's headless testing.

Every raw-QPainter consumer of the colors dict should build its
QColor via this helper instead of calling `QColor(...)` on a
dict value directly.
"""
from PyQt6.QtGui import QColor


def qcolor_from_token(value: str) -> QColor:
    """Builds a QColor from either a plain hex/named-color string or a
    CSS `rgba(r,g,b,a)` string (the format `apply_surface_alpha`
    emits for Card-opacity-affected tokens). Falls back to treating
    `value` as a plain color for anything that isn't `rgba(...)`, so
    every ordinary hex color (the vast majority of calls, and the only
    kind that exists in Dark/Light or Custom-without-a-background-image)
    behaves exactly like a direct `QColor(value)` call always did."""
    if isinstance(value, str) and value.startswith("rgba("):
        try:
            r, g, b, a = (int(p) for p in value[5:-1].split(","))
            return QColor(r, g, b, a)
        except (ValueError, TypeError):
            pass  # malformed -- fall through to QColor's own handling
    return QColor(value)
