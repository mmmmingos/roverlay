"""Start with Windows: one value under the current user's Run key, set only when the user turns it on."""
import sys
import winreg
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
NAME = "Roverlay"


def command():
    if getattr(sys, "frozen", False):  # the packaged Roverlay.exe
        return f'"{sys.executable}" --background'
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    root = Path(__file__).resolve().parent.parent
    return f'cmd /c start "" /d "{root}" "{pythonw}" -m roverlay --background'


def set_enabled(enabled):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, NAME, 0, winreg.REG_SZ, command())
        else:
            try:
                winreg.DeleteValue(key, NAME)
            except FileNotFoundError:
                pass


def is_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, NAME)
            return True
    except FileNotFoundError:
        return False
