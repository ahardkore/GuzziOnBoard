"""Console entry point: ``guzzionboard`` and ``python -m guzzionboard``.

    guzzionboard [--host H] [--port N] [--no-record]

Only the standard library is needed for simulator mode. Hardware transports
need the optional extras (``pip install -e '.[hardware]'``). The server binds
locally by default: this is a tool for one laptop and one motorcycle.
"""
from __future__ import annotations

import argparse
import sys


def build_parser() -> argparse.ArgumentParser:
    from . import __version__

    parser = argparse.ArgumentParser(
        prog="guzzionboard",
        description=(
            "GuzziOnBoard - a multi-brand motorcycle diagnostics, calibration "
            "research and workshop workstation. Coverage varies by ECU and operation."
        ),
        epilog=(
            "quick start:\n"
            "  guzzionboard                 start the workstation (simulator mode needs no hardware)\n"
            "  guzzionboard --port 8080     same, on another port\n"
            "  guzzionboard --desktop       same, in a native window (pywebview)\n"
            "  guzzionboard --selftest      check this installation and exit\n"
            "\n"
            "then open http://127.0.0.1:8000, pick a motorcycle in the Garage\n"
            "and connect. For a real bike:\n"
            "  pip install -e '.[hardware]'   pyserial (K-Line) + python-can (CAN)\n"
            "\n"
            "runs the tests with:  pip install -e '.[dev]' && pytest"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--host", default="127.0.0.1",
        help="bind address (default: 127.0.0.1 - keep it local)",
    )
    parser.add_argument(
        "--port", type=int, default=8000,
        help="port to listen on (default: 8000)",
    )
    parser.add_argument(
        "--no-record", action="store_true",
        help="do not write session logs to ~/.guzzionboard/sessions",
    )
    parser.add_argument(
        "--desktop", action="store_true",
        help="open the workstation in a native desktop window instead of a browser "
             "(see guzzionboard-desktop for window options)",
    )
    parser.add_argument(
        "--selftest", action="store_true",
        help="check this installation (catalog, UI, API, worker) and exit",
    )
    parser.add_argument(
        "--version", action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.desktop or args.selftest:
        # Both live in the desktop module, which owns the window, the export
        # folder and the installation checks. Imported here so the browser
        # entry point stays free of them.
        from .desktop import main as desktop_main

        forwarded = [f"--host={args.host}", f"--port={args.port}"]
        if args.no_record:
            forwarded.append("--no-record")
        if args.selftest:
            forwarded = ["--selftest", f"--host={args.host}"]
        return desktop_main(forwarded)

    from .server import serve

    serve(host=args.host, port=args.port, record=not args.no_record)
    return 0


if __name__ == "__main__":
    sys.exit(main())
