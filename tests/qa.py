"""UI/UX QA pass: timings, fast typing after the hotkey, the hotkey during a draft, and a screenshot of every state.
Types only into the mock chat page; real apps are only screenshotted. Screenshots go to out/qa-*.png (gitignored).
Usage: python qa.py
"""
import ctypes
import re
import subprocess
import sys
import time

import mss
import uiautomation as auto
import win32gui
from PIL import Image

from drive import LOG, OUT, find, press_hotkey, wait_log
from roverlay.winutil import bring_to_front, focus_compose_box, read_box_text
from roverlay.typer import StreamTyper, select_all, _key, _send

user32 = ctypes.windll.user32
MOCK = "Mock chat test"


def bar():
    hits = []
    win32gui.EnumWindows(lambda h, _: hits.append(h) if win32gui.GetWindowText(h) == "Roverlay" else None, None)
    return hits[0]


def snap(name, pad=40):
    """Screenshot the bar plus a margin of what's around it."""
    l, t, r, b = win32gui.GetWindowRect(bar())
    with mss.MSS() as s:
        g = s.grab({"left": l - pad, "top": t - pad, "width": r - l + 2 * pad, "height": b - t + 2 * pad})
    Image.frombytes("RGB", g.size, g.rgb).save(OUT / f"qa-{name}.png")


def snap_screen(name, hwnd):
    import win32api
    import win32con
    mon = win32api.GetMonitorInfo(win32api.MonitorFromWindow(hwnd, win32con.MONITOR_DEFAULTTONEAREST))["Monitor"]
    with mss.MSS() as s:
        g = s.grab({"left": mon[0], "top": mon[1], "width": mon[2] - mon[0], "height": mon[3] - mon[1]})
    Image.frombytes("RGB", g.size, g.rgb).save(OUT / f"qa-{name}.png")


def clear_box(hwnd):
    bring_to_front(hwnd)
    time.sleep(0.3)
    focus_compose_box(hwnd)
    time.sleep(0.1)
    select_all()
    _send([_key(0x08), _key(0x08, True)])  # Backspace
    time.sleep(0.2)


def bar_field_text():
    """What's in the bar's text field, read through UI Automation."""
    with auto.UIAutomationInitializerInThread():
        for ctrl, _ in auto.WalkControl(auto.ControlFromHandle(bar()), maxDepth=40):
            if ctrl.ControlTypeName == "EditControl" and "say" in (ctrl.Name or ""):
                try:
                    return ctrl.GetValuePattern().Value
                except Exception:
                    return None
    return None


def esc():
    auto.SendKeys("{Esc}", waitTime=0.4)


def mark():
    return len(LOG.read_text(encoding="utf-8", errors="ignore"))


def section(title):
    print(f"\n== {title}")


def main():
    OUT.mkdir(exist_ok=True)
    mock = find(MOCK)

    section("A1. How fast the bar opens (5 presses, caret in the chat box)")
    clear_box(mock)
    for _ in range(5):
        bring_to_front(mock)
        time.sleep(0.3)
        focus_compose_box(mock)
        time.sleep(0.2)
        m = mark()
        press_hotkey()
        line = wait_log("bar shown", m, timeout=5) or "no show logged"
        print("  ", re.sub(r"^.*bar shown", "bar shown", line.strip().splitlines()[-1]))
        time.sleep(0.5)
        esc()
        time.sleep(0.4)

    section("A2. Typing straight after the hotkey: where do the first letters go?")
    for delay in (0.0, 0.1, 0.25):
        clear_box(mock)
        focus_compose_box(mock)
        time.sleep(0.2)
        press_hotkey()
        time.sleep(delay)
        auto.SendKeys("hello there", interval=0.02, waitTime=0)
        time.sleep(1.0)
        in_bar = bar_field_text() if win32gui.IsWindowVisible(bar()) else "(bar not open)"
        in_chat = read_box_text(mock)[0]
        print(f"   typed {int(delay * 1000)} ms after the hotkey -> bar field: {in_bar!r} | chat box: {in_chat!r}")
        esc()
        time.sleep(0.4)

    section("B1. New message state (empty box)")
    clear_box(mock)
    focus_compose_box(mock)
    m = mark()
    press_hotkey()
    wait_log("mode ", m)
    time.sleep(0.6)
    snap("b1-new")
    snap_screen("b1-new-screen", mock)
    auto.SendKeys("{Enter}", waitTime=0.5)  # Enter with nothing typed
    snap("b1-new-empty-enter")
    esc()

    section("B2. Rewrite state (box has text)")
    clear_box(mock)
    StreamTyper(mock, replace=True).feed("hey dave the quote is way to much for me tbh can u do it cheaper")
    time.sleep(0.3)
    m = mark()
    press_hotkey()
    wait_log("mode ", m)
    time.sleep(0.6)
    snap("b2-rewrite")
    esc()

    section("A3. Pressing the hotkey while a draft is typing")
    clear_box(mock)
    focus_compose_box(mock)
    m = mark()
    press_hotkey()
    wait_log("mode ", m)
    time.sleep(0.3)
    auto.SendKeys("write a long friendly message thanking him for the quote, explaining my budget is 3k and asking about "
                  "his availability next month and whether he can supply tiles", interval=0.005, waitTime=0)
    auto.SendKeys("{Enter}", waitTime=0)
    time.sleep(0.9)  # mid-draft
    press_hotkey()
    time.sleep(1.5)
    snap_screen("a3-hotkey-mid-draft", mock)
    print("   bar visible after mid-draft press:", bool(win32gui.IsWindowVisible(bar())), "(want False)")
    print("   chat box after the cancel:", repr(read_box_text(mock)[0]), "(want '' : back to empty)")
    print("   log since:", [l for l in LOG.read_text(encoding="utf-8", errors="ignore")[m:].splitlines() if l.strip()][-6:])
    esc()
    time.sleep(3)

    section("B3. Fallback state (a window with no message box: a blank Chrome window)")
    # Find the window this test opens by what's new, never by title: the owner may have their own about:blank
    # window, and closing it by title once closed theirs.
    def windows():
        hs = set()
        win32gui.EnumWindows(lambda h, _: hs.add(h) if win32gui.IsWindowVisible(h) else None, None)
        return hs
    before = windows()
    subprocess.Popen([r"C:\Program Files\Google\Chrome\Application\chrome.exe", "--new-window", "about:blank"])
    time.sleep(2.5)
    new = [h for h in windows() - before if "about:blank" in win32gui.GetWindowText(h)]
    if not new:
        print("   couldn't identify the test window; skipping")
        return
    blank = new[0]
    bring_to_front(blank)
    time.sleep(0.5)
    m = mark()
    press_hotkey()
    wait_log("mode ", m)
    time.sleep(0.5)
    snap("b3-generic-open")
    auto.SendKeys("say thanks for the quote and ask if he can do 3k", interval=0.01, waitTime=0)
    auto.SendKeys("{Enter}", waitTime=0)
    wait_log("showed the draft in the bar", m, timeout=30)
    time.sleep(0.8)
    snap("b3-fallback")
    esc()
    win32gui.PostMessage(blank, 0x0010, 0, 0)  # WM_CLOSE, our own blank window
    time.sleep(1)

    section("B4. Over real WhatsApp (screenshot only, nothing typed)")
    try:
        wa = find("WhatsApp - Google Chrome")
        bring_to_front(wa)
        time.sleep(0.5)
        focus_compose_box(wa)
        time.sleep(0.2)
        m = mark()
        press_hotkey()
        wait_log("mode ", m)
        time.sleep(0.7)
        snap_screen("b4-whatsapp-screen", wa)
        esc()
    except IndexError:
        print("   WhatsApp window not open")

    section("B5. On the vertical monitor, over Discord (screenshot only)")
    try:
        dc = find("- Discord")
        bring_to_front(dc)
        time.sleep(0.5)
        focus_compose_box(dc)
        time.sleep(0.2)
        m = mark()
        press_hotkey()
        wait_log("mode ", m)
        time.sleep(0.7)
        snap_screen("b5-discord-screen", dc)
        esc()
    except IndexError:
        print("   Discord window not open")

    print("\nscreenshots:", sorted(p.name for p in OUT.glob("qa-*.png")))


if __name__ == "__main__":
    sys.exit(main())
