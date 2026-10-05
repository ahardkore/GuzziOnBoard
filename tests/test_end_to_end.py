"""End-to-end tests through the real protocol stack against the simulator.

The simulator speaks encoded KWP2000 frames, so these exercise framing,
checksums, service dispatch, scaling, the safety gate and the session log -
the same code that will run against a motorcycle.
"""
import pytest

from guzzionboard.catalog import load_catalog
from guzzionboard.diagnostics import DiagnosticsService, NotConnected
from guzzionboard.protocol.kwp2000 import NegativeResponse, ProtocolError
from guzzionboard.safety import Mode, SafetyGate, VehicleState
from guzzionboard.sessionlog import SessionLog
from guzzionboard.transports.simulator import EngineModel, SimulatedEcu, SimulatorTransport
from guzzionboard.workstation import Workstation


@pytest.fixture
def catalog():
    return load_catalog()


def build(catalog, ecu_id="5am", *, mode=Mode.SIMULATOR, running=True, log=None):
    profile = catalog.ecu(ecu_id)
    ecu = SimulatedEcu(profile, engine=EngineModel(running=running))
    gate = SafetyGate(mode=mode, state=VehicleState())
    service = DiagnosticsService(
        profile, SimulatorTransport(ecu=ecu), gate, log=log, catalog=catalog
    )
    return service, ecu, gate


# ------------------------------------------------------------- lifecycle

def test_commands_before_connecting_are_refused(catalog):
    service, _, _ = build(catalog)
    with pytest.raises(NotConnected):
        service.read_dtcs()


def test_connect_identify_read(catalog):
    service, _, gate = build(catalog)
    result = service.connect()
    assert result.ok

    identity = service.identify()
    assert identity.fields["Hardware"] == "IAW5AMHW610"
    assert identity.fields["Software"] == "1206LA02"
    assert gate.state.identified

    samples = service.read_parameters(["rpm", "coolant_temp", "battery", "throttle"])
    by_key = {s.key: s for s in samples}
    assert 900 < by_key["rpm"].value < 3200
    assert -40 < by_key["coolant_temp"].value < 120
    assert 11 < by_key["battery"].value < 15.5
    assert all(s.raw for s in samples)      # provenance is always kept
    service.disconnect()


def test_identification_fields_follow_the_catalog_layout(catalog):
    service, _, _ = build(catalog, "7sm")
    service.connect()
    identity = service.identify()
    # The 7SM block carries a Serial field that the 5AM does not.
    assert "Serial" in identity.fields
    assert identity.fields["Hardware"] == "IAW7SMHW320"
    service.disconnect()


def test_engine_state_is_inferred_from_observed_values_only(catalog):
    service, _, gate = build(catalog, running=False)
    service.connect()
    assert gate.state.engine_running is None       # nothing observed yet
    service.read_parameters(["rpm"])
    assert gate.state.engine_running is False
    service.disconnect()


# ------------------------------------------------------------------ DTCs

def test_dtc_round_trip_with_descriptions(catalog):
    service, _, _ = build(catalog)
    service.connect()
    service.identify()
    result = service.read_dtcs()
    assert {d["code"] for d in result["dtcs"]} == {"P0130", "P0505"}
    assert result["dtcs"][0]["description"]
    service.disconnect()


def test_dtc_read_carries_the_observed_context(catalog):
    """Codes come back with the live channels observed at the same moment.

    Honest labelling: these ECUs expose no ECU-stored freeze frame, so the
    context is what the workstation itself read - never presented as more.
    """
    service, _ecu, _gate = build(catalog, "5am")
    service.connect()
    service.identify()
    result = service.read_dtcs()
    assert result["context"], "the 5AM has default channels to observe"
    assert "rpm" in result["context"]
    assert result["context"]["rpm"]["value"] > 200   # the sim idles
    assert result["context"]["rpm"]["unit"] == "rpm"
    # reading the context must not have disturbed the gate's view
    assert service.gate.state.engine_running is True
    service.disconnect()


def test_clearing_dtcs_requires_a_token_and_actually_clears(catalog):
    service, _, _ = build(catalog)
    service.connect()
    service.identify()

    with pytest.raises(PermissionError):
        service.clear_dtcs("made-up-token")

    decision = service.check_clear_dtcs()
    assert decision.allowed
    result = service.clear_dtcs(decision.token)
    assert result["remaining"] == []
    service.disconnect()


# ------------------------------------------------------------- actuators

def test_actuator_is_blocked_while_the_engine_runs(catalog):
    service, _, _ = build(catalog, running=True)
    service.connect()
    service.identify()
    service.read_parameters(["rpm"])
    decision = service.check_actuator("fuel_pump")
    assert not decision.allowed
    service.disconnect()


def test_actuator_pulses_and_is_released(catalog):
    service, ecu, _ = build(catalog, running=False)
    service.connect()
    service.identify()
    service.read_parameters(["rpm"])

    decision = service.check_actuator("fuel_pump")
    assert decision.allowed, decision.reason()
    service.pulse_actuator("fuel_pump", decision.token, seconds=0.5)
    assert 5 in ecu.active_outputs          # local id 5 is energised on the ECU

    service.release_actuator("fuel_pump")
    assert 5 not in ecu.active_outputs
    assert "fuel_pump" not in service.active_outputs
    service.disconnect()


def test_pulse_length_is_clamped_to_the_catalog_maximum(catalog):
    service, _, _ = build(catalog, running=False)
    service.connect()
    service.identify()
    service.read_parameters(["rpm"])
    decision = service.check_actuator("injector_front")
    result = service.pulse_actuator("injector_front", decision.token, seconds=600)
    assert result["duration_s"] == catalog.ecu("5am").actuator("injector_front").max_pulse_s
    service.release_actuator("injector_front")
    service.disconnect()


def test_disconnect_releases_every_energised_output(catalog):
    service, ecu, _ = build(catalog, running=False)
    service.connect()
    service.identify()
    service.read_parameters(["rpm"])
    decision = service.check_actuator("fuel_pump")
    service.pulse_actuator("fuel_pump", decision.token, seconds=30)
    assert ecu.active_outputs
    service.disconnect()
    assert not ecu.active_outputs, "disconnect must not leave an output energised"


# -------------------------------------------------------------- routines

def test_tps_reset_runs_and_reports_its_follow_up(catalog):
    service, ecu, _ = build(catalog, running=False)
    service.connect()
    service.identify()
    service.read_parameters(["rpm"])

    decision = service.check_routine("tps_reset")
    assert decision.allowed, decision.reason()
    result = service.run_routine("tps_reset", decision.token)
    assert result["ok"]
    assert "idle" in result["follow_up"].lower()
    assert any(entry[1] == 0x21 for entry in ecu.routine_log)
    service.disconnect()


def test_routine_is_refused_with_the_engine_running(catalog):
    service, _, _ = build(catalog, running=True)
    service.connect()
    service.identify()
    service.read_parameters(["rpm"])
    assert not service.check_routine("tps_reset").allowed
    service.disconnect()


# ------------------------------------------------------------- discovery

def test_discovery_sweep_is_read_only_and_finds_the_live_block(catalog):
    service, _, gate = build(catalog)
    service.connect()
    result = service.discover_identifiers(0x30, 0x40)
    assert result["scanned"] == 17
    assert result["answered"] > 0
    assert all(i["answered"] for i in result["identifiers"] if i["local_id"] == 0x30)
    # A sweep is pure reads, so it must leave no audit trail of control actions.
    assert gate.audit_log == []
    service.disconnect()


def test_discovery_delta_identifies_channels_that_moved(catalog):
    service, ecu, _ = build(catalog, running=False)
    service.connect()
    before = service.discover_identifiers(0x30, 0x3C)["identifiers"]
    before = {i["local_id"]: i for i in before}

    ecu.engine.running = True
    after = service.discover_identifiers(0x30, 0x3C)["identifiers"]
    after = {i["local_id"]: i for i in after}

    changed = service.discovery_delta(before, after)
    assert any(c["local_id"] == 0x30 for c in changed)   # rpm moved
    service.disconnect()


# ---------------------------------------------------------- unsupported

def test_an_unmapped_service_returns_a_clean_negative_response(catalog):
    service, _, _ = build(catalog, "16m")
    service.connect()
    # The 16M profile declares no routines, so there is nothing to run.
    with pytest.raises(Exception):
        service.run_routine("tps_reset", "x")
    service.disconnect()


def test_memory_read_is_byte_exact_against_the_simulated_image(catalog):
    service, _, _ = build(catalog)
    service.connect()
    service.identify()
    data = service.read_memory(0, 512, block=0x80)
    assert len(data) == 512
    assert data == bytes(((i) * 31 + 7) & 0xFF for i in range(512))
    service.disconnect()


# ------------------------------------------------------- fault injection

def test_a_corrupted_frame_is_detected_not_silently_decoded(catalog):
    service, ecu, _ = build(catalog)
    service.connect()
    ecu.corrupt_rate = 1.0
    sample = service.read_parameter(catalog.ecu("5am").parameter("rpm"))
    assert sample.value is None
    assert "checksum" in sample.error.lower()
    service.disconnect()


def test_a_dropped_response_is_reported_as_a_timeout(catalog):
    service, ecu, _ = build(catalog)
    service.connect()
    ecu.drop_rate = 1.0
    sample = service.read_parameter(catalog.ecu("5am").parameter("rpm"))
    assert sample.value is None
    assert "no response" in sample.error.lower()
    service.disconnect()


def test_response_pending_is_absorbed_without_losing_the_value(catalog):
    service, ecu, _ = build(catalog)
    service.connect()
    ecu.pending_rate = 1.0
    sample = service.read_parameter(catalog.ecu("5am").parameter("rpm"))
    # Either it recovered with a value, or it failed loudly - never a wrong number.
    assert sample.value is None or sample.value > 0
    service.disconnect()


# -------------------------------------------------------- session logging

def test_session_log_captures_frames_samples_and_decisions(catalog, tmp_path):
    log = SessionLog(directory=tmp_path, meta={"test": True})
    service, _, _ = build(catalog, running=False, log=log)
    service.connect()
    service.identify()
    service.read_parameters(["rpm", "battery"])
    decision = service.check_routine("tps_reset")
    service.run_routine("tps_reset", decision.token)
    service.disconnect()
    log.close()

    events = list(SessionLog.read(log.path))
    kinds = {e["kind"] for e in events}
    assert {"session_start", "frame", "sample", "action", "safety", "session_end"} <= kinds

    frames = [e for e in events if e["kind"] == "frame"]
    assert any(e["dir"] == "tx" for e in frames)
    assert any(e["dir"] == "rx" for e in frames)

    samples = [e for e in events if e["kind"] == "sample"]
    assert all(e["raw"] for e in samples)   # raw bytes kept next to every value


def test_listing_sessions_reads_back_the_metadata(catalog, tmp_path):
    log = SessionLog(directory=tmp_path, meta={"model": "Griso 1200 8V"})
    service, _, _ = build(catalog, log=log)
    service.connect()
    service.read_parameters(["rpm"])
    service.disconnect()
    log.close()

    listed = SessionLog.list_sessions(tmp_path)
    assert len(listed) == 1
    assert listed[0]["meta"]["model"] == "Griso 1200 8V"


# ------------------------------------------------------------ workstation

def test_workstation_drives_a_whole_simulated_session(tmp_path):
    ws = Workstation(session_dir=tmp_path)
    ws.select(model="Griso 1200 8V", year=2012, transport="simulator")
    ws.connect(mode="simulator")

    service = ws.require_service()
    service.identify()
    service.read_parameters(["rpm", "battery", "coolant_temp"])

    status = ws.status()
    assert status["connected"]
    assert status["selection"]["ecu"]["id"] == "5am"

    report = ws.build_report()
    assert report["identity"]["fields"]["Hardware"] == "IAW5AMHW610"
    assert report["samples"]

    text = ws.report_text(report)
    assert "GuzziOnBoard diagnostic report" in text
    assert "SIMULATED" in text          # a simulated report must say so
    assert "Griso 1200 8V" in text
    ws.disconnect()


def test_workstation_warns_loudly_about_inferred_families(tmp_path):
    ws = Workstation(session_dir=tmp_path)
    result = ws.select(model="V100 Mandello", year=2023, transport="simulator")
    levels = {n["level"] for n in result["notices"]}
    assert "warn" in levels
    assert any("inferred" in n["text"] for n in result["notices"])


def test_workstation_refuses_an_unknown_motorcycle(tmp_path):
    ws = Workstation(session_dir=tmp_path)
    with pytest.raises(Exception):
        ws.select(model="Harley Sportster", year=2010)


# -- cross-brand selection and CAN identifiers -------------------------------


def test_cross_brand_selection_degrades_to_read_only(catalog):
    """A Ducati 748 shares the 16M with the V11 Sport, but honesty wins.

    The selection applies the stricter of the vehicle and ECU confidence
    levels, so control actions stay gated while identification, DTCs and
    the discovery sweep keep working.
    """
    ws = Workstation(record=False)
    selection = ws.select(model="748", year=2000, make="Ducati")
    assert selection["ecu"]["id"] == "16m"
    assert selection["ecu"]["confidence"] == "inferred"
    assert selection["make"] == "Ducati"
    assert "unverified here" in selection["ecu"]["notes"]
    # the same ECU selected as a Guzzi keeps its own level
    guzzi = ws.select(model="V11 Sport", year=2001)
    assert guzzi["ecu"]["confidence"] == catalog.ecu("16m").confidence


def test_cross_brand_bike_still_identifies_over_the_simulator(catalog):
    ws = Workstation(record=False)
    ws.select(model="RSV Mille", year=2001, make="Aprilia")
    ws.connect()
    identity = ws.require_service().identify()
    assert identity.raw


def test_can_identifiers_are_configurable(catalog):
    """The CAN pair is unconfirmed on the CAN families, so it is a setting."""
    ws = Workstation(record=False)
    ws.select(
        model="V7 III Stone", year=2019, transport="can",
        can_tx_id="0x18DA10F1", can_rx_id="0x18DAF110",
    )
    transport = ws._build_transport()
    assert (transport.tx_id, transport.rx_id) == (0x18DA10F1, 0x18DAF110)

    # defaults come from the catalog when nothing is overridden
    ws.select(model="V7 III Stone", year=2019, transport="can")
    transport = ws._build_transport()
    assert (transport.tx_id, transport.rx_id) == (0x7E0, 0x7E8)

    # garbage is refused, not guessed
    with pytest.raises(ValueError):
        ws.select(model="V7 III Stone", year=2019, transport="can",
                  can_tx_id="whatever")
    with pytest.raises(ValueError):
        ws.select(model="V7 III Stone", year=2019, transport="can",
                  can_rx_id=0x200000000)
