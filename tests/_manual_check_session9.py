"""Session 9 manual on-screen check — throwaway, per the migration
plan's verification rule.

A bare QWidget with "Check connection", "Submit test generation", and
"Stop" buttons wired directly to ComfyCheckWorker / ComfyGenerationWorker,
plus a log box that prints every signal as it fires and a label that
shows the latest preview/result image. Run this against a real ComfyUI
instance (with a PromptForgeConnection node open in the graph) and
watch the log fill in as a generation actually runs; confirm Stop
actually interrupts it.

This file is intentionally NOT wired into MainWindow — it gets thrown
away once Session 11 wires these same worker classes into the real
Builder tab. Run directly:

    python -m tests._manual_check_session9
    # or, headless smoke (won't show a real window, just confirms it
    # constructs without error):
    QT_QPA_PLATFORM=offscreen python -m tests._manual_check_session9 --smoke
"""
import sys

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QPlainTextEdit, QLabel, QLineEdit, QFormLayout,
)

from backend.comfy_client import ComfyUIClient
from backend.constants import COMFY_DEFAULT_HOST, COMFY_DEFAULT_PORT
from workers.comfy_worker import ComfyCheckWorker, ComfyGenerationWorker


class ManualCheckWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Session 9 manual check — ComfyUI workers")
        self.resize(640, 560)

        self.client = None
        self.check_worker = None
        self.gen_worker = None

        layout = QVBoxLayout(self)

        form = QFormLayout()
        self.ent_host = QLineEdit(COMFY_DEFAULT_HOST)
        self.ent_port = QLineEdit(str(COMFY_DEFAULT_PORT))
        form.addRow("Host", self.ent_host)
        form.addRow("Port", self.ent_port)
        layout.addLayout(form)

        btn_row = QHBoxLayout()
        self.btn_check = QPushButton("Check connection")
        self.btn_generate = QPushButton("Submit test generation")
        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setEnabled(False)
        btn_row.addWidget(self.btn_check)
        btn_row.addWidget(self.btn_generate)
        btn_row.addWidget(self.btn_stop)
        layout.addLayout(btn_row)

        self.lbl_image = QLabel("(no image yet)")
        self.lbl_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_image.setMinimumHeight(220)
        self.lbl_image.setStyleSheet("border: 1px solid #888;")
        layout.addWidget(self.lbl_image)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        layout.addWidget(self.log)

        self.btn_check.clicked.connect(self.on_check_clicked)
        self.btn_generate.clicked.connect(self.on_generate_clicked)
        self.btn_stop.clicked.connect(self.on_stop_clicked)

    def _log(self, text):
        self.log.appendPlainText(text)

    def _make_client(self):
        host = self.ent_host.text().strip() or COMFY_DEFAULT_HOST
        port = int(self.ent_port.text().strip() or COMFY_DEFAULT_PORT)
        return ComfyUIClient(host, port)

    def on_check_clicked(self):
        self.client = self._make_client()
        self._log(f"[check] starting against {self.client.base_url} ...")
        self.check_worker = ComfyCheckWorker(self.client)
        self.check_worker.check_done.connect(self.on_check_done)
        self.check_worker.start()

    def on_check_done(self, success, error_msg, out_dir, workflow_ok, workflow_msg, loras):
        self._log(f"[check_done] success={success} error={error_msg!r} "
                   f"out_dir={out_dir!r} workflow_ok={workflow_ok} "
                   f"workflow_msg={workflow_msg!r} loras={loras}")

    def on_generate_clicked(self):
        if self.client is None:
            self.client = self._make_client()
        queue_item = {
            "prompt_text": "a small red fox sitting in snow, detailed fur",
            "seed": 12345,
            "width": 512,
            "height": 512,
            "negative_text": "blurry, low quality",
            "lora_slots_snapshot": [],
        }
        self._log("[generate] submitting test job ...")
        self.gen_worker = ComfyGenerationWorker(self.client, queue_item)
        self.gen_worker.progress_updated.connect(
            lambda cur, mx: self._log(f"[progress_updated] {cur}/{mx}"))
        self.gen_worker.preview_ready.connect(self.on_preview_ready)
        self.gen_worker.image_ready.connect(self.on_image_ready)
        self.gen_worker.generation_failed.connect(
            lambda msg: self._log(f"[generation_failed] {msg}"))
        self.gen_worker.generation_finished.connect(self.on_generation_finished)
        self.gen_worker.start()
        self.btn_stop.setEnabled(True)
        self.btn_generate.setEnabled(False)

    def on_preview_ready(self, img_bytes):
        self._log(f"[preview_ready] {len(img_bytes)} bytes")
        pix = QPixmap()
        if pix.loadFromData(img_bytes):
            self.lbl_image.setPixmap(
                pix.scaled(400, 400, Qt.AspectRatioMode.KeepAspectRatio))

    def on_image_ready(self, img_bytes, filename, subfolder):
        self._log(f"[image_ready] filename={filename!r} subfolder={subfolder!r} "
                   f"{len(img_bytes)} bytes")
        pix = QPixmap()
        if pix.loadFromData(img_bytes):
            self.lbl_image.setPixmap(
                pix.scaled(400, 400, Qt.AspectRatioMode.KeepAspectRatio))

    def on_generation_finished(self):
        self._log("[generation_finished]")
        self.btn_stop.setEnabled(False)
        self.btn_generate.setEnabled(True)

    def on_stop_clicked(self):
        if self.gen_worker is not None:
            self._log("[stop] requesting interrupt ...")
            self.gen_worker.stop()


def main():
    app = QApplication(sys.argv)
    win = ManualCheckWindow()
    if "--smoke" in sys.argv:
        # Headless construction-only smoke check — confirms imports and
        # widget wiring work without needing a real ComfyUI instance or
        # a visible display.
        print("Smoke check OK: window constructed without error.")
        return 0
    win.show()
    return app.exec()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
