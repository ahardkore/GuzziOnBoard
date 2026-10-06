"""Validated registry for user/community recommendation packages.

The project intentionally bundles no tune values.  JSON packages placed in
``~/.guzzionboard/recommendations`` are treated as unendorsed third-party
claims, validated for reproducibility and shown for review.  Their edits still
have to pass source locks, fitment, preview, evidence, and liability gates.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
from urllib.parse import urlparse

PACKAGE_DIR = Path.home() / ".guzzionboard" / "recommendations"
SCHEMA = "guzzionboard.recommendation/v1"


class RecommendationPackageError(ValueError):
    """A package is malformed or lacks traceable provenance."""


def _text(value, label: str, minimum: int = 1) -> str:
    result = str(value or "").strip()
    if len(result) < minimum:
        raise RecommendationPackageError(f"{label} is required")
    return result


def _url(value, label: str) -> str:
    result = _text(value, label)
    parsed = urlparse(result)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise RecommendationPackageError(f"{label} must be an inspectable HTTP(S) URL")
    return result


def validate_package(value: dict, *, path: str = "") -> dict:
    if not isinstance(value, dict) or value.get("schema") != SCHEMA:
        raise RecommendationPackageError(f"schema must be {SCHEMA!r}")
    package_id = _text(value.get("id"), "id")
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,79}", package_id):
        raise RecommendationPackageError("id must be a lowercase package identifier")
    version = _text(value.get("version"), "version")
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?", version):
        raise RecommendationPackageError("version must use semantic version syntax")

    maintainers = value.get("maintainers")
    if not isinstance(maintainers, list) or not maintainers:
        raise RecommendationPackageError("at least one maintainer is required")
    normalized_maintainers = []
    for index, maintainer in enumerate(maintainers):
        if not isinstance(maintainer, dict):
            raise RecommendationPackageError(f"maintainer {index} must be an object")
        normalized_maintainers.append({
            "name": _text(maintainer.get("name"), f"maintainer {index} name"),
            "url": _url(maintainer.get("url"), f"maintainer {index} URL"),
        })

    fitment = value.get("fitment")
    if not isinstance(fitment, dict):
        raise RecommendationPackageError("fitment is required")
    normalized_fitment = {
        "ecu_family": _text(fitment.get("ecu_family"), "fitment ECU family"),
        "motorcycle": _text(fitment.get("motorcycle"), "fitment motorcycle"),
        "hardware": _text(fitment.get("hardware"), "fitment hardware"),
        "configuration": _text(
            fitment.get("configuration"), "fitment configuration", minimum=10
        ),
    }

    definition = value.get("xdf")
    if not isinstance(definition, dict):
        raise RecommendationPackageError("xdf identity is required")
    filename = _text(definition.get("filename"), "xdf filename")
    digest = _text(definition.get("sha256"), "xdf SHA-256").lower()
    if not filename.lower().endswith(".xdf") or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise RecommendationPackageError("xdf needs a .xdf filename and 64-hex SHA-256")

    evidence = value.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        raise RecommendationPackageError("at least one evidence source is required")
    normalized_evidence = []
    for index, source in enumerate(evidence):
        if not isinstance(source, dict):
            raise RecommendationPackageError(f"evidence {index} must be an object")
        source_digest = str(source.get("sha256") or "").strip().lower()
        if source_digest and not re.fullmatch(r"[0-9a-f]{64}", source_digest):
            raise RecommendationPackageError(f"evidence {index} SHA-256 is invalid")
        normalized_evidence.append({
            "title": _text(source.get("title"), f"evidence {index} title", 3),
            "url": _url(source.get("url"), f"evidence {index} URL"),
            "rationale": _text(source.get("rationale"), f"evidence {index} rationale", 10),
            "sha256": source_digest,
        })

    changes = value.get("changes")
    if not isinstance(changes, list) or not changes:
        raise RecommendationPackageError("at least one explicit change is required")
    if len(changes) > 4096:
        raise RecommendationPackageError("a package is limited to 4096 changes")
    normalized_changes = []
    identities = set()
    for index, change in enumerate(changes):
        if not isinstance(change, dict):
            raise RecommendationPackageError(f"change {index} must be an object")
        kind = str(change.get("kind") or "").lower()
        if kind not in ("table", "constant", "axis"):
            raise RecommendationPackageError(f"change {index} has an invalid kind")
        item_id = _text(change.get("id"), f"change {index} id")
        try:
            raw_value = change["expected_raw"]
            expected_raw = int(raw_value)
            target = float(change["value"])
            if isinstance(raw_value, bool) or expected_raw != float(raw_value) or not math.isfinite(target):
                raise ValueError
        except (KeyError, TypeError, ValueError) as exc:
            raise RecommendationPackageError(
                f"change {index} needs integer expected_raw and numeric value"
            ) from exc
        normalized = {
            "kind": kind, "id": item_id,
            "expected_raw": expected_raw, "value": target,
        }
        if kind == "table":
            try:
                row, col = int(change["row"]), int(change["col"])
            except (KeyError, TypeError, ValueError) as exc:
                raise RecommendationPackageError(
                    f"change {index} needs integer row and col"
                ) from exc
            if row < 0 or col < 0:
                raise RecommendationPackageError(f"change {index} row and col cannot be negative")
            normalized.update(row=row, col=col)
            identity = (kind, item_id, row, col)
        elif kind == "axis":
            axis = str(change.get("axis") or "").lower()
            if axis not in ("x", "y"):
                raise RecommendationPackageError(f"change {index} axis must be x or y")
            try:
                axis_index = int(change["index"])
            except (KeyError, TypeError, ValueError) as exc:
                raise RecommendationPackageError(
                    f"change {index} needs an integer axis index"
                ) from exc
            if axis_index < 0:
                raise RecommendationPackageError(f"change {index} axis index cannot be negative")
            normalized.update(axis=axis, index=axis_index)
            identity = (kind, item_id, axis, axis_index)
        else:
            identity = (kind, item_id)
        if identity in identities:
            raise RecommendationPackageError(f"change {index} duplicates another change")
        identities.add(identity)
        normalized_changes.append(normalized)

    validation = value.get("validation") or {}
    if not isinstance(validation, dict):
        raise RecommendationPackageError("validation must be an object")
    normalized_validation = {}
    for kind in ("real_ecu", "dyno"):
        record = validation.get(kind) or {"status": "not-provided", "evidence": []}
        if not isinstance(record, dict):
            raise RecommendationPackageError(f"validation.{kind} must be an object")
        status = str(record.get("status") or "not-provided")
        if status not in ("not-provided", "reported", "independently-reproduced"):
            raise RecommendationPackageError(f"validation.{kind}.status is invalid")
        links = record.get("evidence") or []
        if not isinstance(links, list):
            raise RecommendationPackageError(f"validation.{kind}.evidence must be a list")
        links = [_url(link, f"validation.{kind} evidence") for link in links]
        if status != "not-provided" and not links:
            raise RecommendationPackageError(
                f"validation.{kind} cannot claim {status!r} without evidence URLs"
            )
        normalized_validation[kind] = {"status": status, "evidence": links}

    normalized = {
        "schema": SCHEMA,
        "id": package_id,
        "version": version,
        "title": _text(value.get("title"), "title", 3),
        "license": _text(value.get("license"), "license"),
        "maintainers": normalized_maintainers,
        "fitment": normalized_fitment,
        "xdf": {"filename": filename, "sha256": digest},
        "evidence": normalized_evidence,
        "changes": normalized_changes,
        "validation": normalized_validation,
        "status": "user-supplied-unendorsed",
        "path": path,
    }
    return normalized


def load_packages(directory: str | Path = PACKAGE_DIR) -> tuple[list[dict], list[dict]]:
    root = Path(directory).expanduser()
    if not root.exists():
        return [], []
    packages, errors, identities = [], [], set()
    for path in sorted(root.glob("*.json")):
        try:
            raw = path.read_bytes()
            package = validate_package(json.loads(raw), path=str(path))
            identity = (package["id"], package["version"])
            if identity in identities:
                raise RecommendationPackageError(
                    f"duplicate package {package['id']} {package['version']}"
                )
            identities.add(identity)
            package["package_sha256"] = hashlib.sha256(raw).hexdigest()
            packages.append(package)
        except (OSError, json.JSONDecodeError, RecommendationPackageError, KeyError, ValueError) as exc:
            errors.append({"path": str(path), "error": str(exc)})
    return packages, errors
