"""Global unhandled-exception logging (Session 53, plan 2.A / Q3).

Why this exists: PyQt turns an exception raised inside a slot into a
hard abort (the "green box then the window vanishes, no traceback"
class of bug this plan chased after the old History Copy button). The
documented escape hatch is replacing `sys.excepthook`: PyQt calls it
and — as long as it is no longer the default hook — does not abort.

Two pieces, split on purpose:
- `format_crash_report` / `append_crash_report` are pure data (no Qt),
  so they are covered by the non-Qt test suite.
- `install_excepthook` swaps `sys.excepthook` and optionally calls a
  `notify(summary, log_path)` callback; `main.py` passes a themed
  dialog there. The callback is wrapped in try/except — a broken error
  dialog must never replace the original error.

The hook is idempotent per process (installing twice just re-installs)
and delegates Ctrl+C / `sys.exit()` to the previous default behaviour.
"""
import os
import sys
import time
import traceback

CRASH_LOG_NAME = "crash.log"


def format_crash_report(exc_type, exc_value, exc_tb, timestamp: str = None) -> str:
    """One timestamped block ready to append to the log file."""
    stamp = timestamp or time.strftime("%Y-%m-%d %H:%M:%S")
    body = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    return f"\n===== {stamp} =====\n{body}"


def append_crash_report(data_dir: str, report: str) -> str:
    """Appends `report` to `<data_dir>/crash.log`; returns the path.

    Never raises: logging an error must not become a second error. If
    the write fails, the path is still returned (the caller may show it
    to the user), it just will not contain the report.
    """
    path = os.path.join(data_dir or ".", CRASH_LOG_NAME)
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(report)
    except Exception:
        pass
    return path


def install_excepthook(data_dir: str, notify=None):
    """Installs the crash-logging hook and returns it.

    `notify(summary, log_path)` is optional; any exception it raises is
    swallowed so the dialog can never mask the original traceback.
    """

    def hook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        report = format_crash_report(exc_type, exc_value, exc_tb)
        path = append_crash_report(data_dir, report)
        if notify is not None:
            try:
                notify(f"{exc_type.__name__}: {exc_value}", path)
            except Exception:
                pass

    sys.excepthook = hook
    return hook
