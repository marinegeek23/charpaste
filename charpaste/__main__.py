"""Command-line entry point.

  charpaste              run the tray app
  charpaste --trigger    tell a running instance to type the clipboard now
  charpaste --quit       tell a running instance to exit
  charpaste --paste-now  type the clipboard once and exit (no tray)
  charpaste --config     print the config file path
"""

import argparse
import sys

from . import __version__, config


def main(argv=None):
    parser = argparse.ArgumentParser(prog="charpaste", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--trigger", action="store_true",
                        help="signal a running instance to type the clipboard (for global shortcuts)")
    parser.add_argument("--quit", action="store_true",
                        help="signal a running instance to exit")
    parser.add_argument("--paste-now", action="store_true",
                        help="type the clipboard once and exit, without a tray")
    parser.add_argument("--config", action="store_true",
                        help="print the config file path and exit")
    parser.add_argument("--version", action="version", version=f"charpaste {__version__}")
    args = parser.parse_args(argv)

    cfg = config.load()

    if args.config:
        print(config.config_path())
        return 0

    if args.trigger or args.quit:
        from . import ipc
        port = int(cfg.get("ipc_port", 49677))
        ok = ipc.send(port, "quit" if args.quit else "trigger")
        if not ok:
            print("charpaste: no running instance found", file=sys.stderr)
            return 1
        return 0

    if args.paste_now:
        import time
        from .backends import get_clipboard, type_text
        text = get_clipboard(cfg)
        if not text:
            print("charpaste: clipboard is empty", file=sys.stderr)
            return 1
        time.sleep(int(cfg.get("start_delay_ms", 300)) / 1000.0)
        type_text(text, cfg)
        return 0

    from . import app
    app.run(cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
