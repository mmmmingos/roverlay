"""Record the README demo: the real app on the staged chat page (tests/demo-chat.html, made-up people).

Needs Roverlay running with its log going to tests/roverlay.log:
    .venv/Scripts/python.exe -u -m roverlay --background > tests/roverlay.log 2>&1
Then: .venv/Scripts/python.exe scripts/record_demo.py
Writes docs/demo.mp4 and docs/demo.gif. Takes over the keyboard and screen for about 30 seconds.
"""
import ctypes
import ctypes.wintypes
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
from pathlib import Path

import mss
import uiautomation as auto
import win32con
import win32gui
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from roverlay import memory  # noqa: E402
from roverlay.winutil import bring_to_front, focus_compose_box  # noqa: E402

LOG = Path(os.environ.get("ROVERLAY_LOG", ROOT / "tests" / "roverlay.log"))
PAGE = (ROOT / "tests" / "demo-chat.html").as_uri()
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
X, Y, W, H = 160, 90, 1280, 760  # where the chat window goes; replaced by its visible frame once it is there
FPS = 15
user32 = ctypes.windll.user32


def press_hotkey():
    for vk, up in ((0x11, 0), (0x10, 0), (0x20, 0), (0x20, 2), (0x10, 2), (0x11, 2)):
        user32.keybd_event(vk, 0, up, 0)


def wait_log(token, start, timeout=40):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if token in LOG.read_text(encoding="utf-8", errors="ignore")[start:]:
            return True
        time.sleep(0.1)
    return False


def mark():
    return len(LOG.read_text(encoding="utf-8", errors="ignore"))


def type_slowly(text, per_char=0.045):
    for ch in text:
        auto.SendKeys(ch if ch != " " else " ", interval=0, waitTime=0)
        time.sleep(per_char)


class Recorder(threading.Thread):
    def __init__(self, folder):
        super().__init__(daemon=True)
        self.folder, self.running, self.count = folder, True, 0

    def run(self):
        with mss.MSS() as s:
            nxt = time.perf_counter()
            while self.running:
                g = s.grab({"left": X, "top": Y, "width": W, "height": H})
                Image.frombytes("RGB", g.size, g.rgb).save(self.folder / f"f{self.count:05d}.jpg", quality=92)
                self.count += 1
                nxt += 1 / FPS
                time.sleep(max(0, nxt - time.perf_counter()))


def main():
    before = set()
    win32gui.EnumWindows(lambda h, _: before.add(h), None)
    subprocess.Popen([CHROME, "--new-window", f"--app={PAGE}"])
    chat = 0
    for _ in range(50):
        time.sleep(0.2)
        hits = []
        win32gui.EnumWindows(lambda h, _: hits.append(h) if h not in before and win32gui.IsWindowVisible(h)
                             and win32gui.GetWindowText(h).startswith("Chats") else None, None)
        if hits:
            chat = hits[0]
            break
    if not chat:
        sys.exit("demo chat window didn't open")
    # Other test pages behind it would show at the edges: minimise them.
    win32gui.EnumWindows(lambda h, _: win32gui.ShowWindow(h, win32con.SW_MINIMIZE)
                         if "Mock chat test" in win32gui.GetWindowText(h) else None, None)
    win32gui.MoveWindow(chat, X, Y, W, H, True)
    time.sleep(1.0)
    # Record the window's visible frame: on Windows 10 its rect includes invisible resize borders, through which
    # whatever is behind showed up in the first take.
    frame = ctypes.wintypes.RECT()
    ctypes.windll.dwmapi.DwmGetWindowAttribute(ctypes.wintypes.HWND(chat), 9, ctypes.byref(frame), ctypes.sizeof(frame))
    globals().update(X=frame.left, Y=frame.top, W=(frame.right - frame.left) // 2 * 2, H=(frame.bottom - frame.top) // 2 * 2)

    captions = queue.Queue()
    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.attributes("-alpha", 0.94)
    root.configure(bg="#111317")
    label = tk.Label(root, text="", fg="#f2f2f7", bg="#111317", font=("Segoe UI Semibold", 15), padx=18, pady=9)
    label.pack()

    def poll():
        try:
            while True:
                text = captions.get_nowait()
                if text:
                    label.config(text=text)
                    root.update_idletasks()
                    root.geometry(f"+{X + W - root.winfo_reqwidth() - 28}+{Y + 72}")
                    root.deiconify()
                else:
                    root.withdraw()
        except queue.Empty:
            pass
        root.after(50, poll)

    frames = Path(tempfile.mkdtemp(prefix="roverlay-demo-"))
    rec = Recorder(frames)

    def script():
        say = captions.put
        bring_to_front(chat)
        time.sleep(0.5)
        focus_compose_box(chat)
        rec.start()
        say("Dave's quote is too high. Reply without leaving the chat.")
        time.sleep(2.6)
        say("Ctrl + Shift + Space")
        m = mark()
        press_hotkey()
        wait_log("mode ", m, timeout=10)
        time.sleep(0.9)
        say("Say what you want, in your own words")
        type_slowly("offer 3.2k instead, I have another quote at 3k. ask if he can start in the 2 week gap")
        time.sleep(0.5)
        say("It writes the reply in your tone. It never sends.")
        m = mark()
        auto.SendKeys("{Enter}", waitTime=0)
        wait_log("typed into the box", m)
        time.sleep(2.2)
        say("Not quite right? Press it again and say what to change")
        time.sleep(1.4)
        m = mark()
        press_hotkey()
        wait_log("mode ", m, timeout=10)
        time.sleep(0.8)
        type_slowly("make it a bit friendlier")
        time.sleep(0.4)
        m = mark()
        auto.SendKeys("{Enter}", waitTime=0)
        wait_log("typed into the box", m)
        time.sleep(2.0)
        say("Runs on your own GPU. Nothing leaves your PC.")
        time.sleep(2.8)
        rec.running = False
        rec.join()
        say(None)
        root.after(300, root.destroy)

    root.withdraw()
    root.after(100, poll)
    threading.Thread(target=script, daemon=True).start()
    root.mainloop()
    win32gui.PostMessage(chat, win32con.WM_CLOSE, 0, 0)
    # The staged chat names its senders, so Roverlay saved it to voice memory like a real chat: remove it.
    staged = memory.path_for("Chats", "Dave the tiler")
    if staged.exists():
        staged.unlink()

    docs = ROOT / "docs"
    pattern = str(frames / "f%05d.jpg")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", pattern, "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-crf", "23", "-movflags", "+faststart", str(docs / "demo.mp4")], check=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", pattern, "-vf",
                    "fps=12,scale=960:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128[p];[b][p]paletteuse=dither=bayer",
                    str(docs / "demo.gif")], check=True)
    shutil.rmtree(frames)
    print(f"{rec.count} frames; wrote docs/demo.mp4 and docs/demo.gif")


if __name__ == "__main__":
    main()
