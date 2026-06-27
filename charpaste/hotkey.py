"""Global hotkey listeners.

- Windows / Linux-X11: pynput's GlobalHotKeys (works out of the box).
- Linux-Wayland: pynput can't grab global keys, so we read evdev directly.
  That needs read access to /dev/input/event* (be in the `input` group). If
  that isn't available, start_hotkey() returns None and the app falls back to
  the `charpaste --trigger` IPC path (bind it to a KDE global shortcut).
"""

import sys
import threading

from .backends import IS_LINUX, linux_session

_PYNPUT_MODS = {
    "ctrl": "<ctrl>", "control": "<ctrl>",
    "alt": "<alt>", "altgr": "<alt_gr>",
    "shift": "<shift>",
    "super": "<cmd>", "meta": "<cmd>", "win": "<cmd>", "cmd": "<cmd>",
}


def _to_pynput_combo(spec):
    parts = [p.strip().lower() for p in spec.split("+") if p.strip()]
    return "+".join(_PYNPUT_MODS.get(p, p) for p in parts)


def start_hotkey(cfg, on_trigger):
    """Start a listener. Returns a stop() callable, or None if unavailable."""
    spec = cfg.get("hotkey", "ctrl+alt+v")
    if IS_LINUX and linux_session() == "wayland":
        stop = _start_evdev(spec, on_trigger)
        if stop is None:
            print(
                "charpaste: no built-in hotkey on Wayland (need read access to "
                "/dev/input -- add yourself to the 'input' group, or bind a KDE "
                "Custom Global Shortcut to `charpaste --trigger`).",
                file=sys.stderr,
            )
        return stop
    return _start_pynput(spec, on_trigger)


def _start_pynput(spec, on_trigger):
    try:
        from pynput import keyboard
    except Exception as exc:
        print(f"charpaste: pynput hotkey unavailable ({exc})", file=sys.stderr)
        return None
    combo = _to_pynput_combo(spec)
    hk = keyboard.GlobalHotKeys({combo: on_trigger})
    hk.daemon = True
    hk.start()
    return hk.stop


def _start_evdev(spec, on_trigger):
    try:
        import evdev
        from evdev import ecodes
    except Exception:
        return None

    mods = {
        "ctrl": [ecodes.KEY_LEFTCTRL, ecodes.KEY_RIGHTCTRL],
        "control": [ecodes.KEY_LEFTCTRL, ecodes.KEY_RIGHTCTRL],
        "alt": [ecodes.KEY_LEFTALT, ecodes.KEY_RIGHTALT],
        "shift": [ecodes.KEY_LEFTSHIFT, ecodes.KEY_RIGHTSHIFT],
        "super": [ecodes.KEY_LEFTMETA, ecodes.KEY_RIGHTMETA],
        "meta": [ecodes.KEY_LEFTMETA, ecodes.KEY_RIGHTMETA],
        "win": [ecodes.KEY_LEFTMETA, ecodes.KEY_RIGHTMETA],
    }

    mod_groups = []
    main_key = None
    for part in (p.strip().lower() for p in spec.split("+") if p.strip()):
        if part in mods:
            mod_groups.append(mods[part])
        else:
            main_key = getattr(ecodes, "KEY_" + part.upper(), None)
    if main_key is None:
        return None

    keyboards = []
    for path in evdev.list_devices():
        try:
            dev = evdev.InputDevice(path)
        except OSError:
            continue
        keys = dev.capabilities().get(ecodes.EV_KEY, [])
        if ecodes.KEY_A in keys:
            keyboards.append(dev)
    if not keyboards:
        return None

    import selectors

    sel = selectors.DefaultSelector()
    for dev in keyboards:
        sel.register(dev, selectors.EVENT_READ)

    pressed = set()
    stop_flag = threading.Event()

    def mods_held():
        return all(any(code in pressed for code in grp) for grp in mod_groups)

    def loop():
        while not stop_flag.is_set():
            for key, _ in sel.select(timeout=0.5):
                try:
                    events = list(key.fileobj.read())
                except OSError:
                    continue
                for ev in events:
                    if ev.type != ecodes.EV_KEY:
                        continue
                    if ev.value == 1:
                        pressed.add(ev.code)
                    elif ev.value == 0:
                        pressed.discard(ev.code)
                    if ev.code == main_key and ev.value == 1 and mods_held():
                        on_trigger()

    thread = threading.Thread(target=loop, daemon=True)
    thread.start()

    def stop():
        stop_flag.set()
        for dev in keyboards:
            try:
                dev.close()
            except OSError:
                pass

    return stop
