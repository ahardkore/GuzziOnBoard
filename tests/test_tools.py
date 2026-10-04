"""Adapter pre-flight checks and the standalone calculators."""
from __future__ import annotations

import math

import pytest

from guzzionboard import adapter, tools


# -- adapter ---------------------------------------------------------------


def test_latency_timer_is_unreadable_for_a_non_ftdi_path():
    assert adapter.read_latency_timer("/dev/ttyS0") is None
    assert adapter.read_latency_timer("COM3") is None
    assert not adapter.set_latency_timer("/dev/ttyS0")


def test_latency_fix_instructions_mention_the_right_place(monkeypatch):
    monkeypatch.setattr(adapter.platform, "system", lambda: "Linux")
    assert "latency_timer" in adapter.latency_fix_instructions("/dev/ttyUSB0")
    monkeypatch.setattr(adapter.platform, "system", lambda: "Windows")
    assert "Device Manager" in adapter.latency_fix_instructions("COM3")


def test_a_slow_latency_timer_is_flagged(tmp_path, monkeypatch):
    """16 ms is the FTDI default and the usual cause of a glacial read."""
    port = tmp_path / "ttyUSB9"
    port.write_text("")
    sysfs = tmp_path / "sysfs"
    (sysfs / "ttyUSB9").mkdir(parents=True)
    (sysfs / "ttyUSB9" / "latency_timer").write_text("16\n")
    monkeypatch.setattr(adapter, "SYSFS_USB_SERIAL", sysfs)

    assert adapter.read_latency_timer(str(port)) == 16
    assert adapter.set_latency_timer(str(port), 1)
    assert adapter.read_latency_timer(str(port)) == 1


def test_check_adapter_without_a_port_offers_guidance():
    report = adapter.check_adapter("")
    names = {c.name for c in report.checks}
    assert "pyserial" in names or "port" in names
    assert report.text()


def test_report_serialises_and_fails_on_a_missing_port():
    pytest.importorskip("serial")
    report = adapter.check_adapter("/dev/definitely-not-here")
    assert not report.ok
    assert report.as_dict()["checks"]


# -- tyres and gearing -----------------------------------------------------


def test_tyre_circumference_matches_the_geometry():
    # 180/55-17: 17" rim plus two 99 mm sidewalls.
    diameter_mm = 17 * 25.4 + 2 * 180 * 0.55
    assert tools.tyre_circumference_m("180/55-17") == pytest.approx(
        math.pi * diameter_mm / 1000.0
    )
    assert tools.tyre_circumference_m("180/55ZR17") == pytest.approx(
        tools.tyre_circumference_m("180/55-17")
    )


def test_a_nonsense_tyre_marking_is_rejected():
    with pytest.raises(ValueError, match="cannot parse"):
        tools.tyre_circumference_m("fat one")


def test_road_speed_rises_with_gear_and_rpm():
    gearing = tools.Gearing()
    assert gearing.speed_kmh(4000, 6) > gearing.speed_kmh(4000, 1)
    assert gearing.speed_kmh(6000, 3) > gearing.speed_kmh(3000, 3)
    # A big twin in top at 4000 rpm belongs somewhere sane for a road bike.
    assert 100 < gearing.speed_kmh(4000, 6) < 220


def test_rpm_and_speed_are_inverses():
    gearing = tools.Gearing()
    speed = gearing.speed_kmh(5000, 4)
    assert gearing.rpm_at(speed, 4) == pytest.approx(5000, rel=1e-6)


def test_an_out_of_range_gear_is_rejected():
    with pytest.raises(ValueError, match="outside"):
        tools.Gearing().speed_kmh(3000, 9)


def test_gear_can_be_inferred_from_rpm_and_speed():
    """Labels logged data that has no gear-position signal."""
    gearing = tools.Gearing()
    for gear in range(1, 7):
        speed = gearing.speed_kmh(4500, gear)
        assert gearing.infer_gear(4500, speed) == gear
    assert gearing.infer_gear(0, 0) is None
    # A speed no gear can explain is not forced into one.
    assert gearing.infer_gear(1000, 300) is None


def test_the_gearing_table_covers_every_gear():
    table = tools.Gearing().table([1000, 2000])
    assert len(table["gears"]) == 6
    assert len(table["gears"]["gear1"]) == 2


# -- log export ------------------------------------------------------------


def sample(at, key, value, raw=""):
    return {"kind": "sample", "at": at, "key": key, "value": value, "raw": raw}


def test_samples_become_one_row_per_instant():
    events = [
        sample(100.0, "rpm", 1200), sample(100.0, "coolant_temp", 80),
        sample(100.5, "rpm", 1300), sample(100.5, "coolant_temp", 81),
        {"kind": "frame", "at": 100.2},
    ]
    csv_text = tools.samples_to_csv(events)
    lines = csv_text.strip().splitlines()
    assert lines[0] == "time,rpm,coolant_temp"
    assert lines[1] == "0.0,1200,80"
    assert lines[2] == "0.5,1300,81"


def test_raw_bytes_can_be_included_for_protocol_work():
    events = [sample(1.0, "rpm", 1200, raw="61 30 04 B0")]
    header = tools.samples_to_csv(events, include_raw=True).splitlines()[0]
    assert header == "time,rpm,rpm_raw"


def test_exporting_a_session_with_no_samples_is_empty_not_an_error():
    assert tools.samples_to_csv([{"kind": "frame", "at": 1.0}]) == ""


def test_json_export_is_time_ordered():
    import json

    events = [sample(5.0, "rpm", 2000), sample(1.0, "rpm", 1000)]
    rows = json.loads(tools.samples_to_json(events))
    assert [r["rpm"] for r in rows] == [1000, 2000]
