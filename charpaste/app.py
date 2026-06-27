"""Tray app: wires the clipboard, the per-character typer, the hotkey listener
and the IPC server together behind a system-tray icon.
"""

import sys
import threading
import time

from . import config
from .backends import get_clipboard, type_text
from .hotkey import start_hotkey
from . import ipc


def _make_icon_image():
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([12, 8, 52, 58], radius=6, fill=(40, 44, 52, 255))
    draw.rounded_rectangle([22, 4, 42, 14], radius=3, fill=(120, 170, 255, 255))
    for y in (26, 34, 42):
        draw.line([18, y, 46, y], fill=(205, 214, 232, 255), width=3)
    return img


class App:
    def __init__(self, cfg):
        self.cfg = cfg
        self._busy = threading.Lock()
        self._hotkey_stop = None
        self._ipc_srv = None
        self.icon = None

    # -- core action ----------------------------------------------------- #

    def trigger(self):
        """Read the clipboard and type it out. Runs in a worker thread."""
        threading.Thread(target=self._do_paste, daemon=True).start()

    def _do_paste(self):
        # Ignore overlapping triggers while a paste is already running.
        if not self._busy.acquire(blocking=False):
            return
        try:
            text = get_clipboard(self.cfg)
            if not text:
                self._notify("Clipboard is empty -- nothing to type")
                return
            # Let the user release the hotkey modifiers so they don't combine
            # with the characters we're about to type.
            time.sleep(int(self.cfg.get("start_delay_ms", 300)) / 1000.0)
            type_text(text, self.cfg)
        except Exception as exc:  # surface backend errors instead of dying silently
            self._notify(f"charpaste error: {exc}")
            print(f"charpaste error: {exc}", file=sys.stderr)
        finally:
            self._busy.release()

    # -- tray ------------------------------------------------------------ #

    def _notify(self, message):
        try:
            if self.icon is not None and getattr(self.icon, "HAS_NOTIFICATION", False):
                self.icon.notify(message, "charpaste")
                return
        except Exception:
            pass
        print(f"charpaste: {message}", file=sys.stderr)

    def _reload_config(self, *_):
        self.cfg = config.load()
        self._restart_hotkey()
        self._notify("Config reloaded")

    def _restart_hotkey(self):
        if self._hotkey_stop:
            try:
                self._hotkey_stop()
            except Exception:
                pass
        self._hotkey_stop = start_hotkey(self.cfg, self.trigger)

    def quit(self, *_):
        if self._hotkey_stop:
            try:
                self._hotkey_stop()
            except Exception:
                pass
        if self._ipc_srv:
            try:
                self._ipc_srv.close()
            except Exception:
                pass
        if self.icon:
            self.icon.stop()

    def run(self):
        import pystray
        from pystray import Menu, MenuItem

        self._ipc_srv = ipc.start_server(
            int(self.cfg.get("ipc_port", 49677)), self.trigger, self.quit
        )
        self._restart_hotkey()

        hotkey = self.cfg.get("hotkey", "ctrl+alt+v")
        menu = Menu(
            MenuItem("Type clipboard now", lambda icon, item: self.trigger(), default=True),
            MenuItem(f"Hotkey: {hotkey}", None, enabled=False),
            Menu.SEPARATOR,
            MenuItem("Reload config", self._reload_config),
            MenuItem("Quit", self.quit),
        )
        self.icon = pystray.Icon("charpaste", _make_icon_image(), "charpaste", menu)
        # icon.run() blocks on the main thread until quit().
        self.icon.run()


def run(cfg=None):
    App(cfg or config.load()).run()
