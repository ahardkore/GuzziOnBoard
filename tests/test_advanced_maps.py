from __future__ import annotations

import pytest

from guzzionboard.firmware import FirmwareImage
from guzzionboard.maps import XdfError, XdfFile
from test_maps import DEVICE_SIZE, build_xdf


def image_bytes() -> bytearray:
    image = bytearray(DEVICE_SIZE)
    image[0x8000:0x8002] = (340).to_bytes(2, "big", signed=True)
    image[0x8200:0x8202] = (-455).to_bytes(2, "big", signed=True)
    image[0x8202:0x8204] = (455).to_bytes(2, "big", signed=True)
    image[0x8204:0x8206] = (910).to_bytes(2, "big", signed=True)
    image[0x8208:0x820A] = (1820).to_bytes(2, "big", signed=True)
    image[0x8300:0x8306] = b"".join(value.to_bytes(2, "big") for value in (8, 16, 24))
    image[0x8400:0x8402] = bytes([30, 34])
    image[0x4F000:0x4F002] = bytes([128, 200])
    return image


def spark_render(xdf: XdfFile, image: bytes) -> dict:
    return next(table for table in xdf.render(image)["tables"]
                if table["title"] == "Ignition advance")


def test_render_exposes_structured_embedded_and_static_axes():
    xdf = XdfFile.from_string(build_xdf())
    table = spark_render(xdf, bytes(image_bytes()))
    assert table["x_units"] == "RPM"
    assert table["axes"]["x"] == {
        "id": "x", "units": "RPM", "values": ["800", "1600", "2400"],
        "raw_values": [8, 16, 24], "equation": "X*100", "address": "0x8300",
        "size_bits": 16, "signed": False, "editable": True, "legend": None,
    }
    assert table["axes"]["y"]["editable"] is False
    assert table["axes"]["y"]["raw_values"] == []


def test_embedded_axis_write_is_source_locked_and_reported_in_diff():
    xdf = XdfFile.from_string(build_xdf())
    source = FirmwareImage(data=bytes(image_bytes()))
    table = spark_render(xdf, source.data)
    changed, applied = xdf.apply_changes(source, [{
        "kind": "axis", "id": table["id"], "axis": "x", "index": 1,
        "expected_raw": 16, "value": 1800,
    }])
    assert changed[0x8302:0x8304] == (18).to_bytes(2, "big")
    assert applied[0]["kind"] == "axis"
    assert applied[0]["axis"] == "x"
    assert applied[0]["index"] == 1
    assert applied[0]["before"] == 1600
    assert applied[0]["after"] == 1800
    diff = xdf.diff(source, changed)
    table_diff = next(item for item in diff["tables"]
                      if item["title"] == "Ignition advance")
    assert table_diff["changed_cells"] == 0
    assert table_diff["axis_changes"] == [{
        "axis": "x", "index": 1, "units": "RPM",
        "before": "1600", "after": "1800",
    }]


def test_axis_write_refuses_stale_lock_static_axis_and_bad_index():
    xdf = XdfFile.from_string(build_xdf())
    source = FirmwareImage(data=bytes(image_bytes()))
    item_id = spark_render(xdf, source.data)["id"]
    base = {"kind": "axis", "id": item_id, "axis": "x", "index": 1,
            "expected_raw": 15, "value": 1800}
    with pytest.raises(XdfError, match="source changed"):
        xdf.apply_changes(source, [base])
    with pytest.raises(XdfError, match="static-label"):
        xdf.apply_changes(source, [{**base, "axis": "y", "expected_raw": 0}])
    with pytest.raises(XdfError, match="outside 0"):
        xdf.apply_changes(source, [{**base, "index": 99, "expected_raw": 0}])


def test_definition_validation_checks_round_trip_order_bounds_and_rendering():
    xdf = XdfFile.from_string(build_xdf())
    report = xdf.validate_definition(FirmwareImage(data=bytes(image_bytes())))
    assert report["definition"]["title"] == xdf.title
    assert not any(finding["check"] == "write-equation"
                   and finding["level"] == "fatal" for finding in report["findings"])
    assert not any(finding["check"] == "axis-order"
                   and finding["level"] == "warn" for finding in report["findings"])
    # A from-string fixture has no cataloged file fitment. The validator says so
    # rather than pretending this definition is safe for a physical ECU.
    assert any(finding["check"] == "fitment" and finding["level"] == "fatal"
               for finding in report["findings"])
    assert report["fatal"] >= 1
    assert "cannot prove" in report["note"]


def test_definition_validation_surfaces_declared_calibration_checksums():
    xdf = XdfFile.from_string(build_xdf())
    xdf.checksums = ["Documented calibration sum"]
    report = xdf.validate_definition()
    finding = next(item for item in report["findings"]
                   if item["check"] == "calibration-checksum")
    assert finding["level"] == "warn"
    assert "explicitly selected compatible provider" in finding["detail"]
