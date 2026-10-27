"""Exercise rewrite, undo and tidy-up on the mock chat page, like a person would.

Never run against a real chat: it types into the message box. Screenshots go to out/ (gitignored).
Usage: python test_rewrite.py "<mock chat window title>"
"""
import sys
import time

import uiautomation as auto
import win32gui

from drive import LOG, OUT, find, press_hotkey, shot, wait_log
from roverlay.winutil import bring_to_front, focus_compose_box, read_box_text
from roverlay.typer import StreamTyper

ROUGH = "hey dave the quote is way to much for me tbh can u do it cheaper, i got another quote for 3k"


def box_text(hwnd):
    return read_box_text(hwnd)[0]


def open_bar(hwnd, tag):
    bring_to_front(hwnd)
    time.sleep(0.5)
    if win32gui.GetForegroundWindow() != hwnd:
        sys.exit("ABORT: mock chat isn't in front; pressed nothing")
    focus_compose_box(hwnd)  # the caret is in the box, as when you're mid-conversation
    time.sleep(0.2)
    mark = len(LOG.read_text(encoding="utf-8", errors="ignore"))
    press_hotkey()
    line = (wait_log("mode ", mark) or "no read logged").strip().splitlines()[-1]
    print(f"[{tag}] {line}")
    time.sleep(0.5)
    shot(f"{tag}-bar", hwnd)
    if win32gui.GetWindowText(win32gui.GetForegroundWindow()) != "Roverlay":
        sys.exit("ABORT: the bar doesn't have keyboard focus; typed nothing")
    return mark


def finish(hwnd, mark, tag, token="typed into the box"):
    done = wait_log(token, mark, timeout=40) or "nothing logged"
    print(f"[{tag}] {done.strip().splitlines()[-1]}")
    time.sleep(0.6)
    shot(f"{tag}-after", hwnd)
    print(f"[{tag}] box now: {box_text(hwnd)!r}")


def main():
    OUT.mkdir(exist_ok=True)
    hwnd = find(sys.argv[1])

    # 1. "I" type a rough message myself.
    bring_to_front(hwnd)
    time.sleep(0.5)
    focus_compose_box(hwnd)
    time.sleep(0.2)
    t = StreamTyper(hwnd, replace=True)
    t.feed(ROUGH)
    time.sleep(0.3)
    print(f"[seed] box now: {box_text(hwnd)!r}")

    # 2. Rewrite it: firmer.
    mark = open_bar(hwnd, "rewrite")
    auto.SendKeys("make it firmer but still friendly", interval=0.01, waitTime=0.1)
    auto.SendKeys("{Enter}", waitTime=0)
    finish(hwnd, mark, "rewrite")

    # 3. Undo: the hotkey, then Ctrl+Z in the empty field.
    mark = open_bar(hwnd, "undo")
    auto.SendKeys("{Ctrl}z", waitTime=0)
    finish(hwnd, mark, "undo", token="undo: put back")

    # 4. Tidy up: the hotkey, then Enter with nothing typed.
    mark = open_bar(hwnd, "tidy")
    auto.SendKeys("{Enter}", waitTime=0)
    finish(hwnd, mark, "tidy")


if __name__ == "__main__":
    main()
