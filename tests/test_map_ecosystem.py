from __future__ import annotations

import hashlib
import json

import pytest

from guzzionboard.checksums import (
    ChecksumProvider,
    ChecksumUnavailable,
    load_providers,
)
from guzzionboard.firmware import FirmwareImage
from guzzionboard.map_analysis import LogAnalysisError, analyze_fuel_log
from guzzionboard.physical_validation import validate_manifest
from guzzionboard.recommendations import (
    RecommendationPackageError,
    validate_package,
)
from guzzionboard.tuning import TuningError, preview_tune
from guzzionboard.maps import XdfFile
from test_maps import DEVICE_SIZE, build_xdf


def rendered_fuel_table() -> dict:
    return {
        "id": "0x10", "title": "Main fuel", "units": "ms",
        "x": [1000, 2000, 3000], "y": [10, 20],
        "x_units": "RPM", "y_units": "TPS",
        "values": [[1.0, 2.0, 3.0], [1.5, 2.5, 3.5]],
        "raw_values": [[10, 20, 30], [15, 25, 35]],
    }


def test_log_overlay_requires_explicit_measured_and_target_afr_and_caps_proposals():
    rows = [
        {"rpm": 2000, "tps": 10, "wideband": 15.4, "target": 14.0}
        for _ in range(4)
    ] + [{"rpm": 9000, "tps": 10, "wideband": 14, "target": 14}]
    report = analyze_fuel_log(
        rendered_fuel_table(), rows,
        x_channel="rpm", y_channel="tps",
        measured_afr_channel="wideband", target_afr_channel="target",
        min_samples=3, max_correction_percent=5,
    )
    assert report["review_only"] is True
    assert report["rows_used"] == 4
    assert report["skipped"]["outside_axes"] == 1
    assert report["proposals"][0]["correction_percent"] == 5
    assert report["proposals"][0]["clamped"] is True
    assert report["proposals"][0]["proposed_value"] == pytest.approx(2.1)
    assert report["cells"][0]["measured_afr_stddev"] == 0
    unstable = analyze_fuel_log(
        rendered_fuel_table(), [
            {"rpm": 2000, "tps": 10, "wideband": afr, "target": 14.0}
            for afr in (12.0, 14.0, 16.0, 18.0)
        ],
        x_channel="rpm", y_channel="tps",
        measured_afr_channel="wideband", target_afr_channel="target",
        min_samples=3, max_correction_percent=5, max_afr_stddev=0.5,
    )
    assert not unstable["proposals"]
    assert unstable["cells"][0]["eligibility"] == "measured AFR is too variable"
    with pytest.raises(LogAnalysisError, match="different columns"):
        analyze_fuel_log(
            rendered_fuel_table(), rows,
            x_channel="rpm", y_channel="tps",
            measured_afr_channel="wideband", target_afr_channel="wideband",
        )


def test_time_aware_log_alignment_compensates_delay_and_filters_transients():
    rows = [
        {"time_ms": 0, "rpm": 1000, "tps": 10, "wideband": 14.0, "target": 14.0},
        {"time_ms": 1000, "rpm": 2000, "tps": 10, "wideband": 15.4, "target": 14.0},
        {"time_ms": 2000, "rpm": 3000, "tps": 10, "wideband": 12.6, "target": 14.0},
    ]
    report = analyze_fuel_log(
        rendered_fuel_table(), rows,
        x_channel="rpm", y_channel="tps",
        measured_afr_channel="wideband", target_afr_channel="target",
        time_channel="time_ms", timestamp_unit="milliseconds",
        wideband_delay_ms=1000, settle_time_ms=0, max_time_gap_ms=1100,
        min_samples=1, max_correction_percent=15,
    )
    assert report["time_alignment"] == {
        "enabled": True,
        "time_channel": "time_ms",
        "timestamp_unit": "milliseconds",
        "wideband_delay_ms": 1000.0,
        "settle_time_ms": 0.0,
        "max_time_gap_ms": 1100.0,
        "max_x_rate_per_s": None,
        "max_y_rate_per_s": None,
        "timeline_reordered": False,
        "method": "measured AFR at t; linearly interpolated x/y/target at t minus wideband delay",
    }
    assert report["rows_used"] == 2
    assert report["skipped"]["alignment_gap"] == 1
    assert [(cell["x"], cell["correction_percent"]) for cell in report["cells"]] == [
        (1000, 10.0), (2000, -10.0),
    ]

    moving = [
        {"time_ms": 0, "rpm": 1000, "tps": 10, "wideband": 14, "target": 14},
        {"time_ms": 500, "rpm": 2000, "tps": 10, "wideband": 14, "target": 14},
        {"time_ms": 1000, "rpm": 2000, "tps": 10, "wideband": 14, "target": 14},
        {"time_ms": 1500, "rpm": 2000, "tps": 10, "wideband": 14, "target": 14},
    ]
    filtered = analyze_fuel_log(
        rendered_fuel_table(), moving,
        x_channel="rpm", y_channel="tps",
        measured_afr_channel="wideband", target_afr_channel="target",
        time_channel="time_ms", timestamp_unit="milliseconds",
        settle_time_ms=400, max_time_gap_ms=600, max_x_rate_per_s=100,
        min_samples=1,
    )
    assert filtered["skipped"]["transient"] >= 1
    assert filtered["rows_used"] < len(moving)

    with pytest.raises(LogAnalysisError, match="time_channel is required"):
        analyze_fuel_log(
            rendered_fuel_table(), rows,
            x_channel="rpm", y_channel="tps",
            measured_afr_channel="wideband", target_afr_channel="target",
            wideband_delay_ms=100,
        )


def test_checksum_provider_is_deterministic_verified_and_part_of_plan():
    xdf = XdfFile.from_string(build_xdf(engine_table=False))
    xdf.checksums = ["Calibration sum byte"]
    image = bytearray(DEVICE_SIZE)
    image[0x8000:0x8002] = (340).to_bytes(2, "big", signed=True)

    def update(data: bytes, context: dict) -> bytes:
        result = bytearray(data)
        result[-1] = sum(result[:-1]) & 0xFF
        return bytes(result)

    def verify(data: bytes, context: dict) -> bool:
        return data[-1] == (sum(data[:-1]) & 0xFF)

    provider = ChecksumProvider(
        "test-sum-v1", "Test sum", "1.0", ("Calibration sum byte",),
        update, verify, verified=False, plugin_sha256="a" * 64,
    )
    package = {
        "id": "owner.locked-plan", "version": "1.0.0",
        "package_sha256": "b" * 64, "status": "user-supplied-unendorsed",
    }
    plan = preview_tune(
        FirmwareImage(data=bytes(image)), xdf,
        [{"kind": "constant", "id": "0x1", "expected_raw": 340, "value": 9000}],
        source_is_base_map=True, checksum_provider=provider,
        recommendation_package=package,
    )
    assert plan["checksum_provider"]["id"] == "test-sum-v1"
    assert plan["recommendation_package"] == package
    assert plan["checksum_provider"]["changed_bytes"] == 1
    assert plan["checksum_provider"]["status"] == "in-process-provider-verified-output-not-core-endorsed"
    changed_package = {**package, "package_sha256": "c" * 64}
    changed_plan = preview_tune(
        FirmwareImage(data=bytes(image)), xdf,
        [{"kind": "constant", "id": "0x1", "expected_raw": 340, "value": 9000}],
        source_is_base_map=True, checksum_provider=provider,
        recommendation_package=changed_package,
    )
    assert changed_plan["output_sha256"] == plan["output_sha256"]
    assert changed_plan["plan_sha256"] != plan["plan_sha256"]
    with pytest.raises(TuningError, match="select an explicit compatible"):
        preview_tune(
            FirmwareImage(data=bytes(image)), xdf,
            [{"kind": "constant", "id": "0x1", "expected_raw": 340, "value": 9000}],
            source_is_base_map=True,
        )


def test_checksum_plugin_loader_reports_invalid_plugins(tmp_path):
    (tmp_path / "good.py").write_text(
        "PROVIDER_ID='local-test-v1'\nNAME='Local'\nVERSION='1.0'\n"
        "SUPPORTED_CHECKSUMS=('Named sum',)\nVERIFIED=False\n"
        "def update(image, context): return image\n"
        "def verify(image, context): return True\n"
    )
    (tmp_path / "bad.py").write_text("PROVIDER_ID='bad'\n")
    providers, errors = load_providers(tmp_path)
    assert [provider.provider_id for provider in providers] == ["local-test-v1"]
    assert providers[0].as_dict()["isolation"].startswith("fresh-python-process")
    output, audit = providers[0].apply(b"abc", {"declared_checksums": ["Named sum"]})
    assert output == b"abc"
    assert audit["status"] == "isolated-plugin-verified-output-not-core-endorsed"
    assert len(errors) == 1 and errors[0]["path"].endswith("bad.py")
    with pytest.raises(ChecksumUnavailable, match="must return bytes"):
        ChecksumProvider("bad-return", "Bad", "1", ("x",),
                         lambda data, context: bytearray(data),
                         lambda data, context: True).apply(b"abc", {})


def test_checksum_plugin_isolation_blocks_import_side_effects_and_network(tmp_path):
    marker = tmp_path.parent / "checksum-plugin-escape.txt"
    (tmp_path / "side_effect.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('escaped')\n"
        "PROVIDER_ID='side-effect-v1'\nNAME='bad'\nVERSION='1'\n"
        "SUPPORTED_CHECKSUMS=('x',)\n"
        "def update(image, context): return image\n"
        "def verify(image, context): return True\n"
    )
    providers, errors = load_providers(tmp_path)
    assert not providers
    assert errors and "denied file access" in errors[0]["error"]
    assert not marker.exists()

    (tmp_path / "side_effect.py").unlink()
    (tmp_path / "network.py").write_text(
        "PROVIDER_ID='network-test-v1'\nNAME='network'\nVERSION='1'\n"
        "SUPPORTED_CHECKSUMS=('x',)\n"
        "def update(image, context):\n"
        " import socket\n"
        " socket.socket()\n"
        " return image\n"
        "def verify(image, context): return True\n"
    )
    providers, errors = load_providers(tmp_path)
    assert not errors and len(providers) == 1
    with pytest.raises(ChecksumUnavailable, match="denied socket"):
        providers[0].apply(b"abc", {})


def package_value() -> dict:
    return {
        "schema": "guzzionboard.recommendation/v1",
        "id": "owner.griso.example",
        "version": "1.2.0",
        "title": "Documented Griso example",
        "license": "CC-BY-4.0",
        "maintainers": [{"name": "Example owner", "url": "https://example.com/owner"}],
        "fitment": {
            "ecu_family": "IAW 5AM", "motorcycle": "Moto Guzzi Griso 1200",
            "hardware": "HW610", "configuration": "stock engine and exhaust",
        },
        "xdf": {"filename": "locked.xdf", "sha256": "1" * 64},
        "evidence": [{
            "title": "Published test", "url": "https://example.com/test",
            "rationale": "Measured on the exact listed configuration",
        }],
        "changes": [{
            "kind": "table", "id": "0x10", "row": 1, "col": 2,
            "expected_raw": 100, "value": 101.5,
        }],
        "validation": {
            "real_ecu": {"status": "reported", "evidence": ["https://example.com/ecu"]},
            "dyno": {"status": "not-provided", "evidence": []},
        },
    }


def test_recommendation_package_registry_validates_provenance_without_endorsement():
    package = validate_package(package_value())
    assert package["status"] == "user-supplied-unendorsed"
    assert package["validation"]["dyno"]["status"] == "not-provided"
    broken = package_value()
    broken["validation"]["dyno"] = {"status": "reported", "evidence": []}
    with pytest.raises(RecommendationPackageError, match="without evidence URLs"):
        validate_package(broken)


def test_physical_validation_manifest_verifies_artifact_hash_but_does_not_certify(tmp_path):
    artifact = tmp_path / "capture.log"
    artifact.write_bytes(b"physical capture placeholder")
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    manifest = {
        "schema": "guzzionboard.physical-validation/v1",
        "id": "bench.griso.001", "kind": "real-ecu",
        "performed_at": "2026-10-06T12:00:00-06:00",
        "operator": {"name": "Operator", "organization": "Independent shop"},
        "motorcycle": {"make": "Moto Guzzi", "model": "Griso", "year": 2012,
                       "configuration": "stock intake and exhaust"},
        "ecu": {"family": "5AM", "hardware": "HW610", "software": "2230"},
        "artifacts": [{"kind": "session", "path": artifact.name, "sha256": digest}],
        "checks": [{"name": "double read", "status": "pass",
                    "detail": "two separately captured reads matched"}],
        "result": "pass",
    }
    record = validate_manifest(manifest, path=str(tmp_path / "record.json"))
    assert record["artifacts"][0]["path"] == str(artifact)
    assert record["artifact_summary"] == {
        "total": 1, "missing": 0, "hash_mismatch": 0, "verified": 1,
    }
    assert record["registry_status"] == "evidence-index-locally-complete"
    assert record["endorsement"] == "operator-supplied-not-core-certified"
    broken = {**manifest, "artifacts": [{
        "kind": "invented", "path": artifact.name, "sha256": digest,
    }]}
    with pytest.raises(ValueError, match="invalid kind"):
        validate_manifest(broken, path=str(tmp_path / "record.json"))
