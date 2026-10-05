"""The simulated motorcycle: controls, seeded faults and fault maturation.

The point of these is that the simulator stops being a demo loop and starts
being a thing you can *practise on* - and that the practice is honest: a
seeded fault moves the live channels first and only reaches fault memory
later, the way a real ECU behaves.
"""
from __future__ import annotations

import pytest

from guzzionboard.catalog import load_catalog
from guzzionboard.derived import Analyzer
from guzzionboard.server import Api
from guzzionboard.transports.simulator import (
    FAULTS,
    FAULTS_BY_KEY,
    EngineModel,
    SimulatedEcu,
)
from guzzionboard.workstation import Workstation


@pytest.fixture
def profile():
    return load_catalog().ecu("5am")


@pytest.fixture
def api(tmp_path):
    api = Api(Workstation(session_dir=tmp_path, record=False))
    api.ws.select(model="Griso 1200 8V", year=2012, transport="simulator")
    api.ws.connect(mode="simulator")
    api.get_identify({})          # the safety gate wants a known ECU first
    yield api
    api.ws.disconnect()


def live(api, keys):
    _, body = api.get_live({"keys": [",".join(keys)]})
    return {s["key"]: s for s in body["samples"]}, body


# ----------------------------------------------------------- the controls

def test_the_throttle_is_an_input_now():
    engine = EngineModel(auto_blip=False)
    idle = engine.rpm
    engine.throttle_pct = 80
    assert engine.rpm > idle + 2000
    assert engine.throttle_deg > 50


def test_the_rev_limiter_holds():
    engine = EngineModel(auto_blip=False, throttle_pct=100)
    assert engine.rpm <= EngineModel.REDLINE_RPM


def test_a_stopped_engine_cools_back_towards_ambient():
    engine = EngineModel(ambient_c=10.0)
    engine.advance(900)
    hot = engine.true_coolant_c
    assert hot > 80
    engine.stop()
    engine.advance(3600)
    assert engine.true_coolant_c < hot - 20


def test_idle_speed_agrees_with_the_idle_target_the_ecu_reports(profile):
    """The simulator used to disagree with itself; the derived idle error
    is what caught it, so it is what guards it."""
    ecu = SimulatedEcu(profile, engine=EngineModel(auto_blip=False))
    ecu.engine.advance(600)
    rpm = ecu.engine.rpm
    target = ecu.engine.idle_target_rpm
    assert abs(rpm - target) < 120


def test_road_speed_only_moves_when_the_bike_is_in_gear():
    engine = EngineModel(auto_blip=False, throttle_pct=50)
    assert engine.road_speed == 0
    engine.in_gear = True
    assert engine.road_speed > 20


def test_a_tired_battery_reads_low_with_the_engine_off():
    engine = EngineModel(running=False, battery_health=0.6)
    assert engine.battery_v < 12.0


# ------------------------------------------------------------ the faults

def test_every_catalogued_fault_is_seedable_and_described():
    for fault in FAULTS:
        assert fault.name and fault.description
        engine = EngineModel()
        assert engine.set_faults([fault.key]) == {fault.key}


def test_unknown_faults_are_ignored_rather_than_believed():
    engine = EngineModel()
    assert engine.set_faults(["not_a_fault"]) == set()


def test_an_open_coolant_sensor_rails_the_reading_but_not_the_metal():
    engine = EngineModel(faults={"coolant_sensor_open"})
    engine.advance(900)
    assert engine.coolant_c == -40.0
    assert engine.true_coolant_c > 80          # the engine really is hot
    assert not engine.closed_loop              # and the ECU never warms up


def test_an_air_leak_raises_idle_and_closes_the_stepper_down():
    clean = EngineModel(auto_blip=False)
    leaky = EngineModel(auto_blip=False, faults={"air_leak"})
    for e in (clean, leaky):
        e.advance(600)
    assert leaky.rpm > clean.rpm + 250
    assert leaky.stepper_position < clean.stepper_position
    assert leaky.lambda_integrator(0) > 5


def test_a_blocked_front_injector_shows_up_as_a_bank_split():
    engine = EngineModel(auto_blip=False, faults={"injector_blocked_front"})
    engine.advance(600)
    split = engine.lambda_integrator(0) - engine.lambda_integrator(1)
    assert split > 10


def test_a_dead_lambda_sensor_stops_switching_without_leaving_closed_loop():
    engine = EngineModel(auto_blip=False, faults={"lambda_dead_front"})
    engine.advance(600)
    readings = []
    for _ in range(12):
        engine.advance(1)
        readings.append(engine.lambda_mv(0))
    assert max(readings) - min(readings) < 50
    assert engine.closed_loop                  # the ECU has not noticed yet


def test_charging_failure_drops_the_bus_voltage():
    engine = EngineModel(faults={"charging_failure"})
    assert engine.battery_v < 12.6


# -------------------------------------------------- the faults, end to end

def test_a_seeded_fault_shows_in_the_data_before_it_shows_in_fault_memory(api):
    ecu = api._simulated_ecu()
    ecu.dtc_pending_after = 0.0
    ecu.dtc_confirm_after = 999.0
    ecu.dtcs.clear()
    ecu._fault_since.clear()

    status, body = api.post_sim_faults({"key": "charging_failure", "active": True})
    assert status == 200
    assert [f["active"] for f in body["faults"] if f["key"] == "charging_failure"] == [True]

    samples, payload = live(api, ["rpm", "battery", "stop_state"])
    assert samples["battery"]["value"] < 12.6
    assert any(f["key"] == "charging" for f in payload["findings"])

    codes = {d["code"]: d for d in api.get_dtcs({})[1]["dtcs"]}
    assert codes["P0562"]["status"] in ("pending", "stored", "confirmed")


def test_a_code_comes_back_if_you_clear_it_with_the_cause_still_there(api):
    ecu = api._simulated_ecu()
    ecu.dtc_pending_after = 0.0
    ecu.dtc_confirm_after = 0.0
    ecu.dtcs.clear()
    ecu._fault_since.clear()
    api.post_sim_faults({"key": "air_leak", "active": True})

    assert "P0505" in {d["code"] for d in api.get_dtcs({})[1]["dtcs"]}

    # Erase it with a long maturation delay: the memory really does empty.
    ecu.dtc_pending_after = 60.0
    token = api.get_dtcs({})[1]["clear"]["token"]
    api.post_dtcs_clear({"token": token})
    assert "P0505" not in {d["code"] for d in api.get_dtcs({})[1]["dtcs"]}

    # The cause never went away, so once the delay elapses it sets again.
    ecu.dtc_pending_after = 0.0
    assert "P0505" in {d["code"] for d in api.get_dtcs({})[1]["dtcs"]}


def test_removing_the_cause_leaves_the_stored_code_until_it_is_erased(api):
    ecu = api._simulated_ecu()
    ecu.dtc_pending_after = 0.0
    ecu.dtc_confirm_after = 0.0
    ecu.dtcs.clear()
    ecu._fault_since.clear()

    api.post_sim_faults({"key": "air_leak", "active": True})
    assert "P0505" in {d["code"] for d in api.get_dtcs({})[1]["dtcs"]}

    api.post_sim_faults({"key": "air_leak", "active": False})
    assert "P0505" in {d["code"] for d in api.get_dtcs({})[1]["dtcs"]}

    token = api.get_dtcs({})[1]["clear"]["token"]
    api.post_dtcs_clear({"token": token})
    assert "P0505" not in {d["code"] for d in api.get_dtcs({})[1]["dtcs"]}


def test_an_air_leak_is_diagnosable_from_the_live_data_alone(api):
    api.post_sim_engine({"auto_blip": False, "advance_s": 600})
    api.post_sim_faults({"key": "air_leak", "active": True})

    keys = ["rpm", "idle_target", "stepper_position", "stepper_base",
            "lambda_int_f", "lambda_int_r", "stop_state", "throttle_closed"]
    samples, body = live(api, keys)
    values = {c["key"]: c["value"] for c in body["derived"]}
    assert values["idle_error"] > 200
    assert values["stepper_drift"] < 0
    finding = next(f for f in body["findings"] if f["key"] == "idle_control")
    assert any("Air leak" in s for s in finding["suspects"])


# -------------------------------------------------------------- the API

def test_the_sim_endpoints_describe_themselves_when_not_simulating(tmp_path):
    api = Api(Workstation(session_dir=tmp_path, record=False))
    api.ws.select(model="Griso 1200 8V", year=2012, transport="kline")
    status, body = api.get_sim({})
    assert status == 200 and body["available"] is False
    assert len(body["faults"]) == len(FAULTS)
    # ...and nothing can be driven.
    assert api.post_sim_engine({"running": True})[0] == 400
    assert api.post_sim_faults({"key": "air_leak"})[0] == 400
    assert api.post_sim_comms({"drop_rate": 0.5})[0] == 400


def test_engine_controls_are_clamped(api):
    _, body = api.post_sim_engine({"throttle_pct": 500, "ambient_c": -999,
                                   "battery_health": 9})
    assert body["engine"]["throttle_pct"] == 100
    assert body["engine"]["ambient_c"] == -30
    assert body["engine"]["battery_health"] == 1.1


def test_unknown_faults_are_refused_by_the_api(api):
    status, body = api.post_sim_faults({"faults": ["air_leak", "nonsense"]})
    assert status == 400 and "nonsense" in body["error"]


def test_comms_degradation_is_settable_and_actually_bites(api):
    _, body = api.post_sim_comms({"drop_rate": 1.0})
    assert body["comms"]["drop_rate"] == 1.0
    samples, _ = live(api, ["rpm"])
    assert samples["rpm"]["error"]          # nothing answers at 100% loss
    api.post_sim_comms({"drop_rate": 0.0})
    samples, _ = live(api, ["rpm"])
    assert not samples["rpm"]["error"]


def test_faults_are_catalogued_with_the_codes_they_set():
    assert FAULTS_BY_KEY["air_leak"].dtc == "P0505"
    assert FAULTS_BY_KEY["lambda_dead_front"].dtc == "P0130"
    assert all(f.dtc.startswith("P") for f in FAULTS)


def test_the_analyzer_sees_a_dead_sensor_on_a_seeded_bike(profile):
    ecu = SimulatedEcu(profile, engine=EngineModel(
        auto_blip=False, faults={"lambda_dead_front"}))
    ecu.engine.advance(600)
    analyzer = Analyzer(profile)
    for _ in range(5):
        ecu.engine.advance(2)
        out = analyzer.update([
            {"key": "lambda_f", "value": ecu.engine.lambda_mv(0), "unit": "mV",
             "text": "", "error": ""},
            {"key": "lambda_loop", "value": 2, "unit": "", "text": "Closed loop",
             "error": ""},
            {"key": "rpm", "value": ecu.engine.rpm, "unit": "rpm", "text": "",
             "error": ""},
            {"key": "stop_state", "value": 4, "unit": "", "text": "Running",
             "error": ""},
        ])
    assert any(f["key"] == "lambda_lazy_f" for f in out["findings"])


def test_the_stepper_tells_the_two_idle_faults_apart(api):
    """Same symptom, same stored code, different fingerprint."""
    keys = ["rpm", "idle_target", "stepper_position", "stepper_base",
            "stop_state", "throttle_closed"]
    api.post_sim_engine({"auto_blip": False, "advance_s": 600})

    api.post_sim_faults({"faults": ["air_leak"]})
    _, body = live(api, keys)
    leak = next(f for f in body["findings"] if f["key"] == "idle_control")
    assert leak["suspects"][0].startswith("Air leak")

    api.post_sim_faults({"faults": ["stepper_stuck"]})
    _, body = live(api, keys)
    stuck = next(f for f in body["findings"] if f["key"] == "idle_control")
    assert "stepper" in stuck["suspects"][0].lower()
