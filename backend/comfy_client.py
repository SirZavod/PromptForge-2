"""ComfyUI HTTP/WebSocket client.

Copied verbatim from the original monolith (promptforgeint.py) per the
migration plan's explicit instruction: "Keep ComfyUIClient unmodified.
Its raw WebSocket frame parser, its urllib-only HTTP layer, and its
blocking thread model are carefully tuned. Wrap it; do not rewrite it."

The only change versus the original is the import source for shared
constants (now from backend.constants instead of module-global names
in the monolith). All network calls here are still BLOCKING — callers
(workers/comfy_worker.py) are responsible for running this off the
Qt main thread via QThread.
"""
import base64
import json
import os
import socket
import struct
import threading
import time
import uuid
import urllib.request
import urllib.error

from backend.constants import (
    COMFY_DEFAULT_HOST,
    COMFY_DEFAULT_PORT,
    COMFY_HTTP_TIMEOUT,
    COMFY_POLL_INTERVAL,
    COMFY_POLL_TIMEOUT,
    COMFY_UPLOAD_IMAGE_PATH,
    VIDEO_EXTENSIONS,
)

class ComfyUIError(Exception):
    """Raised for any ComfyUI-related failure — connection, missing node,
    bad workflow JSON, generation failure, or timeout. The message is
    meant to be shown to the user as-is."""
    pass


class ComfyUIClient:
    """Thin HTTP client around ComfyUI's REST API. No third-party
    dependencies — uses urllib from the standard library only.

    This class knows nothing about Tkinter; all of its methods are
    blocking and are meant to be called from a background thread. The
    owner (PromptForgeApp) is responsible for threading and for marshaling
    results back to the main thread via root.after(...).

    Protocol contract with the companion custom node
    (promptforgeconnection.py): the live graph is fetched at generation
    time from GET /promptforge/graph (served by the node's Python bridge).
    That graph must contain exactly one node whose "class_type" equals
    COMFY_NODE_CLASS_TYPE. That node's "inputs" dict is patched with
    prompt/seed/width/height before every submission.
    """

    def __init__(self, host=COMFY_DEFAULT_HOST, port=COMFY_DEFAULT_PORT):
        self.host = host
        self.port = port
        # Reused for both the /prompt submission and the /ws progress
        # listener below — ComfyUI ties "progress" events to the
        # client_id a job was submitted under, so both sides must match.
        self.client_id = uuid.uuid4().hex

    @property
    def base_url(self):
        return f"http://{self.host}:{self.port}"

    # ------------------------------------------------------------ HTTP --
    def _get(self, path, timeout=COMFY_HTTP_TIMEOUT):
        url = f"{self.base_url}{path}"
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as e:
            raise ComfyUIError(f"Could not reach ComfyUI at {self.base_url}: {e.reason}")
        except json.JSONDecodeError:
            raise ComfyUIError(f"ComfyUI returned an unexpected (non-JSON) response from {path}")

    def _post(self, path, payload, timeout=COMFY_HTTP_TIMEOUT):
        url = f"{self.base_url}{path}"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            # ComfyUI's /prompt validation errors come back as JSON with a
            # human-readable "error"/"node_errors" structure — surface it.
            detail = body
            try:
                parsed = json.loads(body)
                detail = parsed.get("error", {}).get("message", body) if isinstance(parsed, dict) else body
            except Exception:
                pass
            raise ComfyUIError(f"ComfyUI rejected the request ({e.code}): {detail}")
        except urllib.error.URLError as e:
            raise ComfyUIError(f"Could not reach ComfyUI at {self.base_url}: {e.reason}")
        except json.JSONDecodeError:
            raise ComfyUIError(f"ComfyUI returned an unexpected (non-JSON) response from {path}")

    # --------------------------------------------------------- queries --
    def check_connection(self):
        """Health check. Returns the system_stats dict on success, raises
        ComfyUIError otherwise."""
        return self._get("/system_stats")

    def get_output_dir(self):
        """Discovers ComfyUI's real output/ folder via the PromptForgeConnection
        bridge's GET /promptforge/output_dir route (backed server-side by
        folder_paths.get_output_directory()). Standard ComfyUI doesn't expose
        filesystem paths through /system_stats, so this requires the bridge
        node to be installed. Returns None gracefully if it's unavailable —
        the /view HTTP download is the primary image retrieval method and
        doesn't require this path at all."""
        try:
            data = self._get("/promptforge/output_dir")
            out_dir = data.get("output_dir")
            if out_dir:
                return out_dir
        except Exception:
            pass
        return None

    def download_image(self, filename, subfolder="", img_type="output"):
        """Downloads image bytes from ComfyUI's GET /view endpoint.
        Returns raw bytes on success, raises ComfyUIError on failure.
        This works even when we don't know the local output directory path
        (Windows paths, network ComfyUI, subfolders like Anima/, etc.)."""
        import urllib.parse
        params = urllib.parse.urlencode({
            "filename": filename,
            "type": img_type,
            "subfolder": subfolder,
        })
        url = f"{self.base_url}/view?{params}"
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            raise ComfyUIError(f"ComfyUI /view returned HTTP {e.code} for {filename}")
        except urllib.error.URLError as e:
            raise ComfyUIError(f"Could not download image from ComfyUI: {e.reason}")

    @staticmethod
    def extract_image_info(history_entry):
        """Extracts (filename, subfolder, type) from the first image in a
        completed /history entry. Returns (None, None, None) if not found."""
        outputs = history_entry.get("outputs", {})
        for node_output in outputs.values():
            images = node_output.get("images")
            if not images:
                continue
            img = images[0]
            filename = img.get("filename")
            if not filename:
                continue
            return filename, img.get("subfolder", ""), img.get("type", "output")
        return None, None, None

    @staticmethod
    def extract_output_info(history_entry):
        """Session 46.3/46.4, added alongside (not replacing)
        `extract_image_info` above -- that one stays exactly as
        migrated from the original monolith per this module's own
        "wrap it, do not rewrite it" docstring, so any existing caller
        keeps working unchanged. This is the new general version: it
        extracts (filename, subfolder, type, is_video) from the first
        media file in a completed /history entry -- image OR video,
        whichever comes first, in any output key, from any node.

        Deliberately does NOT look for any specific node's class_type
        or hardcode "images" as the only output key to check. See
        SESSION 46.3's decision write-up in additionalfeatures.md for
        the reasoning, but in short: ComfyUI's /history entry already
        reports every node's outputs in one flat `outputs` dict
        regardless of what produced them, and the value is always a
        list of {"filename": ..., "subfolder": ..., "type": ...}
        dicts -- SaveImage nodes put theirs under an "images" key,
        VHS_VideoCombine and most other video-output nodes put theirs
        under "gifs" (historical naming from ComfyUI's original
        animated-GIF support) or "videos", and yet other custom nodes
        use other key names again. Hunting for specific node types or
        specific key names both break the moment a new node picks a
        different one; scanning every value in the dict for anything
        shaped like a media-file reference, and classifying
        VIDEO_EXTENSIONS vs. everything else, works for the current
        node ecosystem and whatever replaces it without needing an
        update every time a new video node shows up.

        Returns the first VIDEO match found (in dict-iteration order)
        across every node's every output key if any exist; otherwise
        the first IMAGE match, matching `extract_image_info`'s own
        behavior for the images-only case. Returns (None, None, None,
        False) if nothing matched at all.

        Session 47.5 fix: this used to return strictly the first
        {"filename": ...}-shaped match of ANY kind, image or video,
        with no preference between them. That silently broke video
        results whenever the same node's `outputs` entry contained
        both an `"images"` key (an auto-generated preview/poster PNG,
        which VHS_VideoCombine and similar video-output nodes commonly
        write alongside the real file) and a `"gifs"`/`"videos"` key
        (the actual video) — whichever key ComfyUI happened to
        serialize first in the JSON won, extension classification and
        all, with no regard for which one was the *real* output. In
        practice that consistently turned out to be the preview PNG,
        so every video generation got silently reclassified as an
        image result: `is_video` came back `False`, `video_ready`
        never fired, `image_ready` did instead, and 46.4b's whole
        video-playback path never engaged at all. Now every candidate
        across every key is collected first, then a video one is
        preferred if any exist at all — a node emitting both an image
        and a video output no longer lets iteration order decide which
        one wins."""
        outputs = history_entry.get("outputs", {})
        first_image_match = None
        for node_output in outputs.values():
            for value in node_output.values():
                if not isinstance(value, list) or not value:
                    continue
                first = value[0]
                if not isinstance(first, dict):
                    continue
                filename = first.get("filename")
                if not filename:
                    continue
                ext = os.path.splitext(filename)[1].lower()
                is_video = ext in VIDEO_EXTENSIONS
                if is_video:
                    return filename, first.get("subfolder", ""), first.get("type", "output"), True
                if first_image_match is None:
                    first_image_match = (filename, first.get("subfolder", ""), first.get("type", "output"), False)
        if first_image_match is not None:
            return first_image_match
        return None, None, None, False

    def upload_image(self, path_or_bytes, filename=None, overwrite=False):
        """Uploads an input image to ComfyUI via its stock POST
        /upload/image endpoint -- the same route ComfyUI's own
        browser-side LoadImage "choose file" button calls. Session 46.1:
        this is how an image picked in PromptForge's own UI reaches
        ComfyUI's input/ folder without ever Alt-Tabbing into the
        browser.

        `path_or_bytes` is either a filesystem path (str) to read, or
        raw bytes already in memory. `filename` is required when passing
        bytes (ComfyUI needs a name+extension for the multipart part);
        when passing a path, it defaults to that path's basename.
        `overwrite` is forwarded as ComfyUI's own "overwrite" form field
        (True lets a re-upload of the same filename replace the
        existing file instead of ComfyUI auto-suffixing a new one).

        Returns the {"name", "subfolder", "type"} dict ComfyUI reports
        back -- exactly what needs to be patched into the Connector
        node's `image` widget before submission (see
        workers.comfy_worker.patch_graph_for_generation).
        Raises ComfyUIError on any failure."""
        if isinstance(path_or_bytes, (bytes, bytearray)):
            data = bytes(path_or_bytes)
            if not filename:
                raise ComfyUIError("upload_image: filename is required when passing raw bytes.")
        else:
            path = path_or_bytes
            if not filename:
                filename = os.path.basename(path)
            try:
                with open(path, "rb") as f:
                    data = f.read()
            except OSError as e:
                raise ComfyUIError(f"Could not read image file to upload: {e}")

        boundary = uuid.uuid4().hex
        parts = [
            (f"--{boundary}\r\n"
             f'Content-Disposition: form-data; name="image"; filename="{filename}"\r\n'
             f"Content-Type: application/octet-stream\r\n\r\n").encode("utf-8"),
            data,
            b"\r\n",
            (f'--{boundary}\r\n'
             f'Content-Disposition: form-data; name="overwrite"\r\n\r\n'
             f'{"true" if overwrite else "false"}\r\n').encode("utf-8"),
            f"--{boundary}--\r\n".encode("utf-8"),
        ]
        body = b"".join(parts)

        url = f"{self.base_url}{COMFY_UPLOAD_IMAGE_PATH}"
        req = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body_text = ""
            try:
                body_text = e.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            raise ComfyUIError(f"ComfyUI rejected the image upload ({e.code}): {body_text}")
        except urllib.error.URLError as e:
            raise ComfyUIError(f"Could not reach ComfyUI at {self.base_url}: {e.reason}")
        except json.JSONDecodeError:
            raise ComfyUIError("ComfyUI returned an unexpected (non-JSON) response from /upload/image")

        name = result.get("name")
        if not name:
            raise ComfyUIError(f"ComfyUI accepted the upload but returned no filename: {result}")
        return {
            "name": name,
            "subfolder": result.get("subfolder", ""),
            "type": result.get("type", "input"),
        }

    def submit_prompt(self, workflow_graph, preview_method="auto"):
        """Submits a full API-format workflow graph. Returns the
        prompt_id string.

        preview_method is forwarded as extra_data.preview_method. This is
        NOT cosmetic: ComfyUI's PromptExecutor.execute_async() calls
        set_preview_method(extra_data.get("preview_method")) on EVERY
        single /prompt submission, which overwrites the server's global
        live-preview state for this run. If we omit it (as before), the
        server resets preview to whatever --preview-method it was *launched*
        with (default: none) — completely ignoring the Settings > Comfy >
        Execution > "Live preview method" dropdown, because that dropdown's
        value only reaches the server via extra_data when the official
        browser frontend queues a prompt, not when we POST /prompt ourselves.
        "auto" mirrors ComfyUI's own Auto behaviour (taesd-class decoder if
        vae_approx weights are present for this model, else latent2rgb).
        Pass preview_method=None to skip sending it (server falls back to
        its launch default — equivalent to the old, broken behaviour)."""
        payload = {"prompt": workflow_graph, "client_id": self.client_id}
        if preview_method:
            payload["extra_data"] = {"preview_method": preview_method}
        result = self._post("/prompt", payload)
        prompt_id = result.get("prompt_id")
        if not prompt_id:
            node_errors = result.get("node_errors")
            if node_errors:
                raise ComfyUIError(f"ComfyUI reported node errors: {node_errors}")
            raise ComfyUIError("ComfyUI accepted the request but returned no prompt_id.")
        return prompt_id

    def get_history(self, prompt_id):
        """Returns the /history entry for prompt_id, or None if it hasn't
        completed (or even started) yet."""
        result = self._get(f"/history/{prompt_id}")
        return result.get(prompt_id)

    def interrupt(self):
        """Tells ComfyUI to abort whatever is *currently executing*
        (POST /interrupt — no body). This only affects the job that's
        actively running on the GPU right now; it does NOT touch other
        jobs still sitting in the queue behind it.

        Note this is unconditional on ComfyUI's side: /interrupt always
        stops whatever the server is currently running, regardless of
        which client/prompt_id submitted it. That's fine for our use
        case (a single local user with one generation in flight), but
        it's the reason we don't bother passing prompt_id here — the
        endpoint doesn't take one."""
        self._post("/interrupt", {})

    def delete_queue_item(self, prompt_id):
        """Removes a not-yet-started job from ComfyUI's queue (POST
        /queue with {"delete": [prompt_id]}). Used as a best-effort
        companion to interrupt(): if our job hadn't started executing
        yet (still waiting behind other queued jobs), /interrupt alone
        wouldn't touch it since it only aborts the currently-running
        job. Failures here are non-fatal — the job may simply have
        already started (in which case interrupt() above is what
        actually stops it) or already finished."""
        self._post("/queue", {"delete": [prompt_id]})

    def wait_for_completion(self, prompt_id, poll_interval=COMFY_POLL_INTERVAL,
                             timeout=COMFY_POLL_TIMEOUT, should_cancel=None,
                             progress_callback=None, preview_callback=None):
        """Blocks (in the caller's thread) polling /history until the job
        finishes. `should_cancel` is an optional zero-arg callable the
        owner can use to abort early (e.g. user closed the app).
        `progress_callback(current_step, total_steps)` is called whenever
        the progress estimate changes. `preview_callback(image_bytes)` is
        called with raw JPEG/PNG bytes whenever ComfyUI streams a live
        preview frame over the WebSocket (TAESD/latent2rgb preview during
        KSampler) — see _listen_progress_ws for the wire format. This is
        purely a function of what ComfyUI itself decides to send: if the
        user has "Live preview method" set to "none" in ComfyUI's own
        Settings, no such frames are ever sent and preview_callback simply
        never fires — there is nothing to toggle on this side.

        Real step-by-step progress (the "20/30" KSampler counter visible
        in ComfyUI's own console) is only ever published over its
        WebSocket as {"type": "progress", "data": {"value", "max"}}
        events — the /queue REST endpoint's queue_running entries carry
        no per-node completion status at all (its 5th element is the list
        of node ids still left to execute, not a list of "done" messages),
        which is why a /queue-only counter gets permanently stuck at
        "0/N". So a background thread keeps a small stdlib-only WebSocket
        connection (see _listen_progress_ws) open for real progress, and
        /queue is kept only as a coarse "N total nodes" fallback for the
        brief window before the first WebSocket progress event arrives
        (e.g. while a checkpoint is still loading)."""
        start = time.time()
        last_progress = (-1, -1)

        ws_progress = {"value": None, "max": None}
        ws_stop = threading.Event()
        ws_thread = threading.Thread(
            target=self._listen_progress_ws,
            args=(prompt_id, ws_progress, ws_stop, preview_callback),
            daemon=True)
        if progress_callback or preview_callback:
            ws_thread.start()

        try:
            while True:
                if should_cancel and should_cancel():
                    raise ComfyUIError("Generation cancelled.")
                if time.time() - start > timeout:
                    raise ComfyUIError(
                        f"Timed out after {timeout}s waiting for ComfyUI to finish. "
                        f"The job may still be running — check ComfyUI directly."
                    )
                entry = self.get_history(prompt_id)
                if entry is not None:
                    status = entry.get("status", {})
                    if status.get("completed"):
                        if progress_callback and last_progress != (-1, -1):
                            progress_callback(last_progress[1], last_progress[1])
                        return entry
                    if status.get("status_str") == "error":
                        messages = status.get("messages", [])
                        raise ComfyUIError(f"ComfyUI reported a generation error: {messages}")

                if progress_callback:
                    value, mx = ws_progress["value"], ws_progress["max"]
                    if value is not None and mx:
                        prog = (value, mx)
                        if prog != last_progress:
                            last_progress = prog
                            progress_callback(value, mx)
                    else:
                        # No WebSocket progress event yet (still loading the
                        # checkpoint, or the socket/handshake failed) — show
                        # at least the total node count from /queue so the
                        # bar isn't completely blank.
                        try:
                            queue_data = self._get("/queue", timeout=2)
                            running = queue_data.get("queue_running", [])
                            for item in running:
                                # item structure: [number, prompt_id, prompt_graph, extra, outputs_to_execute]
                                if len(item) > 1 and item[1] == prompt_id:
                                    graph_dict = item[2] if len(item) > 2 else {}
                                    total_nodes = len(graph_dict) if isinstance(graph_dict, dict) else 0
                                    if total_nodes > 0:
                                        prog = (0, total_nodes)
                                        if prog != last_progress:
                                            last_progress = prog
                                            progress_callback(0, total_nodes)
                                    break
                        except Exception:
                            pass  # progress is best-effort, never fail the main loop

                time.sleep(poll_interval)
        finally:
            ws_stop.set()

    def _listen_progress_ws(self, prompt_id, progress_state, stop_event, preview_callback=None):
        """Background-thread helper for wait_for_completion(): opens a raw
        WebSocket connection to ComfyUI's /ws endpoint (over a plain
        `socket` + a hand-rolled RFC 6455 handshake — no third-party
        dependency such as `websocket-client`) and updates `progress_state`
        in place whenever a {"type": "progress"} message arrives. This is
        the only source of real per-step KSampler progress.

        It also recognizes binary frames (opcode 0x2): ComfyUI streams
        live TAESD/latent2rgb preview frames during sampling as a binary
        WebSocket message with an 8-byte header — 4 bytes big-endian
        "event type" (1 = PREVIEW_IMAGE, already-encoded JPEG/PNG bytes;
        2 = UNENCODED_PREVIEW_IMAGE, raw tensor data we can't decode as an
        image and skip) followed by 4 bytes "image format" (1=JPEG,
        2=PNG), then the image bytes themselves. When event type is 1 and
        a preview_callback was given, it's called with just the image
        bytes (header stripped). Whether these frames ever arrive at all
        is entirely up to ComfyUI's own "Live preview method" setting
        (Settings -> Comfy > Execution) — if the user has it set to
        "none" there, ComfyUI never sends them and preview_callback is
        simply never invoked. There is no separate flag to check here.

        Best-effort by design: any failure here (connection refused, bad
        handshake, ComfyUI version without this message shape, etc.) just
        leaves progress_state untouched, and the caller silently falls
        back to its own coarser estimate — this must never raise into the
        polling thread or crash the generation."""
        sock = None
        try:
            sock = socket.create_connection((self.host, self.port), timeout=COMFY_HTTP_TIMEOUT)

            ws_key = base64.b64encode(os.urandom(16)).decode("ascii")
            request = (
                f"GET /ws?clientId={self.client_id} HTTP/1.1\r\n"
                f"Host: {self.host}:{self.port}\r\n"
                f"Upgrade: websocket\r\n"
                f"Connection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {ws_key}\r\n"
                f"Sec-WebSocket-Version: 13\r\n"
                f"\r\n"
            )
            sock.sendall(request.encode("ascii"))

            sock.settimeout(0.5)  # short, so we keep checking stop_event/deadline
            buf = bytearray()
            header_deadline = time.time() + COMFY_HTTP_TIMEOUT
            while b"\r\n\r\n" not in buf:
                if time.time() > header_deadline or stop_event.is_set():
                    return
                try:
                    chunk = sock.recv(4096)
                except socket.timeout:
                    continue
                if not chunk:
                    return
                buf.extend(chunk)

            header_end = buf.index(b"\r\n\r\n") + 4
            status_line = bytes(buf[:buf.index(b"\r\n")]).decode("ascii", "replace")
            if " 101 " not in status_line:
                return  # handshake rejected (e.g. /ws not served here) — give up quietly
            buf = buf[header_end:]  # any bytes after the headers are already frame data

            sock.settimeout(0.5)  # short, so we keep checking stop_event
            while not stop_event.is_set():
                parsed = self._ws_try_parse_frame(buf)
                if parsed is None:
                    try:
                        chunk = sock.recv(4096)
                    except socket.timeout:
                        continue
                    except OSError:
                        return
                    if not chunk:
                        return
                    buf.extend(chunk)
                    continue

                opcode, payload, consumed = parsed
                del buf[:consumed]

                if opcode == 0x8:   # close frame
                    return

                if opcode == 0x2:  # binary frame — possibly a preview image
                    if preview_callback is not None and len(payload) >= 8:
                        try:
                            event_type = struct.unpack(">I", payload[:4])[0]
                            if event_type == 1:  # PREVIEW_IMAGE — bytes after
                                                 # the 8-byte header are a
                                                 # ready-to-decode JPEG/PNG.
                                preview_callback(payload[8:])
                        except Exception:
                            pass  # malformed/partial frame — drop it, never crash
                    continue

                if opcode != 0x1:   # only text frames carry JSON messages
                    continue
                try:
                    msg = json.loads(payload.decode("utf-8", "replace"))
                except Exception:
                    continue

                if msg.get("type") == "progress":
                    data = msg.get("data", {})
                    # Older ComfyUI versions don't echo prompt_id in this
                    # message; since this connection's client_id was only
                    # ever used for this one job, accept it either way.
                    if data.get("prompt_id") in (None, prompt_id):
                        value, mx = data.get("value"), data.get("max")
                        if isinstance(value, (int, float)) and isinstance(mx, (int, float)) and mx > 0:
                            progress_state["value"] = int(value)
                            progress_state["max"] = int(mx)
        except Exception:
            pass  # best-effort: never let WS trouble affect the actual generation
        finally:
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass

    @staticmethod
    def _ws_try_parse_frame(buf):
        """Tries to parse one complete WebSocket frame (RFC 6455) from the
        front of `buf`. Returns (opcode, payload_bytes, total_frame_len)
        if a full frame is already in the buffer, or None if the caller
        needs to read more bytes first. Handles masked frames (in case any
        proxy in front of ComfyUI masks server frames, even though plain
        ComfyUI itself doesn't) and the 16/64-bit extended length forms."""
        if len(buf) < 2:
            return None
        b0, b1 = buf[0], buf[1]
        opcode = b0 & 0x0F
        masked = bool(b1 & 0x80)
        plen = b1 & 0x7F
        offset = 2
        if plen == 126:
            if len(buf) < offset + 2:
                return None
            plen = struct.unpack(">H", bytes(buf[offset:offset + 2]))[0]
            offset += 2
        elif plen == 127:
            if len(buf) < offset + 8:
                return None
            plen = struct.unpack(">Q", bytes(buf[offset:offset + 8]))[0]
            offset += 8
        mask_key = None
        if masked:
            if len(buf) < offset + 4:
                return None
            mask_key = buf[offset:offset + 4]
            offset += 4
        if len(buf) < offset + plen:
            return None
        payload = bytearray(buf[offset:offset + plen])
        if masked:
            for i in range(len(payload)):
                payload[i] ^= mask_key[i % 4]
        return opcode, bytes(payload), offset + plen


    @staticmethod
    def find_node_by_class_type(workflow_graph, class_type):
        """Finds the (single) node dict whose class_type matches. Returns
        (node_id, node_dict) or (None, None) if not found."""
        for node_id, node in workflow_graph.items():
            if isinstance(node, dict) and node.get("class_type") == class_type:
                return node_id, node
        return None, None


