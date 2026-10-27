"""The global hotkey: parse "Ctrl+Shift+Space", register it, and let Settings change it while running."""
import ctypes
import threading
from ctypes import wintypes

import win32api
import win32con

user32 = ctypes.windll.user32
MOD_NOREPEAT = 0x4000
WM_REREGISTER = win32con.WM_APP + 1
HOTKEY_ID = 1

MODS = {"ctrl": win32con.MOD_CONTROL, "control": win32con.MOD_CONTROL, "shift": win32con.MOD_SHIFT,
        "alt": win32con.MOD_ALT, "win": win32con.MOD_WIN}
KEYS = {"space": win32con.VK_SPACE, "enter": win32con.VK_RETURN, "tab": win32con.VK_TAB,
        "backquote": 0xC0, "`": 0xC0, ";": 0xBA, "/": 0xBF, ".": 0xBE, ",": 0xBC, "'": 0xDE,
        "[": 0xDB, "]": 0xDD, "\\": 0xDC, "-": 0xBD, "=": 0xBB}
KEYS.update({f"f{n}": win32con.VK_F1 + n - 1 for n in range(1, 25)})
KEYS.update({"up": win32con.VK_UP, "down": win32con.VK_DOWN, "left": win32con.VK_LEFT, "right": win32con.VK_RIGHT,
             "home": win32con.VK_HOME, "end": win32con.VK_END, "pageup": win32con.VK_PRIOR,
             "pagedown": win32con.VK_NEXT, "insert": win32con.VK_INSERT, "delete": win32con.VK_DELETE})


def parse(combo):
    """'Ctrl+Shift+Space' -> (modifiers, virtual key). Raises ValueError with a message for the user."""
    parts = [p.strip() for p in combo.split("+") if p.strip()]
    mods, vk = 0, None
    for p in parts:
        low = p.lower()
        if low in MODS:
            mods |= MODS[low]
        elif low in KEYS:
            vk = KEYS[low]
        elif len(p) == 1 and p.isalnum():
            vk = ord(p.upper())
        else:
            raise ValueError(f"Roverlay doesn't know the key “{p}”.")
    if vk is None:
        raise ValueError("Add a key to go with the modifiers, like Space or R.")
    if not mods & (win32con.MOD_CONTROL | win32con.MOD_ALT | win32con.MOD_WIN):
        raise ValueError("Include Ctrl, Alt or Win, so the shortcut doesn't fire while you type.")
    return mods, vk


class Hotkey:
    """Runs a message loop on its own thread. on_press is called for each press; presses made while the
    previous one was still being handled are dropped (opening the bar takes a moment, and a queued press
    used to close it the instant it appeared)."""

    def __init__(self, combo, on_press):
        self.combo = combo
        self.on_press = on_press
        self.pending = combo
        self.thread_id = None
        self.ready = threading.Event()
        self.result = {}

    def start(self):
        threading.Thread(target=self._loop, daemon=True).start()
        self.ready.wait(5)
        return self.result.get("ok", False)

    def change(self, combo):
        """Try a new shortcut; keeps the old one if the new one is taken. Returns (ok, error)."""
        try:
            parse(combo)
        except ValueError as e:
            return False, str(e)
        self.result = {}
        self.ready.clear()
        self.pending = combo
        user32.PostThreadMessageW(self.thread_id, WM_REREGISTER, 0, 0)
        self.ready.wait(5)
        return self.result.get("ok", False), self.result.get("error")

    def _register(self, combo):
        mods, vk = parse(combo)
        return bool(user32.RegisterHotKey(None, HOTKEY_ID, mods | MOD_NOREPEAT, vk))

    def _loop(self):
        self.thread_id = win32api.GetCurrentThreadId()
        msg = wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)  # make sure this thread has a message queue
        ok = self._register(self.combo)
        self.result = {"ok": ok, "error": None if ok else f"{self.combo} is already used by another app."}
        self.ready.set()
        handled_until = 0
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            if msg.message == WM_REREGISTER:
                user32.UnregisterHotKey(None, HOTKEY_ID)
                if self._register(self.pending):
                    self.combo, self.result = self.pending, {"ok": True}
                else:
                    self._register(self.combo)  # put the old one back
                    self.result = {"ok": False, "error": f"{self.pending} is already used by another app."}
                self.ready.set()
                continue
            if msg.message != win32con.WM_HOTKEY:
                continue
            if msg.time < handled_until:
                print("hotkey: extra press while the bar was opening; ignored")
                continue
            try:
                self.on_press()
            except Exception as e:  # one bad press must not kill the hotkey
                print("hotkey error:", type(e).__name__, e)
            handled_until = win32api.GetTickCount()
