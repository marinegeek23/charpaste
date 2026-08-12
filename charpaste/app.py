"""Tray app: wires the clipboard, the per-character typer, the hotkey listener
and the IPC server together behind a system-tray icon.
"""

import math
import sys
import threading
import time

from . import config
from . import dialogs
from .backends import get_clipboard, type_text
from .hotkey import start_hotkey
from . import ipc

# Countdown lengths offered directly in the tray menu. Anything else goes
# through "Custom...".
DELAY_PRESETS = (1, 2, 3)


def _font(size):
    """A truetype font at the requested size, or None to fall back to PIL's."""
    from PIL import ImageFont

    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "C:\\Windows\\Fonts\\arialbd.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return None


def _make_icon_image(badge=None):
    """The tray image. With `badge`, show that number instead -- the countdown.

    The countdown replaces the whole glyph rather than sitting in a corner:
    trays render this at roughly 22px, where a corner badge is unreadable.
    """
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    if badge is not None:
        text = str(badge)
        draw.ellipse([2, 2, 62, 62], fill=(40, 44, 52, 255),
                     outline=(120, 170, 255, 255), width=4)
        font = _font(40 if len(text) == 1 else 30)
        if font is not None:
            draw.text((32, 33), text, font=font, fill=(255, 255, 255, 255),
                      anchor="mm")
        else:
            draw.text((26, 24), text, fill=(255, 255, 255, 255))
        return img

    draw.rounded_rectangle([12, 8, 52, 58], radius=6, fill=(40, 44, 52, 255))
    draw.rounded_rectangle([22, 4, 42, 14], radius=3, fill=(120, 170, 255, 255))
    for y in (26, 34, 42):
        draw.line([18, y, 46, y], fill=(205, 214, 232, 255), width=3)
    return img


class App:
    def __init__(self, cfg):
        self.cfg = cfg
        self._busy = threading.Lock()
        self._cancel = threading.Event()
        self._hotkey_stop = None
        self._ipc_srv = None
        self.icon = None

    # -- core action ----------------------------------------------------- #

    def trigger(self):
        """Read the clipboard and type it out. Runs in a worker thread."""
        threading.Thread(target=self._do_paste, daemon=True).start()

    def _do_paste(self):
        if not self._busy.acquire(blocking=False):
            # Already working. If we're mid-countdown, a second trigger is the
            # user changing their mind -- that's the only way to call it off.
            self._cancel.set()
            return
        try:
            self._cancel.clear()
            text = get_clipboard(self.cfg)
            if not text:
                self._notify("Clipboard is empty -- nothing to type")
                return
            if not self._countdown():
                self._notify("Cancelled")
                return
            # Let the user release the hotkey modifiers so they don't combine
            # with the characters we're about to type.
            time.sleep(int(self.cfg.get("start_delay_ms", 300)) / 1000.0)
            type_text(text, self.cfg)
        except Exception as exc:  # surface backend errors instead of dying silently
            self._notify(f"charpaste error: {exc}")
            print(f"charpaste error: {exc}", file=sys.stderr)
        finally:
            self._set_badge(None)
            self._busy.release()

    def _countdown(self):
        """Tick the tray icon down to zero. False if the user cancelled."""
        if not self.cfg.get("delay_enabled", False):
            return True

        remaining = float(self.cfg.get("delay_seconds", 3) or 0)
        while remaining > 0:
            self._set_badge(int(math.ceil(remaining)))
            step = remaining - math.floor(remaining) or 1.0
            if self._cancel.wait(step):
                return False
            remaining -= step
        self._set_badge(None)
        return True

    def _set_badge(self, value):
        if self.icon is None:
            return
        try:
            self.icon.icon = _make_icon_image(value)
        except Exception:
            pass  # a cosmetic failure must never stop the paste

    # -- tray ------------------------------------------------------------ #

    def _notify(self, message):
        try:
            if self.icon is not None and getattr(self.icon, "HAS_NOTIFICATION", False):
                self.icon.notify(message, "charpaste")
                return
        except Exception:
            pass
        print(f"charpaste: {message}", file=sys.stderr)

    def _refresh_menu(self):
        try:
            if self.icon is not None:
                self.icon.update_menu()
        except Exception:
            pass

    def _save(self):
        try:
            config.save(self.cfg)
        except OSError as exc:
            self._notify(f"Could not save config: {exc}")
        self._refresh_menu()

    def _reload_config(self, *_):
        self.cfg = config.load()
        self._restart_hotkey()
        self._refresh_menu()
        self._notify("Config reloaded")

    def _restart_hotkey(self):
        if self._hotkey_stop:
            try:
                self._hotkey_stop()
            except Exception:
                pass
        self._hotkey_stop = start_hotkey(self.cfg, self.trigger)

    # -- delay menu ------------------------------------------------------ #

    def _delay_seconds(self):
        try:
            return float(self.cfg.get("delay_seconds", 3))
        except (TypeError, ValueError):
            return 3.0

    def _delay_label(self):
        seconds = self._delay_seconds()
        text = f"{seconds:g}s"
        return text if self.cfg.get("delay_enabled", False) else f"{text}, off"

    def _toggle_delay(self, *_):
        self.cfg["delay_enabled"] = not self.cfg.get("delay_enabled", False)
        self._save()

    def _set_delay(self, seconds):
        """Build the handler for a preset. Picking a length also switches the
        delay on -- choosing '2 seconds' from a menu means you want 2 seconds.
        """
        def handler(*_):
            self.cfg["delay_seconds"] = seconds
            self.cfg["delay_enabled"] = True
            self._save()
        return handler

    def _ask_custom_delay(self, *_):
        # Dialogs block on a subprocess; the menu handler runs on the toolkit's
        # main loop, so doing this inline would freeze the tray.
        def worker():
            seconds = dialogs.ask_seconds(self._delay_seconds())
            if seconds is None:
                return
            self.cfg["delay_seconds"] = seconds
            self.cfg["delay_enabled"] = True
            self._save()
        threading.Thread(target=worker, daemon=True).start()

    def _open_settings(self, *_):
        def worker():
            new = dialogs.edit_settings(self.cfg)
            if not new:
                return
            hotkey_changed = new.get("hotkey") != self.cfg.get("hotkey")
            self.cfg.update(new)
            self._save()
            if hotkey_changed:
                self._restart_hotkey()
            self._notify("Settings saved")
        threading.Thread(target=worker, daemon=True).start()

    def _delay_submenu(self):
        from pystray import Menu, MenuItem

        items = []
        for seconds in DELAY_PRESETS:
            items.append(MenuItem(
                f"{seconds} second" if seconds == 1 else f"{seconds} seconds",
                self._set_delay(seconds),
                checked=lambda item, s=seconds: self._delay_seconds() == s,
                radio=True,
            ))
        items.append(Menu.SEPARATOR)
        items.append(MenuItem(
            lambda item: (f"Custom... ({self._delay_seconds():g}s)"
                          if self._delay_seconds() not in DELAY_PRESETS
                          else "Custom..."),
            self._ask_custom_delay,
            checked=lambda item: self._delay_seconds() not in DELAY_PRESETS,
            radio=True,
        ))
        return Menu(*items)

    # -- lifecycle ------------------------------------------------------- #

    def quit(self, *_):
        self._cancel.set()
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

    def _build_menu(self):
        from pystray import Menu, MenuItem

        # "Delay" carries the checkbox and the on/off click; the flyout has to
        # be a separate row because a pystray item with a submenu never gets an
        # activate handler -- clicking it could only ever open the submenu.
        return Menu(
            MenuItem("Type clipboard now", lambda icon, item: self.trigger(),
                     default=True),
            MenuItem(lambda item: f"Hotkey: {self.cfg.get('hotkey', 'ctrl+alt+v')}",
                     None, enabled=False),
            Menu.SEPARATOR,
            MenuItem("Delay", self._toggle_delay,
                     checked=lambda item: bool(self.cfg.get("delay_enabled", False))),
            MenuItem(lambda item: f"Delay length: {self._delay_label()}",
                     self._delay_submenu()),
            MenuItem("Settings...", self._open_settings),
            Menu.SEPARATOR,
            MenuItem("Reload config", self._reload_config),
            MenuItem("Quit", self.quit),
        )

    def run(self):
        import pystray

        self._ipc_srv = ipc.start_server(
            int(self.cfg.get("ipc_port", 49677)), self.trigger, self.quit
        )
        self._restart_hotkey()

        self.icon = pystray.Icon("charpaste", _make_icon_image(), "charpaste",
                                 self._build_menu())
        # icon.run() blocks on the main thread until quit().
        self.icon.run()


def run(cfg=None):
    App(cfg or config.load()).run()
