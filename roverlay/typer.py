"""Type text into the focused window as real keystrokes, without touching the clipboard.

Safety rules, because these keystrokes land in someone's chat:
- Never press a bare Enter: in chat apps it sends. A line break is typed as Shift+Enter.
- Stop the moment the target window isn't in front any more (the user switched away).
- Check the caret is still in the message box right before the first keystroke (the model can take a few
  seconds, and the user may have clicked elsewhere in the same window meanwhile).
"""
import ctypes
import time
from ctypes import wintypes

user32 = ctypes.windll.user32
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
VK_SHIFT, VK_CONTROL, VK_RETURN, VK_A = 0x10, 0x11, 0x0D, 0x41


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class MOUSEINPUT(ctypes.Structure):  # only here so the union has the size Windows expects
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _U(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


def _send(events):
    arr = (INPUT * len(events))(*events)
    user32.SendInput(len(events), arr, ctypes.sizeof(INPUT))


def _key(vk, up=False):
    return INPUT(INPUT_KEYBOARD, _U(ki=KEYBDINPUT(vk, 0, KEYEVENTF_KEYUP if up else 0, 0, 0)))


def _unicode(unit, up=False):
    return INPUT(INPUT_KEYBOARD, _U(ki=KEYBDINPUT(0, unit, KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if up else 0), 0, 0)))


def type_char(ch):
    data = ch.encode("utf-16-le")
    units = [int.from_bytes(data[i:i + 2], "little") for i in range(0, len(data), 2)]  # emoji = two units
    _send([_unicode(u) for u in units] + [_unicode(u, True) for u in units])


def shift_enter():
    _send([_key(VK_SHIFT), _key(VK_RETURN), _key(VK_RETURN, True), _key(VK_SHIFT, True)])


def select_all():
    _send([_key(VK_CONTROL), _key(VK_A), _key(VK_A, True), _key(VK_CONTROL, True)])


class Cancelled(Exception):
    """Raised from feed() once the user has asked to stop, to end the model's stream early."""


def backspace():
    _send([_key(0x08), _key(0x08, True)])


class StreamTyper:
    """Feed it model tokens; it types them into the chat box as they arrive."""

    def __init__(self, target_hwnd, replace=False, still_in_box=None):
        self.target = target_hwnd
        self.replace = replace
        self.still_in_box = still_in_box
        self.started = False
        self.stopped = False
        self.cancelled = False
        self.typed = []
        self.pending_newlines = 0

    def cancel(self):
        self.cancelled = True

    def _in_front(self):
        return user32.GetForegroundWindow() == self.target

    def feed(self, piece):
        if self.cancelled:
            raise Cancelled()
        if self.stopped:
            return
        if not self._in_front():
            self.stopped = True
            return
        if not self.started:
            piece = piece.lstrip()
            if not piece:
                return
            if self.still_in_box and not self.still_in_box():
                self.stopped = True
                return
            self.started = True
            if self.replace:  # redo: the old draft is selected and the first character replaces it
                select_all()
                time.sleep(0.03)
        for ch in piece:
            if self.cancelled:
                raise Cancelled()
            if ch == "\r":
                continue
            if ch == "\n":
                self.pending_newlines = 1  # collapse blank lines; typed only if more text follows
                continue
            if self.pending_newlines:
                shift_enter()
                self.typed.append("\n")
                self.pending_newlines = 0
            type_char(ch)
            self.typed.append(ch)

    @property
    def text(self):
        return "".join(self.typed)
