"""The read/backup/verify/write path, exercised against the simulator."""
from __future__ import annotations

import tempfile

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

    The 5AM algorithm from 5am_util is real and reproduces its published
    pairs, but 'verified' means confirmed on a Guzzi-fitted ECU, which has
    not happened yet.
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
    # EcuProfile is frozen, and deliberately so.
    object.__setattr__(
        service.profile, "capabilities",
        list(service.profile.capabilities) + ["memory_write"],
    )
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
    with pytest.raises(Exception, match="validation|size"):
        service.write_region(FirmwareImage(data=b"\x00" * 1024), decision.token)


def test_write_without_a_verified_backup_is_refused(service, monkeypatch):
    image = service.read_region("flash")
    arm_for_writing(service, monkeypatch)
    service.gate.state.verified_backup = True   # satisfy the gate check...
    decision = service.check_write("flash")
    service.gate.state.verified_backup = False  # ...but lose it before writing
    with pytest.raises(SafetyViolation, match="verified-backup"):
        service.write_region(image, decision.token)


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
    assert service.pending_checkpoint("flash")["phase"] == "failed"


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
        "safe to retry" in line for line in ProgrammingService.recovery_advice("starting")
    )


def test_an_interrupted_write_leaves_a_resumable_checkpoint(service, tmp_path):
    path = service._checkpoint_path("flash")
    service._write_checkpoint(path, {"phase": "erased", "region": "flash"})
    pending = service.pending_checkpoint("flash")
    assert pending["phase"] == "erased"
    assert pending["recovery"]

    service._write_checkpoint(path, {"phase": "complete"})
    assert service.pending_checkpoint("flash") is None
