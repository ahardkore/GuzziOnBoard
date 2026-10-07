"""The base map vault: a guaranteed, permanent way back to stock.

A verified backup inside one session is not the same thing as *having a way
back*. Sessions end, temporary files get tidied away, and the one dump that
matters - the untouched calibration the bike arrived with - is usually the
first one taken and the easiest one to lose.

This module keeps that first verified read somewhere separate and durable:

* ``~/.guzzionboard/basemaps/`` holds a copy of the image plus its sidecar;
* ``index.json`` records which ECU it came from, the region, the SHA-256 and
  when it was taken;
* the first base map stored for an ECU is never silently overwritten -
  later verified backups are kept as additional restore points, the base
  map stays the original.

The write path consults :meth:`BaseMapVault.status` and refuses to flash an
ECU that has no intact base map on file (see ``programming.py``). "Intact"
is checked by re-hashing the file, not by trusting the index: a base map
that has been truncated, moved or edited is not a restore map.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import time
import threading
import uuid
from functools import wraps

from .storage import atomic_write
from dataclasses import dataclass
from pathlib import Path

#: Where base maps live. Deliberately not the working image directory.
DEFAULT_BASEMAP_DIR = Path.home() / ".guzzionboard" / "basemaps"

INDEX_NAME = "index.json"


class BaseMapError(Exception):
    """A base map could not be stored or could not be trusted."""


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ecu_key(ecu_id: str, hardware: str = "", region: str = "flash") -> str:
    """Identity of the thing a base map belongs to.

    The ECU profile id alone is not enough: the same family ships in
    several hardware variants, and a base map taken from an HW1xx ECU is
    not a restore map for an HW3xx one. The hardware string, when the
    session captured one, is part of the key.
    """
    parts = [str(ecu_id or "unknown").strip().lower()]
    hardware = "".join(str(hardware or "").split()).upper()
    if hardware:
        parts.append(hardware)
    parts.append(str(region or "flash").strip().lower())
    return "/".join(parts)


# All vault instances in the threaded workstation share the transaction lock.
_VAULT_LOCK = threading.RLock()


def _serialized(method):
    @wraps(method)
    def wrapped(*args, **kwargs):
        with _VAULT_LOCK:
            return method(*args, **kwargs)
    return wrapped


@dataclass
class BaseMapVault:
    """The on-disk store of base maps and extra restore points."""

    directory: Path = DEFAULT_BASEMAP_DIR

    def __post_init__(self) -> None:
        self.directory = Path(self.directory)

    # -- index -------------------------------------------------------------
    @property
    def index_path(self) -> Path:
        return self.directory / INDEX_NAME

    def _read_index(self) -> dict:
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as exc:
            raise BaseMapError(f"cannot read base map index: {exc}") from exc
        if not isinstance(data, dict) or any(not isinstance(v, dict) for v in data.values()):
            raise BaseMapError("invalid base map index; refusing to overwrite it")
        return data

    def _write_index(self, index: dict) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        atomic_write(self.index_path, json.dumps(index, indent=2, sort_keys=True).encode("utf-8"))

    # -- storing -----------------------------------------------------------
    @_serialized
    def store(
        self,
        *,
        ecu_id: str,
        hardware: str = "",
        region: str = "flash",
        source_path: str | Path,
        verified: bool = False,
        identity: dict | None = None,
        note: str = "",
        _replace: bool = False,
    ) -> dict:
        """Copy a verified image into the vault.

        The first one stored for an ECU becomes its base map. Later ones
        are kept as additional restore points; the base map itself is
        never replaced by this call (use :meth:`replace_base_map` if an
        operator really means to).
        """
        source = Path(source_path).expanduser()
        if not source.is_file():
            raise BaseMapError(f"no image at {source}")
        if not verified:
            raise BaseMapError(
                "only a verified backup (read twice, byte-identical) can be "
                "stored as a base map - an unverified read is not a restore map"
            )

        key = ecu_key(ecu_id, hardware, region)
        index = self._read_index()
        entry = index.get(key)
        digest = sha256_file(source)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        folder = self.directory / key.replace("/", "_")
        folder.mkdir(parents=True, exist_ok=True)

        is_base = entry is None or _replace
        # A unique suffix keeps repeated saves of identical bytes separate,
        # including their potentially different provenance sidecars.
        name = (
            f"{'basemap' if is_base else 'restorepoint'}-{stamp}-"
            f"{digest[:12]}-{uuid.uuid4().hex}.bin"
        )
        target = folder / name
        shutil.copy2(source, target)
        sidecar = source.with_suffix(source.suffix + ".json")
        if sidecar.is_file():
            shutil.copy2(sidecar, target.with_suffix(target.suffix + ".json"))

        if sha256_file(target) != digest:
            raise BaseMapError("source changed while copying; base map was not published")

        record = {
            "path": str(target),
            "sha256": digest,
            "bytes": target.stat().st_size,
            "saved_at": time.time(),
            "saved_at_text": time.strftime("%Y-%m-%d %H:%M:%S"),
            "region": region,
            "ecu_id": ecu_id,
            "hardware": hardware,
            "identity": identity or {},
            "note": note,
            "origin": str(source),
        }
        if is_base:
            points = list(entry.get("restore_points") or []) if entry else []
            if entry:
                previous = {k: v for k, v in entry.items() if k != "restore_points"}
                points.append(dict(previous, note="superseded base map"))
            index[key] = dict(record, restore_points=points[-10:])
        else:
            points = list(entry.get("restore_points") or [])
            points.append(record)
            entry["restore_points"] = points[-10:]
            index[key] = entry
        self._write_index(index)
        return dict(self.status(ecu_id, hardware, region), stored=record,
                    is_base_map=is_base)

    def replace_base_map(
        self, *, ecu_id: str, hardware: str = "", region: str = "flash",
        source_path: str | Path, verified: bool = False,
        identity: dict | None = None, note: str = "",
    ) -> dict:
        """Deliberately make a new image the base map for this ECU.

        The previous base map is kept as a restore point - nothing in this
        vault is ever deleted by the application.
        """
        return self.store(
            ecu_id=ecu_id, hardware=hardware, region=region,
            source_path=source_path, verified=verified, identity=identity,
            note=note or "operator-replaced base map", _replace=True,
        )

    # -- reading -----------------------------------------------------------
    def status(self, ecu_id: str, hardware: str = "",
               region: str = "flash") -> dict:
        """Is there an intact base map for this ECU?

        ``intact`` is computed by re-hashing the stored file, so a base map
        that was moved, truncated or edited reports as missing rather than
        as protection that is not there.
        """
        key = ecu_key(ecu_id, hardware, region)
        entry = self._read_index().get(key)
        base = {
            "key": key, "ecu_id": ecu_id, "hardware": hardware,
            "region": region, "directory": str(self.directory),
            "present": False, "intact": False, "restore_points": [],
        }
        if not entry:
            base["reason"] = (
                "no base map saved for this ECU yet - save one before any "
                "write is allowed"
            )
            return base
        path = Path(entry.get("path", ""))
        present = path.is_file()
        intact = False
        reason = ""
        if not present:
            reason = f"the saved base map is gone from {path}"
        else:
            try:
                intact = sha256_file(path) == entry.get("sha256")
            except OSError as exc:                       # pragma: no cover
                reason = f"cannot read the base map: {exc}"
            if present and not intact and not reason:
                reason = (
                    f"{path} no longer matches the SHA-256 recorded when it "
                    "was saved - it is not a trustworthy restore map"
                )
        return dict(
            base,
            present=present,
            intact=intact,
            reason=reason,
            path=str(path),
            sha256=entry.get("sha256", ""),
            bytes=entry.get("bytes", 0),
            saved_at=entry.get("saved_at", 0),
            saved_at_text=entry.get("saved_at_text", ""),
            identity=entry.get("identity", {}),
            note=entry.get("note", ""),
            restore_points=entry.get("restore_points", []),
        )

    def all_entries(self) -> list[dict]:
        out = []
        for key, entry in sorted(self._read_index().items()):
            out.append(dict(entry, key=key))
        return out
