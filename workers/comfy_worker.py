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

from backend.comfy_client import ComfyUIClient, ComfyUIError, combo_choices
from backend.constants import (
    COMFY_GRAPH_PATH,
    COMFY_LORAS_PATH,
    COMFY_HTTP_TIMEOUT,
    COMFY_MODEL_KINDS,
    COMFY_NODE_CLASS_TYPE,
    COMFY_NODE_CLASS_TYPE_CLIP_LOADER,
    COMFY_NODE_CLASS_TYPE_DIFFUSION_LOADER,
    COMFY_NODE_CLASS_TYPE_VAE_LOADER,
    COMFY_POLL_TIMEOUT,
    COMFY_PREVIEW_MIN_INTERVAL,
    COMFY_SAMPLER_CLASS_TYPES,
    COMFY_VIDEO_POLL_TIMEOUT,
    MAX_LORA_SLOTS,
    LORA_NONE_VALUE,
    LORA_STRENGTH_MIN,
    LORA_STRENGTH_MAX,
    PIPELINE_MODE_I2V,
)

LORA_LOADER_CLASS_TYPE = "PromptForgeMultiLoraLoader"

# Session 73: PromptForgeConnection's RETURN_NAMES (nodes.py) are
# prompt, seed, width, height, negative_prompt, image, mask, steps, cfg
# -- the two sampling outputs were appended after mask in Session 70
# (D23), so their slots stay 7 and 8 forever.
CONNECTOR_STEPS_OUTPUT_SLOT = 7
CONNECTOR_CFG_OUTPUT_SLOT = 8

# Session 73 (D22/D24) + Session 73 extra (D34/D35/D36): what a model
# snapshot writes into the graph.
#   (classes searched, input widget name, snapshot key, human label)
# A value is written only when exactly one node of the listed classes is
# in the graph (zero: nothing; several -- Wan high/low noise, two samplers
# -- reported, never guessed at) and only when that input holds a plain
# widget value, never over a link. KSampler and KSamplerAdvanced are
# counted together (D35).
MODEL_WIDGET_PATCHES = (
    ((COMFY_NODE_CLASS_TYPE_DIFFUSION_LOADER,), "diffusion_model",
     "diffusion_model", "diffusion model"),
    ((COMFY_NODE_CLASS_TYPE_CLIP_LOADER,), "clip", "clip", "text encoder"),
    ((COMFY_NODE_CLASS_TYPE_VAE_LOADER,), "vae", "vae", "VAE"),
    ((COMFY_NODE_CLASS_TYPE_CLIP_LOADER,), "type", "clip_type",
     "text encoder type"),
    (COMFY_SAMPLER_CLASS_TYPES, "sampler_name", "sampler", "sampler"),
    (COMFY_SAMPLER_CLASS_TYPES, "scheduler", "scheduler", "scheduler"),
)


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


def connector_sampling_links(graph):
    """Session 73 (D23): which of the Connector's sampling outputs are
    actually wired to something in the live graph.

    Returns {"steps": bool, "cfg": bool}, or {} when the graph has no
    PromptForgeConnection node. In ComfyUI's API-format prompt a link is
    a [node_id, output_slot] pair inside some node's `inputs`, so this
    just scans for pairs pointing at the Connector's slots 7 / 8 -- the
    same order nodes.py's RETURN_TYPES uses. Purely informational: the
    hint in Builder's Sampling card is the only consumer, and a missing
    link never blocks or fails a generation."""
    node_id, node = ComfyUIClient.find_node_by_class_type(graph, COMFY_NODE_CLASS_TYPE)
    if node is None:
        return {}
    linked = {"steps": False, "cfg": False}
    for other in graph.values():
        if not isinstance(other, dict):
            continue
        inputs = other.get("inputs")
        if not isinstance(inputs, dict):
            continue
        for value in inputs.values():
            if (isinstance(value, (list, tuple)) and len(value) == 2
                    and str(value[0]) == str(node_id)
                    and isinstance(value[1], int)):
                if value[1] == CONNECTOR_STEPS_OUTPUT_SLOT:
                    linked["steps"] = True
                elif value[1] == CONNECTOR_CFG_OUTPUT_SLOT:
                    linked["cfg"] = True
    return linked


def _snapshot_int(value):
    """Tolerant int from a queue snapshot: bools and garbage are ignored
    (never invented), so a malformed snapshot cannot abort a run."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _snapshot_float(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _snapshot_str(value):
    """Tolerant string from a queue snapshot: only a non-blank str counts,
    everything else (None, numbers, bools, objects) means "do not touch"
    (D15). Returns the stripped text."""
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _is_link(value):
    """ComfyUI API-graph link: [source_node_id, output_slot]."""
    return isinstance(value, (list, tuple))


def _set_widget(node, name, value, label, notes):
    """Session 73 extra (D36): writes `value` into `node["inputs"][name]`
    unless that input is a link to another node, in which case the link
    is left alone and a one-line note says so. Returns True when written."""
    inputs = node.setdefault("inputs", {})
    if _is_link(inputs.get(name)):
        notes.append(
            f'The "{node.get("class_type")}" {name} input is linked to '
            f'another node — the {label} was not applied.')
        return False
    inputs[name] = value
    return True


def _class_names(nodes):
    """Quoted class names of `nodes` in first-seen order, for a note."""
    names = []
    for node in nodes:
        quoted = f'"{node.get("class_type")}"'
        if quoted not in names:
            names.append(quoted)
    return " / ".join(names)


def _patch_model_widgets(graph, snapshot, notes):
    """Session 73 (D22) + Session 73 extra (D35/D36): writes the preset's
    files, text encoder type, sampler and scheduler into the nodes that
    own those widgets (`MODEL_WIDGET_PATCHES`). Evaluated per field: an
    empty field is D15's "do not touch" and is skipped entirely; zero
    matching nodes means the model simply was not wired into that graph;
    several are ambiguous and left untouched with ONE note per node group
    naming the class (the fields it blocks are listed together); an input
    that is a link is never overwritten."""
    nodes = [node for node in graph.values() if isinstance(node, dict)]
    ambiguous = {}  # classes tuple -> (matching nodes, [labels])
    for classes, input_name, snapshot_key, label in MODEL_WIDGET_PATCHES:
        value = _snapshot_str(snapshot.get(snapshot_key))
        if value is None:
            continue
        matches = [n for n in nodes if n.get("class_type") in classes]
        if not matches:
            continue
        if len(matches) > 1:
            entry = ambiguous.setdefault(classes, (matches, []))
            entry[1].append(label)
            continue
        _set_widget(matches[0], input_name, value, label, notes)
    for matches, labels in ambiguous.values():
        notes.append(
            f'{len(matches)} {_class_names(matches)} nodes are in the '
            f'workflow — the {" / ".join(labels)} was not applied. '
            f'PromptForge needs exactly one.')


def patch_graph_for_generation(graph, prompt_text, seed, width, height,
                                negative_text, lora_slots_snapshot,
                                uploaded_image_filename=None,
                                model_snapshot=None, report=None):
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
    default for a plain t2i graph).

    `model_snapshot` (Session 73, D27) is the model frozen at click
    time: model id / name, the three resolved file names, steps and cfg.
    None keeps the pre-S73 behaviour exactly. Each value is written only
    when it is set (D15): an empty file leaves its loader alone, an
    empty Steps / CFG leaves the Connector's widget alone. Files go into
    the single PromptForge loader of their kind (D22), Steps / CFG into
    the Connector (D23). Multi-node graphs are never guessed at.

    `report` is an optional dict the caller passes in; it receives a
    "notes" list with one-line, user-facing explanations when something
    could not be patched (e.g. two sampler-style loaders). Patching is
    always best-effort: a malformed snapshot or ambiguous graph must
    never abort an otherwise-valid generation."""
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

    notes = []
    if isinstance(model_snapshot, dict):
        steps = _snapshot_int(model_snapshot.get("steps"))
        if steps is not None:
            node["inputs"]["steps"] = steps
        cfg = _snapshot_float(model_snapshot.get("cfg"))
        if cfg is not None:
            node["inputs"]["cfg"] = cfg
        _patch_model_widgets(graph, model_snapshot, notes)

    if report is not None:
        report["notes"] = notes

    return graph


# --------------------------------------------------------------------- #
# Workers
# --------------------------------------------------------------------- #

class ComfyCheckWorker(QThread):
    """Runs `ComfyUIClient.check_connection()`, then fetches the live
    graph (validating the PromptForgeConnection node is present), the
    available LoRA list, the Connector's sampling link state and the
    model-file lists, all off the main thread.

    check_done(success, error_msg, out_dir, workflow_ok, workflow_msg,
               loras, sampling_links, model_files)
      - success: bool — could ComfyUI itself be reached at all.
      - error_msg: str — human-readable failure reason (empty on success).
      - out_dir: str — ComfyUI's real output/ folder if discoverable,
        else "" (never None — pyqtSignal(str) can't carry None).
      - workflow_ok: bool — whether a PromptForgeConnection node was
        found in the currently-open graph.
      - workflow_msg: str — explanation when workflow_ok is False.
      - loras: list — available LoRA filenames (empty list on any
        failure to fetch, connected or not — best-effort).
      - sampling_links: dict — {"steps": bool, "cfg": bool} (Session 73,
        D23), {} when no Connector node / no graph.
      - model_files: dict — `collect_model_files` result for the
        missing-file check (D28) and the old-pack hint (D25).
    """

    check_done = pyqtSignal(bool, str, str, bool, str, list, dict, dict)

    def __init__(self, client: ComfyUIClient, parent=None):
        super().__init__(parent)
        self.client = client

    def run(self):
        try:
            self.client.check_connection()
        except ComfyUIError as e:
            self.check_done.emit(False, str(e), "", False, "", [], {}, {})
            return
        except Exception as e:
            # Anything unexpected here must still reach check_done —
            # an uncaught exception in a QThread.run() just ends the
            # thread silently, leaving the caller waiting forever for
            # a signal that never fires (see comfy_client.py's own
            # note on this same failure mode in the original app).
            self.check_done.emit(
                False, f"Unexpected error while checking connection: {e}",
                "", False, "", [], {}, {})
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

        links = connector_sampling_links(graph) if graph else {}
        # Session 73: same D25/D26 result Settings uses. Best-effort: an
        # old pack or a listing error only adds a hint, never blocks the
        # connection itself.
        try:
            model_files = collect_model_files(self.client)
        except Exception:
            model_files = {}

        self.check_done.emit(
            True, "", out_dir or "", workflow_ok, workflow_msg, loras,
            links, model_files)


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


EMPTY_CHOICES = {"clip_type": [], "sampler": [], "scheduler": []}


def collect_node_choices(client):
    """Session 73 extra (D37): the option lists for the text encoder
    `type`, the sampler and the scheduler, read from ComfyUI's own node
    definitions (`/object_info/<class>`).

        {"clip_type": [...], "sampler": [...], "scheduler": [...]}

    Every list is independent and `[]` when it cannot be read: the class
    is not registered (a pack older than 1.2.0 has no PromptForgeClipLoader,
    a workflow-free ComfyUI still has KSampler), ComfyUI answered with an
    unknown shape, or the request failed. Sampler / scheduler come from
    `KSampler` and fall back to `KSamplerAdvanced` per field. Never raises:
    a missing list only disables its picker."""
    def info(class_type):
        try:
            return client.get_object_info(class_type)
        except Exception:
            return {}

    choices = {key: list(value) for key, value in EMPTY_CHOICES.items()}
    choices["clip_type"] = combo_choices(
        info(COMFY_NODE_CLASS_TYPE_CLIP_LOADER),
        COMFY_NODE_CLASS_TYPE_CLIP_LOADER, "type")
    for class_type in COMFY_SAMPLER_CLASS_TYPES:
        if choices["sampler"] and choices["scheduler"]:
            break
        sampler_info = info(class_type)
        if not choices["sampler"]:
            choices["sampler"] = combo_choices(
                sampler_info, class_type, "sampler_name")
        if not choices["scheduler"]:
            choices["scheduler"] = combo_choices(
                sampler_info, class_type, "scheduler")
    return choices


def collect_model_files(client, refresh=False, kinds=COMFY_MODEL_KINDS):
    """Session 73 extra (D37): the file-list result plus a `choices` key
    (see `collect_node_choices`). Choices are read whenever ComfyUI
    answers -- also with an old pack or a file listing error -- and are
    all empty when ComfyUI is offline."""
    state = _collect_model_file_lists(client, refresh=refresh, kinds=kinds)
    if state.get("status") == "offline":
        state["choices"] = {key: [] for key in EMPTY_CHOICES}
    else:
        state["choices"] = collect_node_choices(client)
    return state


def _collect_model_file_lists(client, refresh=False, kinds=COMFY_MODEL_KINDS):
    """Session 71 (D25/D26): one result dict for the Settings file combos.

        {"status": "ok" | "offline" | "old_pack" | "error",
         "files": {"diffusion": [...], "clip": [...], "vae": [...]},
         "message": user-facing note (empty on success)}

    `get_node_info` is the handshake: when ComfyUI answers but the pack
    does not serve it, the pack is older than 1.2.0 and the combos must
    be disabled. ComfyUI not answering at all is "offline" -- the note
    stays, the stored values remain editable, nothing is cleared."""
    try:
        client.get_node_info()
    except ComfyUIError:
        try:
            client.check_connection()
        except ComfyUIError:
            return {"status": "offline", "files": {}, "message": (
                "ComfyUI is offline — model file lists are unavailable. "
                "Saved values are kept.")}
        except Exception:
            return {"status": "offline", "files": {}, "message": (
                "ComfyUI is offline — model file lists are unavailable. "
                "Saved values are kept.")}
        return {"status": "old_pack", "files": {}, "message": (
            "Update the PromptForge node pack to 1.2.0 or newer to pick "
            "model files here.")}
    except Exception:
        return {"status": "offline", "files": {}, "message": (
            "ComfyUI is offline — model file lists are unavailable. "
            "Saved values are kept.")}

    files = {}
    try:
        for kind in kinds:
            files[kind] = client.get_model_files(kind, refresh=refresh)
    except Exception as exc:
        return {"status": "error", "files": files, "message": (
            f"ComfyUI could not list model files: {exc}. "
            "Saved values are kept.")}
    return {"status": "ok", "files": files, "message": ""}


class ModelFilesWorker(QThread):
    """Session 71: fetches the three model-file lists off the main thread
    the first time a Settings row is expanded."""

    files_ready = pyqtSignal(dict)

    def __init__(self, client: ComfyUIClient, refresh=False, parent=None):
        super().__init__(parent)
        self.client = client
        self.refresh = refresh

    def run(self):
        self.files_ready.emit(
            collect_model_files(self.client, refresh=self.refresh))


class ComfyGenerationWorker(QThread):
    """Runs the full generation pipeline for a single queue item:
    fetch+validate live graph, patch it, submit, listen for
    progress/preview over the WebSocket, wait for completion, download
    the result. Exactly one of these runs at a time — enforced by the
    Builder tab's queue (Session 11), not by this class.

    queue_item is the dict already snapshotted at enqueue time:
    {"prompt_text", "seed", "width", "height", "negative_text",
     "lora_slots_snapshot", "model_snapshot", ...}. Only those keys (plus
    the optional Session 46.1 "input_image_path" for i2i/i2v items) are
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
      status_note(text)               — Session 73 (D22): the graph was
                                         patched except for one ambiguous
                                         thing (e.g. two diffusion loaders);
                                         informational, the run continues.
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
    status_note = pyqtSignal(str)
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

            patch_report = {}
            patch_graph_for_generation(
                graph,
                self.queue_item["prompt_text"],
                self.queue_item["seed"],
                self.queue_item["width"],
                self.queue_item["height"],
                self.queue_item["negative_text"],
                self.queue_item.get("lora_slots_snapshot"),
                uploaded_image_filename=uploaded_filename,
                model_snapshot=self.queue_item.get("model_snapshot"),
                report=patch_report,
            )
            for note in patch_report.get("notes") or []:
                self.status_note.emit(note)

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
