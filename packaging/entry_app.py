#!/usr/bin/env python3
"""Frozen entry point for the GuzziOnBoard desktop application.

Only PyInstaller runs this; the normal ways in are ``guzzionboard-desktop``,
``python -m guzzionboard.desktop``, or ``python -m guzzionboard --desktop``.

It exists because a frozen application needs a real script on disk to start
from, and because the frozen build has to say who it is before anything else
imports: the window is what decides whether a console exists.
"""
from __future__ import annotations

import multiprocessing
import sys


def main() -> int:
    # A frozen application that might ever start a helper process on Windows
    # must say where its own executable is, or the child re-runs the app.
    multiprocessing.freeze_support()

    from guzzionboard import resources
    from guzzionboard.desktop import main as desktop_main

    if resources.frozen():
        # A windowed build has no console: stdout/stderr go nowhere, so the
        # desktop module tees them into <data>/logs/desktop.log and shows a
        # message box for startup failures.
        pass
    return desktop_main(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
