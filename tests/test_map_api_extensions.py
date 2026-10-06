from __future__ import annotations

import hashlib

import pytest

from guzzionboard import server
from guzzionboard.firmware import FirmwareImage
from guzzionboard.server import Api, ROUTES_GET, ROUTES_POST
from guzzionboard.tuning import TuningError
from guzzionboard.workstation import Workstation
from guzzionboard.maps import XdfFile
from test_maps import DEVICE_SIZE, build_xdf


def test_professional_map_endpoints_are_registered():
    assert ROUTES_GET["/api/checksum-providers"] == "get_checksum_providers"
    assert ROUTES_GET["/api/recommendations"] == "get_recommendation_packages"
    assert ROUTES_GET["/api/physical-validation"] == "get_physical_validation"
    for route in (
        "/api/maps/validate-definition", "/api/maps/analyze-log",
        "/api/recommendations/validate", "/api/physical-validation/validate",
    ):
        assert route in ROUTES_POST


def test_offline_log_api_returns_review_only_proposals(tmp_path, monkeypatch):
    xdf = XdfFile.from_string(build_xdf())
    image = bytearray(DEVICE_SIZE)
    image[0x8300:0x8306] = b"".join(value.to_bytes(2, "big") for value in (8, 16, 24))
    image[0x8200:0x8202] = (455).to_bytes(2, "big", signed=True)
    image[0x8202:0x8204] = (455).to_bytes(2, "big", signed=True)
    image[0x8204:0x8206] = (455).to_bytes(2, "big", signed=True)
    image[0x8208:0x820A] = (455).to_bytes(2, "big", signed=True)
    path = tmp_path / "source.bin"
    path.write_bytes(image)
    api = Api(Workstation(session_dir=tmp_path / "sessions"))
    monkeypatch.setattr(api, "_load_xdf", lambda ref: xdf)
    table_id = next(table.item_id for table in xdf.tables
                    if table.title == "Speedo correction")
    status, report = api.post_maps_analyze_log({
        "path": str(path), "xdf": "fixture", "table": table_id,
        "x_channel": "rpm", "y_channel": "tps",
        "measured_afr_channel": "measured", "target_afr_channel": "target",
        "min_samples": 3, "max_correction_percent": 5,
        "time_channel": "time_ms", "timestamp_unit": "milliseconds",
        "wideband_delay_ms": 0, "settle_time_ms": 0, "max_time_gap_ms": 200,
        "min_cell_duration_ms": 0,
        "rows": [
            {"time_ms": time_ms, "rpm": 0, "tps": 0,
             "measured": 15, "target": 14}
            for time_ms in (0, 100, 200)
        ],
    })
    assert status == 200
    assert report["review_only"] is True
    assert report["proposals"]
    assert report["max_correction_percent"] == 5
    assert report["time_alignment"]["enabled"] is True
    assert report["time_alignment"]["wideband_delay_ms"] == 0


def test_definition_validation_api_can_run_without_an_image(tmp_path, monkeypatch):
    xdf = XdfFile.from_string(build_xdf())
    api = Api(Workstation(session_dir=tmp_path / "sessions"))
    monkeypatch.setattr(api, "_load_xdf", lambda ref: xdf)
    status, report = api.post_maps_validate_definition({"xdf": "fixture"})
    assert status == 200
    assert report["definition"]["title"] == xdf.title
    assert report["checksum"]["selection_required"] is False
    assert any(finding["check"] == "write-equation" for finding in report["findings"])


def test_recommendation_package_is_reloaded_and_exactly_locks_the_plan(tmp_path, monkeypatch):
    xdf_path = tmp_path / "5AM_locked.xdf"
    xdf_path.write_text(build_xdf(), encoding="utf-8")
    xdf = XdfFile.from_file(xdf_path)
    digest = hashlib.sha256(xdf_path.read_bytes()).hexdigest()
    package = {
        "id": "owner.griso.locked", "version": "1.0.0",
        "title": "Locked plan", "license": "CC-BY-4.0",
        "maintainers": [{"name": "Owner", "url": "https://example.com/owner"}],
        "fitment": {
            "ecu_family": "5AM", "motorcycle": "Moto Guzzi Griso",
            "hardware": "HW610", "configuration": "stock intake and exhaust",
        },
        "xdf": {"filename": xdf_path.name, "sha256": digest},
        "evidence": [{
            "title": "Locked evidence", "url": "https://example.com/evidence",
            "rationale": "Applies to the exact listed configuration",
            "sha256": "",
        }],
        "changes": [{
            "kind": "constant", "id": "0x1", "expected_raw": 340, "value": 9000.0,
        }],
        "validation": {
            "real_ecu": {"status": "not-provided", "evidence": []},
            "dyno": {"status": "not-provided", "evidence": []},
        },
        "status": "user-supplied-unendorsed",
        "package_sha256": "a" * 64,
    }
    monkeypatch.setattr(server, "load_recommendation_packages", lambda: ([package], []))
    api = Api(Workstation(session_dir=tmp_path / "sessions"))
    monkeypatch.setattr(api.ws, "status", lambda: {
        "selection": {"make": "Moto Guzzi", "model": "Griso"}
    })
    source = FirmwareImage(data=bytes(DEVICE_SIZE), identity={"Hardware": "IAW5AMHW610"})
    body = {
        "recommendation_package": {
            "id": package["id"], "version": package["version"],
            "package_sha256": package["package_sha256"],
        },
        "recommendation": package["evidence"][0],
        "changes": [dict(package["changes"][0])],
    }
    resolved = api._recommendation_package(body, xdf, source)
    assert resolved["package_sha256"] == "a" * 64
    assert resolved["status"] == "user-supplied-unendorsed"

    body["changes"][0]["value"] = 9001
    with pytest.raises(TuningError, match="no longer matches"):
        api._recommendation_package(body, xdf, source)
    body["changes"] = [dict(package["changes"][0]), {
        "kind": "constant", "id": "another", "expected_raw": 0, "value": 1,
    }]
    with pytest.raises(TuningError, match="exactly"):
        api._recommendation_package(body, xdf, source)
