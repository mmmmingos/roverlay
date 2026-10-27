"""Roverlay: press the hotkey in a chat, type what you want to say, and the reply writes itself into the message box.

The bar (ui/bar) reads the chat with UI Automation, a local model drafts the reply (drafter.py), and it's typed
into the chat's message box (typer.py). Voice memory (memory.py) keeps what was on screen per contact, as plain
text, and feeds the user's own past messages back as tone examples. A tray icon and a settings window
(ui/settings) sit around it.
"""
import base64
import ctypes
import json
import os
import queue
import threading
import time
from ctypes import wintypes
from pathlib import Path

import pyperclip
import webview
import win32api
import win32con
import win32gui
import win32process

from . import memory, models, startup
from .config import MODELS, VERSION, Settings
from .drafter import TIDY, Drafter
from .hotkey import Hotkey
from .reader import Chat, read, warm_up
from .tray import Tray
from .typer import Cancelled, StreamTyper, backspace, select_all
from .winutil import (bring_to_front, compose_has_focus, focus_compose_box, focused_box, read_box_text)

HERE = Path(__file__).parent
BAR_TITLE = "Roverlay"
SETTINGS_TITLE = "Roverlay settings"
WIDTH = 780  # widest the panel gets (DigUp's width)
MIN_WIDTH = 560  # narrowest: still fits the field, the chip and the key hints
ROOM = 28  # transparent margin around the panel for its shadow; matches --shadow-room in ui/bar/panel.css
BAR_HEIGHT = 88  # the panel's height before any draft shows: field 56 + footer 30 + borders
GAP = 10  # space from screen edges


def page(folder, css, js):
    """A UI folder as one HTML page. Loaded from a file, pywebview's evaluate_js returned None for every call on
    Windows; passed as HTML it works. So the CSS, JS and logo are inlined."""
    ui = HERE / "ui" / folder
    html = (ui / "index.html").read_text(encoding="utf-8")
    html = html.replace(f'<link rel="stylesheet" href="{css}">', f"<style>{(ui / css).read_text(encoding='utf-8')}</style>")
    html = html.replace(f'<script src="{js}"></script>', f"<script>{(ui / js).read_text(encoding='utf-8')}</script>")
    logo = base64.b64encode((HERE / "assets" / "logo.png").read_bytes()).decode()
    return html.replace('src="logo.png"', f'src="data:image/png;base64,{logo}"')


class BarApi:
    """Called from the bar's JavaScript. Attributes starting with _ are hidden from it."""

    def __init__(self, app):
        self._app = app

    def resize(self, height):
        self._app.resize(int(height))

    def draft(self, instruction):
        threading.Thread(target=self._app.do_draft, args=(instruction,), daemon=True).start()

    def undo(self):
        threading.Thread(target=self._app.do_undo, daemon=True).start()

    def copy(self, text):
        pyperclip.copy(text)
        self._app.hide("copied")

    def hide(self, reason="bar"):
        self._app.hide(reason)

    def log(self, message):
        print(f"[bar] {message}")


class SettingsApi:
    """Called from the settings page."""

    def __init__(self, app):
        self._app = app

    def get_settings(self):
        s = self._app.settings
        return {"version": VERSION, "hotkey": s.hotkey, "model": s.model,
                "models": {name: models.status(name) for name in MODELS},
                "memory_enabled": s.memory_enabled, "memory_folder": str(memory.folder()),
                "launch_at_startup": startup.is_enabled(), "paused": s.paused, "my_names": s.my_names}

    def save_settings(self, changes):
        return self._app.apply_settings(changes or {})

    def set_hotkey(self, combo):
        ok, error = self._app.hotkey.change(combo)
        if ok:
            self._app.settings.hotkey = combo
            self._app.settings.save()
            self._app.tray.refresh()
        return {"ok": ok, "error": error}

    def download_model(self, name):
        if name not in MODELS:
            return {"ok": False, "error": "Unknown model."}
        models.download(name, on_done=self._app.model_downloaded)
        return {"ok": True}

    def open_memory_folder(self):
        os.startfile(memory.folder())
        return {"ok": True}

    def memory_summary(self):
        return memory.summary()

    def forget_everything(self):
        return {"ok": True, "deleted": memory.forget_everything()}

    def close(self):
        self._app.settings_window.hide()


class App:
    def __init__(self, background=False):
        self.settings = Settings.load()
        self.background = background
        self.drafter = Drafter(self.settings.model)
        self.window = None
        self.settings_window = None
        self.tray = None
        self.hotkey = None
        self.hwnd = 0
        self.visible = False
        self.quitting = False
        self.chat = None
        self.target = 0
        self.last = None  # the draft we last typed: {target, chat, first, text, t}
        self.rewrite = None  # when the box already has text: {text, source, written_from}
        self.undo = None  # after a rewrite, what the box held before: {target, box_hint, original, t}
        self.typing = None  # while a draft is being typed: {typer, target, original}
        self.width = WIDTH  # the panel's width this time: fitted to the chat column, at most WIDTH
        self.box_hint = None  # name of the text field the caret was in when the hotkey was pressed
        self.box_rects = {}  # where each window's message box was last found: {hwnd: (box rect, window rect)}
        self.js_queue = queue.Queue()

    # --- settings ---

    def apply_settings(self, changes):
        s = self.settings
        if "model" in changes and changes["model"] in MODELS and changes["model"] != s.model:
            s.model = changes["model"]
            threading.Thread(target=self.drafter.switch, args=(s.model,), daemon=True).start()
        if "memory_enabled" in changes:
            s.memory_enabled = bool(changes["memory_enabled"])
        if "paused" in changes:
            s.paused = bool(changes["paused"])
            if self.tray:
                self.tray.refresh()
        if "my_names" in changes:
            s.my_names = [n.strip() for n in changes["my_names"] if str(n).strip()]
        if "launch_at_startup" in changes:
            try:
                startup.set_enabled(bool(changes["launch_at_startup"]))
                s.launch_at_startup = bool(changes["launch_at_startup"])
            except OSError as e:
                return {"ok": False, "error": f"Couldn't change the startup setting: {e}"}
        s.save()
        return {"ok": True}

    def model_downloaded(self, name):
        if name == self.settings.model and not self.drafter.ready.is_set():
            self.drafter.start()

    def show_settings(self):
        self.settings_window.show()
        if not getattr(self, "_icons_set", False):  # the form only exists for sure once it has been shown
            self.set_window_icons()
            self._icons_set = True
        self.settings_window.evaluate_js("window.settingsUI && window.settingsUI.refresh()")
        for _ in range(40):
            hwnd = win32gui.FindWindow(None, SETTINGS_TITLE)
            if hwnd and win32gui.IsWindowVisible(hwnd):
                bring_to_front(hwnd)
                break
            time.sleep(0.025)

    def toggle_pause(self):
        self.apply_settings({"paused": not self.settings.paused})

    def quit(self):
        self.quitting = True
        if self.tray:
            self.tray.stop()
        self.drafter.stop()
        for w in (self.settings_window, self.window):
            try:
                w.destroy()
            except Exception:
                pass

    # --- bar window ---

    def js(self, call, *args):
        """Queue a call into the bar. evaluate_js waits on the UI thread, so it runs on one worker, in order."""
        self.js_queue.put(f"ui.{call}({', '.join(json.dumps(a) for a in args)})")

    def js_worker(self):
        while True:
            code = self.js_queue.get()
            try:
                self.window.evaluate_js(code)
            except Exception as e:
                print("bar update failed:", code.split("(")[0], type(e).__name__)

    def find_own_window(self, title):
        hits = []

        def cb(h, _):
            if win32process.GetWindowThreadProcessId(h)[1] == os.getpid() and win32gui.GetWindowText(h) == title:
                hits.append(h)
        win32gui.EnumWindows(cb, None)
        return hits[0] if hits else 0

    def style_bar(self):
        self.hwnd = self.find_own_window(BAR_TITLE)
        ex = win32gui.GetWindowLong(self.hwnd, win32con.GWL_EXSTYLE)
        win32gui.SetWindowLong(self.hwnd, win32con.GWL_EXSTYLE, (ex | win32con.WS_EX_TOOLWINDOW) & ~win32con.WS_EX_APPWINDOW)
        self.make_see_through()

    def make_see_through(self):
        """Real per-pixel transparency, so the panel's soft shadow and rounded corners blend into whatever is
        behind the bar. pywebview's transparent=True alone left a grey rectangle around the panel on Windows 10;
        extending the DWM frame over the whole window with a black form background lets the web view's
        transparent pixels through."""
        from System import Action  # pythonnet, loaded by pywebview
        from System.Drawing import Color
        from webview.platforms.winforms import BrowserView

        class MARGINS(ctypes.Structure):
            _fields_ = [("l", ctypes.c_int), ("r", ctypes.c_int), ("t", ctypes.c_int), ("b", ctypes.c_int)]

        form = BrowserView.instances.get(self.window.uid)
        if form is not None:
            form.Invoke(Action(lambda: setattr(form, "BackColor", Color.Black)))
        ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(wintypes.HWND(self.hwnd), ctypes.byref(MARGINS(-1, -1, -1, -1)))

    def focus_webview(self):
        """pywebview focuses the web view only on the window's first show; hand it focus on every show."""
        from System import Action
        from webview.platforms.winforms import BrowserView
        form = BrowserView.instances.get(self.window.uid)
        if form is not None:
            form.Invoke(Action(lambda: form.browser.webview.Focus()))

    def resize(self, height):
        self.window.resize(self.width + 2 * ROOM, max(height, BAR_HEIGHT + 2 * ROOM))

    def place(self, target, anchor):
        """Over the chat's message box when we know where it is, so the newest messages stay visible, sized to the
        chat column. Otherwise centred on the chat's monitor a fifth of the way down, like Spotlight."""
        mon = win32api.MonitorFromWindow(target, win32con.MONITOR_DEFAULTTONEAREST)
        ml, mt, mr, mb = win32api.GetMonitorInfo(mon)["Work"]
        if anchor:
            l, t, r, b = anchor
            self.width = max(MIN_WIDTH, min(WIDTH, r - l + 24))
            x = (l + r) // 2 - self.width // 2
            y = b + 6 - BAR_HEIGHT
        else:
            self.width = WIDTH
            x = ml + (mr - ml - self.width) // 2
            y = mt + (mb - mt) // 5
        x = max(ml + GAP, min(x, mr - self.width - GAP))
        y = max(mt + GAP, min(y, mb - BAR_HEIGHT - GAP))
        self.window.resize(self.width + 2 * ROOM, BAR_HEIGHT + 2 * ROOM)
        self.window.move(x - ROOM, y - ROOM)

    def anchor_for(self, target, rect_now):
        if rect_now:
            return rect_now
        cached = self.box_rects.get(target)
        if cached and cached[1] == win32gui.GetWindowRect(target):
            return cached[0]
        return None

    def show(self):
        target = win32gui.GetForegroundWindow()
        settings_hwnd = win32gui.FindWindow(None, SETTINGS_TITLE)
        if target in (self.hwnd, 0) or (settings_hwnd and target == settings_hwnd):
            target = self.target if self.target and win32gui.IsWindow(self.target) else 0
            if not target:
                print("hotkey ignored: no chat window to attach to")
                return
        t0 = time.perf_counter()
        self.target, self.chat, self.rewrite = target, None, None
        self.box_hint, caret_rect = focused_box(target)
        self.place(target, self.anchor_for(target, caret_rect))
        self.js("open")
        self.window.show()
        self.visible = True
        threading.Thread(target=self.read_chat, args=(target,), daemon=True).start()
        for _ in range(40):  # take focus only once the window is really up, or keystrokes go to the app below
            if win32gui.IsWindowVisible(self.hwnd):
                break
            time.sleep(0.025)
        bring_to_front(self.hwnd)
        self.focus_webview()
        self.js("focus")
        focused = win32gui.GetForegroundWindow() == self.hwnd
        print(f"bar shown (has focus: {focused}; ready in {round((time.perf_counter() - t0) * 1000)} ms)")

    def hide(self, reason="", restore_focus=True):
        """Always hides, whatever the visible flag says. When the bar still holds the foreground (Esc, the hotkey),
        focus goes back to the chat, or the next hotkey press would see the hidden bar as the current window."""
        shown = bool(win32gui.IsWindowVisible(self.hwnd))
        if restore_focus and self.target and win32gui.IsWindow(self.target) \
                and win32gui.GetForegroundWindow() in (self.hwnd, 0):
            bring_to_front(self.target)
        self.visible = False
        self.window.hide()
        if shown:
            print(f"bar hidden ({reason or 'no reason given'})")

    def toggle(self):
        print("hotkey pressed")
        if self.typing:  # the hotkey during a draft stops it, and the box goes back to how it was
            print("hotkey during a draft: stopping it")
            self.typing["typer"].cancel()
            return
        # Close only if the bar is on screen AND we opened it (Windows can report it visible when nobody did).
        if win32gui.IsWindowVisible(self.hwnd) and self.visible:
            self.hide("hotkey pressed while open")
        elif self.settings.paused:
            print("hotkey ignored: paused")
        else:
            self.show()

    # --- reading, drafting, typing ---

    def read_chat(self, target):
        try:
            chat = read(target, self.settings.my_names)
        except Exception as e:
            print("read failed:", type(e).__name__)
            self.js("context", {"app": "this window", "contact": "them", "count": 0, "method": "none", "readMs": 0,
                                "modelReady": self.drafter.ready.is_set()})
            return
        if target != self.target:
            return
        if self.settings.memory_enabled:
            try:
                chat.examples = memory.my_past_messages(chat)
                added = memory.record(chat)
                if added:
                    print(f"memory: {added} new lines saved ({chat.app})")
            except OSError as e:
                print("memory write failed:", e)
        self.chat = chat
        self.rewrite = self.box_contents(target)
        can_undo = bool(self.undo and self.undo["target"] == target and time.time() - self.undo["t"] < 600)
        mode = "rewrite" if self.rewrite else "new"
        print(f"read {chat.app} via {chat.method}: {len(chat.messages)} messages in {chat.read_ms} ms; mode {mode}"
              f"; {len(chat.examples)} tone examples from memory")
        preview = " ".join(self.rewrite["text"].split())[:70] if self.rewrite else ""
        self.js("context", {"app": chat.app, "contact": chat.contact, "count": len(chat.messages),
                            "method": chat.method, "readMs": chat.read_ms, "mode": mode, "preview": preview,
                            "canUndo": can_undo, "modelReady": self.drafter.ready.is_set()})
        self.drafter.prefill(chat)

    def box_contents(self, target):
        """What a rewrite would start from, or None for a new message."""
        text, rect = read_box_text(target, self.box_hint)
        if rect:
            self.box_rects[target] = (rect, win32gui.GetWindowRect(target))
        last = self.last if self.last and self.last["target"] == target else None
        if text:
            ours = bool(last and " ".join(last["text"].split())[:25] in " ".join(text.split()))
            return {"text": text, "source": "our last draft" if ours else "read from the box",
                    "written_from": last["first"] if ours else None}
        if text is None and last and time.time() - last["t"] < 120:
            return {"text": last["text"], "source": "our last draft, box unreadable", "written_from": last["first"]}
        return None

    def do_draft(self, instruction):
        waited = 0
        while self.chat is None and waited < 5:  # the read usually finishes before you've typed
            time.sleep(0.05)
            waited += 0.05
        rewrite, target = self.rewrite, self.target
        if instruction.strip().lower() == "undo":
            return self.do_undo()
        chat = self.chat or Chat("this app", "them")
        if rewrite:
            instruction = instruction.strip() or TIDY
            kwargs = {"existing": rewrite["text"], "written_from": rewrite["written_from"]}
        else:
            kwargs = {}
        if not self.drafter.available():
            self.js("error", "The model isn't downloaded yet. Open Settings from the tray icon to download it.")
            return
        if not self.drafter.ready.is_set():
            self.js("waiting", "Loading the model, about 10 seconds the first time…")
            self.drafter.ready.wait()
        if not self.hand_back_to_box(target):
            text, *_ = self.drafter.draft(chat, instruction, lambda piece: None, **kwargs)
            print("couldn't confirm the message box has focus; showed the draft in the bar instead of typing")
            self.show_fallback(text, "Couldn't find the message box, so nothing was typed. Copy the draft below.")
            return
        typer = StreamTyper(target, replace=bool(rewrite))
        self.typing = {"typer": typer, "target": target, "original": rewrite["text"] if rewrite else ""}
        try:
            text, first_ms, total_ms, retried = self.drafter.draft(chat, instruction, typer.feed, **kwargs)
        except Cancelled:
            self.restore_box(target, self.typing["original"], typer)
            return
        except Exception as e:
            print("drafting failed:", type(e).__name__)
            return
        finally:
            self.typing = None
        if not typer.started:
            print("draft looked like the instruction twice; nothing typed")
            self.show_fallback(text, "That draft restated your instruction, so nothing was typed. Try rewording it.")
            return
        if typer.stopped:
            pyperclip.copy(text)
            print("stopped typing (the chat lost focus); the full draft is on the clipboard")
        if rewrite:
            self.undo = {"target": target, "box_hint": self.box_hint, "original": rewrite["text"], "t": time.time()}
        self.last = {"target": target, "chat": chat, "first": (rewrite or {}).get("written_from") or instruction,
                     "text": text, "t": time.time()}
        print(f"typed into the box: first words after {first_ms} ms, done in {total_ms} ms"
              f" (mode: {'rewrite' if rewrite else 'new'}, echo redone: {retried})")

    def restore_box(self, target, original, typer):
        """After a cancelled draft, put the box back the way it was: the user's text, or empty."""
        if win32gui.GetForegroundWindow() != target or not compose_has_focus(target):
            print("cancelled; couldn't confirm the message box, so it was left as it is")
            return
        if typer.started:
            select_all()
            time.sleep(0.03)
            if original:
                StreamTyper(target, replace=False).feed(original)
            else:
                backspace()
        print(f"cancelled the draft; box restored ({'original text' if original else 'empty'})")

    def hand_back_to_box(self, target):
        """Give focus back to the chat while the bar still owns the foreground, then put the caret in its message
        box. True only when the caret is confirmed there: nothing is typed otherwise."""
        bring_to_front(target)
        self.hide("handing back to the chat", restore_focus=False)
        time.sleep(0.15)
        box_focused = focus_compose_box(target, self.box_hint)
        time.sleep(0.1)
        return box_focused and win32gui.GetForegroundWindow() == target and compose_has_focus(target)

    def do_undo(self):
        u = self.undo
        if not u or u["target"] != self.target:
            self.js("error", "Nothing to undo here.")
            return
        if not self.hand_back_to_box(u["target"]):
            self.show_fallback(u["original"], "Couldn't find the message box. Here's your original text to copy.")
            return
        StreamTyper(u["target"], replace=True).feed(u["original"])
        self.undo = None
        self.last = None
        print(f"undo: put back the original ({len(u['original'])} chars)")

    def show_fallback(self, text, message):
        self.js("fallback", text, message)
        self.window.show()
        self.visible = True
        bring_to_front(self.hwnd)
        self.focus_webview()

    # --- startup ---

    def set_window_icons(self):
        """The Roverlay logo in the settings window's title bar and taskbar button (pywebview shows its own)."""
        from System import Action
        from System.Drawing import Icon
        from webview.platforms.winforms import BrowserView
        try:
            icon = Icon(str(HERE / "assets" / "icon.ico"))
            for w in (self.window, self.settings_window):
                form = BrowserView.instances.get(w.uid)
                if form is not None:
                    form.Invoke(Action(lambda f=form: setattr(f, "Icon", icon)))
        except Exception as e:
            print("couldn't set the window icon:", type(e).__name__, e)

    def started(self):
        threading.Thread(target=self.js_worker, daemon=True).start()
        threading.Thread(target=warm_up, daemon=True).start()
        for _ in range(100):  # the form appears a moment after start, even while hidden
            if self.find_own_window(BAR_TITLE):
                break
            time.sleep(0.1)
        self.style_bar()
        # pywebview shows a transparent window by itself while its page loads: hide until it stays hidden.
        self.window.events.loaded.wait(15)
        quiet_since, deadline = None, time.time() + 8
        while time.time() < deadline:
            if win32gui.IsWindowVisible(self.hwnd):
                self.window.hide()
                quiet_since = None
            elif quiet_since is None:
                quiet_since = time.time()
            elif time.time() - quiet_since > 1.0:
                break
            time.sleep(0.1)
        self.hotkey = Hotkey(self.settings.hotkey, self.toggle)
        if self.hotkey.start():
            print(f"Ready: press {self.settings.hotkey} in a chat.")
        else:
            print(f"{self.settings.hotkey} is taken by another app; choose another shortcut in Settings.")
        self.tray = Tray(self.show_settings, self.toggle_pause, lambda: self.settings.paused, self.quit,
                         lambda: self.hotkey.combo if self.hotkey else self.settings.hotkey)
        self.tray.start()
        threading.Thread(target=self.wait_for_second_launch, daemon=True).start()
        # First run, or launched from the Start menu: show Settings. At login (--background), stay in the tray.
        if not self.drafter.available() or not self.background:
            self.show_settings()

    def wait_for_second_launch(self):
        """Opening Roverlay again while it's running (the Start menu icon) shows Settings instead."""
        import win32event
        event = win32event.CreateEvent(None, False, False, "Roverlay.ShowSettings")
        while not self.quitting:
            if win32event.WaitForSingleObject(event, 500) == win32event.WAIT_OBJECT_0:
                self.show_settings()

    def on_settings_closing(self):
        if self.quitting:
            return True
        threading.Thread(target=self.settings_window.hide, daemon=True).start()
        return False  # keep it: closing the settings window just hides it

    def run(self):
        self.drafter.start()
        self.window = webview.create_window(
            BAR_TITLE, html=page("bar", "panel.css", "panel.js"), js_api=BarApi(self),
            width=WIDTH + 2 * ROOM, height=BAR_HEIGHT + 2 * ROOM, frameless=True, easy_drag=False, on_top=True,
            hidden=True, resizable=False, transparent=True)
        self.settings_window = webview.create_window(
            SETTINGS_TITLE, html=page("settings", "settings.css", "settings.js"), js_api=SettingsApi(self),
            width=580, height=720, hidden=True, resizable=False)
        self.settings_window.events.closing += self.on_settings_closing
        try:
            webview.start(self.started, gui="edgechromium")
        finally:
            self.drafter.stop()

