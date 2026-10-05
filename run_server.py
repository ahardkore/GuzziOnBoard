#!/usr/bin/env python3
"""Launch the GuzziOnBoard workstation (same as the ``guzzionboard`` command).

    python3 run_server.py [--host H] [--port N] [--no-record]

Only the standard library is required for simulator mode. Hardware transports
need the optional extras:  pip install -e '.[hardware]'
"""
from guzzionboard.__main__ import main

if __name__ == "__main__":
    main()
