"""Session 9 tests — workers/comfy_worker.py.

Same PyQt6/network limitation as Sessions 3-8: this file imports
`workers.comfy_worker`, which imports PyQt6 at module level, and this
sandbox has neither PyQt6 installed nor network access to install it
(`pip install PyQt6` fails here with "No matching distribution
found"). These tests are written and believed correct against the
ported logic (see PromptForge_PyQt6_Migration_Plan.md Session 9 notes
below) but have **not been run** in this environment — needs user
verification on a machine with PyQt6 installed, same as the
Library/Gallery tab test suites.

Covers the pure, Qt-free helpers in comfy_worker.py:
  - _validate_live_graph
  - patch_graph_for_generation (prompt/seed/size/negative patch +
    LoRA slot patch, including the graceful-fallback paths)

Does NOT cover ComfyCheckWorker/ComfyGenerationWorker's QThread.run()
bodies directly (that needs a running Qt event loop + a real or mocked
ComfyUIClient over HTTP) — that's what tests/_manual_check_session9.py
and the CLI integration test at the bottom of this file are for.
"""
import copy

import pytest

from workers.comfy_worker import (
    _validate_live_graph,
    patch_graph_for_generation,
    LORA_LOADER_CLASS_TYPE,
)
from backend.constants import (
    COMFY_NODE_CLASS_TYPE,
    MAX_LORA_SLOTS,
    LORA_NONE_VALUE,
    LORA_STRENGTH_MIN,
    LORA_STRENGTH_MAX,
)


def make_graph(with_lora_node=False):
    graph = {
        "1": {"class_type": COMFY_NODE_CLASS_TYPE, "inputs": {}},
        "2": {"class_type": "SaveImage", "inputs": {}},
    }
    if with_lora_node:
        graph["3"] = {"class_type": LORA_LOADER_CLASS_TYPE, "inputs": {}}
    return graph


# ------------------------------------------------------------- validate --

def test_validate_live_graph_ok():
    ok, msg = _validate_live_graph(make_graph())
    assert ok is True
    assert msg == ""


def test_validate_live_graph_missing_node():
    graph = {"1": {"class_type": "SaveImage", "inputs": {}}}
    ok, msg = _validate_live_graph(graph)
    assert ok is False
    assert COMFY_NODE_CLASS_TYPE in msg


# ------------------------------------------------------------- patching --

def test_patch_graph_sets_core_fields():
    graph = make_graph()
    patch_graph_for_generation(
        graph, "a cat", 12345, 1024, 1216, "blurry", [])
    node = graph["1"]
    assert node["inputs"]["prompt"] == "a cat"
    assert node["inputs"]["seed"] == 12345
    assert node["inputs"]["width"] == 1024
    assert node["inputs"]["height"] == 1216
    assert node["inputs"]["negative_prompt"] == "blurry"


def test_patch_graph_no_lora_node_is_noop_for_loras():
    graph = make_graph(with_lora_node=False)
    # Must not raise even with LoRA slots given, since there's nowhere
    # to put them — graceful fallback.
    result = patch_graph_for_generation(
        graph, "x", 1, 512, 512, "", [{"name": "foo.safetensors", "strength": 0.8}])
    assert result is graph  # mutated + returned in place


def test_patch_graph_lora_slots_written_and_padded():
    graph = make_graph(with_lora_node=True)
    slots = [
        {"name": "styleA.safetensors", "strength": 0.75},
        {"name": "styleB.safetensors", "strength": 1.5},
    ]
    patch_graph_for_generation(graph, "x", 1, 512, 512, "", slots)
    lora_inputs = graph["3"]["inputs"]
    assert lora_inputs["lora_1_name"] == "styleA.safetensors"
    assert lora_inputs["lora_1_strength"] == 0.75
    assert lora_inputs["lora_2_name"] == "styleB.safetensors"
    assert lora_inputs["lora_2_strength"] == 1.5
    # Remaining slots up to MAX_LORA_SLOTS are padded with the empty
    # sentinel, never Python None (contract with nodes.py).
    assert lora_inputs["lora_3_name"] == LORA_NONE_VALUE
    assert lora_inputs["lora_3_strength"] == 1.0
    assert lora_inputs[f"lora_{MAX_LORA_SLOTS}_name"] == LORA_NONE_VALUE


def test_patch_graph_lora_strength_clamped():
    graph = make_graph(with_lora_node=True)
    slots = [{"name": "x.safetensors", "strength": 999}]
    patch_graph_for_generation(graph, "x", 1, 512, 512, "", slots)
    assert graph["3"]["inputs"]["lora_1_strength"] == LORA_STRENGTH_MAX

    graph2 = make_graph(with_lora_node=True)
    slots2 = [{"name": "x.safetensors", "strength": -999}]
    patch_graph_for_generation(graph2, "x", 1, 512, 512, "", slots2)
    assert graph2["3"]["inputs"]["lora_1_strength"] == LORA_STRENGTH_MIN


def test_patch_graph_malformed_slot_falls_back_to_none_sentinel():
    graph = make_graph(with_lora_node=True)
    slots = [{"name": None, "strength": "not-a-number"}]
    patch_graph_for_generation(graph, "x", 1, 512, 512, "", slots)
    lora_inputs = graph["3"]["inputs"]
    assert lora_inputs["lora_1_name"] == LORA_NONE_VALUE
    assert lora_inputs["lora_1_strength"] == 1.0


def test_patch_graph_slots_beyond_max_are_ignored():
    graph = make_graph(with_lora_node=True)
    slots = [{"name": f"l{i}.safetensors", "strength": 1.0}
             for i in range(MAX_LORA_SLOTS + 5)]
    patch_graph_for_generation(graph, "x", 1, 512, 512, "", slots)
    lora_inputs = graph["3"]["inputs"]
    assert f"lora_{MAX_LORA_SLOTS + 1}_name" not in lora_inputs
    assert lora_inputs[f"lora_{MAX_LORA_SLOTS}_name"] == f"l{MAX_LORA_SLOTS - 1}.safetensors"


def test_patch_graph_does_not_mutate_original_slot_dicts():
    graph = make_graph(with_lora_node=True)
    slots = [{"name": "a.safetensors", "strength": 0.5}]
    snapshot = copy.deepcopy(slots)
    patch_graph_for_generation(graph, "x", 1, 512, 512, "", slots)
    assert slots == snapshot


# ------------------------------------------------------ CLI integration --

@pytest.mark.skip(reason=(
    "Manual/CLI only — requires a real running ComfyUI instance with the "
    "PromptForgeConnection bridge node open in a browser tab. Run "
    "manually: `python -m pytest tests/test_comfy_worker_session9.py -k "
    "integration --no-skip` after removing this skip, with ComfyUI "
    "listening on 127.0.0.1:8188 (or set COMFY_TEST_HOST/COMFY_TEST_PORT "
    "env vars)."
))
def test_integration_full_generation_round_trip():
    """Documents how to manually verify the real pipeline end-to-end
    without the Qt event loop, using ComfyCheckWorker/
    ComfyGenerationWorker's underlying client calls directly:

    1. Start ComfyUI, load a workflow containing one PromptForgeConnection
       node (and optionally one PromptForgeMultiLoraLoader), leave the
       browser tab open.
    2. `client = ComfyUIClient(host, port)`
    3. `client.check_connection()` should not raise.
    4. `graph, err = _fetch_live_graph(client)` — err should be None.
    5. `ok, msg = _validate_live_graph(graph)` — ok should be True.
    6. `patch_graph_for_generation(graph, "a red fox", 42, 512, 512, "", [])`
    7. `prompt_id = client.submit_prompt(graph)`
    8. `entry = client.wait_for_completion(prompt_id)`
    9. `filename, subfolder, img_type = ComfyUIClient.extract_image_info(entry)`
       should return a real filename.
    10. `img_bytes = client.download_image(filename, subfolder, img_type)`
        should return non-empty bytes decodable as an image.

    This is exactly the sequence ComfyGenerationWorker.run() performs;
    walking it by hand once against a live server is the fastest way to
    catch a protocol drift (e.g. ComfyUI changing its /history or /view
    response shape) that unit tests against fixed fixtures can't catch.
    """
    pass  # pragma: no cover
