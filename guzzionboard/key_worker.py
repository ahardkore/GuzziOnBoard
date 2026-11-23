"""Isolated worker for user-supplied SecurityAccess key plugins.

A frozen build ships exactly one PyInstaller console helper
(``GuzziOnBoard-worker``), so key plugins and checksum plugins are served by
the same worker: :mod:`guzzionboard.checksum_worker` holds the containment
(fresh interpreter, resource limits, audit hook, 4 s timeout, one JSON request
and one JSON response) and the ``describe-key``/``key`` operations.

This file is the source-checkout entry point
(``python -I -S -B guzzionboard/key_worker.py``) and the documented home of the
key contract:

* a plugin defines ``ECU_ID``, ``NAME``, optional ``VERIFIED``/``NOTE`` and
  ``def key(seed: bytes) -> bytes``;
* the seed is 1 to 8 bytes and the answer at most 16 bytes, both hex-encoded
  in the request and the response;
* nothing else crosses the boundary.

``-I`` isolates the interpreter, so the sibling module is loaded by path rather
than by import. Keeping one worker implementation matters: two copies of an
audit hook drift, and the copy nobody runs is the one with the hole.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

_WORKER = Path(__file__).resolve().with_name("checksum_worker.py")


def _load_worker():
    spec = importlib.util.spec_from_file_location("guzzionboard_worker", _WORKER)
    if spec is None or spec.loader is None:      # pragma: no cover - broken build
        raise SystemExit("this build has no isolated plugin worker")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


if __name__ == "__main__":
    if not os.access(_WORKER, os.R_OK):          # pragma: no cover - broken build
        raise SystemExit("this build has no isolated plugin worker")
    raise SystemExit(_load_worker().main())
