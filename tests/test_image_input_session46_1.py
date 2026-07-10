"""Session 46.1 tests — img2img input-image plumbing.

Revised after the actual companion node package (PromptForge-Nodes)
came back: instead of a separate PromptForgeImageInput node,
PromptForgeConnection itself grew an optional `image` (+ derived
`mask`) input/output pair -- same "always passes through, nobody's
forced to wire it" contract negative_prompt already has. So there's no
second class_type to look up; patch_graph_for_generation patches
`image` straight into the same Connector node it already finds for
prompt/seed/width/height/negative_prompt.

Same PyQt6/network limitation as the Session 9 worker tests: this file
imports `workers.comfy_worker` (PyQt6 at module level). Written and
believed correct against the ported logic; the actual upload->patch->
submit->result loop can only be verified with a real ComfyUI + the
updated nodes.py installed.

Covers the pure, Qt-free additions:
  - patch_graph_for_generation's new uploaded_image_filename passthrough
    (writes straight into the Connector node, t2i-default is a no-op)
  - ComfyUIClient.upload_image's multipart body construction and
    response handling (mocked HTTP, same pattern as
    tests/test_comfy_worker_session9.py / test_backend_smoke.py use for
    comfy_client.py's other HTTP methods)
"""
import io
import json

import pytest

from workers.comfy_worker import patch_graph_for_generation
from backend.constants import COMFY_NODE_CLASS_TYPE
from backend.comfy_client import ComfyUIClient, ComfyUIError


def make_graph():
    return {
        "1": {"class_type": COMFY_NODE_CLASS_TYPE, "inputs": {}},
        "2": {"class_type": "SaveImage", "inputs": {}},
    }


# --------------------------------------------------- image passthrough --

def test_patch_graph_writes_image_onto_connector_node():
    graph = make_graph()
    patch_graph_for_generation(
        graph, "a cat", 1, 512, 512, "", [],
        uploaded_image_filename="my_upload.png")
    assert graph["1"]["inputs"]["image"] == "my_upload.png"
    # Core fields still patched as before -- image is additive, not a
    # replacement for anything.
    assert graph["1"]["inputs"]["prompt"] == "a cat"


def test_patch_graph_t2i_default_does_not_touch_image_key():
    # Default uploaded_image_filename=None must be a true no-op: no
    # "image" key gets written at all, leaving the Connector's own
    # "None" widget default in place for a plain t2i graph — existing
    # t2i-only callers/tests keep working unmodified (see
    # test_comfy_worker_session9.py).
    graph = make_graph()
    patch_graph_for_generation(graph, "a cat", 1, 512, 512, "", [])
    assert "image" not in graph["1"]["inputs"]


def test_patch_graph_empty_string_filename_is_also_a_noop():
    graph = make_graph()
    patch_graph_for_generation(
        graph, "a cat", 1, 512, 512, "", [], uploaded_image_filename="")
    assert "image" not in graph["1"]["inputs"]


def test_patch_graph_still_raises_without_connector_node():
    graph = {"2": {"class_type": "SaveImage", "inputs": {}}}
    with pytest.raises(ComfyUIError) as exc:
        patch_graph_for_generation(
            graph, "x", 1, 512, 512, "", [], uploaded_image_filename="a.png")
    assert COMFY_NODE_CLASS_TYPE in str(exc.value)


# --------------------------------------------------------- upload_image --

class _FakeResponse:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_upload_image_bytes_success(monkeypatch):
    client = ComfyUIClient(host="127.0.0.1", port=8188)
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["body"] = req.data
        return _FakeResponse(json.dumps(
            {"name": "clipspace-1.png", "subfolder": "", "type": "input"}
        ).encode("utf-8"))

    monkeypatch.setattr(
        "backend.comfy_client.urllib.request.urlopen", fake_urlopen)

    result = client.upload_image(b"\x89PNGfakebytes", filename="in.png")
    assert result == {"name": "clipspace-1.png", "subfolder": "", "type": "input"}
    assert captured["url"] == "http://127.0.0.1:8188/upload/image"
    assert b'name="image"; filename="in.png"' in captured["body"]
    assert b'name="overwrite"' in captured["body"]
    assert b"\r\nfalse\r\n" in captured["body"]


def test_upload_image_bytes_requires_filename():
    client = ComfyUIClient()
    with pytest.raises(ComfyUIError):
        client.upload_image(b"somebytes")


def test_upload_image_reads_path(monkeypatch, tmp_path):
    p = tmp_path / "input.png"
    p.write_bytes(b"fake-png-bytes")

    client = ComfyUIClient()

    def fake_urlopen(req, timeout=None):
        assert b"fake-png-bytes" in req.data
        return _FakeResponse(json.dumps(
            {"name": "input.png", "subfolder": "", "type": "input"}
        ).encode("utf-8"))

    monkeypatch.setattr(
        "backend.comfy_client.urllib.request.urlopen", fake_urlopen)

    result = client.upload_image(str(p))
    assert result["name"] == "input.png"


def test_upload_image_http_error_raises_comfy_error(monkeypatch):
    import urllib.error
    client = ComfyUIClient()

    def fake_urlopen(req, timeout=None):
        raise urllib.error.HTTPError(
            req.full_url, 400, "Bad Request", hdrs=None,
            fp=io.BytesIO(b'{"error": "bad file"}'))

    monkeypatch.setattr(
        "backend.comfy_client.urllib.request.urlopen", fake_urlopen)

    with pytest.raises(ComfyUIError):
        client.upload_image(b"x", filename="x.png")


def test_upload_image_missing_name_in_response_raises(monkeypatch):
    client = ComfyUIClient()

    def fake_urlopen(req, timeout=None):
        return _FakeResponse(json.dumps({"subfolder": "", "type": "input"}).encode("utf-8"))

    monkeypatch.setattr(
        "backend.comfy_client.urllib.request.urlopen", fake_urlopen)

    with pytest.raises(ComfyUIError):
        client.upload_image(b"x", filename="x.png")
