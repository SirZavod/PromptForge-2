"""THROWAWAY — Session 2 on-screen verification only.

Not part of the shipped app. Per the migration plan's step 6 ("Test all
four widgets in a minimal QApplication throwaway script (not
committed)") and the per-session verification rule for backend/infra
sessions. Delete or ignore after Session 2 is confirmed.

Builds one plain window containing: both theme stylesheets (a toggle
button to flip between them live), an ImageDropZone + ResultImageViewer
side by side, an AutocompleteCombobox pre-loaded with a small fake
library list, and two CollapsibleSections (one expanded, one
collapsed) — enough to actually SEE every Session 2 deliverable
rendering and responding to interaction in one place before Session 3
builds the real MainWindow on top of it.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QGroupBox,
)

import backend
from ui.theme import apply_theme
from ui.widgets.tooltip import set_tooltip
from ui.widgets.image_zone import ImageDropZone, ResultImageViewer
from ui.widgets.autocomplete import AutocompleteCombobox
from ui.widgets.collapsible_section import CollapsibleSection


class CheckWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Session 2 manual check — theme + widgets (THROWAWAY)")
        self.resize(900, 760)
        self.current_theme = "dark"

        root = QVBoxLayout(self)

        title = QLabel("Session 2 — theme + widget layer verification (delete this file after reading)")
        title.setStyleSheet("font-weight: bold; padding: 4px;")
        root.addWidget(title)

        # ---- theme toggle ----
        theme_row = QHBoxLayout()
        self.theme_btn = QPushButton("Toggle dark/light theme")
        self.theme_btn.setObjectName("accent")
        self.theme_btn.clicked.connect(self.toggle_theme)
        set_tooltip(self.theme_btn, "Calls apply_theme() with the other THEMES key")
        theme_row.addWidget(self.theme_btn)
        self.theme_label = QLabel(f"Current theme: {self.current_theme}")
        theme_row.addWidget(self.theme_label)
        theme_row.addStretch(1)
        root.addLayout(theme_row)

        # ---- image zones ----
        zones_box = QGroupBox("ImageDropZone (left) / ResultImageViewer (right)")
        zones_row = QHBoxLayout(zones_box)

        self.drop_zone = ImageDropZone(backend.THEMES[self.current_theme])
        self.drop_zone.apply_panel_height(260)
        self.drop_zone.file_chosen.connect(
            lambda path: self.drop_status.setText(f"file_chosen emitted: {path}"))
        self.drop_zone.unsupported_file_dropped.connect(
            lambda path: self.drop_status.setText(f"unsupported_file_dropped emitted: {path}"))
        zones_row.addWidget(self.drop_zone, 1)

        self.result_viewer = ResultImageViewer(backend.THEMES[self.current_theme])
        self.result_viewer.apply_panel_height(260)
        zones_row.addWidget(self.result_viewer, 1)

        root.addWidget(zones_box)

        self.drop_status = QLabel("(click or drag an image onto the left zone to test the signal)")
        self.drop_status.setObjectName("dim")
        root.addWidget(self.drop_status)

        # ---- autocomplete combobox ----
        combo_box = QGroupBox("AutocompleteCombobox")
        combo_layout = QVBoxLayout(combo_box)
        self.combo = AutocompleteCombobox()
        self.combo.set_items(["Megumin", "Akane", "Aqua", "Kazuma", "Darkness", "Wiz", "Yunyun"])
        set_tooltip(self.combo, "Click or type to filter — try 'a' for a substring match")
        self.combo.item_selected.connect(
            lambda v: self.combo_status.setText(f"item_selected emitted: {v}"))
        combo_layout.addWidget(self.combo)
        self.combo_status = QLabel("(click the box, or type 'a', to see the filtered popup)")
        self.combo_status.setObjectName("dim")
        combo_layout.addWidget(self.combo_status)
        root.addWidget(combo_box)

        # ---- collapsible sections ----
        sections_box = QGroupBox("CollapsibleSection (one expanded, one collapsed by default)")
        sections_layout = QVBoxLayout(sections_box)

        section_a = CollapsibleSection("Negative Prompt (expanded)", "negative_prompt", default_expanded=True)
        section_a.body_layout.addWidget(QLineEdit("low quality, blurry, watermark"))
        section_a.toggled.connect(lambda exp: print(f"[toggled] negative_prompt -> expanded={exp}"))
        sections_layout.addWidget(section_a)

        section_b = CollapsibleSection("LoRA Manager (collapsed)", "lora_manager", default_expanded=False)
        section_b.body_layout.addWidget(QLabel("Slot 1: None  |  Slot 2: None"))
        section_b.toggled.connect(lambda exp: print(f"[toggled] lora_manager -> expanded={exp}"))
        sections_layout.addWidget(section_b)

        root.addWidget(sections_box)
        root.addStretch(1)

    def toggle_theme(self):
        self.current_theme = "light" if self.current_theme == "dark" else "dark"
        apply_theme(QApplication.instance(), self.current_theme)
        self.drop_zone.set_colors(backend.THEMES[self.current_theme])
        self.result_viewer.set_colors(backend.THEMES[self.current_theme])
        self.theme_label.setText(f"Current theme: {self.current_theme}")


def main():
    app = QApplication(sys.argv)
    apply_theme(app, "dark")

    window = CheckWindow()
    window.show()

    if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
        out_path = os.environ.get("MANUAL_CHECK_SCREENSHOT", "/home/claude/session2_check.png")
        pixmap = window.grab()
        pixmap.save(out_path, "PNG")
        print(f"[offscreen mode] window grab saved to {out_path}")
        app.quit()
        return

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
