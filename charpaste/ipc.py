"""Tiny localhost IPC so `charpaste --trigger` / `--quit` can poke a running
instance. On Wayland this is the recommended trigger path: bind a KDE Custom
Global Shortcut to `charpaste --trigger`.
"""

import socket
import threading

HOST = "127.0.0.1"


def start_server(port, on_trigger, on_quit):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((HOST, port))
    srv.listen(8)

    def loop():
        while True:
            try:
                conn, _ = srv.accept()
            except OSError:
                break
            with conn:
                try:
                    data = conn.recv(64)
                except OSError:
                    continue
                if b"trigger" in data:
                    on_trigger()
                elif b"quit" in data:
                    on_quit()

    threading.Thread(target=loop, daemon=True).start()
    return srv


def send(port, command):
    """Send a command to a running instance. Returns True on success."""
    try:
        with socket.create_connection((HOST, port), timeout=2) as sock:
            sock.sendall(command.encode("ascii") + b"\n")
        return True
    except OSError:
        return False
