"""THROWAWAY — Session 1 on-screen verification only.

Not part of the shipped app. Delete or ignore after Session 1 is
confirmed; nothing in Session 2+ imports this file.

Opens a bare QApplication + one plain QWidget with a QPlainTextEdit
log, then calls a handful of the just-extracted backend functions
directly and prints a PASS/FAIL line per call — the only way to
actually *see* Session 1's work, since the real app has no UI yet.
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtWidgets import QApplication, QWidget, QPlainTextEdit, QVBoxLayout, QLabel

import backend


def run_checks(log):
    tmp = tempfile.mkdtemp()

    def line(ok, label, detail=""):
        tag = "PASS" if ok else "FAIL"
        text = f"[{tag}] {label}" + (f"  —  {detail}" if detail else "")
        log.appendPlainText(text)

    log.appendPlainText("=" * 60)
    log.appendPlainText("Session 1 backend verification — " + tmp)
    log.appendPlainText("=" * 60)

    # ---- 1. load_json / save_json round trip ----
    try:
        path = os.path.join(tmp, "roundtrip.json")
        payload = {"theme": "dark", "n": 42, "list": [1, 2, 3]}
        backend.save_json(path, payload)
        loaded = backend.load_json(path, default=None)
        line(loaded == payload, "load_json/save_json round trip", f"loaded={loaded}")
    except Exception as e:
        line(False, "load_json/save_json round trip", repr(e))

    # ---- 2. parse_custom_template, including [Tool] ----
    try:
        text = "[Name 1] ([Description 1]) wearing [Outfit 1]. Style: [Style]. Tool: [Tool]"
        parsed = backend.parse_custom_template(text)
        ok = (parsed["name_idx"] == {1} and parsed["desc_idx"] == {1}
              and parsed["outfit_idx"] == {1} and parsed["use_style"] is True
              and parsed["use_tool"] is True and parsed["use_scenario"] is False)
        line(ok, "parse_custom_template (incl. [Tool])", str(parsed))
    except Exception as e:
        line(False, "parse_custom_template (incl. [Tool])", repr(e))

    # ---- 3. generate_custom_prompt substitution ----
    try:
        result = backend.generate_custom_prompt(
            "[Name 1] ([Description 1]) wearing [Outfit 1]. [Style] [Tool]",
            name_vals={1: "Megumin"}, desc_vals={1: "red eyes"}, outfit_vals={1: "casual"},
            style_val="anime style.", scenario_val="", tool_val="@fixedanatomy")
        ok = "Megumin" in result and "@fixedanatomy" in result
        line(ok, "generate_custom_prompt substitution", result)
    except Exception as e:
        line(False, "generate_custom_prompt substitution", repr(e))

    # ---- 4. find_lora_candidates: exact / collision / no-match ----
    try:
        available = ["Other/megumin.safetensors", "Yet/Another/megumin.safetensors",
                     "Anima/Characters/akane.safetensors"]
        missing = ["Old/megumin.safetensors", "Old/akane.safetensors", "Old/nope.safetensors"]
        results = backend.find_lora_candidates(available, missing)
        ok = (isinstance(results["Old/megumin.safetensors"], list)
              and len(results["Old/megumin.safetensors"]) == 2
              and results["Old/akane.safetensors"] == "Anima/Characters/akane.safetensors"
              and results["Old/nope.safetensors"] is None)
        line(ok, "find_lora_candidates (collision/exact/none)", str(results))
    except Exception as e:
        line(False, "find_lora_candidates (collision/exact/none)", repr(e))

    # ---- 5. generate_standard_prompt end-to-end ----
    try:
        data_dir = os.path.join(tmp, "prompt_forge_data")
        backend.init_folders(data_dir, backend.CATEGORIES)
        with open(os.path.join(data_dir, "styles", "Anime.txt"), "w") as f:
            f.write("anime style")
        with open(os.path.join(data_dir, "characters", "Megumin.txt"), "w") as f:
            f.write("megumin, red eyes")
        with open(os.path.join(data_dir, "scenarios", "Forest.txt"), "w") as f:
            f.write("in a forest")
        prompt = backend.generate_standard_prompt(
            data_dir, style_name="Anime",
            valid_chars=[{"char_name": "Megumin", "outfit_selection": "None"}],
            scenario_name="Forest", active_tool_names=[],
            block_order=["style", "characters", "scenario", "tools"])
        ok = "megumin" in prompt and "forest" in prompt
        line(ok, "generate_standard_prompt end-to-end", prompt.replace("\n", " | "))
    except Exception as e:
        line(False, "generate_standard_prompt end-to-end", repr(e))

    # ---- 6. export_library / import_library (zip) against a throwaway sample folder ----
    try:
        src_dir = os.path.join(tmp, "lib_src")
        backend.init_folders(src_dir, backend.CATEGORIES)
        with open(os.path.join(src_dir, "characters", "Sample.txt"), "w") as f:
            f.write("sample tags")
        zip_path = os.path.join(tmp, "export.zip")
        backend.export_library(src_dir, zip_path)

        dest_dir = os.path.join(tmp, "lib_dest")
        backend.init_folders(dest_dir, backend.CATEGORIES)
        extract_tmp = os.path.join(dest_dir, "_import_tmp")
        backend.extract_library_zip(zip_path, extract_tmp)
        folder_maps = {c: {} for c in backend.CATEGORIES}
        folders_file = os.path.join(dest_dir, "_folders.json")
        imported, skipped = backend.merge_imported_library(
            dest_dir, extract_tmp, backend.CATEGORIES, folder_maps, folders_file)
        shutil.rmtree(extract_tmp, ignore_errors=True)
        ok = ("characters", "Sample") in imported and not skipped
        line(ok, "export_library / import_library round trip",
             f"imported={imported} skipped={skipped}")
    except Exception as e:
        line(False, "export_library / import_library round trip", repr(e))

    # ---- 7. zero-Tkinter sanity check ----
    line("tkinter" not in sys.modules, "zero Tkinter dependency in backend",
         f"sys.modules has tkinter: {'tkinter' in sys.modules}")

    log.appendPlainText("=" * 60)
    log.appendPlainText("Done. Read the lines above — every one should say PASS.")

    shutil.rmtree(tmp, ignore_errors=True)


def main():
    app = QApplication(sys.argv)
    window = QWidget()
    window.setWindowTitle("Session 1 manual check — backend extraction (THROWAWAY)")
    window.resize(820, 560)

    layout = QVBoxLayout(window)
    title = QLabel("Session 1 — backend extraction verification (delete this file after reading)")
    title.setStyleSheet("font-weight: bold; padding: 4px;")
    layout.addWidget(title)

    log = QPlainTextEdit()
    log.setReadOnly(True)
    log.setStyleSheet("font-family: monospace; font-size: 12px;")
    layout.addWidget(log)

    window.show()
    run_checks(log)

    # Headless/offscreen-platform support: if QT_QPA_PLATFORM=offscreen is
    # set (e.g. CI, this sandbox, or anywhere a real X server isn't
    # available), grab the rendered window to a PNG and exit automatically
    # instead of blocking forever on app.exec() with nothing able to close
    # it. Under a normal display this env var is unset and the window
    # behaves exactly as the plan describes: stays open until closed by
    # hand.
    if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
        out_path = os.environ.get("MANUAL_CHECK_SCREENSHOT", "/home/claude/session1_check.png")
        pixmap = window.grab()
        pixmap.save(out_path, "PNG")
        print(f"[offscreen mode] window grab saved to {out_path}")
        app.quit()
        return

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
