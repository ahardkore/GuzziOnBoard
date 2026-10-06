"""Simulation carries its own, proven, honestly-labelled capability set.

The catalogue profiles answer for real hardware, so they deliberately
under-declare whatever never met a bench (no shipped ECU declares
write).  The simulator is hardware we command: its complete flash cycle
is part of the protocol test suite, so a session that talks to the
simulator presents those capabilities — flagged as simulated everywhere
they are reported.  This file also locks the two seams the reachable
write path needed: a programming session entered via the opt-in really
is in programming mode, and an image the workstation *saved* (bytes +
``.json`` sidecar) carries enough provenance to be flashed back.
"""
from __future__ import annotations

import json
import pathlib
import time

import pytest

from guzzionboard.catalog import load_catalog
from guzzionboard.firmware import FirmwareImage
from guzzionboard.safety import Mode, SafetyGate
from guzzionboard.server import Api
from guzzionboard.workstation import Workstation

ACK = SafetyGate.PROGRAMMING_ACKNOWLEDGEMENT


# ------------------------------------------------------------- the overlay


def test_simulated_session_flips_memory_capabilities():
    ws = Workstation(record=False)
    ws.select(model="Griso 1200 8V", year=2012, transport="simulator")
    ws.connect(mode="simulator")
    profile = ws.require_service().profile
    memory = profile.memory
    assert memory["write_supported"] is True
    assert memory["regions"]["flash"]["writable"] is True
    # regions whose geometry is genuinely unknown stay unwritable —
    # the simulation does not invent an eeprom
    assert memory["regions"]["eeprom"]["writable"] is False
    assert memory["simulated"] is True
    assert "Simulated ECU" in memory["simulation_note"]
    # the original hardware block reason is preserved, not erased
    assert "real IAW 5AM" in memory["simulation_note"] or "real" in memory["simulation_note"]
    assert "memory_write" in profile.capabilities
    ws.disconnect()


def test_the_catalogue_profile_is_never_mutated():
    ws = Workstation(record=False)
    before = load_catalog().ecu("5am")
    ws.select(model="Griso 1200 8V", year=2012, transport="simulator")
    ws.connect(mode="simulator")
    after = load_catalog().ecu("5am")
    ws.disconnect()
    assert after is before                                   # same object
    assert after.memory.get("write_supported") is False
    assert "memory_write" not in after.capabilities


def test_capabilities_endpoint_flags_the_simulation():
    ws = Workstation(record=False)
    ws.select(model="Griso 1200 8V", year=2012, transport="simulator")
    ws.connect(mode="simulator")
    status, mem = Api(ws).get_memory({})
    assert status == 200
    caps = mem["capabilities"]
    assert caps["write_supported"] is True
    assert caps["simulated"] is True
    assert caps["simulation_note"]
    assert caps["write_blocked_reason"] == ""
    ws.disconnect()


def test_disconnect_drops_the_simulated_profile():
    ws = Workstation(record=False)
    ws.select(model="Griso 1200 8V", year=2012, transport="simulator")
    ws.connect(mode="simulator")
    ws.disconnect()
    assert ws._session_profile is None


# --------------------------------- the programming-mode elevation seam


def test_enable_programming_enters_programming_mode_and_disable_restores():
    gate = SafetyGate(mode=Mode.SIMULATOR)
    gate.enable_programming(ACK)
    assert gate.mode is Mode.PROGRAMMING
    gate.disable_programming()
    assert gate.mode is Mode.SIMULATOR
    # a wrong acknowledgement must not change anything
    gate2 = SafetyGate(mode=Mode.READ_ONLY)
    with pytest.raises(Exception):
        gate2.enable_programming("sure why not")
    assert gate2.mode is Mode.READ_ONLY
    assert gate2.allow_programming is False


# ------------------------------------------------ the provenance seam


def test_from_file_picks_up_the_save_sidecar(tmp_path):
    image = FirmwareImage(
        data=b"\x00" * 64,
        ecu_id="5am",
        identity={"Hardware": "IAW5AMHW610", "Software": "1206LA02"},
    )
    path = image.save(tmp_path / "backup.bin")
    loaded = FirmwareImage.from_file(path)
    assert loaded.identity["Hardware"] == "IAW5AMHW610"
    assert loaded.ecu_id == "5am"
    assert loaded.data == b"\x00" * 64


def test_a_file_without_a_sidecar_stays_unprovenanced_and_refused(tmp_path):
    bare = tmp_path / "mystery.bin"
    bare.write_bytes(b"\xAA" * 64)
    loaded = FirmwareImage.from_file(bare)
    assert loaded.identity == {}


def test_a_broken_sidecar_is_ignored(tmp_path):
    path = tmp_path / "odd.bin"
    path.write_bytes(b"\xBB" * 64)
    tmp_path.joinpath("odd.bin.json").write_text("{not json", encoding="utf-8")
    assert FirmwareImage.from_file(path).identity == {}


# --------------------------------------------- the full flash round trip


@pytest.fixture
def api(tmp_path):
    return Api(Workstation(session_dir=tmp_path, record=False))


def _wait_job(api, timeout=600.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = api.get_memory({})[1]["job"]
        if job["state"] in ("done", "failed"):
            assert job["state"] == "done", f"job failed: {job.get('error')}"
            return job["result"]
        time.sleep(0.2)
    raise AssertionError("job timed out")


def test_a_complete_flash_round_trip_at_the_webpage_s_pleasure(api):
    """Every step the ECU-memory view drives, in order, all simulation."""
    api.post_select({"model": "Griso 1200 8V", "year": 2012,
                     "transport": "simulator"})
    api.post_connect({"mode": "simulator"})
    api.get_identify({})
    api.get_live({})
    api.post_checklist({"accepted": True})
    api.post_security_unverified({"accept": True})

    api.post_memory_backup({"region": "flash"})
    backup = _wait_job(api)
    assert backup["verified"] is True
    path = pathlib.Path(backup["path"])

    status, validation = api.post_memory_validate(
        {"path": str(path), "region": "flash"}
    )
    assert status == 200 and validation["ok"]

    api.post_programming_enable(
        {"acknowledgement": ACK, "allow_unverified_keys": True}
    )
    status, decision = api.post_memory_check_write({"region": "flash"})
    assert status == 200
    assert decision["allowed"], decision.get("reason")
    assert decision["token"]
    passed = {c["name"] for c in decision["checks"] if c["passed"]}
    assert {"mode", "capability", "programming-enabled"} <= passed

    status, _job = api.post_memory_write(
        {"path": str(path), "token": decision["token"], "region": "flash"}
    )
    assert status == 202
    written = _wait_job(api)
    assert written["ok"] is True and written["verified"] is True
    assert written["bytes"] == len(path.read_bytes())

    # disabling programming makes the whole surface refuse again
    api.post_programming_disable({})
    status, again = api.post_memory_check_write({"region": "flash"})
    assert status == 200 and again["allowed"] is False
    assert again["token"] is None
    api.post_disconnect({})
