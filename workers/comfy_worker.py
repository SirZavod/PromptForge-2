"""QThread-based workers wrapping every blocking ComfyUI network call.

Built in Session 9 per the migration plan ("Worker threads
(ComfyCheckWorker / ComfyGenerationWorker)"). Replaces the Session 3
stub. No UI changes here — orchestrating *when* a queued generation
starts is a Builder-tab concern (Session 11); this module only knows
how to run a single check or a single generation off the main thread
and report back over signals.

Per the plan's hard rules:
- Every network call (`check_connection`, `submit_prompt`,
  `wait_for_completion`, `_listen_progress_ws`, `download_image`) runs
  inside a `QThread`, never on the main thread.
- Workers never call `QApplication.processEvents()` — all UI updates
  go through signals.
- `ComfyUIClient` itself is wrapped, never modified.

`_fetch_live_graph` / `_validate_live_graph` / `patch_graph_for_generation`
are ported near-verbatim from the original monolith's
`PromptForgeApp._fetch_live_graph` / `_validate_live_graph` / the
graph-patching block inside `_start_comfy_generation`'s worker
closure — pulled out to module-level, dependency-free functions here
so they're usable (and unit-testable) from both worker classes
without a Qt event loop.
"""
import json
import time
import urllib.request
import urllib.error

from PyQt6.QtCore import QThread, pyqtSignal

from backend.comfy_client import ComfyUIClient, ComfyUIError
from backend.constants import (
    COMFY_GRAPH_PATH,
    COMFY_LORAS_PATH,
    COMFY_HTTP_TIMEOUT,
    COMFY_NODE_CLASS_TYPE,
    COMFY_POLL_TIMEOUT,
    COMFY_PREVIEW_MIN_INTERVAL,
    COMFY_VIDEO_POLL_TIMEOUT,
    MAX_LORA_SLOTS,
    LORA_NONE_VALUE,
    LORA_STRENGTH_MIN,
    LORA_STRENGTH_MAX,
    PIPELINE_MODE_I2V,
)

LORA_LOADER_CLASS_TYPE = "PromptForgeMultiLoraLoader"


# --------------------------------------------------------------------- #
# Pure helpers — no Qt, no threading. Shared by ComfyCheckWorker and
# ComfyGenerationWorker, and directly unit-testable.
# --------------------------------------------------------------------- #

def _fetch_live_graph(client: ComfyUIClient):
    """Fetches the current graph from the JS bridge route GET
    /promptforge/graph (served by the custom node's Python side).
    Returns (graph_dict, None) on success or (None, error_str) on
    failure. Blocking — only ever call this from a worker thread."""
    url = f"{client.base_url}{COMFY_GRAPH_PATH}"
    try:
        with urllib.request.urlopen(url, timeout=COMFY_HTTP_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            graph = data.get("graph")
            if not isinstance(graph, dict):
                return None, "Bridge returned unexpected data (no 'graph' key)."
            return graph, None
    except urllib.error.HTTPError as e:
        if e.code == 503:
            try:
                body = json.loads(e.read().decode("utf-8"))
                detail = body.get("detail", "")
            except Exception:
                detail = ""
            return None, (
                "No graph snapshot available yet.\n"
                "Open the ComfyUI browser tab (or reload it) so the "
                "PromptForge Bridge extension can push the current graph." +
                (f"\n\nDetails: {detail}" if detail else "")
            )
        return None, f"HTTP {e.code} from ComfyUI bridge: {e.reason}"
    except urllib.error.URLError as e:
        return None, f"Could not reach ComfyUI at {client.base_url}: {e.reason}"
    except json.JSONDecodeError:
        return None, "ComfyUI bridge returned invalid JSON."


def _validate_live_graph(graph: dict):
    """Checks that a fetched graph dict contains exactly one
    PromptForgeConnection node. Returns (ok: bool, message: str)."""
    node_id, node = ComfyUIClient.find_node_by_class_type(graph, COMFY_NODE_CLASS_TYPE)
    if node is None:
        return False, (
            f"No \"{COMFY_NODE_CLASS_TYPE}\" node was found in the "
            f"currently open ComfyUI workflow. Add the node to your "
            f"graph and make sure the browser tab is open."
        )
    return True, ""


def patch_graph_for_generation(graph, prompt_text, seed, width, height,
                                negative_text, lora_slots_snapshot,
                                uploaded_image_filename=None):
    """Patches the (already-fetched, already-validated) live graph in
    place with this generation's parameters. Mutates and returns
    `graph`. Raises ComfyUIError if no PromptForgeConnection node is
    present (callers should already have validated via
    `_validate_live_graph`, but this stays defensive).

    LoRA patching is graceful-fallback: an absent
    PromptForgeMultiLoraLoader node, or malformed slot data, must
    never abort an otherwise-valid generation.

    `uploaded_image_filename` (Session 46.1) is the filename ComfyUI's
    /upload/image handed back for this queue item's input image --
    None/empty in plain t2i mode. There's no separate image-input node
    to find: the Connector itself grew an optional `image` (+ derived
    `mask`) input/output pair, the same "always passes through, nobody's
    forced to wire it" contract negative_prompt already has -- so this
    patches straight into the same node found below, right alongside
    prompt/seed/width/height/negative_prompt. A falsy
    uploaded_image_filename simply isn't written at all, leaving
    whatever the node's own `image` widget already has (its "None"
    default for a plain t2i graph)."""
    node_id, node = ComfyUIClient.find_node_by_class_type(graph, COMFY_NODE_CLASS_TYPE)
    if node is None:
        raise ComfyUIError(f"No \"{COMFY_NODE_CLASS_TYPE}\" node found in graph.")
    node.setdefault("inputs", {})
    node["inputs"]["prompt"] = prompt_text
    node["inputs"]["seed"] = seed
    node["inputs"]["width"] = width
    node["inputs"]["height"] = height
    node["inputs"]["negative_prompt"] = negative_text
    if uploaded_image_filename:
        node["inputs"]["image"] = uploaded_image_filename

    lora_node = None
    for nid, n in graph.items():
        if isinstance(n, dict) and n.get("class_type") == LORA_LOADER_CLASS_TYPE:
            lora_node = n
            break
    if lora_node is not None:
        lora_node.setdefault("inputs", {})
        active_count = 0
        for i, slot in enumerate(lora_slots_snapshot or [], start=1):
            if i > MAX_LORA_SLOTS:
                break
            try:
                slot_name = (slot.get("name") or "").strip() or LORA_NONE_VALUE
                slot_str = float(slot.get("strength", 1.0))
                slot_str = max(LORA_STRENGTH_MIN, min(LORA_STRENGTH_MAX, slot_str))
            except (ValueError, TypeError, AttributeError):
                slot_name = LORA_NONE_VALUE
                slot_str = 1.0
            lora_node["inputs"][f"lora_{i}_name"] = slot_name
            lora_node["inputs"][f"lora_{i}_strength"] = slot_str
            active_count = i
        for i in range(active_count + 1, MAX_LORA_SLOTS + 1):
            lora_node["inputs"][f"lora_{i}_name"] = LORA_NONE_VALUE
            lora_node["inputs"][f"lora_{i}_strength"] = 1.0

    return graph


# --------------------------------------------------------------------- #
# Workers
# --------------------------------------------------------------------- #

class ComfyCheckWorker(QThread):
    """Runs `ComfyUIClient.check_connection()`, then fetches the live
    graph (validating the PromptForgeConnection node is present) and
    the available LoRA list, all off the main thread.

    check_done(success, error_msg, out_dir, workflow_ok, workflow_msg, loras)
      - success: bool — could ComfyUI itself be reached at all.
      - error_msg: str — human-readable failure reason (empty on success).
      - out_dir: str — ComfyUI's real output/ folder if discoverable,
        else "" (never None — pyqtSignal(str) can't carry None).
      - workflow_ok: bool — whether a PromptForgeConnection node was
        found in the currently-open graph.
      - workflow_msg: str — explanation when workflow_ok is False.
      - loras: list — available LoRA filenames (empty list on any
        failure to fetch, connected or not — best-effort).
    """

    check_done = pyqtSignal(bool, str, str, bool, str, list)

    def __init__(self, client: ComfyUIClient, parent=None):
        super().__init__(parent)
        self.client = client

    def run(self):
        try:
            self.client.check_connection()
        except ComfyUIError as e:
            self.check_done.emit(False, str(e), "", False, "", [])
            return
        except Exception as e:
            # Anything unexpected here must still reach check_done —
            # an uncaught exception in a QThread.run() just ends the
            # thread silently, leaving the caller waiting forever for
            # a signal that never fires (see comfy_client.py's own
            # note on this same failure mode in the original app).
            self.check_done.emit(
                False, f"Unexpected error while checking connection: {e}", "", False, "", [])
            return

        try:
            out_dir = self.client.get_output_dir()
        except ComfyUIError:
            out_dir = None

        graph, err = _fetch_live_graph(self.client)
        if err:
            workflow_ok, workflow_msg = False, err
        else:
            workflow_ok, workflow_msg = _validate_live_graph(graph)

        loras = []
        try:
            data = self.client._get(COMFY_LORAS_PATH)
            fetched = data.get("loras", [])
            if isinstance(fetched, list):
                loras = fetched
        except Exception:
            loras = []  # best-effort — an empty list just means no LoRAs to offer yet

        self.check_done.emit(True, "", out_dir or "", workflow_ok, workflow_msg, loras)


class FetchLorasWorker(QThread):
    """Standalone LoRA-list refresh, for re-fetching later (e.g. after
    the user adds LoRA files without restarting ComfyUI) without
    re-running a full connection check."""

    loras_fetched = pyqtSignal(list)

    def __init__(self, client: ComfyUIClient, parent=None):
        super().__init__(parent)
        self.client = client

    def run(self):
        try:
            data = self.client._get(COMFY_LORAS_PATH)
            loras = data.get("loras", [])
            if not isinstance(loras, list):
                loras = []
        except Exception:
            loras = []
        self.loras_fetched.emit(loras)


class ComfyGenerationWorker(QThread):
    """Runs the full generation pipeline for a single queue item:
    fetch+validate live graph, patch it, submit, listen for
    progress/preview over the WebSocket, wait for completion, download
    the result. Exactly one of these runs at a time — enforced by the
    Builder tab's queue (Session 11), not by this class.

    queue_item is the dict already snapshotted at enqueue time:
    {"prompt_text", "seed", "width", "height", "negative_text",
     "lora_slots_snapshot", ...}. Only those five keys (plus the
     optional Session 46.1 "input_image_path" for i2i/i2v items) are
     read here; any extra keys (e.g. "history_id") are the caller's
     concern.

    Signals:
      progress_updated(current, max)
      preview_ready(image_bytes)      — throttled to COMFY_PREVIEW_MIN_INTERVAL
      image_ready(img_bytes, filename, subfolder)
      video_ready(video_bytes, filename, subfolder)  — Session 46.3/46.4:
                                         mutually exclusive with image_ready,
                                         never both for the same run. Which
                                         one fires is decided by
                                         ComfyUIClient.extract_output_info's
                                         is_video flag (file-extension based,
                                         not node-type based — see that
                                         method's docstring).
      generation_failed(error_msg)
      generation_finished()           — fires on completion, failure, OR
                                         stop, always exactly once, always
                                         last. The Builder tab's queue
                                         should hook only this one signal
                                         to know "this slot is free, try
                                         the next queued item."
    """

    progress_updated = pyqtSignal(int, int)
    preview_ready = pyqtSignal(bytes)
    image_ready = pyqtSignal(bytes, str, str)
    video_ready = pyqtSignal(bytes, str, str)
    generation_failed = pyqtSignal(str)
    generation_finished = pyqtSignal()

    def __init__(self, client: ComfyUIClient, queue_item: dict, parent=None):
        super().__init__(parent)
        self.client = client
        self.queue_item = queue_item
        self._stop_flag = False
        self._stopping = False
        self.was_stopped = False
        self._prompt_id = None
        self._last_preview_ts = 0.0

    def stop(self):
        """Requests cancellation. Sends a real POST /interrupt (and a
        best-effort dequeue) to ComfyUI so the GPU actually stops
        sampling — mirrors the original's on_comfy_stop_clicked. Both
        HTTP calls are blocking, so they run on a throwaway daemon
        thread rather than this method's caller (the Qt main thread)
        so the button click never freezes the UI. The cancel flag
        itself is set unconditionally regardless of whether those
        calls succeed, so our own wait_for_completion loop always
        stops even if ComfyUI is unreachable right now."""
        if self._stopping:
            return
        self._stopping = True
        self.was_stopped = True
        prompt_id = self._prompt_id
        client = self.client

        import threading

        def _interrupt_worker():
            try:
                client.interrupt()
            except ComfyUIError:
                pass
            if prompt_id:
                try:
                    client.delete_queue_item(prompt_id)
                except ComfyUIError:
                    pass
            self._stop_flag = True

        threading.Thread(target=_interrupt_worker, daemon=True).start()

    def run(self):
        try:
            graph, err = _fetch_live_graph(self.client)
            if err:
                self.generation_failed.emit(err)
                return

            ok, msg = _validate_live_graph(graph)
            if not ok:
                self.generation_failed.emit(msg)
                return

            # Session 46.1: i2i/i2v queue items carry a local input-image
            # path picked in PromptForge's own UI. Upload it to ComfyUI's
            # input/ folder now (same stock /upload/image route its own
            # LoadImage "choose file" button uses) so the filename it
            # comes back with can be patched straight into the Connector
            # node's own `image` widget below. Plain t2i items have no
            # "input_image_path" key (or it's falsy) and this is skipped
            # entirely.
            uploaded_filename = None
            input_image_path = self.queue_item.get("input_image_path")
            if input_image_path:
                try:
                    uploaded = self.client.upload_image(input_image_path)
                except ComfyUIError as e:
                    self.generation_failed.emit(f"Could not upload input image to ComfyUI: {e}")
                    return
                uploaded_filename = uploaded["name"]

            patch_graph_for_generation(
                graph,
                self.queue_item["prompt_text"],
                self.queue_item["seed"],
                self.queue_item["width"],
                self.queue_item["height"],
                self.queue_item["negative_text"],
                self.queue_item.get("lora_slots_snapshot"),
                uploaded_image_filename=uploaded_filename,
            )

            try:
                prompt_id = self.client.submit_prompt(graph)
            except ComfyUIError as e:
                self.generation_failed.emit(str(e))
                return
            self._prompt_id = prompt_id

            def _on_preview_frame(img_bytes):
                # Throttled here, in this WS-listener thread, so a fast
                # stream of KSampler preview frames doesn't flood the
                # Qt main thread with a decode+redraw per step.
                now = time.monotonic()
                if now - self._last_preview_ts < COMFY_PREVIEW_MIN_INTERVAL:
                    return
                self._last_preview_ts = now
                self.preview_ready.emit(img_bytes)

            def _on_progress(cur, total):
                self.progress_updated.emit(cur, total)

            entry = self.client.wait_for_completion(
                prompt_id,
                progress_callback=_on_progress,
                preview_callback=_on_preview_frame,
                should_cancel=lambda: self._stop_flag,
                # Session 47.4 fix: COMFY_POLL_TIMEOUT's 300s was sized
                # for t2i/i2i and was silently inherited by i2v too,
                # where a real generation can legitimately run 10-30
                # minutes -- every video run was failing with "Generation
                # Failed" well before ComfyUI was actually done. i2v
                # queue items get COMFY_VIDEO_POLL_TIMEOUT instead; t2i/
                # i2i (and any older queue item dict without a
                # "pipeline_mode" key at all) keep the original, much
                # tighter ceiling so a genuinely stuck/crashed job still
                # reports failure in ~5 minutes, not 40.
                timeout=(COMFY_VIDEO_POLL_TIMEOUT
                         if self.queue_item.get("pipeline_mode") == PIPELINE_MODE_I2V
                         else COMFY_POLL_TIMEOUT))

            filename, subfolder, img_type, is_video = ComfyUIClient.extract_output_info(entry)
            if not filename:
                self.generation_failed.emit(
                    "Generation finished but the result file couldn't be located.\n"
                    "Check that a Save node (image or video) is in your graph.")
                return

            try:
                # `download_image` despite the name is just a generic
                # GET /view — works identically for a video file's
                # bytes. Not renamed: ComfyUIClient itself is meant to
                # stay unmodified from the original monolith (see this
                # module's own docstring / comfy_client.py's).
                result_bytes = self.client.download_image(filename, subfolder, img_type)
            except ComfyUIError as e:
                kind = "video" if is_video else "image"
                self.generation_failed.emit(f"Generation completed but the {kind} "
                                             f"could not be downloaded: {e}")
                return
            if is_video:
                self.video_ready.emit(result_bytes, filename, subfolder)
            else:
                self.image_ready.emit(result_bytes, filename, subfolder)

        except ComfyUIError as e:
            if self.was_stopped:
                self.generation_failed.emit("Stopped.")
            else:
                self.generation_failed.emit(str(e))
        except Exception as e:
            self.generation_failed.emit(f"Unexpected error during generation: {e}")
        finally:
            self.generation_finished.emit()
