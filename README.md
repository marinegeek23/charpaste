# charpaste

[![CI](https://github.com/marinegeek23/charpaste/actions/workflows/ci.yml/badge.svg)](https://github.com/marinegeek23/charpaste/actions/workflows/ci.yml)

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

### Linux — one command (recommended)

On a fresh or rebuilt machine, everything outside the repo is set up for you:

```bash
git clone https://github.com/marinegeek23/charpaste.git
cd charpaste
./packaging/install-linux.sh
```

That checks your system dependencies, builds the venv, puts `charpaste` on your
`PATH`, installs the autostart and application-menu entries, enables `ydotoold`
on Wayland, and registers the `Ctrl+Alt+V` global shortcut on KDE. It is
idempotent — re-run it after a `git pull` to pick up code changes.

Two things it deliberately does *not* do: run `sudo` (anything needing root is
printed for you to run), and put the venv inside the repo. The venv lives at
`~/.local/share/charpaste/venv` so the repo can sit on a network share that
can't hold symlinks, and so moving the repo never breaks the install. Override
with `CHARPASTE_VENV=/some/path`, and the hotkey with `CHARPASTE_HOTKEY='Meta+V'`.

The venv is created with `--system-site-packages` on purpose: `pystray` needs
your distro's PyGObject and Ayatana AppIndicator bindings to draw a tray icon,
and a sealed venv silently gets no tray.

### Manual / other platforms

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
  "delay_enabled": false,   // the tray "Delay" checkbox
  "delay_seconds": 3,       // how long that countdown runs
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
`packaging/install-linux.sh` sets this up for you. It installs the hidden
launcher `packaging/net.local.charpaste.desktop` (KDE can only bind a shortcut
to a `.desktop` entry, so that file exists purely to be the hotkey's target) and
writes the binding into `kglobalshortcutsrc`:

```ini
[services][net.local.charpaste.desktop]
_launch=Ctrl+Alt+V
```

`kglobalaccel` has no D-Bus reload, so **the shortcut starts working at your
next login.** To do it by hand instead: System Settings → Shortcuts → Add →
Command/URL → `charpaste --trigger`.

Either way, this talks to the running tray app over localhost and is the most
reliable option on Wayland.

> Give the launcher an **absolute** `Exec=` path (`~/.local/bin/charpaste
> --trigger`). `kglobalaccel` does not necessarily inherit a `PATH` containing
> `~/.local/bin`, so a bare `Exec=charpaste` can fail silently — the hotkey
> appears bound and simply does nothing. The install script handles this.

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

## Starting, stopping, and relaunching

charpaste is a normal foreground program with a tray icon — there's no
background service for the app itself (only `ydotoold` runs as a service on
Wayland). To **quit**, right-click the tray icon → **Quit**.

To **start it again** after quitting, do any one of:

- Run `charpaste` (it's on your `PATH` via `~/.local/bin`). To detach it from
  the terminal so closing the terminal doesn't kill it:
  ```bash
  setsid charpaste >/dev/null 2>&1 < /dev/null &
  ```
- Launch **charpaste** from the KDE application launcher (if you installed the
  app-menu entry — see below).
- Just **log out and back in** — autostart relaunches it.

Only one instance runs the tray at a time; extra `charpaste` invocations with
`--trigger` / `--quit` talk to the already-running one over localhost.

## Autostart on login (KDE)

Done for you by `packaging/install-linux.sh`. By hand:

```bash
cp packaging/charpaste.desktop ~/.config/autostart/
```

## Show it in the KDE application launcher

Done for you by `packaging/install-linux.sh`. By hand:

```bash
cp packaging/charpaste.desktop ~/.local/share/applications/
update-desktop-database ~/.local/share/applications 2>/dev/null || true
```

---

## What lives outside the repo

Everything below is machine state, not source. `packaging/install-linux.sh`
recreates all of it, so a rebuilt machine needs nothing but a `git clone`. The
list is here so the setup is never trapped in one box's filesystem:

| Path | What it is |
|---|---|
| `~/.local/share/charpaste/venv` | the venv (`--system-site-packages`) |
| `~/.local/bin/charpaste` | symlink onto `PATH` |
| `~/.config/autostart/charpaste.desktop` | start on login |
| `~/.local/share/applications/charpaste.desktop` | app-menu entry |
| `~/.local/share/applications/net.local.charpaste.desktop` | hidden target for the global shortcut |
| `~/.config/kglobalshortcutsrc` | the `Ctrl+Alt+V` binding itself |
| `~/.config/systemd/user/ydotoold.service` | Wayland typing daemon |
| `~/.config/charpaste/config.json` | your settings (regenerated at defaults on first run) |

System packages are the only other requirement: `ydotool` + `wl-clipboard` on
Wayland, `xclip` on X11. The install script checks for them and tells you the
command to install them.

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

## The tray menu

```
Type clipboard now
Hotkey: ctrl+alt+v
────────────────────
[x] Delay                    ← click to switch the countdown on/off
    Delay length: 3s  ▸      ← 1s / 2s / 3s / Custom...
Settings...
────────────────────
Reload config
Quit
```

### Countdown delay

Switch **Delay** on and the app waits before it starts typing, so you have time
to click into the target window after firing the hotkey. The tray icon counts
the seconds down, and **triggering again while it counts cancels the paste** —
that's the escape hatch if you fire it at the wrong window.

Picking a length from **Delay length** also switches the delay on, since
choosing "2 seconds" from a menu means you want 2 seconds. **Custom...** takes
any value from 0 to 600 and the menu then shows it, e.g. `Custom... (7s)`.

The countdown is separate from `start_delay_ms`, which is a much shorter grace
period that always applies so your hotkey modifiers aren't still held when
typing starts. Leave that one alone; this is the knob you want.

> The checkbox and the flyout are two rows rather than one because pystray
> never connects an activate handler to an item that has a submenu — a single
> "Delay ▸" row could open the flyout or respond to clicks, but not both.

### Settings

**Settings...** opens a small form for the config values worth changing
regularly: hotkey, countdown length, per-character delay, hotkey-release grace,
and the typing/clipboard backends. Saving writes `config.json` and applies
immediately — a changed hotkey restarts the listener without a relaunch.

The form is Tk, run in a subprocess (the tray already owns a GTK main loop, and
two toolkit main loops in one process do not coexist). Without Tk installed
(`python3-tk`), **Custom...** falls back to kdialog/zenity and **Settings...**
opens `config.json` in your editor.

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
