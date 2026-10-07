"""Atomic single-file publication for persistent application records."""
from __future__ import annotations

import os
from pathlib import Path
import tempfile


def atomic_write(path: str | Path, data: bytes) -> None:
    """Publish complete bytes, leaving the old file intact on write failure.

    The temporary file is on the destination filesystem so replace is atomic.
    This is a single-file guarantee, not a multi-file transaction.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
