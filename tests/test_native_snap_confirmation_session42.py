"""Session 42, step 1: `main._apply_native_snap_confirmation` prints an
stderr banner confirming which window class actually got instantiated --
per additionalfeatures.md SESSION 42, the leading suspect was that
`MainWindowWinSnap` never actually got instantiated (env var not set in
the launching shell) and Session 41's gate gave no visible way to tell.

Session 43 cleanup: the `[native-snap]` window-title/title-bar-label tag
from the original debug version has been removed now that Snap is
confirmed working on real hardware and default-on (Session 42.3) --
these tests now only cover that plain `MainWindow` stays untouched and
that the stderr banner fires only for the native subclass, not the
(removed) title tagging.

Run with: python -m pytest tests/test_native_snap_confirmation_session42.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication(sys.argv)

from main import MainWindow, _apply_native_snap_confirmation


class _NotMainWindow:
    """Stand-in subclass identity distinct from MainWindow, without
    needing a real MainWindowWinSnap (which only imports on Windows).
    """
    pass


class TestNativeSnapConfirmation(unittest.TestCase):
    def setUp(self):
        self.w = MainWindow()
        self.original_title = self.w.windowTitle()

    def tearDown(self):
        self.w.close()
        self.w.deleteLater()

    def test_plain_main_window_untouched(self):
        _apply_native_snap_confirmation(self.w, MainWindow)
        self.assertEqual(self.w.windowTitle(), self.original_title)
        self.assertEqual(self.w.title_bar.lbl_title.text(), self.original_title)

    def test_native_subclass_does_not_tag_window_title(self):
        # Session 43: the debug [native-snap] tag was removed. The
        # window title must stay exactly as-is even for the native
        # subclass now.
        _apply_native_snap_confirmation(self.w, _NotMainWindow)
        self.assertEqual(self.w.windowTitle(), self.original_title)
        self.assertEqual(self.w.title_bar.lbl_title.text(), self.original_title)

    def test_banner_printed_to_stderr_only_for_native_subclass(self):
        import io
        captured = io.StringIO()
        old_stderr = sys.stderr
        sys.stderr = captured
        try:
            _apply_native_snap_confirmation(self.w, MainWindow)
            self.assertEqual(captured.getvalue(), "")
            _apply_native_snap_confirmation(self.w, _NotMainWindow)
            self.assertIn("mainwindowwinsnap is active", captured.getvalue().lower())
        finally:
            sys.stderr = old_stderr


if __name__ == "__main__":
    unittest.main()
