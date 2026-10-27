"""Windows helpers: focus handling and the chat's message box, through UI Automation."""
import ctypes
import time

import uiautomation as auto
import win32api
import win32con
import win32gui

user32 = ctypes.windll.user32


def bring_to_front(hwnd):
    """Make hwnd the foreground window without pressing any key. (An Alt tap, the usual trick, moves focus
    to the menu bar in Notepad and to the ⋮ button in Chrome, so a following Ctrl+V lands nowhere.)
    Windows lets a thread attached to the current foreground thread's input hand focus over."""
    if win32gui.IsIconic(hwnd):
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    fg = win32gui.GetForegroundWindow()
    me = win32api.GetCurrentThreadId()
    fg_thread = user32.GetWindowThreadProcessId(fg, None) if fg else 0
    attached = fg_thread and fg_thread != me and user32.AttachThreadInput(fg_thread, me, True)
    try:
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(fg_thread, me, False)


def focused_box(hwnd):
    """If the caret is already in a text field of this window when the hotkey is pressed, return its name and
    rect: that's where the user meant to reply (in Slack, an open thread rather than the channel box), and
    where the bar should appear. One quick call, so the bar can still open instantly. (None, None) otherwise."""
    with auto.UIAutomationInitializerInThread():
        try:
            f = auto.GetFocusedControl()
            if (f and f.ControlTypeName == "EditControl" and "Address and search" not in (f.Name or "")
                    and f.GetTopLevelControl().NativeWindowHandle == hwnd):
                r = f.BoundingRectangle
                return f.Name or "", (r.left, r.top, r.right, r.bottom)
        except Exception:
            pass
    return None, None


def find_compose_box(hwnd, prefer_name=None):
    """The chat's message box: the lowest text field (EditControl) that isn't the browser's address bar or a
    search box, unless the caret was in another text field when the hotkey was pressed (prefer_name).
    Documents don't count: Chrome reports the whole web page as a focusable document, and picking it sent
    keystrokes to the page instead of the box (caught on a mock chat before any real one).
    Call inside UIAutomationInitializerInThread."""
    best = None
    for ctrl, _ in auto.WalkControl(auto.ControlFromHandle(hwnd), maxDepth=60):
        try:
            if ctrl.ControlTypeName != "EditControl":
                continue
            name = ctrl.Name or ""
            if "Address and search" in name or name.lower().startswith("search") or not ctrl.IsKeyboardFocusable:
                continue
            bottom = ctrl.BoundingRectangle.bottom
            if prefer_name is not None and name == prefer_name:
                bottom = 10 ** 9
            if best is None or bottom > best[0]:
                best = (bottom, ctrl)
        except Exception:
            continue
    return best[1] if best else None


def focus_compose_box(hwnd, prefer_name=None):
    """Put the caret in the chat's message box and confirm it's there."""
    with auto.UIAutomationInitializerInThread():
        box = find_compose_box(hwnd, prefer_name)
        if box is None:
            return False
        try:
            if box.HasKeyboardFocus:
                return True
            box.SetFocus()
            time.sleep(0.05)
            return bool(box.HasKeyboardFocus)
        except Exception:
            return False


def read_box_text(hwnd, prefer_name=None):
    """What's in the message box right now, and where the box is: (text, rect).
    text is '' when the box is empty and None when the app won't say; rect is None when there's no box.

    Tries the text interface first: on Chrome's message boxes the value interface returned '' even with
    text in the box. Placeholder text ("Type a message to …") counts as empty."""
    with auto.UIAutomationInitializerInThread():
        box = find_compose_box(hwnd, prefer_name)
        if box is None:
            return None, None
        try:
            r = box.BoundingRectangle
            rect = (r.left, r.top, r.right, r.bottom)
        except Exception:
            rect = None
        return _box_text(box), rect


def _box_text(box):
    text = None
    try:
        pattern = box.GetTextPattern()
        if pattern is not None:
            text = pattern.DocumentRange.GetText(-1)
    except Exception:
        text = None
    if text is None:
        try:
            text = box.GetValuePattern().Value or None  # '' from this interface isn't trustworthy
        except Exception:
            text = None
    if text is None:
        return None
    # Editors pad empty boxes with invisible characters: Discord's holds a lone U+FEFF, which read as
    # "1 character" and would have flipped an empty box into rewrite mode. Only padding is removed from real
    # text; a zero-width joiner inside it holds emoji like \ud83e\udd37\u200d\u2642\ufe0f together, so it stays.
    visible = text
    for invisible in ("\ufffc", "\ufeff", "\u200b", "\u200c", "\u200d", "\u2060"):
        visible = visible.replace(invisible, "")
    if not visible.strip():
        return ""
    text = text.replace("\ufffc", "").replace("\ufeff", "").replace("\r", "\n").strip()
    name = (box.Name or "").strip()
    if text == name or text in ("Type a message", "Message", "Message...", "Write a message"):
        return ""
    return text


def compose_has_focus(target):
    """True only if the keyboard caret is in an editable field inside the chat window (not the address bar).
    Typing happens only when this holds, so keystrokes never land somewhere unexpected."""
    with auto.UIAutomationInitializerInThread():
        try:
            f = auto.GetFocusedControl()
            if f is None or f.ControlTypeName != "EditControl":  # never a whole page or document
                return False
            if "Address and search" in (f.Name or ""):
                return False
            return f.GetTopLevelControl().NativeWindowHandle == target
        except Exception:
            return False
