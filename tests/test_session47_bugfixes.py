"""Session 47 tests — regression coverage for the four bugs found
during live manual testing right after 46.4b landed (see
additionalfeatures.md's SESSION 47 write-up for the full diagnosis of
each):

- 47.1: Library save wrongly required tags/content for edit_tools/video_tools.
- 47.2/47.3: the i2i/i2v Actions slot was never read by prompt assembly.
- 47.4: ComfyUI's 300s poll timeout was far too short for video generation.
- 47.5: a video result could be misclassified as its own preview PNG.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication

from backend.comfy_client import ComfyUIClient
from backend.constants import (
    CATEGORIES, COMFY_POLL_TIMEOUT, COMFY_VIDEO_POLL_TIMEOUT,
    PIPELINE_MODE_I2I, PIPELINE_MODE_I2V, PIPELINE_MODE_T2I,
    TOOLS_LIKE_CATEGORIES,
)
from backend.file_manager import init_folders
from backend.prompt_builder import generate_standard_prompt
from ui.tabs.builder_tab import BuilderTab


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


COLORS = {
    "bg": "#202020", "bg_alt": "#242424", "bg_card": "#282828",
    "bg_input": "#2c2c2c", "border": "#3a3a3a", "fg": "#f0f0f0",
    "fg_dim": "#9a9a9a", "accent": "#5b8def", "accent_text": "#ffffff",
    "accent_hover": "#6f9bf2", "success": "#4caf50", "danger": "#e05252",
    "warn": "#e0a852", "tree_bg": "#242424", "tree_alt": "#262626",
    "select_bg": "#31445e",
}


def make_builder(tmp_path):
    init_folders(str(tmp_path), CATEGORIES)
    settings_file = str(tmp_path / "settings.json")
    return BuilderTab(str(tmp_path), COLORS, {}, settings_file)


def _history_entry(outputs):
    return {"outputs": outputs}


# ---------------------------------------------------------------------
# 47.1 — Library save: edit_tools/video_tools allow empty tags
# ---------------------------------------------------------------------
def test_tools_like_categories_includes_the_two_new_tools_categories():
    assert TOOLS_LIKE_CATEGORIES == ("tools", "edit_tools", "video_tools")


def test_tools_like_categories_excludes_actions():
    assert "image_actions" not in TOOLS_LIKE_CATEGORIES
    assert "video_actions" not in TOOLS_LIKE_CATEGORIES


def test_library_save_allows_empty_tags_for_edit_tools(app, tmp_path):
    from ui.tabs.library_tab import LibraryTab
    init_folders(str(tmp_path), CATEGORIES)
    lib = LibraryTab(str(tmp_path), COLORS, {}, str(tmp_path / "settings.json"))
    lib.switch_library_category("edit_tools")
    lib.start_new_library_entry(keep_category=True)
    lib.ent_lib_name.setText("Anatomy Fixer")
    lib.txt_lib_tags.setPlainText("")  # deliberately empty -- LoRA-only entry
    lib.save_to_library()
    assert os.path.exists(os.path.join(str(tmp_path), "edit_tools", "Anatomy Fixer.txt"))


def test_library_save_allows_empty_tags_for_video_tools(app, tmp_path):
    from ui.tabs.library_tab import LibraryTab
    init_folders(str(tmp_path), CATEGORIES)
    lib = LibraryTab(str(tmp_path), COLORS, {}, str(tmp_path / "settings.json"))
    lib.switch_library_category("video_tools")
    lib.start_new_library_entry(keep_category=True)
    lib.ent_lib_name.setText("Camera Stabilizer")
    lib.txt_lib_tags.setPlainText("")
    lib.save_to_library()
    assert os.path.exists(os.path.join(str(tmp_path), "video_tools", "Camera Stabilizer.txt"))


def test_library_save_still_requires_tags_for_image_actions(app, tmp_path):
    from ui.dialogs import themed_message_box
    from ui.tabs.library_tab import LibraryTab
    init_folders(str(tmp_path), CATEGORIES)
    lib = LibraryTab(str(tmp_path), COLORS, {}, str(tmp_path / "settings.json"))
    lib.switch_library_category("image_actions")
    lib.start_new_library_entry(keep_category=True)
    lib.ent_lib_name.setText("Zoom In")
    lib.txt_lib_tags.setPlainText("")
    lib._test_warning_seen = False
    original = themed_message_box.warning
    try:
        themed_message_box.warning = lambda *a, **k: setattr(lib, "_test_warning_seen", True)
        lib.save_to_library()
    finally:
        themed_message_box.warning = original
    assert lib._test_warning_seen is True
    assert not os.path.exists(os.path.join(str(tmp_path), "image_actions", "Zoom In.txt"))


# ---------------------------------------------------------------------
# 47.2/47.3 — Actions slot text actually reaches the assembled prompt
# ---------------------------------------------------------------------
def test_generate_standard_prompt_includes_actions_text():
    """Direct backend-level check, no Qt needed: actions_category set
    means an active action's tags land in the assembled prompt."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        init_folders(d, CATEGORIES)
        with open(os.path.join(d, "image_actions", "Zoom In.txt"), "w") as fh:
            fh.write("slow zoom in, cinematic")

        prompt = generate_standard_prompt(
            d, "None", [], "None", [], ["style", "characters", "scenario", "tools"],
            tools_category="edit_tools",
            active_action_names=["Zoom In"],
            actions_category="image_actions",
        )
        assert "slow zoom in, cinematic" in prompt


def test_generate_standard_prompt_combines_actions_and_tools():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        init_folders(d, CATEGORIES)
        with open(os.path.join(d, "image_actions", "Zoom In.txt"), "w") as fh:
            fh.write("slow zoom in")
        with open(os.path.join(d, "edit_tools", "Anatomy Fixer.txt"), "w") as fh:
            fh.write("anatomically correct")

        prompt = generate_standard_prompt(
            d, "None", [], "None", ["Anatomy Fixer"], ["style", "characters", "scenario", "tools"],
            tools_category="edit_tools",
            active_action_names=["Zoom In"],
            actions_category="image_actions",
        )
        assert "slow zoom in" in prompt
        assert "anatomically correct" in prompt


def test_generate_standard_prompt_without_actions_category_is_unchanged():
    """t2i-style callers that never pass actions_category keep working
    exactly as before this fix."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        init_folders(d, CATEGORIES)
        with open(os.path.join(d, "tools", "Grain.txt"), "w") as fh:
            fh.write("film grain")
        prompt = generate_standard_prompt(
            d, "None", [], "None", ["Grain"], ["style", "characters", "scenario", "tools"])
        assert prompt.strip() == "film grain"


def test_builder_actions_slot_reaches_generated_prompt(app, tmp_path):
    init_folders(str(tmp_path), CATEGORIES)
    with open(os.path.join(str(tmp_path), "image_actions", "Zoom In.txt"), "w") as fh:
        fh.write("slow zoom in")

    b = make_builder(tmp_path)
    b.pipeline_mode = PIPELINE_MODE_I2I
    b.add_action_slot()
    b.active_actions[0]["action_combo"].set_items(["None", "Zoom In"])
    b.active_actions[0]["action_combo"].set_value("Zoom In")

    seen = {}
    b._finalize_generated_prompt = lambda prompt: seen.setdefault("prompt", prompt)
    b._generate_standard_prompt()

    assert "prompt" in seen, "generate_prompt should not have hit the empty-prompt error"
    assert "slow zoom in" in seen["prompt"]


def test_builder_empty_prompt_message_is_mode_aware(app, tmp_path):
    from ui.dialogs import themed_message_box
    b = make_builder(tmp_path)
    b.pipeline_mode = PIPELINE_MODE_I2V

    seen = {}
    original = themed_message_box.information
    try:
        themed_message_box.information = lambda self_, title, msg: seen.setdefault("msg", msg)
        b._generate_standard_prompt()
    finally:
        themed_message_box.information = original

    assert seen.get("msg") == "Select at least one action or tool."


# ---------------------------------------------------------------------
# 47.4 — i2v gets a much longer poll timeout than t2i/i2i
# ---------------------------------------------------------------------
def test_video_poll_timeout_is_much_larger_than_the_default():
    assert COMFY_VIDEO_POLL_TIMEOUT > COMFY_POLL_TIMEOUT
    assert COMFY_VIDEO_POLL_TIMEOUT >= 1800  # at least 30 minutes


def test_generation_worker_picks_video_timeout_for_i2v(monkeypatch):
    from workers.comfy_worker import ComfyGenerationWorker

    captured = {}

    class FakeClient:
        base_url = "http://127.0.0.1:8188"

        def wait_for_completion(self, prompt_id, **kwargs):
            captured["timeout"] = kwargs.get("timeout")
            raise RuntimeError("stop here, we only care about the timeout kwarg")

        def submit_prompt(self, graph):
            return "fake-id"

    worker = ComfyGenerationWorker(FakeClient(), {"pipeline_mode": PIPELINE_MODE_I2V})
    worker._prompt_id = "fake-id"
    try:
        worker.client.wait_for_completion(
            "fake-id",
            timeout=(COMFY_VIDEO_POLL_TIMEOUT
                     if worker.queue_item.get("pipeline_mode") == PIPELINE_MODE_I2V
                     else COMFY_POLL_TIMEOUT))
    except RuntimeError:
        pass
    assert captured["timeout"] == COMFY_VIDEO_POLL_TIMEOUT


def test_generation_worker_picks_default_timeout_for_t2i():
    from workers.comfy_worker import ComfyGenerationWorker

    captured = {}

    class FakeClient:
        def wait_for_completion(self, prompt_id, **kwargs):
            captured["timeout"] = kwargs.get("timeout")
            raise RuntimeError("stop here")

    worker = ComfyGenerationWorker(FakeClient(), {"pipeline_mode": PIPELINE_MODE_T2I})
    try:
        worker.client.wait_for_completion(
            "fake-id",
            timeout=(COMFY_VIDEO_POLL_TIMEOUT
                     if worker.queue_item.get("pipeline_mode") == PIPELINE_MODE_I2V
                     else COMFY_POLL_TIMEOUT))
    except RuntimeError:
        pass
    assert captured["timeout"] == COMFY_POLL_TIMEOUT


def test_generation_worker_defaults_to_normal_timeout_when_mode_missing():
    """An older/hand-built queue item dict with no "pipeline_mode" key
    at all must not accidentally get the long video timeout."""
    from workers.comfy_worker import ComfyGenerationWorker
    worker = ComfyGenerationWorker(object(), {})
    assert worker.queue_item.get("pipeline_mode") != PIPELINE_MODE_I2V


# ---------------------------------------------------------------------
# 47.5 — video output preferred over an accompanying preview PNG
# ---------------------------------------------------------------------
def test_video_preferred_over_sibling_preview_png_same_node():
    """The exact VHS_VideoCombine-shaped case reported: one node's
    outputs dict has both an "images" (preview PNG) and a "gifs"
    (real video) key, PNG serialized first."""
    entry = _history_entry({
        "9": {
            "images": [{"filename": "result_00001_.png", "subfolder": "", "type": "output"}],
            "gifs": [{"filename": "result_00001_.mp4", "subfolder": "", "type": "output"}],
        }
    })
    filename, subfolder, kind, is_video = ComfyUIClient.extract_output_info(entry)
    assert filename == "result_00001_.mp4"
    assert is_video is True


def test_video_preferred_even_when_video_key_appears_second_across_nodes():
    entry = _history_entry({
        "8": {"images": [{"filename": "preview.png", "subfolder": "", "type": "output"}]},
        "9": {"videos": [{"filename": "clip.mp4", "subfolder": "", "type": "output"}]},
    })
    filename, subfolder, kind, is_video = ComfyUIClient.extract_output_info(entry)
    assert filename == "clip.mp4"
    assert is_video is True


def test_image_only_history_entry_still_returns_the_image():
    entry = _history_entry({
        "9": {"images": [{"filename": "result_00001_.png", "subfolder": "", "type": "output"}]},
    })
    filename, subfolder, kind, is_video = ComfyUIClient.extract_output_info(entry)
    assert filename == "result_00001_.png"
    assert is_video is False


def test_video_only_history_entry_still_returns_the_video():
    entry = _history_entry({
        "9": {"gifs": [{"filename": "clip.mp4", "subfolder": "", "type": "output"}]},
    })
    filename, subfolder, kind, is_video = ComfyUIClient.extract_output_info(entry)
    assert filename == "clip.mp4"
    assert is_video is True
