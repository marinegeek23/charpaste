"""Small GUI prompts: the custom-delay box and the settings form.

Tk runs in a **subprocess**, never in-process. The tray icon already owns a GTK
main loop on the main thread, and starting Tk's main loop alongside it either
deadlocks or crashes depending on the backend. A subprocess keeps the two
toolkits entirely apart, at the cost of a few hundred milliseconds per prompt.

If Tk is unavailable (no python3-tk), single-value prompts fall back to
kdialog/zenity, and the settings form falls back to opening config.json in
whatever editor the desktop uses.

Every entry point returns ``None`` when the user cancels or nothing worked, so
callers can treat "no answer" and "no dialog available" identically.
"""

import json
import os
import shutil
import subprocess
import sys

# Runs in the subprocess: reads a field spec as JSON on stdin, writes the
# filled-in values as JSON on stdout. Cancelling writes nothing.
_TK_FORM = r"""
import json, sys
import tkinter as tk
from tkinter import ttk, messagebox

spec = json.load(sys.stdin)
fields = spec["fields"]

root = tk.Tk()
root.title(spec.get("title", "charpaste"))
root.resizable(False, False)

frame = ttk.Frame(root, padding=12)
frame.grid(sticky="nsew")

vars_ = {}
for row, f in enumerate(fields):
    ttk.Label(frame, text=f["label"]).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=4)
    var = tk.StringVar(value=str(f.get("value", "")))
    vars_[f["key"]] = (var, f)
    if f.get("options"):
        w = ttk.Combobox(frame, textvariable=var, values=f["options"],
                         state="readonly", width=22)
    else:
        w = ttk.Entry(frame, textvariable=var, width=24)
    w.grid(row=row, column=1, sticky="ew", pady=4)
    if row == 0:
        w.focus_set()
        if not f.get("options"):
            w.select_range(0, tk.END)

if spec.get("hint"):
    ttk.Label(frame, text=spec["hint"], foreground="#666", wraplength=320,
              justify="left").grid(row=len(fields), column=0, columnspan=2,
                                   sticky="w", pady=(8, 0))

result = {}

def on_ok(*_):
    out = {}
    for key, (var, f) in vars_.items():
        raw = var.get().strip()
        kind = f.get("kind", "text")
        if kind in ("int", "float"):
            try:
                val = int(raw) if kind == "int" else float(raw)
            except ValueError:
                messagebox.showerror("charpaste", "%s must be a number." % f["label"])
                return
            lo, hi = f.get("min"), f.get("max")
            if (lo is not None and val < lo) or (hi is not None and val > hi):
                messagebox.showerror(
                    "charpaste", "%s must be between %s and %s." % (f["label"], lo, hi))
                return
            out[key] = val
        else:
            out[key] = raw
    result.update(out)
    root.destroy()

def on_cancel(*_):
    root.destroy()

buttons = ttk.Frame(frame)
buttons.grid(row=len(fields) + 1, column=0, columnspan=2, sticky="e", pady=(12, 0))
ttk.Button(buttons, text="Cancel", command=on_cancel).grid(row=0, column=0, padx=(0, 6))
ttk.Button(buttons, text="OK", command=on_ok).grid(row=0, column=1)

root.bind("<Return>", on_ok)
root.bind("<Escape>", on_cancel)
root.protocol("WM_DELETE_WINDOW", on_cancel)
try:
    root.eval("tk::PlaceWindow . center")
    root.attributes("-topmost", True)
except tk.TclError:
    pass
root.mainloop()

if result:
    json.dump(result, sys.stdout)
"""


def _tk_form(title, fields, hint=None):
    """Show a Tk form.

    Returns ``(shown, values)``. Cancelling gives ``(True, None)`` and a missing
    or broken Tk gives ``(False, None)`` -- callers must tell those apart, or
    cancelling a dialog would trip the "no GUI available" fallback.
    """
    spec = json.dumps({"title": title, "fields": fields, "hint": hint})
    try:
        proc = subprocess.run(
            [sys.executable, "-c", _TK_FORM],
            input=spec, capture_output=True, text=True, timeout=600,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False, None

    if proc.returncode != 0:
        # No python3-tk, no display, etc. The dialog never reached the user.
        return False, None

    out = proc.stdout.strip()
    if not out:
        return True, None  # shown, and the user cancelled
    try:
        return True, json.loads(out)
    except ValueError:
        return True, None


def _have(cmd):
    return shutil.which(cmd) is not None


def _cli_prompt(title, label, initial):
    """Fallback single-value prompt via kdialog/zenity. Returns str or None."""
    if _have("kdialog"):
        cmd = ["kdialog", "--title", title, "--inputbox", label, str(initial)]
    elif _have("zenity"):
        cmd = ["zenity", "--entry", "--title", title, "--text", label,
               "--entry-text", str(initial)]
    else:
        return None
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def ask_seconds(current):
    """Prompt for a countdown length in seconds. Returns a number, or None."""
    fields = [{
        "key": "seconds", "label": "Seconds before typing:",
        "kind": "float", "value": current, "min": 0, "max": 600,
    }]
    shown, got = _tk_form("charpaste - delay", fields,
                          hint="How long to wait after the hotkey before typing starts.")
    if shown:
        return got["seconds"] if got else None

    raw = _cli_prompt("charpaste - delay", "Seconds before typing:", current)
    if raw is None:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if 0 <= value <= 600 else None


# Config keys exposed in the settings form, in display order.
SETTINGS_FIELDS = (
    ("hotkey", "Hotkey:", "text", None),
    ("delay_seconds", "Countdown (seconds):", "float", None),
    ("char_delay_ms", "Delay per character (ms):", "int", None),
    ("start_delay_ms", "Hotkey release grace (ms):", "int", None),
    ("typing_backend", "Typing backend:", "text", ["auto", "pynput", "ydotool"]),
    ("clipboard_backend", "Clipboard backend:", "text",
     ["auto", "wl-paste", "xclip", "xsel", "pyperclip"]),
)

_LIMITS = {
    "delay_seconds": (0, 600),
    "char_delay_ms": (0, 1000),
    "start_delay_ms": (0, 10000),
}


def edit_settings(cfg):
    """Show the settings form. Returns a dict of new values, or None."""
    fields = []
    for key, label, kind, options in SETTINGS_FIELDS:
        field = {"key": key, "label": label, "kind": kind, "value": cfg.get(key, "")}
        if options:
            field["options"] = options
        if key in _LIMITS:
            field["min"], field["max"] = _LIMITS[key]
        fields.append(field)

    shown, got = _tk_form(
        "charpaste - settings", fields,
        hint="On KDE Wayland the hotkey above is unused -- the trigger is a "
             "KDE global shortcut running 'charpaste --trigger'.")
    if shown:
        return got

    # No Tk: there is no sensible multi-field fallback, so hand over the file.
    open_config_file()
    return None


def open_config_file():
    """Last resort: hand config.json to the desktop's editor."""
    from . import config

    path = config.config_path()
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)  # noqa: B606 - Windows-only API
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
        return True
    except OSError:
        return False
