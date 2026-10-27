"""The tray icon: Open settings (also a left click), Pause, Quit."""
from pathlib import Path

import pystray
from PIL import Image

ASSETS = Path(__file__).parent / "assets"


class Tray:
    def __init__(self, on_settings, on_pause_toggle, is_paused, on_quit, hotkey_label):
        self.on_settings = on_settings
        self.on_pause_toggle = on_pause_toggle
        self.is_paused = is_paused
        self.on_quit = on_quit
        self.hotkey_label = hotkey_label
        self.icon = None

    def _menu(self):
        return pystray.Menu(
            pystray.MenuItem(lambda _: f"Roverlay · {self.hotkey_label()}", None, enabled=False),
            pystray.MenuItem("Open settings", lambda: self.on_settings(), default=True),
            pystray.MenuItem("Pause", lambda: self.on_pause_toggle(), checked=lambda _: self.is_paused()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit Roverlay", lambda: self.on_quit()),
        )

    def start(self):
        image = Image.open(ASSETS / "tray.png")
        self.icon = pystray.Icon("Roverlay", image, "Roverlay", self._menu())
        self.icon.run_detached()

    def refresh(self):
        if self.icon:
            self.icon.title = "Roverlay (paused)" if self.is_paused() else "Roverlay"
            self.icon.update_menu()

    def stop(self):
        if self.icon:
            self.icon.stop()
