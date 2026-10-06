"""Registry for physical ECU/dyno evidence manifests.

Manifests are evidence indexes, not self-proving certifications.  No records are
bundled.  Operators place completed JSON files in ``~/.guzzionboard/validation``
and retain their hashed captures/reports at the paths named by each record.
"""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import re

VALIDATION_DIR = Path.home() / ".guzzionboard" / "validation"
SCHEMA = "guzzionboard.physical-validation/v1"


class PhysicalValidationError(ValueError):
    pass


def _required_text(container: dict, key: str, prefix: str = "") -> str:
    value = str(container.get(key) or "").strip()
    if not value:
        raise PhysicalValidationError(f"{prefix}{key} is required")
    return value


def _sha(value: object, label: str) -> str:
    result = str(value or "").lower()
    if not re.fullmatch(r"[0-9a-f]{64}", result):
        raise PhysicalValidationError(f"{label} must be a 64-hex SHA-256")
    return result


def validate_manifest(value: dict, *, path: str = "") -> dict:
    if not isinstance(value, dict) or value.get("schema") != SCHEMA:
        raise PhysicalValidationError(f"schema must be {SCHEMA!r}")
    result = str(value.get("result") or "")
    kind = str(value.get("kind") or "")
    if kind not in ("real-ecu", "dyno"):
        raise PhysicalValidationError("kind must be real-ecu or dyno")
    if result not in ("pass", "fail", "incomplete"):
        raise PhysicalValidationError("result must be pass, fail, or incomplete")
    record_id = _required_text(value, "id")
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,79}", record_id):
        raise PhysicalValidationError("id must be a lowercase record identifier")
    performed_at = _required_text(value, "performed_at")
    try:
        datetime.fromisoformat(performed_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PhysicalValidationError("performed_at must be an ISO date-time") from exc
    for section, keys in {
        "operator": ("name", "organization"),
        "motorcycle": ("make", "model", "year", "configuration"),
        "ecu": ("family", "hardware", "software"),
    }.items():
        body = value.get(section)
        if not isinstance(body, dict):
            raise PhysicalValidationError(f"{section} is required")
        for key in keys:
            _required_text(body, key, f"{section}.")
    try:
        year = int(value["motorcycle"]["year"])
    except (TypeError, ValueError) as exc:
        raise PhysicalValidationError("motorcycle.year must be an integer") from exc
    if not 1900 <= year <= 2200:
        raise PhysicalValidationError("motorcycle.year is outside 1900..2200")
    if len(str(value["motorcycle"]["configuration"]).strip()) < 10:
        raise PhysicalValidationError("motorcycle.configuration needs specific detail")
    if kind == "dyno":
        for section in ("build", "dyno"):
            if not isinstance(value.get(section), dict):
                raise PhysicalValidationError(f"dyno records require {section}")
        for key in ("make", "model", "serial", "calibration_date", "correction_standard"):
            _required_text(value["dyno"], key, "dyno.")
        try:
            datetime.strptime(str(value["dyno"]["calibration_date"]), "%Y-%m-%d")
        except ValueError as exc:
            raise PhysicalValidationError("dyno.calibration_date must be YYYY-MM-DD") from exc
    if isinstance(value.get("build"), dict):
        for key in ("source_sha256", "output_sha256", "xdf_sha256", "plan_sha256"):
            _sha(value["build"].get(key), f"build.{key}")
    artifacts = value.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise PhysicalValidationError("at least one hashed artifact is required")
    normalized_artifacts = []
    missing, mismatched = 0, 0
    for index, artifact in enumerate(artifacts):
        if not isinstance(artifact, dict):
            raise PhysicalValidationError(f"artifact {index} must be an object")
        artifact_kind = str(artifact.get("kind") or "")
        if artifact_kind not in (
            "session", "ecu-readback", "scope", "log", "dyno-run",
            "photo", "report", "other",
        ):
            raise PhysicalValidationError(f"artifact {index} has an invalid kind")
        artifact_path = Path(
            _required_text(artifact, "path", f"artifact {index}.")
        ).expanduser()
        if not artifact_path.is_absolute() and path:
            artifact_path = Path(path).expanduser().parent / artifact_path
        expected = _sha(artifact.get("sha256"), f"artifact {index} sha256")
        status = "not-locally-available"
        if artifact_path.is_file():
            try:
                actual = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
                status = "verified" if actual == expected else "hash-mismatch"
            except OSError:
                status = "not-locally-available"
        if status == "not-locally-available": missing += 1
        if status == "hash-mismatch": mismatched += 1
        normalized_artifacts.append({**artifact, "path": str(artifact_path), "sha256": expected,
                                     "local_status": status})
    checks = value.get("checks")
    if not isinstance(checks, list) or not checks:
        raise PhysicalValidationError("at least one check result is required")
    for index, check in enumerate(checks):
        if not isinstance(check, dict) or check.get("status") not in ("pass", "fail", "incomplete"):
            raise PhysicalValidationError(f"check {index} has an invalid status")
        _required_text(check, "name", f"check {index}.")
        _required_text(check, "detail", f"check {index}.")
    if result == "pass" and any(check["status"] != "pass" for check in checks):
        raise PhysicalValidationError("a pass record cannot contain failed or incomplete checks")
    return {
        **value,
        "id": record_id,
        "artifacts": normalized_artifacts,
        "path": path,
        "artifact_summary": {
            "total": len(normalized_artifacts), "missing": missing, "hash_mismatch": mismatched,
            "verified": len(normalized_artifacts) - missing - mismatched,
        },
        "registry_status": (
            "evidence-index-locally-complete" if not missing and not mismatched
            else "evidence-index-incomplete"
        ),
        "endorsement": "operator-supplied-not-core-certified",
    }


def load_manifests(directory: str | Path = VALIDATION_DIR) -> tuple[list[dict], list[dict]]:
    root = Path(directory).expanduser()
    if not root.exists():
        return [], []
    records, errors, ids = [], [], set()
    for path in sorted(root.glob("*.json")):
        try:
            record = validate_manifest(json.loads(path.read_text()), path=str(path))
            if record["id"] in ids:
                raise PhysicalValidationError(f"duplicate validation id {record['id']!r}")
            ids.add(record["id"])
            record["manifest_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            records.append(record)
        except (OSError, json.JSONDecodeError, PhysicalValidationError) as exc:
            errors.append({"path": str(path), "error": str(exc)})
    return records, errors
