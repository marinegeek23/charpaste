# charpaste

A small cross-platform tray app that **types your clipboard one character at a
time** instead of doing a `Ctrl+V` paste. That lets you "paste" into places
where the clipboard is blocked — Azure Virtual Desktop / AVD, Citrix, locked-down
RDP, some KVM/IP consoles, etc.

It's a port of the AutoHotkey `KaseyaPaste.ahk` script to Linux (Wayland & X11)
and Windows, with no AutoHotkey required.

- Runs in the system tray (KDE StatusNotifier supported).
- Press a hotkey → the clipboard is typed out keystroke-by-keystroke.
- Right-click the tray icon → **Quit**.

---

## How it works per platform

| Platform | Type into other apps | Global hotkey |
|---|---|---|
| Windows | `pynput` | `pynput` (built-in hotkey) |
| Linux X11 | `pynput` | `pynput` (built-in hotkey) |
| Linux Wayland | `ydotool` (uinput) | `evdev` if you're in the `input` group, **or** a KDE global shortcut → `charpaste --trigger` |

Backends are auto-detected; you can pin them in the config file.

---

## Install

Python 3.9+.

```bash
cd charpaste
python3 -m pip install --user .
# or, to run without installing:
python3 -m pip install --user pystray pillow pynput pyperclip evdev
python3 -m charpaste
```

Run it:

```bash
charpaste
```

A config file is created on first run. Print its path with:

```bash
charpaste --config
```

```jsonc
{
  "hotkey": "ctrl+alt+v",   // trigger for the built-in listener
  "char_delay_ms": 8,       // raise to 20-40 if a session drops characters
  "start_delay_ms": 300,    // pause before typing so you can release the hotkey
  "typing_backend": "auto", // auto | pynput | ydotool
  "clipboard_backend": "auto",
  "ipc_port": 49677
}
```

---

## Linux (KDE) — Wayland setup

You need two pieces on Wayland: a way to **type** into other windows, and a way
to **trigger**.

### 1. Typing — install `ydotool` + clipboard tools

Ubuntu:
```bash
sudo apt install ydotool wl-clipboard
```
Fedora:
```bash
sudo dnf install ydotool wl-clipboard
```

`ydotool` needs the `ydotoold` daemon running with access to `/dev/uinput`.
Allow your user to use uinput without root:

```bash
echo 'KERNEL=="uinput", GROUP="input", MODE="0660", OPTIONS+="static_node=uinput"' \
  | sudo tee /etc/udev/rules.d/80-uinput.rules
sudo usermod -aG input "$USER"
sudo udevadm control --reload-rules && sudo udevadm trigger
# log out and back in for the group change to take effect
```

Then run the daemon as your user (a unit file is provided):

```bash
mkdir -p ~/.config/systemd/user
cp packaging/ydotoold.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now ydotoold
```

> charpaste calls `ydotool` with the default socket. If you customize
> `--socket-path`, export `YDOTOOL_SOCKET` for the charpaste process too.

### 2. Trigger — pick one

**A. KDE Custom Global Shortcut (recommended, no extra permissions).**
System Settings → Shortcuts → Add → Command/URL:
- Command: `charpaste --trigger`
- Assign it `Ctrl+Alt+V` (or whatever you like).

This talks to the running tray app over localhost and is the most reliable
option on Wayland.

**B. Built-in evdev hotkey.** Add yourself to the `input` group (same
`usermod -aG input` as above, log out/in). charpaste will then read the
keyboard directly and use the `hotkey` from the config. No KDE shortcut needed.

---

## Linux — X11 setup

```bash
sudo apt install xclip            # or: sudo dnf install xclip
python3 -m pip install --user .
```

On X11 the built-in `hotkey` works directly — no `ydotool`, no `input` group.

---

## Windows setup

```powershell
python -m pip install --user .
charpaste
```

The built-in `hotkey` (default `Ctrl+Alt+V`) and typing both work out of the
box. To start on login, drop a shortcut to `charpaste` in
`shell:startup`.

---

## Autostart on KDE

```bash
cp packaging/charpaste.desktop ~/.config/autostart/
```

---

## Usage

1. Copy text to the clipboard.
2. Focus the target window (the AVD/RDP session, etc.).
3. Press your hotkey (or click the tray icon → **Type clipboard now**).
4. After a short delay, the text is typed in character by character.

Other commands:

```bash
charpaste --paste-now   # type the clipboard once, no tray (handy for testing)
charpaste --trigger     # tell the running app to type now
charpaste --quit        # tell the running app to exit
```

---

## Tuning / troubleshooting

- **Characters dropped or out of order** in the remote session → raise
  `char_delay_ms` (try 25).
- **First characters come out as shortcuts** (e.g. typing triggers menus) → the
  hotkey modifiers were still held; raise `start_delay_ms`.
- **Nothing typed on Wayland** → check `systemctl --user status ydotoold` and
  that `/dev/uinput` is group-`input` writable.
- **Hotkey does nothing on Wayland** → use the KDE Custom Global Shortcut
  (option A); the built-in listener needs `input`-group access.
- **Wrong characters for non-US layouts under ydotool** → ydotool is layout-
  sensitive for some symbols; the KDE-shortcut + ydotool path follows your
  active layout. Increase delays if needed.

---

## Notes vs. the original AHK script

- The AHK version triggered on the **middle mouse button**; on KDE that's
  already "paste primary selection", so this port uses a **keyboard hotkey** by
  default (configurable).
- `SendRaw` → per-character typing with a configurable inter-key delay.
- Tray right-click → Quit, same as the AHK tray exit.
