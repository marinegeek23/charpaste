#!/usr/bin/env bash
#
# charpaste — one-shot Linux install/wiring.
#
# Sets up everything that lives OUTSIDE the git repo, so a rebuilt machine only
# needs:  git clone … && ./packaging/install-linux.sh
#
# Idempotent: safe to re-run after a `git pull` to pick up code changes.
#
# What it does:
#   1. checks system dependencies (ydotool/wl-clipboard on Wayland, xclip on X11)
#   2. creates a venv and installs charpaste into it
#   3. links `charpaste` onto your PATH (~/.local/bin)
#   4. installs the autostart + application-menu entries
#   5. Wayland: installs and enables the ydotoold user service
#   6. KDE: registers the Ctrl+Alt+V global shortcut
#
# It never runs sudo. Anything needing root is printed for you to run.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# The venv deliberately lives outside the repo: the repo may sit on a network
# share (CIFS/NFS) that can't hold the symlinks a venv needs, and keeping them
# separate means moving the repo never breaks the install.
VENV="${CHARPASTE_VENV:-$HOME/.local/share/charpaste/venv}"

BIN_DIR="$HOME/.local/bin"
APP_DIR="$HOME/.local/share/applications"
AUTOSTART_DIR="$HOME/.config/autostart"
UNIT_DIR="$HOME/.config/systemd/user"

HOTKEY="${CHARPASTE_HOTKEY:-Ctrl+Alt+V}"
SHORTCUT_ID="net.local.charpaste.desktop"

note() { printf '  %s\n' "$*"; }
step() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[33m  ! %s\033[0m\n' "$*"; }

is_wayland() { [ "${XDG_SESSION_TYPE:-}" = "wayland" ]; }
is_kde() { case "${XDG_CURRENT_DESKTOP:-}" in *KDE*) return 0 ;; *) return 1 ;; esac; }

# ---------------------------------------------------------------- 1. system deps

step "Checking system dependencies"

missing=()
if is_wayland; then
    note "session: Wayland — typing goes through ydotool"
    command -v ydotool  >/dev/null || missing+=(ydotool)
    command -v ydotoold >/dev/null || missing+=(ydotool)
    command -v wl-paste >/dev/null || missing+=(wl-clipboard)
else
    note "session: X11 — typing goes through pynput"
    command -v xclip >/dev/null || command -v xsel >/dev/null || missing+=(xclip)
fi

if [ ${#missing[@]} -gt 0 ]; then
    # de-duplicate
    mapfile -t missing < <(printf '%s\n' "${missing[@]}" | sort -u)
    warn "missing: ${missing[*]}"
    if command -v apt >/dev/null; then
        note "install with:  sudo apt install ${missing[*]}"
    elif command -v dnf >/dev/null; then
        note "install with:  sudo dnf install ${missing[*]}"
    fi
    warn "re-run this script once they're installed"
    exit 1
fi
note "all present"

# ------------------------------------------------------------------- 2. the venv

step "Installing charpaste into $VENV"

# --system-site-packages matters: pystray needs the DISTRO's PyGObject and
# Ayatana AppIndicator bindings to draw a tray icon. A sealed venv gets no tray.
if [ ! -x "$VENV/bin/python" ]; then
    mkdir -p "$(dirname "$VENV")"
    python3 -m venv --system-site-packages "$VENV"
    note "created"
else
    note "reusing existing venv"
fi

"$VENV/bin/python" -m pip install --quiet --upgrade pip
"$VENV/bin/python" -m pip install --quiet --upgrade "$REPO_DIR"
note "charpaste $("$VENV/bin/charpaste" --version 2>/dev/null | awk '{print $2}') installed"

# -------------------------------------------------------------------- 3. on PATH

step "Linking onto PATH"

mkdir -p "$BIN_DIR"
ln -sfn "$VENV/bin/charpaste" "$BIN_DIR/charpaste"
note "$BIN_DIR/charpaste -> $VENV/bin/charpaste"

case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) warn "$BIN_DIR is not on your PATH — add it to your shell profile" ;;
esac

# ------------------------------------------------------------- 4. desktop entries

step "Installing desktop entries"

mkdir -p "$APP_DIR" "$AUTOSTART_DIR"

# Exec= is rewritten to an absolute path so the entries work even when the
# desktop session (or kglobalaccel) starts with a PATH that lacks ~/.local/bin.
install_desktop() {
    sed "s|^Exec=charpaste\b|Exec=$BIN_DIR/charpaste|" "$1" > "$2"
}

install_desktop "$REPO_DIR/packaging/charpaste.desktop" "$AUTOSTART_DIR/charpaste.desktop"
note "autostart:    $AUTOSTART_DIR/charpaste.desktop"

install_desktop "$REPO_DIR/packaging/charpaste.desktop" "$APP_DIR/charpaste.desktop"
note "app menu:     $APP_DIR/charpaste.desktop"

update-desktop-database "$APP_DIR" 2>/dev/null || true

# ------------------------------------------------------------ 5. ydotoold service

if is_wayland; then
    step "Setting up ydotoold (Wayland typing backend)"

    mkdir -p "$UNIT_DIR"
    install -m 644 "$REPO_DIR/packaging/ydotoold.service" "$UNIT_DIR/ydotoold.service"
    systemctl --user daemon-reload
    systemctl --user enable --now ydotoold.service
    note "ydotoold: $(systemctl --user is-active ydotoold.service)"

    # ydotool synthesises input through /dev/uinput. On most systems logind
    # grants the seat owner an ACL and this Just Works; if not, a udev rule and
    # the `input` group are needed.
    if [ ! -w /dev/uinput ]; then
        warn "/dev/uinput is not writable by you — ydotool cannot type"
        note "fix with:"
        note "  echo 'KERNEL==\"uinput\", GROUP=\"input\", MODE=\"0660\", OPTIONS+=\"static_node=uinput\"' | sudo tee /etc/udev/rules.d/80-uinput.rules"
        note "  sudo usermod -aG input \"\$USER\""
        note "  sudo udevadm control --reload-rules && sudo udevadm trigger"
        note "  # then log out and back in"
    else
        note "/dev/uinput is writable"
    fi
fi

# ------------------------------------------------------------- 6. global shortcut

if is_kde; then
    step "Registering the KDE global shortcut ($HOTKEY)"

    install_desktop "$REPO_DIR/packaging/$SHORTCUT_ID" "$APP_DIR/$SHORTCUT_ID"
    note "launcher:     $APP_DIR/$SHORTCUT_ID"

    kwriteconfig=$(command -v kwriteconfig6 || command -v kwriteconfig5 || true)
    if [ -n "$kwriteconfig" ]; then
        # Nested group: [services][net.local.charpaste.desktop]
        "$kwriteconfig" --file kglobalshortcutsrc \
                        --group services \
                        --group "$SHORTCUT_ID" \
                        --key _launch "$HOTKEY"
        note "bound $HOTKEY -> charpaste --trigger"
        # kglobalaccel has no D-Bus config-reload method, so the binding is
        # picked up when the session next starts.
        warn "log out and back in to activate the shortcut"
    else
        warn "kwriteconfig not found — bind it by hand:"
        note "System Settings > Shortcuts > Add > Command: charpaste --trigger"
    fi
elif is_wayland; then
    step "Global shortcut"
    warn "not KDE — bind your desktop's custom shortcut to: charpaste --trigger"
    note "(on Wayland the built-in hotkey needs you in the 'input' group)"
fi

# ------------------------------------------------------------------------ summary

step "Done"
note "start it now with:   setsid charpaste >/dev/null 2>&1 < /dev/null &"
note "or just log out and back in — autostart handles it"
note "config lives at:     ~/.config/charpaste/config.json"
