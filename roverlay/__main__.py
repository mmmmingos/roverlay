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
    # Its own taskbar identity, so Windows shows Roverlay's icon rather than Python's.
    import ctypes
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("MingXu.Roverlay")
    from .app import App
    App(background="--background" in sys.argv).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
