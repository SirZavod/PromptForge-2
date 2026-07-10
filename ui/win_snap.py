"""Session 41 — Windows-native Snap/Snap Layouts, take two.

See additionalfeatures.md, SESSION 38 follow-up, for the full
post-mortem of the first attempt: a `nativeEvent` override placed
directly on `MainWindow` crashed real hardware twice, and the root
cause was that PyQt registers *any* overridden `nativeEvent` with the
underlying C++ vtable the moment the class is defined -- not the
moment it's actually called -- and Windows can deliver a native
message (`WM_WINDOWPOSCHANGING`) during the window's own
`CreateWindowEx`, before sip has finished linking the C++ object to
its Python wrapper. A runtime `if` inside the method body doesn't
help, because the method still exists on the class either way.

This module is the "real architectural split" the post-mortem asked
for: `nativeEvent` and its hit-test helpers live ONLY on
`MainWindowWinSnap`, a subclass that `main.py` instantiates only when
BOTH of these are true:
  1. the process is actually running on Windows, and
  2. the `PROMPTFORGE_ENABLE_WIN_NATIVE_SNAP` environment variable is
     set to a truthy value (opt-in, not a stored setting -- this is a
     "someone is actively testing this" switch, not a user preference,
     until it's proven safe across enough real machines to trust as a
     default).

Everyone else -- including every Windows user who doesn't set that
variable -- imports nothing from this module and never causes
`MainWindowWinSnap` to be defined-and-instantiated together, so the
plain `MainWindow` base (frameless + the `eventFilter`-based manual
drag/resize, confirmed working on all three platforms) is completely
unaffected. `main.py` only imports this module lazily, inside the
opt-in branch, so merely having this file on disk changes nothing for
anyone not explicitly opting in.

STATUS: written, NOT verified on real hardware. This environment has
no Windows box, no display, and no debugger -- exactly the conditions
the post-mortem said made the first attempt unsafe to ship. Do not
flip the env var on for anyone but yourself, with a debugger attached
from process launch, until the checklist at the bottom of this file's
docstring-equivalent section in additionalfeatures.md (SESSION 41) has
been clicked through.
"""
import ctypes
import sys
from ctypes import wintypes

from main import MainWindow

# --- Win32 constants used below (kept local to this file; nothing here
# is imported by main.py at module load time) -----------------------------
WM_NCCALCSIZE = 0x0083
WM_NCHITTEST = 0x0084

HTCLIENT = 1
HTCAPTION = 2
HTLEFT = 10
HTRIGHT = 11
HTTOP = 12
HTTOPLEFT = 13
HTTOPRIGHT = 14
HTBOTTOM = 15
HTBOTTOMLEFT = 16
HTBOTTOMRIGHT = 17
HTMINBUTTON = 8
HTMAXBUTTON = 9
HTCLOSE = 20

# Session 42.1: native WM_NCHITTEST resize band. Deliberately its own
# constant, separate from the base class's RESIZE_MARGIN -- that one
# feeds the eventFilter-based manual resize (Session 38), which gets
# continuous mouse-move events and Qt's own cursor-shape feedback to
# smooth over small aiming misses. This one is a single native
# per-pixel yes/no test with no such smoothing, so the same value felt
# uncomfortably thin in practice (real-hardware report, Session 42.1).
# 8px at 96 DPI is the common value for this exact trick in the wild
# (e.g. Windows Terminal's own borderless-window resize band); scaled
# by devicePixelRatioF() the same way the rest of `_win_hit_test`
# already scales screen coordinates. Module-level (not a class
# attribute) so `_win_hit_test` reads the same value regardless of
# which instance it's bound to -- including the test suite's headless
# trick of binding it onto a plain `MainWindow`, which has no
# `MainWindowWinSnap`-specific class attributes of its own.
NATIVE_RESIZE_MARGIN = 8


class MainWindowWinSnap(MainWindow):
    """Same window, plus native Snap/Snap Layouts/DWM shadow support on
    Windows, via the "hide the real frame, don't remove it" trick
    described in additionalfeatures.md's Session 38 follow-up:

    - Keep the OS's real `WS_CAPTION | WS_THICKFRAME` frame (unlike the
      base class, this one does NOT set `FramelessWindowHint`), so DWM
      still believes there's a real resizable window and keeps drawing
      its shadow / Win11 rounded corners and honoring Snap for free.
    - Hide that frame purely visually by answering `WM_NCCALCSIZE` with
      "no adjustment" (client rect == whole window rect).
    - Answer `WM_NCHITTEST` by hand so clicks on the custom title bar
      strip and its three buttons are reported as native non-client
      hits (`HTCAPTION` / `HTMINBUTTON` / `HTMAXBUTTON` / `HTCLOSE`),
      which is what makes native drag, Win+Up/Down, edge/corner Snap,
      and Win11's maximize-button hover flyout all work -- and reports
      an `_NATIVE_RESIZE_MARGIN`-px edge/corner band as the matching
      `HT*` resize codes, replacing this window's own
      eventFilter-based manual resize (which stays installed but goes
      inert here, since `_resize_edge_at` is overridden to always
      return None below -- cheaper and safer than trying to uninstall
      the app-wide filter).
    """

    def __init__(self):
        # Session 42.1: this flag is the ONLY thing nativeEvent is
        # allowed to check before deciding whether it's safe to do
        # anything else. It has to be a plain Python instance
        # attribute -- never a Qt property, never something that
        # resolves through a C++ getter -- because Windows can (and,
        # on real hardware, does) deliver a native message
        # (WM_WINDOWPOSCHANGING) WHILE `super().__init__()` below is
        # still running, i.e. before the C++ QMainWindow base has
        # finished constructing. At that point `self` exists as a
        # Python object (that's how nativeEvent gets called on it at
        # all -- it's already on the vtable at class definition time,
        # see the module docstring), but calling anything that reaches
        # into the C++ side -- including `self.geometry()`, even
        # attribute lookups that trigger a Qt property getter -- can
        # crash, because that C++ object isn't done being built yet. A
        # plain `dict.get` on `self.__dict__` never touches C++, so
        # it's the one thing safe to check unconditionally, from
        # message zero.
        self._win_snap_ready = False
        super().__init__()
        self._win_snap_ready = True

    # Session 42.1: this used to call
    # `self.setWindowFlags(... & ~FramelessWindowHint)` from *inside*
    # __init__, AFTER super().__init__() had already created and shown
    # the frameless window. That toggled the flag on an
    # already-existing native window, which forces Qt to destroy and
    # recreate the underlying HWND -- a second CreateWindowEx -- while
    # nativeEvent was already live on this class's vtable. That's the
    # exact race the original Session 38 post-mortem was about, just
    # moved to a different trigger, and it's what produced the first
    # real APPCRASH (0xc000041d in QtCore.pyd) on real hardware.
    # Overriding this hook instead means the base class never sets
    # FramelessWindowHint to begin with, so there is nothing to remove
    # and no flag-change-triggered window recreation at all -- no
    # extra setWindowFlags() call needed here, and no extra show()
    # either, since the window was only ever created once.
    def _use_frameless_hint(self):
        return False

    # The base class's manual resize is edge/corner-triggered off this
    # method; short-circuiting it to None makes that whole codepath
    # permanently inert here without touching or removing it, since
    # WM_NCHITTEST below now owns resize entirely.
    def _resize_edge_at(self, local_pos):
        return None

    # ------------------------------------------------------------------
    def nativeEvent(self, eventType, message):
        # Session 42.1: must be first, must be a plain dict lookup, and
        # must short-circuit without calling super() or touching any
        # other self.* -- see the comment on `_win_snap_ready` in
        # __init__ for why: this is what stops the
        # WM_WINDOWPOSCHANGING (0x0046) crash that arrives mid-
        # `super().__init__()`.
        if not self.__dict__.get("_win_snap_ready", False):
            return False, 0

        try:
            if eventType == b"windows_generic_MSG":
                msg = wintypes.MSG.from_address(int(message))

                if msg.message == WM_NCCALCSIZE:
                    if msg.wParam:
                        # "Handled, no adjustment" -> client rect stays the
                        # full window rect; DWM still draws its shadow and
                        # (Win11) rounded corners since the real frame is
                        # still there underneath, just not reserved for.
                        return True, 0

                elif msg.message == WM_NCHITTEST:
                    # title_bar may not exist yet if this message arrives
                    # before __init__ has built it (same reasoning as the
                    # first attempt's bug fix -- see the post-mortem).
                    if not hasattr(self, "title_bar"):
                        return False, 0
                    result = self._win_hit_test(msg.lParam)
                    if result is not None:
                        return True, result
        except Exception:
            import traceback
            print("[win-snap] unexpected exception in nativeEvent, "
                  "falling through to default handling:", file=sys.stderr)
            traceback.print_exc()
            return False, 0

        # Session 42.1: root cause of the third real-hardware crash.
        # This used to fall through to
        # `return super().nativeEvent(eventType, message)` for any
        # message not explicitly handled above -- i.e. handing it to
        # QMainWindow's own C++ default handling. That call itself is
        # what crashed (confirmed via faulthandler catching a genuine
        # access violation, then bisected by temporarily skipping this
        # exact call): on this window (real WS_CAPTION frame, no
        # FramelessWindowHint, nativeEvent overridden), routing an
        # unrecognized message into Qt's own nativeEvent was unsafe on
        # this PyQt6/Qt6 build. Returning "not handled" here already
        # lets Windows' own DefWindowProc do the correct default
        # processing at the OS level -- the extra call into Qt's C++
        # layer was both redundant and the actual fault, so it's gone,
        # not gated.
        return False, 0

    def _win_hit_test(self, lparam):
        """Decode lParam's packed screen coordinates, map to local
        window coordinates (accounting for DPI scale), and report which
        native hit-test code applies. Returns None to fall through to
        Qt/DefWindowProc's own default handling (plain client area)."""
        x_screen = ctypes.c_short(lparam & 0xFFFF).value
        y_screen = ctypes.c_short((lparam >> 16) & 0xFFFF).value

        # Session 42.3 bug fix: `WM_NCHITTEST`'s lParam is in *physical*
        # screen pixels (raw monitor pixels), but `self.geometry()`
        # (and therefore `origin`, `self.width()`, `self.height()`) is
        # already in Qt's *logical* (device-independent) pixels -- Qt
        # itself did the physical->logical scaling for every other
        # coordinate in the app. The previous version subtracted the
        # physical `x_screen`/`y_screen` from the logical `origin`
        # directly and only *then* divided by `dpr`, which mixes the
        # two unit systems: it's only correct when `dpr == 1` (100%
        # display scaling). At any other scale factor the leftover
        # cross-term (`origin * (dpr-1)/dpr`) throws the computed local
        # coordinate off by an amount that grows with the window's
        # screen position -- on real hardware (fixed at anything other
        # than 100% scaling) this showed up as the resize-cursor band
        # extending far past the actual edge in one direction while
        # barely existing in the other, exactly matching your marked
        # screenshots. Fix: convert the physical screen coordinate to
        # logical FIRST (divide by `dpr`), then subtract the
        # already-logical `origin` -- both sides of the subtraction are
        # now the same unit.
        # NOTE (flagged, still not fully verified): still assumes a
        # single, uniform per-monitor scale factor. Multi-monitor rigs
        # with *different* per-monitor DPI, or dragging the window
        # across that boundary, aren't covered by this fix -- see
        # additionalfeatures.md, SESSION 41, checklist.
        dpr = self.devicePixelRatioF() or 1.0
        origin = self.geometry().topLeft()
        x = int(x_screen / dpr) - origin.x()
        y = int(y_screen / dpr) - origin.y()

        w, h = self.width(), self.height()

        # Resize bands take priority over caption/buttons at the
        # corners, matching native window behavior. Uses
        # `NATIVE_RESIZE_MARGIN` (Session 42.1), not the base class's
        # `RESIZE_MARGIN` -- see the constant's comment above for why
        # this hit-test needs a wider band than the eventFilter path.
        margin = NATIVE_RESIZE_MARGIN
        left = x <= margin
        right = x >= w - margin
        top = y <= margin
        bottom = y >= h - margin
        if not self.isMaximized():
            if top and left:
                return HTTOPLEFT
            if top and right:
                return HTTOPRIGHT
            if bottom and left:
                return HTBOTTOMLEFT
            if bottom and right:
                return HTBOTTOMRIGHT
            if left:
                return HTLEFT
            if right:
                return HTRIGHT
            if top:
                return HTTOP
            if bottom:
                return HTBOTTOM

        # Title bar buttons: Session 42.2 bug fix. This used to report
        # HTMINBUTTON/HTMAXBUTTON/HTCLOSE for these rects, which is
        # what real native caption buttons return -- but that hands the
        # button entirely to Windows' own non-client button handling
        # (DefWindowProc paints the hover/press state itself and, on
        # release, fires WM_SYSCOMMAND SC_MINIMIZE/SC_MAXIMIZE/SC_CLOSE
        # directly). None of that ever reaches Qt as a mouse press/
        # release on the widget, so `btn_minimize.clicked` etc. never
        # fire -- these are ordinary QPushButtons wired to
        # `clicked.connect(...)` in `title_bar.py`, not real caption
        # buttons Windows knows how to operate. That's why the buttons
        # "sometimes" clicked (a stray WM_LBUTTONUP arriving on the
        # client side of a hit-test-timing race) but mostly resolved to
        # a maximize/restore toggle regardless of which of the three
        # was clicked -- HTMAXBUTTON is the code Win11 treats as the
        # snap-layout-flyout / default double-role button, and its
        # DefWindowProc click action is exactly "toggle maximize".
        # Reporting HTCLIENT here instead makes Windows treat this
        # region as ordinary client area: the mouse press/release goes
        # through untouched to Qt, so the real QPushButtons receive it
        # and `clicked` fires normally, same as in the base
        # (non-native-snap) `MainWindow`. The one thing this gives up is
        # Win11's hover-preview flyout on the maximize button specific
        # to HTMAXBUTTON -- an acceptable trade for buttons that
        # actually work.
        tb = self.title_bar
        for widget in (tb.btn_minimize, tb.btn_maximize, tb.btn_close):
            top_left = widget.mapTo(self, widget.rect().topLeft())
            rect = widget.rect().translated(top_left)
            if rect.contains(x, y):
                return HTCLIENT

        # Rest of the strip: native caption (drag, Win+Up/Down,
        # edge/corner Snap, Win11 shake-to-minimize-others).
        tb_top_left = tb.mapTo(self, tb.rect().topLeft())
        tb_rect = tb.rect().translated(tb_top_left)
        if tb_rect.contains(x, y):
            return HTCAPTION

        return None
