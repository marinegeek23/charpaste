"""Platform backends: clipboard reading and per-character typing.

The whole point of this app lives here: type_text() emits the clipboard one
character at a time instead of doing a Ctrl+V paste.
"""

import os
import shutil
import subprocess
import sys
import time

IS_WIN = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")


def linux_session():
    """Return 'wayland', 'x11', or None."""
    if not IS_LINUX:
        return None
    if os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"
    if os.environ.get("DISPLAY"):
        return "x11"
    return None


# --------------------------------------------------------------------------- #
# Clipboard
# --------------------------------------------------------------------------- #

def _run_capture(cmd):
    try:
        res = subprocess.run(cmd, capture_output=True, check=False)
        return res.stdout.decode("utf-8", "replace")
    except (OSError, ValueError):
        return None


def get_clipboard(cfg):
    backend = cfg.get("clipboard_backend", "auto")

    def via_wl():
        return _run_capture(["wl-paste", "--no-newline"]) if shutil.which("wl-paste") else None

    def via_xclip():
        return _run_capture(["xclip", "-selection", "clipboard", "-o"]) if shutil.which("xclip") else None

    def via_xsel():
        return _run_capture(["xsel", "--clipboard", "--output"]) if shutil.which("xsel") else None

    def via_pyperclip():
        try:
            import pyperclip
            return pyperclip.paste()
        except Exception:
            return None

    if backend == "wl-paste":
        return via_wl() or ""
    if backend == "xclip":
        return via_xclip() or ""
    if backend == "xsel":
        return via_xsel() or ""
    if backend == "pyperclip":
        return via_pyperclip() or ""

    # auto
    if IS_LINUX:
        if linux_session() == "wayland":
            text = via_wl()
            if text is not None:
                return text
        text = via_xclip()
        if text is not None:
            return text
        text = via_xsel()
        if text is not None:
            return text
    return via_pyperclip() or ""


# --------------------------------------------------------------------------- #
# Typing (the per-character "paste")
# --------------------------------------------------------------------------- #

def choose_typing_backend(cfg):
    backend = cfg.get("typing_backend", "auto")
    if backend != "auto":
        return backend
    if IS_LINUX and linux_session() == "wayland":
        return "ydotool"
    return "pynput"


def type_text(text, cfg):
    """Type `text` one character at a time into the focused window."""
    if not text:
        return
    backend = choose_typing_backend(cfg)
    delay_ms = int(cfg.get("char_delay_ms", 8))
    if backend == "ydotool":
        _type_ydotool(text, delay_ms)
    else:
        _type_pynput(text, delay_ms)


def _type_ydotool(text, delay_ms):
    if not shutil.which("ydotool"):
        raise RuntimeError("ydotool not found. Install ydotool and run ydotoold (see README).")
    # ydotool reads the text from a file; /dev/stdin lets us pipe it in without
    # worrying about argument escaping or length limits. It turns '\n' into Enter
    # and types each character with the given key delay.
    subprocess.run(
        ["ydotool", "type", "--key-delay", str(delay_ms), "--file", "/dev/stdin"],
        input=text.encode("utf-8"),
        check=False,
    )


def _type_pynput(text, delay_ms):
    from pynput.keyboard import Controller, Key

    kb = Controller()
    delay = delay_ms / 1000.0
    for ch in text:
        if ch == "\r":
            continue
        if ch == "\n":
            kb.press(Key.enter)
            kb.release(Key.enter)
        elif ch == "\t":
            kb.press(Key.tab)
            kb.release(Key.tab)
        else:
            try:
                kb.type(ch)
            except Exception:
                # Skip characters the active layout can't represent.
                pass
        if delay:
            time.sleep(delay)
