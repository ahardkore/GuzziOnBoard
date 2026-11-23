"""Session recording.

Every session writes a newline-delimited JSON file holding raw frames,
decoded samples, safety decisions and operator actions. Two reasons:

1. Provenance. A decoded value is only trustworthy if the bytes behind it were
   kept, so each sample records the identifier and the raw bytes next to the
   engineering value.
2. Replay. A recorded session can be played back through the exact same
   protocol stack, which is how a decoder gets fixed without owning the bike
   that produced the fault.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from . import resources

DEFAULT_DIR = resources.data_root() / "sessions"

#: Keep at most this many recorded sessions, and none older than the age cap.
#: Sessions are large (raw frames per sample), so an unbounded directory is a
#: disk-exhaustion bug rather than a convenience.
MAX_SESSIONS = 200
MAX_SESSION_AGE_DAYS = 90


@dataclass
class SessionLog:
    """Append-only JSONL recorder."""

    directory: Path = field(default_factory=lambda: DEFAULT_DIR)
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    meta: dict = field(default_factory=dict)
    enabled: bool = True
    #: Keep the last N events in memory for the UI without re-reading the file.
    ring_size: int = 2000

    _handle: object = field(default=None, init=False, repr=False)
    _recent: list[dict] = field(default_factory=list, init=False, repr=False)
    _counts: dict = field(default_factory=dict, init=False, repr=False)
    #: Recording is called from the diagnostics thread, from job threads and
    #: from the HTTP handler; the handle, ring buffer and counts are shared
    #: mutable state and are guarded by this lock.
    _lock: threading.RLock = field(default_factory=threading.RLock,
                                   init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        self.started_at = time.time()
        if self.enabled:
            self.directory = Path(self.directory)
            self.directory.mkdir(parents=True, exist_ok=True)
            self._handle = self.path.open("a", encoding="utf-8")
            self.write("session_start", {"meta": self.meta, "id": self.session_id})
            self.prune()

    @property
    def path(self) -> Path:
        stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(self.started_at))
        return Path(self.directory) / f"{stamp}-{self.session_id}.jsonl"

    # -- writing ----------------------------------------------------------
    def write(self, kind: str, payload: dict) -> dict:
        event = {"t": round(time.time(), 4), "kind": kind, **payload}
        with self._lock:
            self._counts[kind] = self._counts.get(kind, 0) + 1
            self._recent.append(event)
            if len(self._recent) > self.ring_size:
                del self._recent[: len(self._recent) - self.ring_size]
            if self._handle is not None:
                self._handle.write(json.dumps(event, separators=(",", ":")) + "\n")
                self._handle.flush()
        return event

    def frame(self, direction: str, raw: bytes) -> None:
        self.write("frame", {"dir": direction, "hex": raw.hex(" ")})

    def sample(self, key: str, local_id: int, raw: bytes, value, unit: str = "") -> None:
        self.write(
            "sample",
            {
                "key": key,
                "lid": local_id,
                "raw": raw.hex(),
                "value": value,
                "unit": unit,
            },
        )

    def action(self, name: str, detail: dict | None = None) -> None:
        self.write("action", {"name": name, "detail": detail or {}})

    def decision(self, decision_dict: dict) -> None:
        self.write("safety", decision_dict)

    def error(self, where: str, message: str) -> None:
        self.write("error", {"where": where, "message": message})

    def close(self) -> None:
        if self._handle is not None:
            with self._lock:
                self.write("session_end", {"counts": dict(self._counts)})
                self._handle.close()
                self._handle = None

    # -- retention --------------------------------------------------------
    def prune(self, directory: str | Path | None = None, *,
              keep: int = MAX_SESSIONS,
              max_age_days: float = MAX_SESSION_AGE_DAYS) -> list[Path]:
        """Delete old session files; never the one being recorded here.

        Returns the paths removed. Called at session start so a long-running
        install cannot fill the disk with logs nothing ever expires.
        """
        target = Path(directory) if directory is not None else Path(self.directory)
        if not target.is_dir():
            return []
        keep_path = self.path.resolve() if self.enabled else None
        cutoff = time.time() - max_age_days * 86400
        removed: list[Path] = []
        files = sorted(target.glob("*.jsonl"), key=lambda p: p.stat().st_mtime,
                       reverse=True)
        for index, path in enumerate(files):
            if keep_path is not None and path.resolve() == keep_path:
                continue
            try:
                too_old = path.stat().st_mtime < cutoff
            except OSError:
                continue
            if index < keep and not too_old:
                continue
            try:
                path.unlink()
            except OSError:
                continue
            removed.append(path)
        return removed

    # -- reading ----------------------------------------------------------
    @property
    def recent(self) -> list[dict]:
        with self._lock:
            return list(self._recent)

    @property
    def counts(self) -> dict:
        with self._lock:
            return dict(self._counts)

    def summary(self) -> dict:
        return {
            "id": self.session_id,
            "path": str(self.path) if self.enabled else "",
            "started_at": self.started_at,
            "duration_s": round(time.time() - self.started_at, 1),
            "counts": self.counts,
            "meta": self.meta,
        }

    @staticmethod
    def read(path: str | Path) -> Iterator[dict]:
        with Path(path).open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    yield json.loads(line)

    @staticmethod
    def list_sessions(directory: str | Path = DEFAULT_DIR) -> list[dict]:
        directory = Path(directory)
        if not directory.is_dir():
            return []
        found = []
        for path in sorted(directory.glob("*.jsonl"), reverse=True):
            meta: dict = {}
            counts: dict = {}
            samples = 0
            try:
                for event in SessionLog.read(path):
                    if event["kind"] == "session_start":
                        meta = event.get("meta", {})
                    elif event["kind"] == "session_end":
                        counts = event.get("counts", {})
                    elif event["kind"] == "sample":
                        samples += 1
            except (OSError, json.JSONDecodeError):
                continue
            found.append(
                {
                    "path": str(path),
                    "name": path.name,
                    "size": path.stat().st_size,
                    "modified": path.stat().st_mtime,
                    "meta": meta,
                    "counts": counts or {"sample": samples},
                }
            )
        return found


class NullSessionLog(SessionLog):
    """Recorder that keeps a ring buffer but never touches the disk."""

    def __init__(self, **kw):
        super().__init__(enabled=False, **kw)
