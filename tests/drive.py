"""Drive the running overlay like a person would, and screenshot each step into out/ (gitignored).

Usage: python drive.py "<chat window title substring>" "<instruction>" [paste]
Without 'paste' it closes the bar with Esc, so nothing goes into the chat.
"""
import ctypes
import sys
import time
from pathlib import Path

import mss
import uiautomation as auto
import win32api
import win32con
import win32gui
from PIL import Image

OUT = Path(__file__).parent / "out"
LOG = Path(__file__).parent / "roverlay.log"
user32 = ctypes.windll.user32


def find(substr):
    hits = []
    win32gui.EnumWindows(lambda h, _: hits.append(h) if win32gui.IsWindowVisible(h) and substr in win32gui.GetWindowText(h) else None, None)
    return hits[0]


def shot(name, hwnd):
    mon = win32api.GetMonitorInfo(win32api.MonitorFromWindow(hwnd, win32con.MONITOR_DEFAULTTONEAREST))["Monitor"]
    with mss.MSS() as s:
        g = s.grab({"left": mon[0], "top": mon[1], "width": mon[2] - mon[0], "height": mon[3] - mon[1]})
    Image.frombytes("RGB", g.size, g.rgb).save(OUT / f"{name}.png")


def wait_log(token, after, timeout=30):
    t0 = time.time()
    while time.time() - t0 < timeout:
        text = LOG.read_text(encoding="utf-8", errors="ignore")[after:]
        if token in text:
            return text
        time.sleep(0.2)
    return None


def press_hotkey():
    for vk, up in ((0x11, 0), (0x10, 0), (0x20, 0), (0x20, 2), (0x10, 2), (0x11, 2)):
        user32.keybd_event(vk, 0, up, 0)


def ask_once(hwnd, instruction, tag):
    """Open the bar over the chat, type an instruction, press Enter, wait for the draft to be typed in."""
    from roverlay.winutil import bring_to_front
    bring_to_front(hwnd)
    time.sleep(0.6)
    if win32gui.GetForegroundWindow() != hwnd:
        sys.exit("ABORT: couldn't bring the chat window to the front; pressed nothing")
    mark = len(LOG.read_text(encoding="utf-8", errors="ignore"))
    press_hotkey()
    print(tag, "read:", (wait_log("read ", mark) or "no read logged").strip().splitlines()[-1])
    time.sleep(0.4)
    shot(f"{tag}-1-open", hwnd)
    # Never type unless the bar really has focus: keystrokes would land in whatever app is underneath.
    if win32gui.GetWindowText(win32gui.GetForegroundWindow()) != "Roverlay":
        sys.exit("ABORT: the bar doesn't have keyboard focus; typed nothing")
    auto.SendKeys(instruction, interval=0.01, waitTime=0.1)
    auto.SendKeys("{Enter}", waitTime=0)
    done = wait_log("typed into the box", mark) or wait_log("couldn't confirm", mark, timeout=1) or "nothing logged"
    print(tag, "result:", done.strip().splitlines()[-1])
    time.sleep(0.5)
    shot(f"{tag}-2-typed", hwnd)


def main():
    title, instruction = sys.argv[1], sys.argv[2]
    refine = next((a[7:] for a in sys.argv[3:] if a.startswith("refine=")), None)
    OUT.mkdir(exist_ok=True)
    hwnd = find(title)
    ask_once(hwnd, instruction, "a")
    if refine:
        time.sleep(1.0)
        ask_once(hwnd, refine, "b")


if __name__ == "__main__":
    main()
