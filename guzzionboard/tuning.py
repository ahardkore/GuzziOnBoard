"""Evidence-backed, non-destructive map builds.

Tuning an engine is not made safe by putting an editor in front of a binary.
This module therefore treats a tune as a reproducible build artifact:

* a source image (preferably the immutable base-map vault copy) is hashed;
* an exact XDF and explicit list of cell edits are recorded;
* every edit is tied to a recommendation source a reviewer can open;
* the operator repeats a liability acknowledgement for every build;
* a new image and sidecar are written -- the source is never overwritten.

It deliberately contains no suggested fuel, spark, lambda, limiter or idle
values.  Recommendations are motorcycle- and configuration-specific; shipping
an unattributed number would contradict the evidence-first safety model.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from urllib.parse import urlparse

from .checksums import ChecksumProvider, ChecksumUnavailable
from .firmware import FirmwareImage
from .maps import XdfError, XdfFile

TUNING_ACKNOWLEDGEMENT = (
    "I understand modified maps can damage the engine and accept responsibility"
)

DEFAULT_TUNING_DIR = Path.home() / ".guzzionboard" / "images"


class TuningError(ValueError):
    """A tuning build was unsafe, incomplete or not reproducible."""


def validate_recommendation(value: dict | None) -> dict:
    """Validate and normalise the evidence attached to a set of changes.

    A URL is not an endorsement.  It makes the recommendation inspectable;
    the build sidecar also keeps the title, rationale and optional content hash
    so another operator can decide whether it applies to this motorcycle.
    """
    if not isinstance(value, dict):
        raise TuningError("recommendation evidence is required")
    title = str(value.get("title") or value.get("source_title") or "").strip()
    url = str(value.get("url") or value.get("source_url") or "").strip()
    rationale = str(value.get("rationale") or "").strip()
    if len(title) < 3:
        raise TuningError("recommendation evidence needs a source title")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise TuningError(
            "recommendation evidence needs an inspectable http(s) source URL"
        )
    if len(rationale) < 10:
        raise TuningError(
            "explain why this recommendation applies to this motorcycle "
            "and configuration"
        )
    digest = str(value.get("sha256") or value.get("source_sha256") or "").strip().lower()
    if digest and not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise TuningError("recommendation source SHA-256 must be 64 hex characters")
    return {
        "title": title,
        "url": url,
        "publisher": str(value.get("publisher") or "").strip(),
        "published": str(value.get("published") or "").strip(),
        "retrieved": str(value.get("retrieved") or "").strip(),
        "sha256": digest,
        "rationale": rationale,
        "quote": str(value.get("quote") or "").strip(),
        "status": "traceable-not-endorsed",
    }


def _xdf_sha256(xdf: XdfFile) -> str:
    try:
        return hashlib.sha256(Path(xdf.path).read_bytes()).hexdigest()
    except OSError:
        # XDFs constructed by API users/tests still get a deterministic
        # structural fingerprint rather than a made-up file hash.
        body = "\n".join(
            [xdf.title, xdf.version]
            + [f"table:{x.item_id}:{x.math}" for x in xdf.tables]
            + [f"constant:{x.item_id}:{x.math}" for x in xdf.constants]
        ).encode("utf-8")
        return hashlib.sha256(body).hexdigest()


def prepare_tune(
    source: FirmwareImage,
    xdf: XdfFile,
    changes: list[dict],
    *,
    source_is_base_map: bool,
    address_base: int | None = None,
    checksum_provider: ChecksumProvider | None = None,
    recommendation_package: dict | None = None,
) -> tuple[bytes, dict]:
    """Encode edits once and produce the deterministic part of a build."""
    if xdf.checksums and checksum_provider is None:
        raise TuningError(
            "this XDF declares calibration checksum(s) "
            f"({', '.join(xdf.checksums)}); select an explicit compatible "
            "checksum provider plugin or no image will be produced"
        )
    if not xdf.checksums and checksum_provider is not None:
        raise TuningError(
            "a checksum provider was selected, but this XDF declares no "
            "calibration checksum; refusing an unscoped plugin write"
        )
    if checksum_provider is not None and not checksum_provider.supports(xdf.checksums):
        raise TuningError(
            f"checksum provider {checksum_provider.provider_id!r} does not "
            "explicitly support every checksum declared by this XDF"
        )
    package = None
    if recommendation_package is not None:
        if not isinstance(recommendation_package, dict):
            raise TuningError("recommendation_package must be a validated object")
        package_id = str(recommendation_package.get("id") or "").strip()
        package_version = str(recommendation_package.get("version") or "").strip()
        package_sha = str(
            recommendation_package.get("package_sha256") or ""
        ).strip().lower()
        if (not package_id or not package_version
                or not re.fullmatch(r"[0-9a-f]{64}", package_sha)):
            raise TuningError(
                "recommendation_package needs id, version and package_sha256"
            )
        try:
            package = json.loads(json.dumps(
                recommendation_package, sort_keys=True, separators=(",", ":")
            ))
        except (TypeError, ValueError) as exc:
            raise TuningError("recommendation_package is not JSON serializable") from exc
    source_hash = source.sha256
    try:
        tuned_data, applied = xdf.apply_changes(
            source, changes, address_base=address_base
        )
    except XdfError as exc:
        raise TuningError(str(exc)) from exc
    effective_base = (
        xdf.suggest_address_base(source.size)
        if address_base is None else address_base
    )
    xdf_hash = _xdf_sha256(xdf)
    checksum = None
    if checksum_provider is not None:
        context = {
            "xdf_title": xdf.title,
            "xdf_path": xdf.path,
            "xdf_sha256": xdf_hash,
            "declared_checksums": list(xdf.checksums),
            "source_sha256": source_hash,
            "address_base": effective_base,
            "changes": applied,
        }
        try:
            tuned_data, checksum = checksum_provider.apply(tuned_data, context)
        except ChecksumUnavailable as exc:
            raise TuningError(str(exc)) from exc
    tuned_hash = hashlib.sha256(tuned_data).hexdigest()
    if source_hash == tuned_hash:
        raise TuningError("the requested build does not change the source image")
    plan_body = {
        "source_sha256": source_hash,
        "xdf_sha256": xdf_hash,
        "address_base": effective_base,
        "changes": applied,
        "checksum_provider": checksum,
        "recommendation_package": package,
        "output_sha256": tuned_hash,
    }
    plan_hash = hashlib.sha256(json.dumps(
        plan_body, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()
    return tuned_data, {
        "source": {
            "path": source.path,
            "sha256": source_hash,
            "bytes": source.size,
            "is_base_map": bool(source_is_base_map),
            "ecu_id": source.ecu_id,
            "region": source.region,
        },
        "xdf": {
            "path": xdf.path,
            "title": xdf.title,
            "version": xdf.version,
            "sha256": xdf_hash,
        },
        "address_base": effective_base,
        "changes": applied,
        "checksum_provider": checksum,
        "recommendation_package": package,
        "output_sha256": tuned_hash,
        "plan_sha256": plan_hash,
        "warnings": [
            "Recommendation evidence is traceable, not endorsed by GuzziOnBoard.",
            (
                "The selected checksum plugin verified its own deterministic output; "
                "that is not a core endorsement or proof on physical ECU hardware."
                if checksum else
                "No XDF calibration checksum was declared; validate the built image "
                "and review the named diff before programming."
            ),
        ] + ([
            "The recommendation package is user-supplied and unendorsed; its "
            "identity, evidence, fitment and validation claims are provenance, "
            "not proof of safety."
        ] if package else []),
    }


def preview_tune(
    source: FirmwareImage,
    xdf: XdfFile,
    changes: list[dict],
    *,
    source_is_base_map: bool,
    address_base: int | None = None,
    checksum_provider: ChecksumProvider | None = None,
    recommendation_package: dict | None = None,
) -> dict:
    """Quantize and hash a plan without writing any file."""
    _, plan = prepare_tune(
        source, xdf, changes,
        source_is_base_map=source_is_base_map,
        address_base=address_base,
        checksum_provider=checksum_provider,
        recommendation_package=recommendation_package,
    )
    return plan


def build_tune(
    source: FirmwareImage,
    xdf: XdfFile,
    changes: list[dict],
    *,
    recommendation: dict,
    acknowledgement: str,
    source_is_base_map: bool,
    accept_non_base_source: bool = False,
    address_base: int | None = None,
    checksum_provider: ChecksumProvider | None = None,
    recommendation_package: dict | None = None,
    expected_plan_sha256: str = "",
    output_dir: str | Path = DEFAULT_TUNING_DIR,
) -> dict:
    """Build and save a tuned copy, returning its complete manifest."""
    if acknowledgement.strip() != TUNING_ACKNOWLEDGEMENT:
        raise TuningError(
            "to build a modified map, repeat exactly: "
            f"{TUNING_ACKNOWLEDGEMENT!r}"
        )
    if not source_is_base_map and not accept_non_base_source:
        raise TuningError(
            "the source is not the protected base map; explicitly acknowledge "
            "the non-base source or load the base map instead"
        )
    evidence = validate_recommendation(recommendation)
    tuned_data, plan = prepare_tune(
        source, xdf, changes,
        source_is_base_map=source_is_base_map,
        address_base=address_base,
        checksum_provider=checksum_provider,
        recommendation_package=recommendation_package,
    )
    if expected_plan_sha256 and expected_plan_sha256 != plan["plan_sha256"]:
        raise TuningError(
            "the reviewed tuning plan no longer matches this source/XDF/change "
            "set; preview it again before building"
        )
    tuned_hash = plan["output_sha256"]
    applied = plan["changes"]

    built_at = time.time()
    manifest = {
        "schema": 1,
        "built_at": built_at,
        "built_at_text": time.strftime(
            "%Y-%m-%d %H:%M:%S", time.localtime(built_at)
        ),
        **plan,
        "recommendation": evidence,
        "liability_acknowledged": True,
        "acknowledgement": TUNING_ACKNOWLEDGEMENT,
    }

    previous_meta = dict(source.meta or {})
    # Do not retain an older build as if it described the new bytes.
    previous_meta.pop("tuning_build", None)
    tuned = FirmwareImage(
        data=tuned_data,
        ecu_id=source.ecu_id,
        region=source.region,
        source="tuning-build",
        identity=dict(source.identity or {}),
        meta={**previous_meta, "tuning_build": manifest},
    )
    directory = Path(output_dir).expanduser()
    directory.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(source.path or "basemap").stem)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(built_at))
    output = directory / f"{stem}-tune-{stamp}-{tuned_hash[:8]}.bin"
    suffix = 1
    while output.exists():
        output = directory / f"{stem}-tune-{stamp}-{tuned_hash[:8]}-{suffix}.bin"
        suffix += 1
    manifest["output_path"] = str(output)
    tuned.meta["tuning_build"] = manifest
    tuned.save(output)

    return {
        "path": str(output),
        "image": tuned.describe(),
        "manifest": manifest,
        "changes": applied,
    }
