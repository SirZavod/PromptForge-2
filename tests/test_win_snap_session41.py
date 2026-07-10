"""Session 41 smoke tests: `ui/win_snap.py`'s pure-geometry hit-test
logic (`_win_hit_test`), plus the isolation property the whole module
exists to guarantee -- that `nativeEvent` is defined ONLY on the opt-in
`MainWindowWinSnap` subclass and never touches the base `MainWindow`
class object.

This can only exercise the Python-side geometry math headless (no real
Win32 message pump exists in this environment) -- it does NOT verify
real Snap/Snap Layouts/DWM behavior. See additionalfeatures.md, SESSION
41, for the live-hardware checklist this still needs.

Run with: python -m pytest tests/test_win_snap_session41.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication(sys.argv)

from main import MainWindow
from ui.win_snap import (
    MainWindowWinSnap, HTCAPTION, HTCLIENT, HTLEFT,
    HTRIGHT, HTTOPLEFT, NATIVE_RESIZE_MARGIN,
)


def _lparam(x, y):
    """Pack (screen_x, screen_y) the way real WM_NCHITTEST does."""
    return (y & 0xFFFF) << 16 | (x & 0xFFFF)


class TestNativeEventIsolation(unittest.TestCase):
    def test_native_event_not_on_base_class(self):
        self.assertNotIn("nativeEvent", MainWindow.__dict__)
        self.assertNotIn("_win_hit_test", MainWindow.__dict__)

    def test_native_event_only_on_snap_subclass(self):
        self.assertIn("nativeEvent", MainWindowWinSnap.__dict__)
        self.assertIn("_win_hit_test", MainWindowWinSnap.__dict__)


class TestHitTestGeometry(unittest.TestCase):
    def setUp(self):
        self.w = MainWindow()  # base class: safe to construct headless
        self.w.show()
        self.w.resize(800, 600)
        self.w.move(0, 0)
        _app.processEvents()
        # Bind the unbound function so we can test the pure geometry
        # logic against a plain MainWindow instance, without going
        # through MainWindowWinSnap.__init__ (which flips window flags
        # in a way that's meaningless/untestable off real Windows).
        self._hit_test = MainWindowWinSnap._win_hit_test.__get__(self.w)

    def tearDown(self):
        self.w.close()

    def test_top_left_corner_is_resize_handle(self):
        result = self._hit_test(_lparam(1, 1))
        self.assertEqual(result, HTTOPLEFT)

    def test_left_edge_mid_height(self):
        result = self._hit_test(_lparam(1, 300))
        self.assertEqual(result, HTLEFT)

    def test_right_edge(self):
        # Use the window's actual width rather than assuming resize()
        # took effect verbatim -- MainWindow enforces a content-driven
        # minimum width (see _update_minimum_size), so an 800px request
        # can legitimately be clamped upward.
        w = self.w.width()
        result = self._hit_test(_lparam(w - 1, 300))
        self.assertEqual(result, HTRIGHT)

    def test_title_bar_button_rects(self):
        # Session 42.2: these must be HTCLIENT, not HTMINBUTTON/
        # HTMAXBUTTON/HTCLOSE. The buttons are ordinary QPushButtons
        # wired to Qt `clicked` signals (see ui/title_bar.py) -- not
        # real native caption buttons Windows knows how to operate.
        # Reporting the native button codes here hands the click to
        # Windows' own non-client button handling and the buttons never
        # actually fire; reporting HTCLIENT lets the press/release
        # reach Qt normally, same as the base MainWindow.
        for widget in (
            self.w.title_bar.btn_minimize,
            self.w.title_bar.btn_maximize,
            self.w.title_bar.btn_close,
        ):
            top_left = widget.mapTo(self.w, widget.rect().topLeft())
            cx = top_left.x() + widget.width() // 2
            cy = top_left.y() + widget.height() // 2
            result = self._hit_test(_lparam(cx, cy))
            self.assertEqual(result, HTCLIENT, f"expected HTCLIENT at ({cx},{cy})")

    def test_plain_title_bar_area_is_caption(self):
        # Somewhere on the strip, away from the resize band and away
        # from any button (near the icon/title on the left).
        result = self._hit_test(_lparam(NATIVE_RESIZE_MARGIN + 5, 10))
        self.assertEqual(result, HTCAPTION)

    def test_native_event_guards_missing_title_bar(self):
        # This is the exact bug class the first (crashed) attempt hit:
        # WM_NCHITTEST can arrive before __init__ has built title_bar.
        # Can't safely construct a title_bar-less *real* QMainWindow
        # off Windows, so this asserts the guard is present in source
        # rather than driving a live message through it -- weaker than
        # an execution test, but the real verification of this path is
        # necessarily a live Windows run anyway (see additionalfeatures.md,
        # SESSION 41).
        import inspect
        src = inspect.getsource(MainWindowWinSnap.nativeEvent)
        self.assertIn("hasattr(self, \"title_bar\")", src)


class TestHitTestGeometryScaled(unittest.TestCase):
    """Session 42.3 regression test: the previous `_win_hit_test`
    subtracted a *physical*-pixel screen coordinate from the *logical*
    `self.geometry()` origin before dividing by `devicePixelRatioF()`,
    which only happened to cancel out at `dpr == 1.0` (100% display
    scaling) -- exactly the value every other test in this file runs
    at headless, which is why this class of bug wasn't caught earlier.
    This test forces a non-1.0 `dpr` *and* a non-zero window position
    (the bug's error term is proportional to the origin, so it's
    invisible at `move(0, 0)` even with `dpr != 1.0`) and checks the
    hit-test recovers the correct native code from physical coordinates
    built the same way real Win32 would deliver them.
    """

    def setUp(self):
        self.w = MainWindow()
        self.w.show()
        self.w.resize(800, 600)
        self.w.move(200, 150)  # non-zero origin -- see docstring above
        _app.processEvents()
        self._hit_test = MainWindowWinSnap._win_hit_test.__get__(self.w)
        self._dpr = 1.5
        self.w.devicePixelRatioF = lambda: self._dpr

    def tearDown(self):
        self.w.close()

    def _physical(self, local_x, local_y):
        """Build the physical-pixel screen coords real Windows would
        report for a given point in this window's local logical space,
        given the mocked `dpr` and the window's actual logical origin."""
        origin = self.w.geometry().topLeft()
        screen_x = int((origin.x() + local_x) * self._dpr)
        screen_y = int((origin.y() + local_y) * self._dpr)
        return screen_x, screen_y

    def test_top_left_corner_is_resize_handle_at_scale(self):
        result = self._hit_test(_lparam(*self._physical(1, 1)))
        self.assertEqual(result, HTTOPLEFT)

    def test_right_edge_at_scale(self):
        w = self.w.width()
        result = self._hit_test(_lparam(*self._physical(w - 1, 300)))
        self.assertEqual(result, HTRIGHT)

    def test_plain_title_bar_area_is_caption_at_scale(self):
        result = self._hit_test(
            _lparam(*self._physical(NATIVE_RESIZE_MARGIN + 5, 10)))
        self.assertEqual(result, HTCAPTION)

    def test_title_bar_button_is_client_at_scale(self):
        widget = self.w.title_bar.btn_close
        top_left = widget.mapTo(self.w, widget.rect().topLeft())
        cx = top_left.x() + widget.width() // 2
        cy = top_left.y() + widget.height() // 2
        result = self._hit_test(_lparam(*self._physical(cx, cy)))
        self.assertEqual(result, HTCLIENT)


if __name__ == "__main__":
    unittest.main()
