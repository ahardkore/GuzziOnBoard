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
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

DEFAULT_DIR = Path.home() / ".guzzionboard" / "sessions"


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

    def __post_init__(self) -> None:
        self.started_at = time.time()
        if self.enabled:
            self.directory = Path(self.directory)
            self.directory.mkdir(parents=True, exist_ok=True)
            self._handle = self.path.open("a", encoding="utf-8")
            self.write("session_start", {"meta": self.meta, "id": self.session_id})

    @property
    def path(self) -> Path:
        stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(self.started_at))
        return Path(self.directory) / f"{stamp}-{self.session_id}.jsonl"

    # -- writing ----------------------------------------------------------
    def write(self, kind: str, payload: dict) -> dict:
        event = {"t": round(time.time(), 4), "kind": kind, **payload}
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
            self.write("session_end", {"counts": self._counts})
            self._handle.close()
            self._handle = None

    # -- reading ----------------------------------------------------------
    @property
    def recent(self) -> list[dict]:
        return list(self._recent)

    @property
    def counts(self) -> dict:
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
