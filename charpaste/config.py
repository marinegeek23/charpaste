"""Configuration loading. One small JSON file in the user config dir."""

import json
import os
import sys

DEFAULTS = {
    # Hotkey for the built-in listener (pynput on X11/Windows, evdev on Wayland).
    # On KDE Wayland the recommended trigger is a KDE Custom Global Shortcut that
    # runs `charpaste --trigger` instead -- see the README.
    "hotkey": "ctrl+alt+v",

    # Delay between each typed character, in milliseconds. Bump this up if a
    # remote session drops characters when typing fast (try 20-40).
    "char_delay_ms": 8,

    # Pause after the trigger before typing starts, in milliseconds. Gives you
    # time to release the hotkey modifiers so they don't combine with the typed
    # characters (e.g. Ctrl still held -> Ctrl+a). 250-400 is usually plenty.
    "start_delay_ms": 300,

    # Optional countdown before typing, toggled from the tray menu. This is the
    # "give me time to click into the session first" delay, and is deliberately
    # separate from start_delay_ms: that one is a short grace period that always
    # applies, this one is a longer pause you switch on when you need it. While
    # it runs the tray icon shows the seconds remaining, and triggering again
    # cancels the paste.
    "delay_enabled": False,
    "delay_seconds": 3,

    # "auto" | "pynput" | "ydotool". auto -> ydotool on Wayland, pynput elsewhere.
    "typing_backend": "auto",

    # "auto" | "wl-paste" | "xclip" | "xsel" | "pyperclip".
    "clipboard_backend": "auto",

    # Localhost TCP port used by `charpaste --trigger` to poke a running instance.
    "ipc_port": 49677,
}


def config_dir():
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, "charpaste")
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "charpaste")


def config_path():
    return os.path.join(config_dir(), "config.json")


def load():
    """Load config, creating it with defaults on first run."""
    path = config_path()
    cfg = dict(DEFAULTS)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            cfg.update(json.load(fh))
    except FileNotFoundError:
        save(cfg)
    except (ValueError, OSError) as exc:
        print(f"charpaste: could not read config ({exc}); using defaults", file=sys.stderr)
    return cfg


def save(cfg):
    path = config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)
