"""Persistent workstation preferences, save-location presets, and load-location presets.

Preferences live in ``<data_root>/preferences.json`` so both the native desktop
shell and local browser sessions share the same user settings, while remaining
strictly local to this machine and isolated under ``GOB_HOME`` in tests.
"""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path

from . import resources
from .storage import atomic_write

SCHEMA = "guzzionboard.preferences/v1"
SCHEMA_VERSION = SCHEMA
PreferencesError = ValueError
THEMES = ("dark", "light", "system")
DENSITIES = ("comfortable", "compact")
TEMP_UNITS = ("C", "F")
SESSION_MODES = ("simulator", "hardware")
LOAD_KINDS = ("any", "images", "basemaps", "xdfs", "logs")
LOAD_KIND_EXTS: dict[str, set[str] | None] = {
    "any": None,
    "images": {".bin", ".rom", ".hex", ".eep", ".epr"},
    "basemaps": {".bin", ".rom", ".json"},
    "xdfs": {".xdf"},
    "logs": {".csv", ".log", ".txt", ".json", ".zdl", ".dif"},
}
POLL_INTERVALS = (150, 250, 500, 1000, 2000)

MAX_PRESETS = 25
MAX_NAME_LEN = 80
MAX_DESC_LEN = 200
MAX_PATH_LEN = 1024
MAX_SAVE_BYTES = 4 * 1024 * 1024
MAX_BROWSE_FILES = 200

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")
_lock = threading.Lock()


def preferences_file() -> Path:
    return resources.data_root() / "preferences.json"


def _clean_text(value: object, *, field_name: str, max_len: int, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"'{field_name}' must be a string")
    if any(ord(ch) < 32 for ch in value):
        raise ValueError(f"'{field_name}' must not contain control characters")
    cleaned = value.strip()
    if not allow_empty and not cleaned:
        raise ValueError(f"'{field_name}' must not be empty")
    if len(cleaned) > max_len:
        raise ValueError(f"'{field_name}' exceeds {max_len} characters")
    return cleaned


def _clean_path(value: object, *, field_name: str = "path") -> str:
    raw = _clean_text(value, field_name=field_name, max_len=MAX_PATH_LEN)
    expanded = Path(raw).expanduser()
    return str(expanded.absolute())


def _clean_id(value: object, *, fallback_index: int = 0) -> str:
    if isinstance(value, str) and _ID_RE.match(value.strip()):
        return value.strip()
    slug = re.sub(r"[^a-z0-9_-]+", "-", str(value or "").strip().lower()).strip("-_")
    if not slug or not slug[0].isalnum():
        slug = f"preset-{fallback_index + 1}"
    slug = slug[:48]
    if not _ID_RE.match(slug):
        raise ValueError("invalid preset id")
    return slug


def default_save_presets(default_export_dir: Path | str | None = None) -> list[dict]:
    exports = (
        Path(default_export_dir).expanduser().resolve()
        if default_export_dir
        else resources.default_export_dir()
    )
    return [
        {
            "id": "exports",
            "name": "Default Exports",
            "path": str(exports),
            "description": "Primary folder for exported CSVs, reports, and project files.",
            "builtin": True,
        },
        {
            "id": "reports",
            "name": "Service Reports",
            "path": str((resources.data_root() / "reports").absolute()),
            "description": "Dedicated folder for diagnostic and service report snapshots.",
            "builtin": True,
        },
        {
            "id": "images",
            "name": "ECU Images & Backups",
            "path": str((resources.data_root() / "images").absolute()),
            "description": "Workstation ECU binary reads and tuned calibration outputs.",
            "builtin": True,
        },
        {
            "id": "sessions",
            "name": "Session Captures",
            "path": str(resources.sessions_dir().absolute()),
            "description": "Recorded diagnostic sweeps and exported telemetry logs.",
            "builtin": True,
        },
    ]


def default_load_presets(default_export_dir: Path | str | None = None) -> list[dict]:
    downloads = (
        Path(default_export_dir).expanduser().resolve()
        if default_export_dir
        else resources.default_export_dir()
    )
    return [
        {
            "id": "images",
            "name": "ECU Images & BINs",
            "path": str((resources.data_root() / "images").absolute()),
            "kind": "images",
            "description": "Saved ECU flash/EEPROM dumps and candidate calibration files.",
            "builtin": True,
        },
        {
            "id": "basemaps",
            "name": "Protected Base Maps",
            "path": str((resources.data_root() / "basemaps").absolute()),
            "kind": "basemaps",
            "description": "Verified two-pass stock base map backups.",
            "builtin": True,
        },
        {
            "id": "xdfs",
            "name": "Custom XDF Definitions",
            "path": str((resources.data_root() / "xdfs").absolute()),
            "kind": "xdfs",
            "description": "User-supplied TunerPro .xdf definition files.",
            "builtin": True,
        },
        {
            "id": "sessions",
            "name": "Session & Bus Logs",
            "path": str(resources.sessions_dir().absolute()),
            "kind": "logs",
            "description": "Recorded session logs, CAN captures, and K-Line traces.",
            "builtin": True,
        },
        {
            "id": "downloads",
            "name": "Downloads / Exports",
            "path": str(downloads),
            "kind": "any",
            "description": "Downloaded images, logs, manuals, and map projects.",
            "builtin": True,
        },
    ]


def defaults(default_export_dir: Path | str | None = None) -> dict:
    save_list = default_save_presets(default_export_dir)
    load_list = default_load_presets(default_export_dir)
    return _enrich({
        "schema": SCHEMA,
        "theme": "dark",
        "layout_density": "comfortable",
        "temp_unit": "C",
        "poll_interval_ms": 250,
        "confirm_before_exit": True,
        "default_session_mode": "simulator",
        "save_presets": save_list,
        "active_save_preset": "exports",
        "load_presets": load_list,
        "active_load_preset": "images",
    })


def _validate_preset_list(raw_list: object, *, is_load: bool) -> list[dict]:
    label = "load_presets" if is_load else "save_presets"
    if not isinstance(raw_list, list) or not raw_list:
        raise ValueError(f"'{label}' must be a non-empty list")
    if len(raw_list) > MAX_PRESETS:
        raise ValueError(f"'{label}' supports at most {MAX_PRESETS} presets")
    out: list[dict] = []
    seen: set[str] = set()
    for idx, item in enumerate(raw_list):
        if not isinstance(item, dict):
            raise ValueError(f"each entry in '{label}' must be an object")
        pid = _clean_id(item.get("id") or item.get("name"), fallback_index=idx)
        if pid in seen:
            raise ValueError(f"duplicate preset id {pid!r} in '{label}'")
        seen.add(pid)
        entry = {
            "id": pid,
            "name": _clean_text(item.get("name"), field_name=f"{label}[{idx}].name", max_len=MAX_NAME_LEN),
            "path": _clean_path(item.get("path"), field_name=f"{label}[{idx}].path"),
            "description": _clean_text(
                item.get("description", ""),
                field_name=f"{label}[{idx}].description",
                max_len=MAX_DESC_LEN,
                allow_empty=True,
            ),
            "builtin": bool(item.get("builtin", False)),
        }
        if is_load:
            kind = str(item.get("kind") or "any")
            if kind not in LOAD_KINDS:
                raise ValueError(f"load preset kind must be one of {', '.join(LOAD_KINDS)}")
            entry["kind"] = kind
        out.append(entry)
    return out


def _enrich(data: dict) -> dict:
    save_presets = data.get("save_presets") or []
    load_presets = data.get("load_presets") or []
    active_save = data.get("active_save_preset")
    active_load = data.get("active_load_preset")
    save_ids = {p["id"]: p for p in save_presets}
    load_ids = {p["id"]: p for p in load_presets}
    if active_save not in save_ids and save_presets:
        active_save = save_presets[0]["id"]
    if active_load not in load_ids and load_presets:
        active_load = load_presets[0]["id"]
    data["active_save_preset"] = active_save
    data["active_load_preset"] = active_load
    data["active_save_dir"] = save_ids[active_save]["path"] if active_save in save_ids else ""
    data["active_load_dir"] = load_ids[active_load]["path"] if active_load in load_ids else ""
    return data


def load(default_export_dir: Path | str | None = None) -> dict:
    base = defaults(default_export_dir)
    path = preferences_file()
    with _lock:
        if not path.is_file():
            return base
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return base
    if not isinstance(stored, dict):
        return base
    try:
        return _merge(base, stored, strict=False)
    except ValueError:
        return base


def _merge(current: dict, patch: dict, *, strict: bool) -> dict:
    merged = {
        "schema": SCHEMA,
        "theme": current["theme"],
        "layout_density": current["layout_density"],
        "temp_unit": current["temp_unit"],
        "poll_interval_ms": current["poll_interval_ms"],
        "confirm_before_exit": current["confirm_before_exit"],
        "default_session_mode": current["default_session_mode"],
        "save_presets": [dict(p) for p in current["save_presets"]],
        "active_save_preset": current["active_save_preset"],
        "load_presets": [dict(p) for p in current["load_presets"]],
        "active_load_preset": current["active_load_preset"],
    }

    if "theme" in patch:
        val = patch["theme"]
        if val not in THEMES:
            if strict:
                raise ValueError(f"'theme' must be one of {', '.join(THEMES)}")
        else:
            merged["theme"] = val

    if "layout_density" in patch:
        val = patch["layout_density"]
        if val not in DENSITIES:
            if strict:
                raise ValueError(f"'layout_density' must be one of {', '.join(DENSITIES)}")
        else:
            merged["layout_density"] = val

    if "temp_unit" in patch:
        val = patch["temp_unit"]
        if val not in TEMP_UNITS:
            if strict:
                raise ValueError(f"'temp_unit' must be one of {', '.join(TEMP_UNITS)}")
        else:
            merged["temp_unit"] = val

    if "poll_interval_ms" in patch:
        val = patch["poll_interval_ms"]
        if isinstance(val, bool) or not isinstance(val, int) or val < 100 or val > 5000:
            if strict:
                raise ValueError("'poll_interval_ms' must be an integer between 100 and 5000")
        else:
            merged["poll_interval_ms"] = val

    if "confirm_before_exit" in patch:
        val = patch["confirm_before_exit"]
        if not isinstance(val, bool):
            if strict:
                raise ValueError("'confirm_before_exit' must be true or false")
        else:
            merged["confirm_before_exit"] = val

    if "default_session_mode" in patch:
        val = patch["default_session_mode"]
        if val not in SESSION_MODES:
            if strict:
                raise ValueError(f"'default_session_mode' must be one of {', '.join(SESSION_MODES)}")
        else:
            merged["default_session_mode"] = val

    if "save_presets" in patch:
        merged["save_presets"] = _validate_preset_list(patch["save_presets"], is_load=False)

    if "load_presets" in patch:
        merged["load_presets"] = _validate_preset_list(patch["load_presets"], is_load=True)

    if "active_save_preset" in patch:
        val = patch["active_save_preset"]
        valid_ids = {p["id"] for p in merged["save_presets"]}
        if not isinstance(val, str) or val not in valid_ids:
            if strict:
                raise ValueError(f"unknown save preset {val!r}")
        else:
            merged["active_save_preset"] = val

    if "active_load_preset" in patch:
        val = patch["active_load_preset"]
        valid_ids = {p["id"] for p in merged["load_presets"]}
        if not isinstance(val, str) or val not in valid_ids:
            if strict:
                raise ValueError(f"unknown load preset {val!r}")
        else:
            merged["active_load_preset"] = val

    return _enrich(merged)


def update(patch: dict, *, default_export_dir: Path | str | None = None) -> dict:
    if not isinstance(patch, dict):
        raise ValueError("preferences payload must be an object")
    if patch.get("reset") is True:
        fresh = defaults(default_export_dir)
        to_store = {k: v for k, v in fresh.items() if k not in ("active_save_dir", "active_load_dir")}
        with _lock:
            atomic_write(preferences_file(), (json.dumps(to_store, indent=2) + "\n").encode("utf-8"))
        return fresh

    current = load(default_export_dir)
    merged = _merge(current, patch, strict=True)
    to_store = {k: v for k, v in merged.items() if k not in ("active_save_dir", "active_load_dir")}
    with _lock:
        atomic_write(preferences_file(), (json.dumps(to_store, indent=2) + "\n").encode("utf-8"))
    return merged


def reset(*, default_export_dir: Path | str | None = None) -> dict:
    return update({"reset": True}, default_export_dir=default_export_dir)


def browse_preset(
    scope: str,
    preset_id: str | None = None,
    *,
    default_export_dir: Path | str | None = None,
) -> dict:
    if scope not in ("load", "save"):
        raise ValueError("'scope' must be 'load' or 'save'")
    prefs = load(default_export_dir)
    presets = prefs["load_presets"] if scope == "load" else prefs["save_presets"]
    chosen_id = preset_id or (prefs["active_load_preset"] if scope == "load" else prefs["active_save_preset"])
    preset = next((p for p in presets if p["id"] == chosen_id), None)
    if preset is None:
        raise ValueError(f"unknown {scope} preset {chosen_id!r}")
    allowed_exts = LOAD_KIND_EXTS.get(preset.get("kind", "any")) if scope == "load" else None
    directory = Path(preset["path"]).expanduser().absolute()
    files: list[dict] = []
    exists = directory.is_dir()
    if exists:
        entries = []
        try:
            for item in directory.iterdir():
                if item.name.startswith("."):
                    continue
                if allowed_exts is not None and item.suffix.lower() not in allowed_exts:
                    continue
                try:
                    st = item.stat()
                except OSError:
                    continue
                if not item.is_file():
                    continue
                entries.append((st.st_mtime, item, st.st_size))
        except OSError:
            exists = False
        entries.sort(key=lambda row: (-row[0], row[1].name.lower()))
        for mtime, item, size in entries[:MAX_BROWSE_FILES]:
            files.append({
                "name": item.name,
                "path": str(item),
                "size": size,
                "modified": mtime,
                "ext": item.suffix.lower(),
            })
    return {
        "scope": scope,
        "preset": preset,
        "path": str(directory),
        "exists": exists,
        "files": files,
    }


def save_to_preset(
    name: str,
    content: str,
    *,
    preset_id: str | None = None,
    default_export_dir: Path | str | None = None,
) -> dict:
    clean_name = _clean_text(name, field_name="name", max_len=160)
    if not isinstance(content, str):
        raise ValueError("'content' must be a string")
    encoded = content.encode("utf-8")
    if len(encoded) > MAX_SAVE_BYTES:
        raise ValueError("file content exceeds 4 MiB limit")
    prefs = load(default_export_dir)
    chosen_id = preset_id or prefs["active_save_preset"]
    preset = next((p for p in prefs["save_presets"] if p["id"] == chosen_id), None)
    if preset is None:
        raise ValueError(f"unknown save preset {chosen_id!r}")
    target_dir = Path(preset["path"]).expanduser().absolute()
    path = resources.unique_path(target_dir, clean_name)
    atomic_write(path, encoded)
    return {
        "ok": True,
        "preset_id": preset["id"],
        "preset_name": preset["name"],
        "name": path.name,
        "path": str(path),
        "dir": str(path.parent),
        "bytes": len(encoded),
    }
