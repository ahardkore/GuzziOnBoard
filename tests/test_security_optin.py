"""Operator opt-in for unverified SecurityAccess key providers.

No shipped key algorithm is bench-verified on Guzzi-fitted hardware, so the
provider registry refuses unverified providers by default. In-process tests
pass ``allow_unverified_key=True`` directly; users of the app could not —
until the gate grew an explicit, audited, session-scoped acceptance. These
tests pin the behaviour: refused by default, unblocked through the gate, and
exposed over the HTTP API surface.
"""
from __future__ import annotations

from guzzionboard.diagnostics import DiagnosticsService
from guzzionboard.programming import ProgrammingService
from guzzionboard.catalog import load_catalog
from guzzionboard.safety import Mode, SafetyGate, VehicleState
from guzzionboard.security import (
    SecurityUnavailable,
    providers_for,
)
from guzzionboard.transports.simulator import (
    EngineModel,
    SimulatedEcu,
    SimulatorTransport,
)

import pytest

from guzzionboard.server import Api
from guzzionboard.workstation import Workstation


# ------------------------------------------------------------- gate level


def test_unverified_keys_are_refused_until_explicitly_accepted():
    gate = SafetyGate(mode=Mode.READ_ONLY, state=VehicleState())
    assert gate.allow_unverified_keys is False

    gate.accept_unverified_key_risk(True)
    assert gate.allow_unverified_keys is True

    gate.accept_unverified_key_risk(False)
    assert gate.allow_unverified_keys is False

    events = [entry["event"] for entry in gate.audit_log]
    assert events == ["unverified_keys_accepted", "unverified_keys_declined"]


# ---------------------------------------------------------- service level


@pytest.fixture
def profile():
    load_catalog.cache_clear()
    return load_catalog().ecu("5am")


def _build(profile, tmp_path):
    ecu = SimulatedEcu(profile, engine=EngineModel(running=False))
    # The simulated ECU demands the real, shipped-but-unverified key —
    # the one transcribed from the reference tool's source.
    ecu.key_algorithm = providers_for("5am")[0]
    gate = SafetyGate(mode=Mode.READ_ONLY, state=VehicleState())
    diag = DiagnosticsService(profile, SimulatorTransport(ecu=ecu), gate)
    diag.connect()
    diag.identify()
    prog = ProgrammingService(diag, image_dir=tmp_path)
    prog.hardware_pacing = False
    return diag, gate, prog, ecu


def test_gate_acceptance_unlocks_and_completes_the_backup(profile, tmp_path):
    diag, gate, prog, ecu = _build(profile, tmp_path)
    prog.enter_programming_session()

    # default posture: refused before any frame leaves the tester
    with pytest.raises(SecurityUnavailable, match="only unverified"):
        prog.unlock()
    assert not ecu.security_unlocked

    # the operator's in-app route: accept the risk through the gate
    gate.accept_unverified_key_risk(True)
    result = prog.unlock()      # no in-process flag, gate flag wins
    assert result["unlocked"] is True
    assert result["verified"] is False
    assert ecu.security_unlocked

    # ... and the backup the reference readers provide now completes,
    # two reads verified byte-for-byte, still with no in-process flag.
    backup = prog.backup("flash")
    assert backup["verified"] is True
    events = [entry["event"] for entry in gate.audit_log]
    assert "unverified_keys_accepted" in events
    diag.disconnect()


# ------------------------------------------------------------- HTTP layer


def test_security_unverified_endpoint_sets_the_gate(tmp_path):
    api = Api(Workstation(session_dir=tmp_path, record=False))

    status, payload = api.post_security_unverified({"accept": True})
    assert status == 200
    assert payload["allow_unverified_keys"] is True
    assert api.ws.gate.allow_unverified_keys is True

    status, payload = api.post_security_unverified({"accept": False})
    assert status == 200
    assert api.ws.gate.allow_unverified_keys is False


def test_programming_enable_can_carry_the_key_opt_in(tmp_path):
    api = Api(Workstation(session_dir=tmp_path, record=False))

    # plain enablement leaves the key posture alone
    status, payload = api.post_programming_enable(
        {"acknowledgement": SafetyGate.PROGRAMMING_ACKNOWLEDGEMENT}
    )
    assert status == 200
    assert payload["unverified_keys_accepted"] is False

    # explicit combined opt-in sets both, and reports it
    status, payload = api.post_programming_enable(
        {
            "acknowledgement": SafetyGate.PROGRAMMING_ACKNOWLEDGEMENT,
            "allow_unverified_keys": True,
        }
    )
    assert status == 200
    assert payload["programming_enabled"] is True
    assert payload["unverified_keys_accepted"] is True
    assert api.ws.gate.allow_unverified_keys is True


def test_report_text_renders_gate_events_alongside_decisions(tmp_path):
    ws = Workstation(session_dir=tmp_path, record=False)
    ws.gate.enable_programming(SafetyGate.PROGRAMMING_ACKNOWLEDGEMENT)
    ws.gate.accept_unverified_key_risk(True)
    text = ws.report_text()
    # both the decision-shaped and event-shaped audit entries render
    assert "programming_enabled" in text
    assert "unverified_keys_accepted" in text
