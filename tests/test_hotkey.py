"""Check the bar opens, closes and hands focus back the way the hints say. Mock chat only; types nothing.
Usage: python test_hotkey.py "<mock chat window title>"
"""
import ctypes
import sys
import time

import uiautomation as auto
import win32api
import win32con
import win32gui

from drive import find, press_hotkey
from roverlay.winutil import bring_to_front, compose_has_focus, focus_compose_box

user32 = ctypes.windll.user32
results = []


def bar():
    hits = []
    win32gui.EnumWindows(lambda h, _: hits.append(h) if win32gui.GetWindowText(h) == "Roverlay" else None, None)
    return hits[0]


def state(chat):
    b = bar()
    return {"bar_visible": bool(win32gui.IsWindowVisible(b)), "bar_has_focus": win32gui.GetForegroundWindow() == b,
            "chat_in_front": win32gui.GetForegroundWindow() == chat, "caret_in_chat_box": compose_has_focus(chat)}


def check(name, chat, **want):
    time.sleep(0.9)
    got = state(chat)
    ok = all(got[k] == v for k, v in want.items())
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}: {got}")


def click(x, y):
    win32api.SetCursorPos((x, y))
    user32.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    user32.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


def main():
    chat = find(sys.argv[1])
    bring_to_front(chat)
    time.sleep(0.5)
    focus_compose_box(chat)
    time.sleep(0.3)

    press_hotkey()
    check("1. hotkey opens the bar with focus", chat, bar_visible=True, bar_has_focus=True)

    auto.SendKeys("{Esc}", waitTime=0)
    check("2. Esc closes it and the caret is back in the chat box", chat, bar_visible=False, chat_in_front=True,
          caret_in_chat_box=True)

    press_hotkey()
    check("3. hotkey opens it again", chat, bar_visible=True, bar_has_focus=True)

    press_hotkey()
    check("4. hotkey again closes it, back in the chat", chat, bar_visible=False, chat_in_front=True)

    press_hotkey()
    time.sleep(0.05)
    press_hotkey()
    check("5. quick double press leaves it open", chat, bar_visible=True)

    # Click on the bar's footer, so focus leaves the text field, then Esc.
    l, t, r, b = win32gui.GetWindowRect(bar())
    click((l + r) // 2, b - 28 - 12)
    time.sleep(0.3)
    auto.SendKeys("{Esc}", waitTime=0)
    check("6. Esc after clicking inside the bar (not the field) still closes it", chat, bar_visible=False)

    press_hotkey()
    time.sleep(0.6)
    click(200, 300)  # into the chat page, away from the bar
    check("7. clicking away closes it", chat, bar_visible=False)

    print(f"\n{sum(results)}/{len(results)} passed")


if __name__ == "__main__":
    main()
