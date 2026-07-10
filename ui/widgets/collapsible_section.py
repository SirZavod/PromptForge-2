"""Generic collapsible header/body section — ported from
`PromptForgeApp._make_collapsible_section` in the original monolith,
promoted to its own reusable widget per the migration plan (it was a
method on the app before; nothing about it actually needs `self`).

Used by the LoRA Manager panel (Session 11) and is generic enough to
reuse anywhere else a collapsible group is wanted later (the original's
docstring specifically called out Negative prompt, LoRA Manager, and
Tools as the three sections that stay visually "full" all the time even
though most of a session never needs to look at or touch them again
after first setup).

Persistence note: unlike the original, which read/wrote
`self.settings`/`self.SETTINGS_FILE` directly inside the toggle
handler, this widget is a UI/widget-layer class with zero backend
imports and therefore does no file I/O itself. `settings_key` is kept
as a plain attribute the owning tab reads off this widget — the tab is
responsible for calling `backend.save_json(...)` itself in a slot
connected to `toggled`, exactly mirroring the original's
"save immediately on toggle" behavior at the call site instead of
inside this generic widget.
"""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QToolButton, QVBoxLayout, QWidget


class CollapsibleSection(QWidget):
    """A QToolButton header (checkable, arrow-icon, text label) above a
    body QWidget. Toggling the header calls `body.setVisible(checked)`
    and emits `toggled = pyqtSignal(bool)`.

    Usage:
        section = CollapsibleSection("LoRA Manager", "lora_manager",
                                      default_expanded=True)
        section.body_layout.addWidget(my_content_widget)
        section.toggled.connect(lambda expanded: backend.save_json(
            settings_path, {**settings, f"section_collapsed_{section.settings_key}": not expanded}))
        parent_layout.addWidget(section)
    """

    toggled = pyqtSignal(bool)

    def __init__(self, title: str, settings_key: str, default_expanded: bool = True,
                 parent=None, card: bool = False):
        """`card`: Session 20 step 1 -- when True, the section's outer
        widget gets the same bordered/backed "card" treatment every
        other Builder block already has (`QGroupBox#CompactGroup`,
        `QFrame#Card`), via the object-name-only `#Card` QSS selector
        (matches regardless of widget class, see ui/theme.py) plus
        `WA_StyledBackground` so a bare QWidget actually paints that
        background instead of silently no-op'ing (same failure mode
        Session 16 hit and fixed for QFrame#Card). Off by default so
        every other current/future caller is unaffected."""
        super().__init__(parent)
        self.settings_key = settings_key

        outer = QVBoxLayout(self)
        if card:
            self.setObjectName("Card")
            self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            outer.setContentsMargins(8, 6, 8, 8)
        else:
            outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        self.header = QToolButton(self)
        self.header.setObjectName("CollapsibleHeader")
        self.header.setText(title)
        self.header.setCheckable(True)
        self.header.setChecked(default_expanded)
        self.header.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.header.setArrowType(
            Qt.ArrowType.DownArrow if default_expanded else Qt.ArrowType.RightArrow)
        self.header.setCursor(Qt.CursorShape.PointingHandCursor)
        self.header.toggled.connect(self._on_header_toggled)
        outer.addWidget(self.header)

        self.body = QWidget(self)
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(4, 0, 0, 0)
        self.body.setVisible(default_expanded)
        outer.addWidget(self.body)

    def _on_header_toggled(self, checked: bool):
        self.body.setVisible(checked)
        self.header.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)
        self.toggled.emit(checked)

    def is_expanded(self) -> bool:
        return self.header.isChecked()

    def set_expanded(self, expanded: bool):
        """Programmatic expand/collapse (e.g. restoring persisted state
        on tab construction) — goes through the same visual update as a
        click, but does NOT re-emit `toggled` (the caller already knows
        the state it's restoring; re-emitting would make the tab
        re-save the exact value it just loaded)."""
        self.header.blockSignals(True)
        self.header.setChecked(expanded)
        self.header.blockSignals(False)
        self.body.setVisible(expanded)
        self.header.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
