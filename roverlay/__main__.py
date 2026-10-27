"""Run Roverlay: python -m roverlay [--background]

Only one copy runs at a time. Launching it again (the Start menu icon) asks the running copy to open Settings.
--background starts quietly in the tray, for start-with-Windows.
"""
import sys

import win32api
import win32event
import winerror


def main():
    global _MUTEX  # held for the life of the process: it is how a second launch knows we are running
    _MUTEX = win32event.CreateMutex(None, False, "Roverlay.SingleInstance")
    if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
        event = win32event.CreateEvent(None, False, False, "Roverlay.ShowSettings")
        win32event.SetEvent(event)
        return 0
    # The packaged app has no console: keep its log (timings and counts, never message text) in a file.
    if getattr(sys, "frozen", False) or sys.stdout is None:
        from .config import DATA_DIR
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        log = DATA_DIR / "roverlay.log"
        if log.exists() and log.stat().st_size > 1_000_000:
            log.replace(log.with_suffix(".old.log"))
        sys.stdout = sys.stderr = open(log, "a", encoding="utf-8", buffering=1)
    # Its own taskbar identity, so Windows shows Roverlay's icon rather than Python's.
    import ctypes
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("MingXu.Roverlay")
    from .app import App
    App(background="--background" in sys.argv).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
