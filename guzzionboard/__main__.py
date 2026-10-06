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
            "GuzziOnBoard - a safety-first diagnostic workstation for the "
            "Magneti Marelli ECUs of Moto Guzzi motorcycles (and the same "
            "ECUs in Ducatis and Aprilias)."
        ),
        epilog=(
            "quick start:\n"
            "  guzzionboard                 start the workstation (simulator mode needs no hardware)\n"
            "  guzzionboard --port 8080     same, on another port\n"
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
        "--version", action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    from .server import serve

    serve(host=args.host, port=args.port, record=not args.no_record)
    return 0


if __name__ == "__main__":
    sys.exit(main())
