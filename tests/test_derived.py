"""Derived channels and plausibility checks.

These are the workstation's own arithmetic and the workstation's own
opinions, so the tests care about two things: that the maths is right, and
that nothing is claimed when the inputs for it were never read.
"""
from __future__ import annotations

import time

import pytest

from guzzionboard.catalog import load_catalog
from guzzionboard.derived import CHANNELS_BY_KEY, Analyzer


def sample(key, value, unit="", text="", error=""):
    return {
        "key": key, "name": key, "local_id": 0x30, "raw": "00",
        "value": value, "unit": unit, "text": text, "at": time.time(),
        "error": error,
    }


def analyze(rows, profile=None, sweeps=1, analyzer=None):
    a = analyzer or Analyzer(profile)
    for _ in range(sweeps):
        out = a.update(rows)
    return out


def values(out):
    return {c["key"]: c["value"] for c in out["derived"]}


def levels(out):
    return {f["key"]: f["level"] for f in out["findings"]}


# ------------------------------------------------------------ arithmetic

def test_injector_duty_is_the_fraction_of_the_available_window():
    # 6000 rpm injects every 20 ms; a 10 ms pulse is half the window.
    out = analyze([sample("rpm", 6000, "rpm"), sample("injection_ms", 10.0, "ms")])
    assert values(out)["inj_duty"] == pytest.approx(50.0, abs=0.1)


def test_duty_is_not_computed_on_a_stopped_engine():
    out = analyze([sample("rpm", 0, "rpm"), sample("injection_ms", 0.0, "ms")])
    assert "inj_duty" not in values(out)


def test_idle_error_and_stepper_drift():
    out = analyze([
        sample("rpm", 1500, "rpm"), sample("idle_target", 1250, "rpm"),
        sample("stepper_position", 130, "steps"), sample("stepper_base", 117, "steps"),
    ])
    v = values(out)
    assert v["idle_error"] == 250
    assert v["stepper_drift"] == 13


def test_temperature_split_is_marked_as_a_difference():
    out = analyze([sample("coolant_temp", 88, "\u00b0C"), sample("air_temp", 22, "\u00b0C")])
    channel = next(c for c in out["derived"] if c["key"] == "temp_split")
    assert channel["value"] == 66
    # A display converting to Fahrenheit must scale this, not shift it.
    assert channel["delta"] is True
    assert CHANNELS_BY_KEY["temp_split"].delta is True


def test_windowed_channels_need_history():
    a = Analyzer()
    rows = [sample("lambda_f", 450, "mV"), sample("lambda_loop", 2, text="Closed loop")]
    assert "lambda_swing_f" not in values(a.update(rows))
    for mv in (120, 800, 300):
        out = a.update([sample("lambda_f", mv, "mV"),
                        sample("lambda_loop", 2, text="Closed loop")])
    v = values(out)
    assert v["lambda_swing_f"] == 680          # 800 - 120
    assert v["closed_loop_share"] == 100


def test_a_channel_is_skipped_when_a_source_was_not_read():
    out = analyze([sample("rpm", 3000, "rpm")])     # no injection_ms
    assert "inj_duty" not in values(out)


def test_errored_samples_are_not_treated_as_values():
    out = analyze([
        sample("rpm", 3000, "rpm"),
        sample("injection_ms", None, "ms", error="no answer"),
    ])
    assert "inj_duty" not in values(out)


def test_derived_values_inherit_the_worst_input_confidence():
    profile = load_catalog().ecu("5am")
    out = analyze([
        sample("rpm", 3000, "rpm"), sample("injection_ms", 3.0, "ms"),
    ], profile=profile)
    channel = next(c for c in out["derived"] if c["key"] == "inj_duty")
    assert channel["confidence"] == "verified-capture"
    assert channel["sources"] == ["injection_ms", "rpm"]
    assert channel["derived"] is True


# ---------------------------------------------------------------- rules

def test_a_healthy_idling_engine_raises_nothing():
    out = analyze([
        sample("rpm", 1250, "rpm"), sample("idle_target", 1250, "rpm"),
        sample("battery", 14.1, "V"), sample("coolant_temp", 88, "\u00b0C"),
        sample("air_temp", 24, "\u00b0C"), sample("injection_ms", 2.0, "ms"),
        sample("stop_state", 4, text="Running"),
        sample("throttle_closed", 1, text="Shut"),
    ])
    assert out["findings"] == []


def test_a_dead_charging_system_is_called_out():
    out = analyze([
        sample("rpm", 3000, "rpm"), sample("battery", 12.1, "V"),
        sample("stop_state", 4, text="Running"),
    ])
    assert levels(out)["charging"] == "bad"
    finding = next(f for f in out["findings"] if f["key"] == "charging")
    assert "Regulator/rectifier" in finding["suspects"]
    assert finding["evidence"]["battery"] == "12.1 V"


def test_a_railed_temperature_sensor_is_called_out():
    out = analyze([sample("coolant_temp", -40, "\u00b0C")])
    assert levels(out)["coolant_sensor_range"] == "bad"


def test_idle_hunting_is_blamed_on_air_when_the_stepper_is_closing_down():
    out = analyze([
        sample("rpm", 1800, "rpm"), sample("idle_target", 1250, "rpm"),
        sample("stepper_position", 140, "steps"), sample("stepper_base", 117, "steps"),
        sample("stop_state", 4, text="Running"),
        sample("throttle_closed", 1, text="Shut"),
    ])
    finding = next(f for f in out["findings"] if f["key"] == "idle_control")
    assert finding["level"] == "warn"
    assert any("Air leak" in s for s in finding["suspects"])


def test_idle_is_not_judged_while_the_rider_is_on_the_throttle():
    out = analyze([
        sample("rpm", 5000, "rpm"), sample("idle_target", 1250, "rpm"),
        sample("stop_state", 4, text="Running"),
        sample("throttle_closed", 4, text="Open"),
    ])
    assert "idle_control" not in levels(out)


def test_a_lazy_lambda_sensor_is_only_flagged_in_closed_loop():
    open_loop = Analyzer()
    for _ in range(4):
        out = open_loop.update([
            sample("lambda_f", 450, "mV"), sample("lambda_loop", 0, text="Open loop"),
            sample("rpm", 1300, "rpm"), sample("stop_state", 4, text="Running"),
        ])
    assert "lambda_lazy_f" not in levels(out)

    closed = Analyzer()
    for _ in range(4):
        out = closed.update([
            sample("lambda_f", 450, "mV"), sample("lambda_loop", 2, text="Closed loop"),
            sample("rpm", 1300, "rpm"), sample("stop_state", 4, text="Running"),
        ])
    assert levels(out)["lambda_lazy_f"] == "warn"


def test_a_bank_split_points_at_the_hungrier_cylinder():
    out = analyze([
        sample("lambda_int_f", 18.0, "%"), sample("lambda_int_r", 1.0, "%"),
        sample("rpm", 1300, "rpm"), sample("stop_state", 4, text="Running"),
    ])
    finding = next(f for f in out["findings"] if f["key"] == "bank_split")
    assert "front" in finding["title"]


def test_a_warm_engine_stuck_in_open_loop_is_flagged():
    a = Analyzer()
    for _ in range(4):
        out = a.update([
            sample("coolant_temp", 90, "\u00b0C"), sample("lambda_loop", 0, text="Open loop"),
            sample("rpm", 1300, "rpm"), sample("stop_state", 4, text="Running"),
        ])
    assert levels(out)["open_loop"] == "warn"


def test_findings_are_ordered_worst_first():
    out = analyze([
        sample("rpm", 1800, "rpm"), sample("idle_target", 1250, "rpm"),
        sample("battery", 12.0, "V"), sample("stop_state", 4, text="Running"),
        sample("throttle_closed", 1, text="Shut"),
    ])
    assert [f["level"] for f in out["findings"]] == sorted(
        [f["level"] for f in out["findings"]], key=lambda l: {"bad": 0, "warn": 1}[l]
    )


def test_nothing_is_claimed_without_inputs():
    out = analyze([sample("road_speed", 0, "km/h")])
    assert out["derived"] == []
    assert out["findings"] == []


# ------------------------------------------------------- through the API

def test_live_endpoint_returns_derived_values_and_findings(tmp_path):
    from guzzionboard.server import Api
    from guzzionboard.workstation import Workstation

    api = Api(Workstation(session_dir=tmp_path, record=False))
    api.ws.select(model="Griso 1200 8V", year=2012, transport="simulator")
    api.ws.connect(mode="simulator")

    status, body = api.get_live({"keys": ["rpm,injection_ms,battery,coolant_temp,air_temp"]})
    assert status == 200
    assert body["samples"]
    assert {c["key"] for c in body["derived"]} >= {"inj_duty", "temp_split", "charge_margin"}
    assert "not read from the ECU" in body["analysis_note"]
    assert isinstance(body["findings"], list)

    status, catalog = api.get_derived_catalog({})
    assert status == 200
    assert {c["key"] for c in catalog["channels"]} >= {"inj_duty", "idle_error"}
    assert all(c["sources"] for c in catalog["channels"])
    api.ws.disconnect()


def test_report_separates_derived_values_from_measured_ones(tmp_path):
    from guzzionboard.workstation import Workstation

    ws = Workstation(session_dir=tmp_path, record=False)
    ws.select(model="Griso 1200 8V", year=2012, transport="simulator")
    ws.connect(mode="simulator")
    ws.require_service().read_parameters(["rpm", "injection_ms", "battery"])

    report = ws.build_report()
    assert any(c["key"] == "inj_duty" for c in report["derived"])

    text = ws.report_text(report)
    assert "Derived by the workstation (not read from the ECU)" in text
    assert "Injector duty cycle" in text
    ws.disconnect()
