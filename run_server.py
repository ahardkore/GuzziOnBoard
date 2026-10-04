#!/usr/bin/env python3
"""Launch the GuzziOnBoard workstation.

    python3 run_server.py [--host H] [--port N] [--no-record]

Only the standard library is required for simulator mode. Hardware transports
need the optional extras:  pip install -e '.[hardware]'
"""
import argparse

from guzzionboard.server import serve


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1",
                        help="bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-record", action="store_true",
                        help="do not write session logs to disk")
    args = parser.parse_args()
    serve(args.host, args.port, record=not args.no_record)


if __name__ == "__main__":
    main()
