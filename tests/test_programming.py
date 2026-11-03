"""The read/backup/verify/write path, exercised against the simulator."""
from __future__ import annotations

import tempfile
from dataclasses import replace

import pytest

from guzzionboard.catalog import load_catalog
from guzzionboard.diagnostics import DiagnosticsService
from guzzionboard.firmware import FirmwareImage
from guzzionboard.programming import (
    ProgrammingError,
    ProgrammingService,
    VerificationFailed,
)
from guzzionboard.safety import Mode, SafetyGate, SafetyViolation, VehicleState
from guzzionboard.security import (
    Provider,
    SecurityUnavailable,
    best_provider,
    providers_for,
)
from guzzionboard.transports.simulator import (
    EngineModel,
    SimulatedEcu,
    SimulatorTransport,
)

ACK = SafetyGate.PROGRAMMING_ACKNOWLEDGEMENT

#: A simulator-only key routine. Emphatically not the real algorithm.
def sim_key(seed: bytes) -> bytes:
    return bytes(b ^ 0x5A for b in seed)


@pytest.fixture
def profile():
    # Fresh objects per test: the catalog is cached and these tests mutate
    # profile data to simulate a family whose write path has been verified.
    load_catalog.cache_clear()
    return load_catalog().ecu("5am")


@pytest.fixture
def service(profile, tmp_path):
    ecu = SimulatedEcu(profile, engine=EngineModel(running=False))
    ecu.key_algorithm = sim_key
    gate = SafetyGate(mode=Mode.READ_ONLY, state=VehicleState())
    diag = DiagnosticsService(profile, SimulatorTransport(ecu=ecu), gate)
    diag.connect()
    diag.identify()
    prog = ProgrammingService(diag, image_dir=tmp_path)
    prog.key_provider = Provider("5am", "simulator", sim_key, verified=True)
    # Real ECUs need ~12 s of pacing across erase and program; the simulator
    # does not, and the tests would crawl.
    prog.hardware_pacing = False
    yield prog
    diag.disconnect()


# -- capability reporting --------------------------------------------------


def test_capabilities_describe_the_5am_read_path(service):
    caps = service.capabilities()
    assert caps["protocol"] == "iaw_transfer"
    assert caps["read_supported"] is True
    assert caps["write_supported"] is False
    assert caps["write_blocked_reason"]
    assert caps["regions"]["flash"]["start"] == 0x4000
    assert caps["regions"]["flash"]["size"] == 0x4C000


def test_families_without_a_captured_reader_say_so():
    catalog = load_catalog()
    p8 = catalog.ecu("p8")
    assert p8.memory["read_supported"] is False
    assert "EPROM" in p8.memory["write_blocked_reason"]


# -- session and security --------------------------------------------------


def test_programming_session_and_baud_switch(service):
    steps = service.enter_programming_session()["steps"]
    assert all(s["ok"] for s in steps)
    names = [s["step"] for s in steps]
    assert "StartDiagnosticSession 0x85" in names
    assert "baud switch" in names
    # The 5AM transcript shows the tester address changing after the switch.
    assert service.diag._require().source == 0x01


def test_unlock_performs_the_seed_key_exchange(service):
    service.enter_programming_session()
    result = service.unlock()
    assert result["unlocked"]
    assert result["seed"]
    assert bytes.fromhex(result["key"].replace(" ", "")) == sim_key(
        bytes.fromhex(result["seed"].replace(" ", ""))
    )


def test_a_wrong_key_is_reported_without_retrying(service):
    service.key_provider = Provider("5am", "wrong", lambda s: b"\x00\x00\x00\x00")
    service.enter_programming_session()
    with pytest.raises(ProgrammingError, match="SecurityAccess rejected"):
        service.unlock()


def test_no_verified_key_algorithm_ships_for_any_guzzi_ecu():
    """Honesty check: nothing is marked verified until a bench ECU says so.

    The 5AM algorithm reproduces published pairs and the upstream utility
    reports a Guzzi write; GuzziOnBoard itself has not tested the integration
    on hardware.
    """
    for ecu_id in ("5am", "7sm", "15m", "15rc", "miug3"):
        assert not [p for p in providers_for(ecu_id) if p.verified]


def test_the_5am_algorithm_is_available_but_never_chosen_by_default():
    provider = providers_for("5am")[0]
    assert provider.name == "iaw5am-kwp-divmod"
    assert not provider.verified
    assert "5am_util" in provider.source
    with pytest.raises(SecurityUnavailable, match="only unverified"):
        best_provider("5am")
    assert best_provider("5am", allow_unverified=True) is provider


def test_the_5am_algorithm_reproduces_both_published_pairs():
    """Known-answer: the two seed/key pairs in the 5am_util transcript."""
    provider = providers_for("5am")[0]
    assert provider(bytes.fromhex("27882789")) == bytes.fromhex("DA786927")
    assert provider(bytes.fromhex("3CA93CAA")) == bytes.fromhex("0E816927")


def test_the_real_5am_algorithm_unlocks_the_simulated_ecu(profile):
    """End to end: the fixed simulator seed goes through the real provider."""
    ecu = SimulatedEcu(profile, engine=EngineModel(running=False))
    ecu.key_algorithm = providers_for("5am")[0]   # the ECU now checks the real key
    gate = SafetyGate(mode=Mode.READ_ONLY, state=VehicleState())
    diag = DiagnosticsService(profile, SimulatorTransport(ecu=ecu), gate)
    diag.connect()
    prog = ProgrammingService(diag, image_dir=tempfile.mkdtemp())
    prog.hardware_pacing = False
    prog.enter_programming_session()
    result = prog.unlock(allow_unverified=True)
    assert result["key"] == "da 78 69 27"        # the fixed seed is 27 88 27 89
    assert ecu.security_unlocked
    diag.disconnect()


def test_an_ecu_with_no_provider_explains_how_to_add_one():
    with pytest.raises(SecurityUnavailable, match="no SecurityAccess key provider"):
        best_provider("7sm")


# -- reading ---------------------------------------------------------------


def test_read_region_returns_the_whole_flash(service):
    image = service.read_region("flash")
    assert image.size == 0x4C000
    assert image.describe()["vector_table"]
    assert image.identity["Hardware"]
    assert image.meta["protocol"] == "iaw_transfer"


def test_read_reports_progress(service):
    seen = []
    service.read_region("flash", progress=lambda p: seen.append(p))
    assert len(seen) == 0x4C000 // 0x20
    assert seen[-1].fraction == 1.0
    assert seen[0].phase == "read"


def test_reading_requires_identification_first(profile, tmp_path):
    ecu = SimulatedEcu(profile, engine=EngineModel(running=False))
    ecu.key_algorithm = sim_key
    diag = DiagnosticsService(
        profile, SimulatorTransport(ecu=ecu), SafetyGate(Mode.READ_ONLY, VehicleState())
    )
    diag.connect()
    prog = ProgrammingService(diag, image_dir=tmp_path)
    with pytest.raises(ProgrammingError, match="identify"):
        prog.read_region("flash")
    diag.disconnect()


def test_a_region_with_unknown_geometry_refuses_instead_of_guessing(service):
    with pytest.raises(ProgrammingError, match="never been captured"):
        service.read_eeprom()


# -- backup ----------------------------------------------------------------


def test_backup_reads_twice_and_records_provenance(service, tmp_path):
    result = service.backup("flash")
    assert result["verified"] is True
    assert result["attempts"] == 2
    assert service.gate.state.verified_backup
    assert service.gate.state.backup_path == result["path"]

    import pathlib

    path = pathlib.Path(result["path"])
    assert path.stat().st_size == 0x4C000
    assert path.with_suffix(".bin.json").is_file()


def test_an_unreliable_link_fails_the_backup_rather_than_saving_it(service, monkeypatch):
    """Two disagreeing reads must never be stored as a backup."""
    calls = {"n": 0}
    real = service.read_region

    def flaky(*a, **kw):
        calls["n"] += 1
        image = real(*a, **kw)
        if calls["n"] == 2:
            corrupt = bytearray(image.data)
            corrupt[1234] ^= 0xFF
            image.data = bytes(corrupt)
        return image

    monkeypatch.setattr(service, "read_region", flaky)
    with pytest.raises(VerificationFailed, match="differ in 1 bytes"):
        service.backup("flash")
    assert not service.gate.state.verified_backup


# -- the base map (the guaranteed restore image) ---------------------------


def test_a_verified_backup_also_files_the_base_map(service):
    result = service.backup("flash")
    base = result["base_map"]
    assert base["is_base_map"] is True
    status = service.base_map_status("flash")
    assert status["intact"] is True
    assert service.gate.state.base_map is True
    assert status["path"] != result["path"], "the vault keeps its own copy"


def test_a_later_backup_does_not_displace_the_original_calibration(service):
    first = service.backup("flash")
    original = service.base_map_status("flash")["path"]
    second = service.backup("flash")
    assert second["base_map"]["is_base_map"] is False
    assert service.base_map_status("flash")["path"] == original
    assert len(service.base_map_status("flash")["restore_points"]) == 1
    assert first["verified"] and second["verified"]


def test_a_base_map_that_went_missing_fails_the_gate(service, monkeypatch):
    service.backup("flash")
    arm_for_writing(service, monkeypatch)
    assert service.check_write("flash").allowed

    import pathlib as _pathlib

    _pathlib.Path(service.base_map_status("flash")["path"]).unlink()
    decision = service.check_write("flash")
    assert not decision.allowed
    assert any(c.name == "base-map" for c in decision.failures)


def test_writing_without_a_base_map_is_refused(service, monkeypatch):
    """The gate cannot be talked into a write; it re-reads the vault."""
    image = service.backup("flash")
    arm_for_writing(service, monkeypatch)
    decision = service.check_write("flash")
    assert decision.allowed

    import pathlib as _pathlib

    _pathlib.Path(service.base_map_status("flash")["path"]).unlink()
    service.gate.state.base_map = True              # claim one anyway...
    with pytest.raises(SafetyViolation, match="base-map"):
        service.write_region(                       # ...the vault disagrees
            FirmwareImage.from_file(image["path"]), decision.token
        )


def test_an_existing_image_can_be_filed_as_the_base_map(service, tmp_path):
    read = service.read_region("flash")
    path = read.save(tmp_path / "earlier-backup.bin")
    service.save_base_map(path, "flash")
    assert service.base_map_status("flash")["intact"] is True


def test_the_restore_plan_names_the_file_and_the_order(service):
    assert service.restore_plan("flash")["ready"] is False
    service.backup("flash")
    plan = service.restore_plan("flash")
    assert plan["ready"] is True
    assert plan["path"] in " ".join(plan["steps"])
    assert any("charger" in step for step in plan["steps"])


# -- writing ---------------------------------------------------------------


def test_writing_is_refused_while_the_catalog_has_no_verified_write_path(service):
    image = service.read_region("flash")
    service.gate.enable_programming(ACK)
    with pytest.raises(SafetyViolation):
        service.write_region(image, "token")


def test_programming_opt_in_requires_the_exact_acknowledgement(service):
    gate = service.gate
    assert not gate.allow_programming
    for wrong in ("yes", "", ACK.upper(), ACK[:-1]):
        with pytest.raises(SafetyViolation):
            gate.enable_programming(wrong)
    assert not gate.allow_programming

    gate.enable_programming(f"  {ACK}  ")
    assert gate.allow_programming
    assert any(e["event"] == "programming_enabled" for e in gate.audit_log)

    gate.disable_programming()
    assert not gate.allow_programming


def test_the_frame_guard_allows_reads_but_not_downloads(service):
    """TransferData is how the IAW reads flash, so a read may send it."""
    from guzzionboard.protocol.kwp2000 import Service

    gate = service.gate
    read_guard = gate.session_guard({Service.TRANSFER_DATA}, purpose="read")
    assert read_guard(Service.TRANSFER_DATA)
    assert not read_guard(Service.REQUEST_DOWNLOAD)
    assert not read_guard(Service.WRITE_MEMORY_BY_ADDRESS)

    write_guard = gate.session_guard({Service.TRANSFER_DATA})
    assert not write_guard(Service.TRANSFER_DATA)
    gate.enable_programming(ACK)
    assert write_guard(Service.TRANSFER_DATA)
    assert not write_guard(Service.ECU_RESET)


def arm_for_writing(service, monkeypatch):
    """Satisfy every precondition the gate asks for, honestly.

    Nothing is stubbed: the catalog is given a verified write path, the
    vehicle state is made valid, and the operator opts in. The gate then
    issues a real token.
    """
    monkeypatch.setitem(service.profile.memory, "write_supported", True)
    monkeypatch.setitem(
        service.profile.memory["programming"], "confidence", "verified-capture"
    )
    monkeypatch.setitem(service.profile.memory["regions"]["flash"], "writable", True)
    # Never mutate the cached frozen catalog profile across test cases.
    monkeypatch.setattr(service, "profile", replace(
        service.profile, capabilities=tuple(service.profile.capabilities) + ("memory_write",),
    ))
    service.gate.mode = Mode.PROGRAMMING
    service.gate.state.battery_v = 13.2
    service.gate.state.engine_running = False
    service.gate.state.checklist_accepted = True
    service.gate.enable_programming(ACK)


def test_a_fully_armed_gate_does_allow_a_write(service, monkeypatch):
    """Writing is gated, not forbidden: satisfy the gate and it says yes."""
    service.backup("flash")
    arm_for_writing(service, monkeypatch)
    decision = service.check_write("flash")
    assert decision.allowed, decision.reason()
    assert decision.token


def test_write_refuses_an_image_that_fails_validation(service, monkeypatch):
    service.backup("flash")
    arm_for_writing(service, monkeypatch)
    decision = service.check_write("flash")
    # Provenance a real backup would carry, so the refusal below is about
    # the image's *content* (blank, wrong size), not its missing identity -
    # the missing-identity refusal has its own tests.
    original = service.read_region("flash")
    with pytest.raises(Exception, match="validation|size"):
        service.write_region(
            FirmwareImage(data=b"\x00" * 1024, identity=original.identity),
            decision.token,
        )


def test_write_without_a_verified_backup_is_refused(service, monkeypatch):
    image = service.read_region("flash")
    arm_for_writing(service, monkeypatch)
    service.gate.state.verified_backup = True   # satisfy the gate check...
    decision = service.check_write("flash")
    service.gate.state.verified_backup = False  # ...but lose it before writing
    with pytest.raises(SafetyViolation, match="verified-backup"):
        service.write_region(image, decision.token)


# -- the hardware-family gate ----------------------------------------------
# "Don't flash HW1xx versions in a HW3xx ECU and vice versa. You will brick
# your ECU!" - the 7SM reference documentation. The gate has to enforce it
# even when everything else about the file is perfect.


def test_an_hw1xx_image_is_refused_by_an_hw3xx_ecu(service, monkeypatch):
    """The headline mistake, end to end: not one byte reaches the ECU."""
    ecu = service.diag.transport.ecu
    # The bench ECU now reports an HW3xx hardware string, and identification
    # is what teaches the gate that (never the filename or the selection).
    ecu.identity = {**ecu.identity, "Hardware": "IAW7SMHW320"}
    service.diag.identify()
    assert service.gate.state.ecu_hardware == "IAW7SMHW320"

    service.backup("flash")
    arm_for_writing(service, monkeypatch)

    original = service.read_region("flash")
    # A file that is perfect in every other way: right ECU, right size, real
    # bytes - it just came off an HW1xx unit.
    hw1xx = FirmwareImage(
        data=original.data,
        ecu_id=original.ecu_id,
        region=original.region,
        identity={**original.identity, "Hardware": "IAW7SMHW100"},
    )

    decision = service.check_write("flash", image=hw1xx)
    assert not decision.allowed
    assert any(c.name == "hardware-family" for c in decision.failures)

    with pytest.raises(SafetyViolation, match="hardware-family.*bricks the ECU"):
        service.write_region(hw1xx, "token")

    # The refusal happened before the write sequence began: nothing was
    # erased, downloaded or programmed.
    assert not ecu.erased
    assert not ecu.programmed
    assert not ecu.download_pending
    assert not ecu.upload_blob
    assert service.pending_checkpoint("flash") is None


def test_a_matching_family_still_writes_after_the_gate(service, monkeypatch):
    """The gate refuses cross-family files, not writing itself."""
    service.backup("flash")
    arm_for_writing(service, monkeypatch)

    original = service.read_region("flash")
    same_family = FirmwareImage(
        data=original.data,
        identity={**original.identity, "Hardware": "IAW5AMHW640"},
    )
    decision = service.check_write("flash", image=same_family)
    assert decision.allowed, decision.reason()
    result = service.write_region(same_family, decision.token)
    assert result["ok"] and result["verified"]


def test_an_image_without_provenance_is_refused_even_with_a_token(
    service, monkeypatch
):
    """A valid token for a provenance-free file still buys nothing."""
    service.backup("flash")
    arm_for_writing(service, monkeypatch)

    original = service.read_region("flash")
    mystery = FirmwareImage(data=original.data)      # no captured identity
    decision = service.check_write("flash")
    assert decision.allowed                           # no image on the bench...
    with pytest.raises(SafetyViolation, match="hardware-family"):
        service.write_region(mystery, decision.token)  # ...but there is now
    assert not service.diag.transport.ecu.erased


def test_a_complete_write_round_trip_succeeds_and_verifies(service, monkeypatch):
    """Erase, transfer, program, read back, compare."""
    service.backup("flash")
    arm_for_writing(service, monkeypatch)

    original = service.read_region("flash")
    modified = bytearray(original.data)
    modified[5000:5004] = b"\xde\xad\xbe\xef"
    new_image = FirmwareImage(data=bytes(modified), identity=original.identity)

    phases = []
    decision = service.check_write("flash")
    result = service.write_region(
        new_image, decision.token,
        progress=lambda p: phases.append(p.phase),
    )
    assert result["ok"] and result["verified"]
    assert result["sha256"] == new_image.sha256
    assert {"erase", "write", "program", "read"} <= set(phases)

    # The ECU really holds the new bytes.
    assert service.read_region("flash").data[5000:5004] == b"\xde\xad\xbe\xef"
    assert service.pending_checkpoint("flash") is None


def test_a_write_follows_the_documented_5am_sequence(service, monkeypatch):
    """Records, routine arms, encoded transfer and checksum - as documented.

    This is the fidelity check for the 5am_util transcription: the simulator
    enforces the sequence, and the wire payload is the *encoded* blob, not
    the plain image.
    """
    from guzzionboard.firmware import iaw5am_upload_blob

    service.backup("flash")
    arm_for_writing(service, monkeypatch)

    original = service.read_region("flash")
    ecu = service.diag.transport.ecu

    decision = service.check_write("flash")
    service.write_region(original, decision.token)

    # 0x3B writer and date records, in order, before anything else.
    assert ecu.records_written == [b"\x98\x20", b"\x99\x20"]
    # The erase ran as 31 02 then 33 02, and programming as 31 01 then 33
    # 01 - four routine operations, not a RequestDownload shortcut.
    assert ecu.erased
    routine_ids = [entry[1] for entry in ecu.routine_log]
    assert routine_ids == [0x02, 0x02, 0x01, 0x01]
    # The upload was the encoded blob, byte for byte.
    assert bytes(ecu.upload_blob) == iaw5am_upload_blob(original.data)
    # The program routine validated the checksum of what it actually holds.
    assert ecu.last_program_checksum_ok is True
    assert ecu.programmed


def test_the_ecu_refuses_a_download_without_the_writer_records(service, monkeypatch):
    """5am_util: skip the 0x3B records and RequestDownload fails."""
    service.backup("flash")
    arm_for_writing(service, monkeypatch)
    monkeypatch.setitem(
        service.profile.memory["programming"]["write"], "records", []
    )
    image = service.read_region("flash")
    decision = service.check_write("flash")
    with pytest.raises(Exception, match="conditionsNotCorrect|rejected"):
        service.write_region(image, decision.token)
    assert service.pending_checkpoint("flash")["phase"] == "failed_after_erase_requested"


def test_a_corrupted_write_fails_verification_and_leaves_recovery(service, monkeypatch):
    """If the ECU does not contain what we sent, say so loudly."""
    service.backup("flash")
    arm_for_writing(service, monkeypatch)
    service.diag.transport.ecu.corrupt_write_at = 0x4000 + 5001

    original = service.read_region("flash")
    modified = bytearray(original.data)
    modified[5000:5004] = b"\xde\xad\xbe\xef"

    decision = service.check_write("flash")
    with pytest.raises(VerificationFailed, match="DO NOT power the ECU down"):
        service.write_region(
            FirmwareImage(data=bytes(modified), identity=original.identity),
            decision.token,
        )
    pending = service.pending_checkpoint("flash")
    assert pending["phase"] == "verify_failed"
    assert pending["backup"]
    assert any("Restore" in l or "Retry" in l for l in pending["recovery"])


def test_a_token_cannot_be_spent_twice(service, monkeypatch):
    service.backup("flash")
    arm_for_writing(service, monkeypatch)
    image = service.read_region("flash")
    decision = service.check_write("flash")
    service.write_region(image, decision.token)
    with pytest.raises(PermissionError, match="no valid confirmation token"):
        service.write_region(image, decision.token)


# -- recovery --------------------------------------------------------------


def test_recovery_advice_is_specific_to_the_phase():
    advice = ProgrammingService.recovery_advice("erased")
    assert any("erased but not written" in line for line in advice)
    assert any("charger" in line for line in advice)

    assert any(
        "erase was not yet requested" in line for line in ProgrammingService.recovery_advice("starting")
    )


def test_an_interrupted_write_leaves_a_resumable_checkpoint(service, tmp_path):
    path = service._checkpoint_path("flash")
    service._write_checkpoint(path, {"phase": "erased", "region": "flash"})
    pending = service.pending_checkpoint("flash")
    assert pending["phase"] == "erased"
    assert pending["recovery"]

    service._write_checkpoint(path, {"phase": "complete"})
    assert service.pending_checkpoint("flash") is None


def test_programming_read_rejects_short_address_response(service, monkeypatch):
    from guzzionboard.programming import Region
    from guzzionboard.protocol.kwp2000 import ProtocolError
    monkeypatch.setattr(service.diag.session, 'read_memory_by_address', lambda *a, **k: b'\x00')
    with pytest.raises(ProtocolError, match='returned 1 bytes, expected 4'):
        service._read_by_address(Region('flash',0,4,block=4))


@pytest.mark.parametrize('data', [
    b'\x22\x00\x00\x00\x04\x11\x22\x33\x44', # wrong subfunction
    b'\x21\x00\x01\x00\x04\x11\x22\x33\x44', # wrong address
    b'\x21\x00\x00\x00\x03\x11\x22\x33',      # wrong announced size
    b'\x21\x00\x00\x00\x04\x11\x22\x33',      # truncated data
    b'\x21\x00\x00\x00\x04\x11\x22\x33\x44\x55', # excess data
])
def test_programming_transfer_read_rejects_invalid_blocks(service, monkeypatch, data):
    from guzzionboard.programming import Region
    from guzzionboard.protocol.kwp2000 import ProtocolError
    class Frame:
        def __init__(self, data): self.data = data
        def hex(self): return self.data.hex()
    monkeypatch.setattr(service.diag.session, 'request', lambda payload: Frame(data))
    with pytest.raises(ProtocolError, match='memory block'):
        service._read_by_transfer(Region('flash',0,4,block=4))


def test_read_succeeds_when_optional_report_thread_cannot_start(service, monkeypatch):
    """A synthetic read result must survive failure to start the optional reporter."""
    import threading
    from guzzionboard import read_sharing

    monkeypatch.setattr(read_sharing, 'configured', lambda: True)
    def unavailable(_thread):
        raise RuntimeError('thread limit')
    monkeypatch.setattr(threading.Thread, 'start', unavailable)
    image = service.read_region('flash')
    assert image.source == 'read' and image.size == service.profile.memory['regions']['flash']['size']


def test_failed_reidentification_clears_all_vehicle_evidence_and_confirmations(service, monkeypatch):
    diag, gate = service.diag, service.gate
    gate.state.battery_v = 13
    gate.state.engine_running = False
    gate.state.verified_backup = gate.state.base_map = True
    gate.state.backup_path, gate.state.base_map_path = 'old-backup', 'old-base'
    gate._tokens['old'] = ('write:flash', 0)
    def fail(_option):
        raise ProtocolError('synthetic interrupted identification')
    from guzzionboard.protocol.kwp2000 import ProtocolError
    monkeypatch.setattr(diag.session, 'read_ecu_identification', fail)
    with pytest.raises(ProtocolError, match='interrupted'):
        diag.identify()
    assert diag.identity is None and not gate.state.identified
    assert not gate.state.ecu_hardware and gate.state.ecu_confidence == 'unknown'
    assert gate.state.battery_v is None and gate.state.engine_running is None
    assert not gate.state.verified_backup and not gate.state.base_map
    assert not gate.state.backup_path and not gate.state.base_map_path and not gate._tokens


@pytest.mark.parametrize('payload', [b'\x67', b'\x67\x01', b'\x67\x02\x00'])
def test_programming_unlock_does_not_accept_malformed_seed(service, monkeypatch, payload):
    from guzzionboard.protocol.kwp2000 import decode_frame, encode_request
    session = service.diag._require()
    calls = []
    def fake_request(request):
        calls.append(bytes(request))
        return decode_frame(encode_request(payload, target=0xf1, source=0x10))
    monkeypatch.setattr(session, 'request', fake_request)
    service.unlocked = True  # A previous unlock is not evidence for this exchange.
    with pytest.raises(ProgrammingError, match='seed'):
        service.unlock()
    assert not service.unlocked and len(calls) == 1


def test_5am_source_block_read_uses_selected_windows_and_labels_gaps(service, monkeypatch):
    from types import SimpleNamespace
    calls = []

    class SourceSession:
        write_guard = None
        block = 0

        def request(self, payload):
            calls.append(bytes(payload))
            if payload[1] == 0x11:
                self.block = payload[-1]
                return SimpleNamespace(data=bytes([0x11, 0x02]))
            # The newer upstream simulator uses this fixed metadata on every
            # window. It is not evidence that the ECU echoes each offset.
            return SimpleNamespace(data=bytes.fromhex('21 40 00 00 20') + bytes([self.block]) * 32)

    session = SourceSession()
    monkeypatch.setattr(service.diag, "_require", lambda: session)
    result = service._read_5am_source_blocks(service.region("flash"))
    assert len(result) == 0x4C000
    assert result[:0x4000] == b"\x01" * 0x4000
    assert result[0x4000:0x14000] == b"\xff" * 0x10000
    assert result[0x14000:0x18000] == b"\x06" * 0x4000
    assert result[-0x4000:] == b"\x13" * 0x4000
    setups = [p[-1] for p in calls if p[1] == 0x11]
    assert setups == [1, *range(6, 20)]
    reads = [p for p in calls if p[1] == 0x21]
    assert len(reads) == 15 * 512
    assert reads[0] == bytes.fromhex("36 21 00 40 00 20")
    assert reads[511] == bytes.fromhex("36 21 00 7f e0 20")
    assert reads[512] == reads[0]


def test_5am_source_read_rejects_short_or_wrong_subfunction(service, monkeypatch):
    from types import SimpleNamespace
    from guzzionboard.protocol.kwp2000 import ProtocolError

    class BadSession:
        write_guard = None
        def request(self, payload):
            return SimpleNamespace(data=b"\x11\x02" if payload[1] == 0x11 else b"\x21\x00")

    session = BadSession()
    monkeypatch.setattr(service.diag, "_require", lambda: session)
    with pytest.raises(ProtocolError, match="invalid 5AM read response"):
        service._read_5am_source_blocks(service.region("flash"))
    assert session.write_guard is not None


def test_5am_physical_baud_switch_changes_source_before_request(service, monkeypatch):
    from guzzionboard.protocol.kwp2000 import decode_frame
    session = service.diag._require()
    tx = []
    old_write = session.connection.write
    monkeypatch.setattr(session.connection, "write", lambda raw: (tx.append(raw), old_write(raw))[1])
    speeds = []
    monkeypatch.setattr(session.connection, "set_baudrate", speeds.append, raising=False)
    monkeypatch.setattr(service.diag.transport, "is_physical", True)
    waits = []
    monkeypatch.setattr(service, "_wait", waits.append)
    service.enter_programming_session()
    switch = next(decode_frame(raw) for raw in tx if decode_frame(raw).payload == bytes.fromhex("10 0c 0c 09"))
    assert switch.source == 1
    assert speeds == [64200]
    assert waits == [0.06]


def test_5am_physical_partial_read_is_not_promoted_to_backup_or_evidence(service, monkeypatch):
    monkeypatch.setattr(service.diag.transport, "is_physical", True)
    monkeypatch.setattr(service, "enter_programming_session", lambda: {})
    monkeypatch.setattr(service, "unlock", lambda **kw: {})
    monkeypatch.setattr(service, "_read_5am_source_blocks", lambda region: bytearray(b"\xff" * region.size))
    image = service.read_region()
    assert image.source == "research-read"
    assert image.meta["verified_backup"] is False
    assert image.meta["synthetic_blocks"] == [2, 3, 4, 5]
    with pytest.raises(ProgrammingError, match="partial.*verified backup"):
        service.backup()


def test_partial_5am_sidecar_refuses_flash_validation(service, tmp_path):
    partial = FirmwareImage(data=b"\xff" * 0x4C000, ecu_id="5am", region="flash",
                            source="research-read", meta={"verified_backup": False})
    path = partial.save(tmp_path / "partial.bin")
    reloaded = FirmwareImage.from_file(path)
    findings = reloaded.validate_for(service.profile)
    assert any(f.level == "fatal" and f.check == "experimental_read" for f in findings)


def test_5am_failed_baud_switch_does_not_continue(service, monkeypatch):
    session = service.diag._require()
    original = session.try_request
    monkeypatch.setattr(session, "try_request", lambda payload, **kw: None if list(payload) == [0x10, 0x0c, 0x0c, 0x09] else original(payload, **kw))
    speeds = []
    monkeypatch.setattr(session.connection, "set_baudrate", speeds.append, raising=False)
    monkeypatch.setattr(service.diag.transport, "is_physical", True)
    with pytest.raises(ProgrammingError, match="did not confirm the baud switch"):
        service.enter_programming_session()
    assert speeds == []
    assert session.source == 0xF1


def test_memory_read_holds_session_lock_through_transfer(service, monkeypatch):
    locked = []
    def read_blocks(region):
        locked.append(service.diag._lock._is_owned())
        return bytearray(b"\xff" * region.size)
    monkeypatch.setattr(service.diag.transport, "is_physical", True)
    monkeypatch.setattr(service, "enter_programming_session", lambda: {})
    monkeypatch.setattr(service, "unlock", lambda **kw: {})
    monkeypatch.setattr(service, "_read_5am_source_blocks", read_blocks)
    service.read_region()
    assert locked == [True]


def test_write_readiness_reports_disabled_writer_and_region_without_token(service, monkeypatch):
    """A green policy gate must not hide a disabled implementation."""
    backup = service.backup('flash')
    arm_for_writing(service, monkeypatch)
    monkeypatch.setitem(service.profile.memory, 'write_supported', False)
    decision = service.check_write('flash')
    assert not decision.allowed and decision.token is None
    assert 'write-supported' in decision.reason()
    with pytest.raises(SafetyViolation, match='write-supported') as error:
        service.write_region(FirmwareImage.from_file(backup['path']), 'unused')
    assert not error.value.decision.allowed
    assert not service.diag.transport.ecu.erased

    monkeypatch.setitem(service.profile.memory, 'write_supported', True)
    monkeypatch.setitem(service.profile.memory['regions']['flash'], 'writable', False)
    decision = service.check_write('flash')
    assert not decision.allowed and decision.token is None
    assert 'writable-region' in decision.reason()


def test_5am_write_session_switches_physical_baud_before_timing(service, monkeypatch):
    """Synthetic transcript: validates ordering, not physical flash operation."""
    from types import SimpleNamespace
    session = service.diag._require()
    session.source = 1  # A prior read uses 0x01; write must start at 0xF1.
    events = []
    monkeypatch.setattr(service.diag.transport, "is_physical", True)
    monkeypatch.setattr(session, "try_request", lambda payload: (events.append(("tx", session.source, bytes(payload))), SimpleNamespace(data=b"\x85", hex=lambda: "ok"))[1])
    monkeypatch.setattr(session.connection, "set_baudrate", lambda baud: events.append(("baud", baud)), raising=False)
    monkeypatch.setattr(service, "_wait", lambda seconds: events.append(("wait", seconds)))
    service._enter_write_session()
    assert events == [
        ("tx", 0xF1, bytes.fromhex("10 85 03")),
        ("wait", 0.06), ("baud", 38400),
        ("tx", 0xF1, bytes.fromhex("83 03 1e 02 0a 14 00")),
    ]


def test_5am_write_session_baud_failure_stops_before_timing(service, monkeypatch):
    from types import SimpleNamespace
    session = service.diag._require()
    sent = []
    monkeypatch.setattr(service.diag.transport, "is_physical", True)
    monkeypatch.setattr(service, "_wait", lambda _: None)
    monkeypatch.setattr(session, "try_request", lambda payload: (sent.append(bytes(payload)), SimpleNamespace(data=b"\x85", hex=lambda: "ok"))[1])
    def fail(_):
        raise OSError("unsupported baud")
    monkeypatch.setattr(session.connection, "set_baudrate", fail, raising=False)
    with pytest.raises(ProgrammingError, match="write baud switch failed"):
        service._enter_write_session()
    assert sent == [bytes.fromhex("10 85 03")]


def test_5am_extra_blocks_are_read_not_placeholder_and_mismatches_abort(service, monkeypatch):
    """Synthetic ECU; real access to the four skipped blocks is unknown."""
    from types import SimpleNamespace
    from guzzionboard.protocol.kwp2000 import ProtocolError
    calls = []
    class Session:
        write_guard = None
        block = 0
        mismatch = False
        def request(self, payload):
            calls.append(bytes(payload))
            if payload[1] == 0x11:
                self.block = payload[-1]
                return SimpleNamespace(data=b"\x11\x02")
            offset = (payload[3] << 8) | payload[4]
            if self.mismatch and self.block == 2:
                return SimpleNamespace(data=b"\x21\x00")
            return SimpleNamespace(data=bytes([0x21, offset >> 8, offset & 255, 0, 0x20]) + bytes([self.block]) * 32)
    session = Session()
    monkeypatch.setattr(service.diag, "_require", lambda: session)
    result = service._read_5am_source_blocks(service.region("flash"), attempt_skipped=True)
    assert [p[-1] for p in calls if p[1] == 0x11] == list(range(1, 20))
    assert result == b"".join(bytes([i]) * 0x4000 for i in range(1, 20))
    calls.clear()
    session.mismatch = True
    with pytest.raises(ProtocolError, match="invalid 5AM read response at block 2"):
        service._read_5am_source_blocks(service.region("flash"), attempt_skipped=True)
    assert not any(p[1] == 0x11 and p[-1] > 2 for p in calls)
    assert session.write_guard is not None


def test_5am_extra_block_attempt_requires_confirmation_and_stays_research(service, monkeypatch, tmp_path):
    monkeypatch.setattr(service.diag.transport, "is_physical", True)
    entered = []
    monkeypatch.setattr(service, "enter_programming_session", lambda: entered.append(True))
    monkeypatch.setattr(service, "unlock", lambda **kw: {})
    monkeypatch.setattr(service, "_read_5am_source_blocks", lambda region, *, attempt_skipped=False: bytearray(b"\x01" * region.size) if attempt_skipped else None)
    with pytest.raises(ProgrammingError, match="confirm"):
        service.read_region(attempt_5am_skipped_blocks=True)
    assert not entered
    image = service.read_region(attempt_5am_skipped_blocks=True, experimental_confirmation=True)
    assert image.source == "research-read"
    assert image.meta["synthetic_blocks"] == []
    assert image.meta["extra_blocks_attempted"] is True
    assert image.meta["verified_backup"] is False
    path = image.save(tmp_path / "extended.bin")
    assert any(f.level == "fatal" and f.check == "experimental_read" for f in FirmwareImage.from_file(path).validate_for(service.profile))
    with pytest.raises(ProgrammingError, match="partial.*verified backup"):
        service.backup()


def test_5am_extra_block_api_saves_only_confirmed_research_image(service, monkeypatch, tmp_path):
    from guzzionboard.server import Api
    from pathlib import Path
    monkeypatch.setattr(service.diag.transport, "is_physical", True)
    monkeypatch.setattr(service, "enter_programming_session", lambda: {})
    unlock_calls = []
    monkeypatch.setattr(service, "unlock", lambda **kw: unlock_calls.append(kw))
    monkeypatch.setattr(service, "_read_5am_source_blocks", lambda region, *, attempt_skipped=False: bytearray(b"\x01" * region.size))
    api = Api(object())
    api._programming = lambda: service
    class Immediate:
        def start(self, name, fn): return fn(lambda _: None)
    api.jobs = Immediate()
    with pytest.raises(ProgrammingError, match="confirm"):
        api.post_memory_read({"region": "flash", "attempt_5am_skipped_blocks": True})
    assert not list(tmp_path.iterdir())
    status, result = api.post_memory_read({"region": "flash", "attempt_5am_skipped_blocks": True,
                                           "confirm_research_read": True, "confirm_5am_read_key": True})
    assert unlock_calls == [{"allow_unverified": True}]
    assert not service.gate.allow_unverified_keys  # one read does not authorize later writes
    assert status == 202 and result["research_only"] is True
    assert result["describe"]["meta"]["extra_blocks_attempted"] is True
    assert result["describe"]["meta"]["verified_backup"] is False
    assert Path(result["path"]).is_file() and Path(result["path"] + ".json").is_file()


def test_5am_erase_requires_positive_completion_before_download(service, monkeypatch):
    from types import SimpleNamespace
    calls = []
    class Synthetic:
        def request(self, payload, **kw):
            calls.append((bytes(payload), kw))
            if payload[:2] == [0x31, 0x02]:
                return SimpleNamespace(data=b'\x02')
            raise ProtocolError('erase completion timed out')
    from guzzionboard.protocol.kwp2000 import ProtocolError
    monkeypatch.setattr(service.diag, '_require', lambda: Synthetic())
    with pytest.raises(ProtocolError, match='timed out'):
        service._erase(service.region('flash'))
    assert calls[-1] == (b'\x33\x02', {'timeout':3.0, 'pending_timeout':90.0})
    assert all(req[0] != 0x34 for req, _ in calls)


def test_5am_program_uses_source_long_frame_forms_and_bounded_wait(service, monkeypatch):
    from types import SimpleNamespace
    calls = []
    class Synthetic:
        def request(self, payload, **kw):
            calls.append((bytes(payload), kw))
            return SimpleNamespace(data=b'\x01')
    monkeypatch.setattr(service.diag, '_require', lambda: Synthetic())
    image = FirmwareImage(data=bytes(0x4c000))
    service._finalise(image, service.region('flash'), checksum=0xabcd)
    assert calls[0] == (b'\x37', {'force_long':True})
    assert calls[1] == (bytes.fromhex('31 01 00 40 00 04 ff ff ab cd'), {'force_long':True})
    assert calls[2] == (bytes.fromhex('33 01'), {'timeout':3.0, 'pending_timeout':120.0})


def test_write_exclusively_holds_diagnostic_lock(service, monkeypatch):
    seen = []
    def locked(*args, **kwargs):
        seen.append(service.diag._lock._is_owned())
        return {'test': True}
    monkeypatch.setattr(service, '_write_region_locked', locked)
    assert service.write_region(FirmwareImage(data=b''), 'unused') == {'test': True}
    assert seen == [True]


def test_5am_encoding_failure_happens_before_any_erase(service, monkeypatch):
    service.backup('flash')
    arm_for_writing(service, monkeypatch)
    image = service.read_region('flash')
    decision = service.check_write('flash')
    def fail(_):
        raise ProgrammingError('synthetic encoder failure')
    monkeypatch.setattr(service, '_upload_payload', fail)
    with pytest.raises(ProgrammingError, match='encoder failure'):
        service.write_region(image, decision.token)
    assert not service.diag.transport.ecu.erased
    assert service.pending_checkpoint('flash') is None


def test_5am_erase_arm_failure_marks_erase_as_uncertain(service, monkeypatch):
    service.backup('flash')
    arm_for_writing(service, monkeypatch)
    image = service.read_region('flash')
    decision = service.check_write('flash')
    def fail(_):
        raise ProgrammingError('synthetic erase reply lost')
    monkeypatch.setattr(service, '_erase', fail)
    with pytest.raises(ProgrammingError, match='erase reply lost'):
        service.write_region(image, decision.token)
    checkpoint = service.pending_checkpoint('flash')
    assert checkpoint['phase'] == 'failed_after_erase_requested'
    assert checkpoint['erase_may_have_started'] is True
    assert any('may not have a valid program' in line for line in checkpoint['recovery'])


def test_5am_writer_record_response_mismatch_stops_before_erase(service, monkeypatch):
    from types import SimpleNamespace
    from guzzionboard.protocol.kwp2000 import ProtocolError
    sent = []
    class Synthetic:
        def request(self, payload):
            sent.append(bytes(payload))
            return SimpleNamespace(data=b'\x99')
    monkeypatch.setattr(service.diag, '_require', lambda: Synthetic())
    with pytest.raises(ProtocolError, match='writer/date record response mismatch'):
        service._pre_write_records()
    assert sent == [bytes.fromhex('3b 98 20')]


# -- unlocked physical writers, external backup attestation & 15-block verify --


class TestUnlockedPhysicalWritersAndAttestation:
    """Unlocking implemented KWP2000 writers without mutating catalog JSON."""

    def test_writer_unlock_and_lock_gate_and_capabilities(self, service):
        # Default state: 5am catalog has write_supported=False, so non-simulated
        # capabilities report write_supported=False until explicitly unlocked.
        service.diag.gate.mode = Mode.SERVICE
        service.diag.gate.state.battery_v = 13.4
        service.diag.gate.state.checklist_accepted = True
        caps_locked = service.capabilities()
        assert caps_locked["implemented_writer_available"] is True
        assert caps_locked["implemented_writer_regions"] == ["flash"]
        assert caps_locked["unverified_hardware_writer_unlocked"] is False
        assert caps_locked["write_supported"] is False

        with pytest.raises(SafetyViolation, match="unverified ECU write risk"):
            service.diag.gate.enable_unverified_hardware_writes("wrong phrase")

        service.diag.gate.enable_unverified_hardware_writes(
            SafetyGate.UNVERIFIED_WRITER_ACKNOWLEDGEMENT
        )
        caps_unlocked = service.capabilities()
        assert caps_unlocked["unverified_hardware_writes_enabled"] is True
        assert caps_unlocked["unverified_hardware_writer_unlocked"] is True
        assert caps_unlocked["write_supported"] is True
        assert service.region("flash").writable is True

        service.diag.gate.disable_unverified_hardware_writes()
        assert service.capabilities()["write_supported"] is False
        assert service.region("flash").writable is False

    def test_external_backup_attestation_normalizes_320kb_and_unlocks_5am_partial_verify_write(
        self, service, tmp_path, monkeypatch
    ):
        from pathlib import Path
        # Read a real 311,296-byte flash image (0x4000..0x50000) from the simulated 5AM,
        # then prepend 0x4000 bytes (0x0000..0x4000) to form a 327,680-byte GuzziDiag/IAW5xReader dump.
        raw_304k = service.read_region("flash")
        assert len(raw_304k.data) == 311296
        raw_320k = (b"\xff" * 0x4000) + raw_304k.data
        assert len(raw_320k) == 327680
        ext_file = tmp_path / "external_guzzidiag_dump.bin"
        ext_file.write_bytes(raw_320k)

        # Fresh gate on physical SERVICE/PROGRAMMING mode (non-simulator).
        service.diag.gate.mode = Mode.SERVICE
        service.diag.gate.state.battery_v = 13.6
        service.diag.gate.state.checklist_accepted = True
        service.diag.gate.state.engine_running = False
        service.diag.gate.state.verified_backup = False
        service.diag.gate.state.base_map = False

        with pytest.raises(ProgrammingError, match="repeat exactly"):
            service.attest_external_backup(ext_file, acknowledgement="wrong")

        attested = service.attest_external_backup(
            ext_file,
            acknowledgement=ProgrammingService.EXTERNAL_BACKUP_ACKNOWLEDGEMENT,
            note="GuzziDiag 320 KB stock dump",
        )
        assert attested["verified"] is True
        assert attested["sliced_from_full_dump"] is True
        assert Path(attested["path"]).stat().st_size == 311296
        assert service.diag.gate.state.verified_backup is True
        assert service.diag.gate.state.base_map is True

        # Enable programming + unlock implemented 5AM writer without mutating profile!
        service.diag.gate.enable_programming(ACK)
        service.diag.gate.enable_unverified_hardware_writes(
            SafetyGate.UNVERIFIED_WRITER_ACKNOWLEDGEMENT
        )

        # Emulate physical IAW 5AM post-write readback where blocks 2..5 return 0xFF
        # placeholders with meta["synthetic_blocks"] == [2, 3, 4, 5]:
        real_read_region = service.read_region

        def physical_5am_partial_readback(region_name="flash", **kwargs):
            full = real_read_region(region_name, **kwargs)
            buf = bytearray(full.data)
            buf[0x4000:0x14000] = b"\xff" * 0x10000
            return FirmwareImage(
                data=bytes(buf),
                ecu_id=full.ecu_id,
                region=full.region,
                source="research-read",
                identity=full.identity,
                meta={"synthetic_blocks": [2, 3, 4, 5]},
            )

        monkeypatch.setattr(service, "read_region", physical_5am_partial_readback)

        # Run unlocked physical write + 15-block partial readback verification!
        decision = service.check_write("flash", image=raw_304k)
        assert decision.allowed, decision.reason
        write_res = service.write_region(raw_304k, decision.token)
        assert write_res["verified"] is True
        assert write_res["partial_readback_unverified_blocks"] == [2, 3, 4, 5]

        # And if one of the 15 readable blocks is corrupted, verification MUST still fail!
        service.diag.transport.ecu.corrupt_write_at = 0x4000 + 0x15000
        decision2 = service.check_write("flash", image=raw_304k)
        with pytest.raises(VerificationFailed):
            service.write_region(raw_304k, decision2.token)

