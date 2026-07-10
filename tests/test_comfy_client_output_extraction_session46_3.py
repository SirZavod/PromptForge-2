"""Session 46.3/46.4 tests — ComfyUIClient.extract_output_info, the
generalized (image-or-video, any node, any output key) successor to
extract_image_info. See additionalfeatures.md's SESSION 46.3 write-up
for why this scans every output key instead of hardcoding "images" or
hunting for a specific node's class_type.

extract_image_info itself is deliberately NOT touched or retested here
-- this module's own docstring promises it's still exactly what was
migrated from the original monolith, unmodified.
"""
from backend.comfy_client import ComfyUIClient


def _history_entry(outputs):
    return {"outputs": outputs}


def test_extracts_image_from_images_key():
    entry = _history_entry({
        "9": {"images": [{"filename": "result_00001_.png", "subfolder": "", "type": "output"}]},
    })
    filename, subfolder, out_type, is_video = ComfyUIClient.extract_output_info(entry)
    assert filename == "result_00001_.png"
    assert subfolder == ""
    assert out_type == "output"
    assert is_video is False


def test_extracts_video_from_gifs_key():
    """VHS_VideoCombine's historical key name -- still "gifs" even for
    an actual .mp4 output, a ComfyUI-ecosystem quirk this function has
    to tolerate rather than assume away."""
    entry = _history_entry({
        "12": {"gifs": [{"filename": "AnimateDiff_00001.mp4", "subfolder": "video", "type": "output"}]},
    })
    filename, subfolder, out_type, is_video = ComfyUIClient.extract_output_info(entry)
    assert filename == "AnimateDiff_00001.mp4"
    assert subfolder == "video"
    assert is_video is True


def test_extracts_video_from_videos_key():
    entry = _history_entry({
        "7": {"videos": [{"filename": "clip.webm", "subfolder": "", "type": "output"}]},
    })
    filename, subfolder, out_type, is_video = ComfyUIClient.extract_output_info(entry)
    assert filename == "clip.webm"
    assert is_video is True


def test_extracts_from_arbitrary_unknown_key_name():
    """The whole point: no hardcoded key allowlist. A brand-new custom
    node inventing its own output key name still gets picked up as
    long as the value shape matches (list of {"filename": ...} dicts)."""
    entry = _history_entry({
        "3": {"some_future_node_output_key": [{"filename": "thing.mov", "subfolder": "", "type": "output"}]},
    })
    filename, subfolder, out_type, is_video = ComfyUIClient.extract_output_info(entry)
    assert filename == "thing.mov"
    assert is_video is True


def test_classification_is_purely_extension_based():
    for name, expected_video in [
        ("a.png", False), ("a.jpg", False), ("a.webp", False), ("a.gif", False),
        ("a.mp4", True), ("a.webm", True), ("a.mov", True), ("a.mkv", True), ("a.avi", True),
        ("a.MP4", True),  # case-insensitive
    ]:
        entry = _history_entry({"1": {"images": [{"filename": name, "subfolder": "", "type": "output"}]}})
        _, _, _, is_video = ComfyUIClient.extract_output_info(entry)
        assert is_video is expected_video, f"{name} expected is_video={expected_video}"


def test_returns_none_tuple_when_nothing_found():
    entry = _history_entry({"1": {"some_key": "not a list"}})
    assert ComfyUIClient.extract_output_info(entry) == (None, None, None, False)


def test_empty_history_entry():
    assert ComfyUIClient.extract_output_info({}) == (None, None, None, False)


def test_ignores_non_dict_list_items():
    """A list of plain strings (or anything else not dict-shaped) must
    be skipped rather than crashing on `.get`."""
    entry = _history_entry({
        "1": {"weird_key": ["not", "a", "dict"]},
        "2": {"images": [{"filename": "real.png", "subfolder": "", "type": "output"}]},
    })
    filename, _, _, is_video = ComfyUIClient.extract_output_info(entry)
    assert filename == "real.png"
    assert is_video is False


def test_extract_image_info_unchanged_and_still_images_only():
    """extract_image_info must still ONLY look at "images" -- a video
    living under "gifs"/"videos" must be invisible to it, exactly as
    before this session. Any caller still using the old method should
    behave identically to pre-46.3."""
    entry = _history_entry({
        "12": {"gifs": [{"filename": "clip.mp4", "subfolder": "", "type": "output"}]},
    })
    assert ComfyUIClient.extract_image_info(entry) == (None, None, None)

    entry2 = _history_entry({
        "9": {"images": [{"filename": "pic.png", "subfolder": "sub", "type": "output"}]},
    })
    assert ComfyUIClient.extract_image_info(entry2) == ("pic.png", "sub", "output")


def test_worker_has_video_ready_signal():
    """Cheap smoke check that the new signal exists with the right
    name/arity — catches an import/typo error without needing a full
    QThread.run() integration test (which would need a real or heavily
    mocked ComfyUIClient over HTTP)."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from workers.comfy_worker import ComfyGenerationWorker
    assert hasattr(ComfyGenerationWorker, "video_ready")
    assert hasattr(ComfyGenerationWorker, "image_ready")
