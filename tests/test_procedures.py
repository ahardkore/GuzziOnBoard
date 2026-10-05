"""Guided test procedures.

The things worth guarding: a procedure never invents a capability, an
actuator step is refused by the same safety gate as a manual pulse, an
observation really does sample, and the verdict changes when the bike
changes - which is checked by seeding the matching fault in the simulator.
"""
from __future__ import annotations

import pytest

from guzzionboard import procedures
from guzzionboard.catalog import load_catalog
from guzzionboard.server import Api
from guzzionboard.workstation import Workstation


@pytest.fixture
def api(tmp_path):
    api = Api(Workstation(session_dir=tmp_path, record=False))
    api.ws.select(model="Griso 1200 8V", year=2012, transport="simulator")
    api.ws.connect(mode="simulator")
    api.get_identify({})
    # Keep the observation steps quick; the sampling itself is what matters.
    yield api
    api.ws.disconnect()


def run_to_end(api, key, answers=None, quick=True):
    answers = dict(answers or {})
    status, body = api.post_procedure_start({"key": key})
    assert status == 200, body
    if quick:
        for step in api._run.procedure.steps:
            object.__setattr__(step, "seconds", 0.6)
        api._run.sample_interval = 0.05

    state = body["run"]
    guard = 0
    while state["status"] == "running" and guard < 20:
        guard += 1
        step = state["step"]
        value = answers.get(step["key"]) if step else None
        state = api.post_procedure_advance({"value": value})[1]["run"]
    return state


# ------------------------------------------------------------ the catalog

def test_every_procedure_declares_what_it_needs():
    profile = load_catalog().ecu("5am")
    for procedure in procedures.PROCEDURES:
        assert procedure.name and procedure.purpose
        assert procedure.steps[-1].kind == "verdict"
        assert procedure.missing_for(profile) == []


def test_procedures_are_withheld_from_families_that_cannot_run_them():
    bare = load_catalog().ecu("16m")          # no parameters, no actuators yet
    offered = procedures.available(bare)
    assert all(not p["available"] for p in offered)
    pump = next(p for p in offered if p["key"] == "fuel_pressure")
    assert any("actuator fuel_pump" in m for m in pump["missing"])


def test_the_api_lists_them_with_availability(api):
    status, body = api.get_procedures({})
    assert status == 200
    assert {p["key"] for p in body["procedures"]} >= {"idle_health", "fuel_pressure"}
    assert all(p["available"] for p in body["procedures"])
    assert "interpretation" in body["note"]


def test_an_unknown_procedure_is_refused(api):
    assert api.post_procedure_start({"key": "polish_the_tank"})[0] == 400


def test_advancing_without_a_run_is_refused(tmp_path):
    api = Api(Workstation(session_dir=tmp_path, record=False))
    assert api.post_procedure_advance({})[0] == 400
    assert api.post_procedure_abort({})[0] == 400


# ------------------------------------------------------------- the runner

def test_the_idle_check_samples_and_reaches_a_verdict(api):
    state = run_to_end(api, "idle_health")
    assert state["status"] == "done"
    observed = next(r for r in state["results"] if r["kind"] == "observe")
    assert observed["stats"]["rpm"]["count"] > 1
    assert state["verdict"]["level"] in ("ok", "warn")


def test_the_idle_check_changes_its_mind_when_the_bike_has_an_air_leak(api):
    api.post_sim_engine({"auto_blip": False, "advance_s": 600})
    healthy = run_to_end(api, "idle_health")
    assert healthy["verdict"]["level"] == "ok"

    api.post_sim_faults({"faults": ["air_leak"]})
    leaky = run_to_end(api, "idle_health")
    assert leaky["verdict"]["level"] == "warn"
    assert leaky["verdict"]["suspects"][0].startswith("Air leak")


def test_the_charging_check_reads_the_charging_fault(api):
    api.post_sim_engine({"auto_blip": False})
    api.post_sim_faults({"faults": ["charging_failure"]})
    state = run_to_end(api, "charging_system")
    assert state["verdict"]["level"] == "bad"
    assert "Not charging" in state["verdict"]["title"]


def test_the_cold_sensor_check_catches_a_railed_sensor(api):
    api.post_sim_faults({"faults": ["coolant_sensor_open"]})
    state = run_to_end(api, "cold_sensor_check")
    assert state["verdict"]["level"] == "bad"
    assert "rail" in state["verdict"]["title"].lower()


def test_the_fuel_pressure_test_judges_the_decay(api):
    api.post_sim_engine({"running": False})
    good = run_to_end(api, "fuel_pressure",
                      {"pressure_primed": 3.0, "pressure_rested": 2.9})
    assert good["verdict"]["level"] == "ok"

    leaking = run_to_end(api, "fuel_pressure",
                         {"pressure_primed": 3.0, "pressure_rested": 1.2})
    assert leaking["verdict"]["level"] == "warn"
    assert "Leaking injector" in leaking["verdict"]["suspects"]


def test_a_number_step_refuses_nonsense(api):
    api.post_sim_engine({"running": False})
    api.post_procedure_start({"key": "fuel_pressure"})
    for step in api._run.procedure.steps:
        object.__setattr__(step, "seconds", 0.6)
    api._run.sample_interval = 0.05
    api.post_procedure_advance({})          # instruct
    api.post_procedure_advance({})          # observe the engine state
    api.post_procedure_advance({})          # actuate the pump
    status, body = api.post_procedure_advance({"value": "banana"})
    assert status == 400 and "number" in body["error"]


def test_the_injector_test_reports_a_silent_injector(api):
    api.post_sim_engine({"running": False})
    state = run_to_end(api, "injector_click",
                       {"heard_front": True, "heard_rear": False})
    assert state["verdict"]["level"] == "bad"
    assert "rear" in state["verdict"]["title"]


def test_an_actuator_step_is_refused_while_the_engine_runs(api):
    api.post_sim_engine({"running": True})
    api.get_live({"keys": ["rpm,stop_state"]})      # let the gate observe it

    api.post_procedure_start({"key": "fuel_pressure"})
    for step in api._run.procedure.steps:
        object.__setattr__(step, "seconds", 0.6)
    api._run.sample_interval = 0.05
    state = api.post_procedure_advance({})[1]["run"]     # instruct
    state = api.post_procedure_advance({})[1]["run"]     # observe: running
    state = api.post_procedure_advance({})[1]["run"]     # try to prime
    assert state["status"] == "blocked"
    blocked = state["results"][-1]
    assert blocked["blocked"] is True
    assert "safety gate" in blocked["detail"]
    # ...and a blocked run cannot be walked past.
    assert api.post_procedure_advance({})[0] == 400


def test_aborting_releases_outputs(api):
    api.post_sim_engine({"running": False})
    api.post_procedure_start({"key": "fuel_pressure"})
    for step in api._run.procedure.steps:
        object.__setattr__(step, "seconds", 0.6)
    api._run.sample_interval = 0.05
    api.post_procedure_advance({})          # instruct
    api.post_procedure_advance({})          # observe the engine state
    api.post_procedure_advance({})          # pump energised
    state = api.post_procedure_abort({})[1]["run"]
    assert state["status"] == "aborted"
    assert api.ws.require_service().active_outputs == {}


def test_a_run_records_itself_in_the_session_log(tmp_path):
    api = Api(Workstation(session_dir=tmp_path))
    api.ws.select(model="Griso 1200 8V", year=2012, transport="simulator")
    api.ws.connect(mode="simulator")
    api.get_identify({})
    run_to_end(api, "idle_health")
    kinds = [e.get("name") for e in api.ws.log.recent if e["kind"] == "action"]
    assert "procedure_start" in kinds and "procedure_end" in kinds
    api.ws.disconnect()
