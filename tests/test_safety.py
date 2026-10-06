"""The safety gate is the most important code in the project."""
from dataclasses import replace

import pytest

from guzzionboard.catalog import load_catalog
from guzzionboard.protocol.kwp2000 import Service
from guzzionboard.safety import (
    Mode,
    Risk,
    SafetyGate,
    TokenError,
    VehicleState,
)


@pytest.fixture
def profile():
    return load_catalog().ecu("5am")


@pytest.fixture
def gate():
    return SafetyGate(mode=Mode.SERVICE, state=VehicleState())


def ready(gate):
    """A fully satisfied state for a service-mode operation on hardware."""
    gate.state.identified = True
    gate.state.engine_running = False
    gate.state.battery_v = 13.2
    gate.state.checklist_accepted = True
    return gate


# ------------------------------------------------------------ basics

def test_reads_never_need_evidence(gate):
    decision = gate.evaluate("read", Risk.READ)
    assert decision.allowed


def test_read_only_mode_refuses_every_control_action(profile):
    gate = ready(SafetyGate(mode=Mode.READ_ONLY))
    decision = gate.evaluate_actuator(profile, profile.actuator("fuel_pump"))
    assert not decision.allowed
    assert any(c.name == "mode" for c in decision.failures)


def test_unidentified_ecu_blocks_control(profile, gate):
    ready(gate)
    gate.state.identified = False
    decision = gate.evaluate_actuator(profile, profile.actuator("fuel_pump"))
    assert not decision.allowed
    assert any(c.name == "identified" for c in decision.failures)


def test_unknown_engine_state_is_not_treated_as_stopped(profile, gate):
    ready(gate)
    gate.state.engine_running = None      # never observed
    decision = gate.evaluate_actuator(profile, profile.actuator("fuel_pump"))
    assert not decision.allowed
    assert any(c.name == "engine-off" for c in decision.failures)


def test_engine_running_blocks_an_engine_off_actuator(profile, gate):
    ready(gate)
    gate.state.engine_running = True
    decision = gate.evaluate_actuator(profile, profile.actuator("injector_front"))
    assert not decision.allowed


def test_stepper_needs_the_engine_running(profile, gate):
    ready(gate)
    decision = gate.evaluate_actuator(profile, profile.actuator("idle_stepper"))
    assert not decision.allowed
    assert any(c.name == "engine-running" for c in decision.failures)
    gate.state.engine_running = True
    assert gate.evaluate_actuator(profile, profile.actuator("idle_stepper")).allowed


def test_low_battery_blocks_control_on_hardware(profile, gate):
    ready(gate)
    gate.state.battery_v = 10.8
    decision = gate.evaluate_actuator(profile, profile.actuator("fuel_pump"))
    assert not decision.allowed
    assert any("battery" in c.detail for c in decision.failures)


def test_unaccepted_checklist_blocks_control_on_hardware(profile, gate):
    ready(gate)
    gate.state.checklist_accepted = False
    assert not gate.evaluate_actuator(profile, profile.actuator("fuel_pump")).allowed


def test_simulator_mode_skips_the_hardware_checks(profile):
    gate = SafetyGate(mode=Mode.SIMULATOR)
    gate.state.identified = True
    gate.state.engine_running = False
    # No battery reading and no checklist, yet allowed: nothing can be harmed.
    assert gate.evaluate_actuator(profile, profile.actuator("fuel_pump")).allowed


def test_happy_path_is_actually_reachable(profile, gate):
    ready(gate)
    decision = gate.evaluate_actuator(profile, profile.actuator("fuel_pump"))
    assert decision.allowed, decision.reason()
    assert decision.token


# -------------------------------------------------------- confidence

def test_low_confidence_definitions_cannot_run_control_actions():
    catalog = load_catalog()
    profile = catalog.ecu("11mp")           # inferred
    gate = ready(SafetyGate(mode=Mode.SERVICE))
    decision = gate.evaluate(
        "routine:throttle_learning", Risk.ADAPTATION,
        profile=profile, capability="throttle_learning",
    )
    assert not decision.allowed
    assert any(c.name in ("capability", "definition-confidence") for c in decision.failures)


def test_inferred_actuator_cannot_hide_inside_documented_profile(profile):
    actuator = replace(profile.actuator("fuel_pump"), confidence="inferred")
    decision = ready(SafetyGate(mode=Mode.SERVICE)).evaluate_actuator(
        profile, actuator
    )
    assert not decision.allowed
    assert any(c.name == "operation-confidence" for c in decision.failures)


def test_inferred_routine_cannot_hide_inside_documented_profile(profile):
    routine = replace(profile.routine("tps_reset"), confidence="inferred")
    decision = ready(SafetyGate(mode=Mode.SERVICE)).evaluate_routine(
        profile, routine
    )
    assert not decision.allowed
    assert any(c.name == "operation-confidence" for c in decision.failures)


# ------------------------------------------------------- programming

def test_programming_is_refused_even_with_perfect_evidence(profile, gate):

    ready(gate)
    gate.state.verified_backup = True
    decision = gate.evaluate("flash", Risk.IRREVERSIBLE, profile=profile)
    assert not decision.allowed
    assert any(c.name == "programming-enabled" for c in decision.failures)


def test_programming_still_needs_a_verified_backup_when_enabled(profile):
    gate = ready(SafetyGate(mode=Mode.PROGRAMMING, allow_programming=True))
    decision = gate.evaluate("flash", Risk.IRREVERSIBLE, profile=profile)
    assert not decision.allowed
    assert any(c.name == "verified-backup" for c in decision.failures)


# -------------------------------------------------- hardware family gate
# The single most destructive mistake in this ECU world: flashing an HW1xx
# image into an HW3xx ECU (or any other cross-family pair) bricks it.


def armed_gate(hardware: str) -> SafetyGate:
    """A programming-mode gate whose ECU reported ``hardware``."""
    gate = ready(SafetyGate(mode=Mode.PROGRAMMING, allow_programming=True))
    gate.state.verified_backup = True
    gate.state.base_map = True
    gate.state.ecu_hardware = hardware
    return gate


def test_an_hw1xx_image_cannot_be_flashed_into_an_hw3xx_ecu():
    gate = armed_gate("IAW7SMHW320")
    decision = gate.evaluate(
        "write:flash", Risk.IRREVERSIBLE, image_hardware="IAW7SMHW100"
    )
    assert not decision.allowed
    failure = next(c for c in decision.failures if c.name == "hardware-family")
    assert "IAW7SMHW100" in failure.detail and "IAW7SMHW320" in failure.detail
    assert "bricks the ECU" in failure.detail


def test_the_same_family_is_allowed_through_the_gate():
    gate = armed_gate("IAW7SMHW320")
    decision = gate.evaluate(
        "write:flash", Risk.IRREVERSIBLE,
        image_hardware="IAW7SMHW340",
        image_embedded_hardware=["IAW7SMHW340"],
    )
    hardware = [c for c in decision.checks if c.name == "hardware-family"]
    assert len(hardware) == 1 and hardware[0].passed
    assert not [c for c in decision.failures if c.name == "hardware-family"]


def test_the_gate_refuses_the_reverse_direction_too():
    gate = armed_gate("IAW7SMHW100")
    decision = gate.evaluate(
        "write:flash", Risk.IRREVERSIBLE, image_hardware="IAW7SMHW310"
    )
    assert not decision.allowed
    assert any(c.name == "hardware-family" for c in decision.failures)


def test_an_image_with_embedded_strings_of_another_family_is_refused():
    """Provenance says one thing, the bytes say another: the bytes lose."""
    gate = armed_gate("IAW7SMHW320")
    decision = gate.evaluate(
        "write:flash", Risk.IRREVERSIBLE,
        image_hardware="IAW7SMHW320",
        image_embedded_hardware=["IAW5AMHW610"],
    )
    assert not decision.allowed
    failure = next(c for c in decision.failures if c.name == "hardware-family")
    assert "IAW5AMHW610" in failure.detail


def test_an_image_without_captured_identity_is_refused_not_assumed():
    """No provenance, no embedded string: 'cannot confirm' must refuse."""
    gate = armed_gate("IAW7SMHW320")
    decision = gate.evaluate(
        "write:flash", Risk.IRREVERSIBLE, image_hardware="", image_embedded_hardware=[]
    )
    assert not decision.allowed
    failure = next(c for c in decision.failures if c.name == "hardware-family")
    assert "cannot be confirmed" in failure.detail


def test_an_ecu_that_did_not_report_hardware_never_receives_a_write():
    gate = armed_gate("")            # identified, but no usable Hardware field
    decision = gate.evaluate(
        "write:flash", Risk.IRREVERSIBLE, image_hardware="IAW7SMHW100"
    )
    assert not decision.allowed
    assert any(c.name == "hardware-family" for c in decision.failures)


def test_a_decision_without_an_image_says_nothing_about_hardware():
    """check-write without a candidate image must not invent a verdict."""
    gate = armed_gate("IAW7SMHW320")
    decision = gate.evaluate("write:flash", Risk.IRREVERSIBLE)
    assert decision.allowed
    assert not [c for c in decision.checks if c.name == "hardware-family"]


def test_hardware_family_refusals_are_audited():
    gate = armed_gate("IAW7SMHW320")
    gate.evaluate(
        "write:flash", Risk.IRREVERSIBLE, image_hardware="IAW7SMHW100"
    )
    refusal = gate.audit_log[-1]
    assert refusal["allowed"] is False
    assert any(
        c["name"] == "hardware-family" and not c["passed"] for c in refusal["checks"]
    )


# ------------------------------------------------------------- tokens

def test_token_is_single_use(profile, gate):
    ready(gate)
    decision = gate.evaluate_actuator(profile, profile.actuator("fuel_pump"))
    gate.consume(decision.token, "actuator:fuel_pump")
    with pytest.raises(PermissionError):
        gate.consume(decision.token, "actuator:fuel_pump")


def test_token_cannot_be_replayed_against_another_operation(profile, gate):
    ready(gate)
    decision = gate.evaluate_actuator(profile, profile.actuator("fuel_pump"))
    with pytest.raises(PermissionError, match="issued for"):
        gate.consume(decision.token, "actuator:injector_front")


def test_token_expires(profile, gate):
    ready(gate)
    decision = gate.evaluate_actuator(profile, profile.actuator("fuel_pump"))
    with pytest.raises(PermissionError, match="expired"):
        gate.consume(decision.token, "actuator:fuel_pump", max_age=-1)


def test_missing_token_is_refused(gate):
    with pytest.raises(PermissionError):
        gate.consume(None, "actuator:fuel_pump")


def test_token_errors_are_distinct_from_other_refusals(profile, gate):
    """The HTTP surface reports token trouble with its own code.

    A missing/stale/wrong-operation token is a TokenError (code 'token'),
    not the frame guard's plain PermissionError (code 'refused') and not a
    SafetyViolation (code 'safety') - the dispatch maps each differently.
    """
    ready(gate)
    decision = gate.evaluate_actuator(profile, profile.actuator("fuel_pump"))
    with pytest.raises(TokenError):
        gate.consume("not-a-token", "actuator:fuel_pump")
    with pytest.raises(TokenError):
        gate.consume(decision.token, "actuator:injector_front")
    ok = gate.evaluate_actuator(profile, profile.actuator("fuel_pump"))
    gate.consume(ok.token, "actuator:fuel_pump")      # right op: fine
    with pytest.raises(TokenError):
        gate.consume(ok.token, "actuator:fuel_pump")  # already spent
    assert issubclass(TokenError, PermissionError)


def test_a_refused_decision_mints_no_token(profile):
    gate = SafetyGate(mode=Mode.READ_ONLY)
    assert gate.evaluate_actuator(profile, profile.actuator("fuel_pump")).token is None


# -------------------------------------------------------- session guard

def test_session_guard_allows_reads_and_blocks_unarmed_writes(gate):
    guard = gate.session_guard()
    assert guard(Service.READ_DATA_BY_LOCAL_ID)
    assert guard(Service.READ_ECU_IDENTIFICATION)
    assert not guard(Service.IO_CONTROL_BY_LOCAL_ID)
    assert not guard(Service.CLEAR_DIAGNOSTIC_INFORMATION)


def test_session_guard_arms_exactly_one_service(gate):
    guard = gate.session_guard({Service.IO_CONTROL_BY_LOCAL_ID})
    assert guard(Service.IO_CONTROL_BY_LOCAL_ID)
    assert not guard(Service.START_ROUTINE_BY_LOCAL_ID)


def test_programming_services_are_blocked_even_when_armed(gate):
    guard = gate.session_guard({Service.WRITE_MEMORY_BY_ADDRESS, Service.TRANSFER_DATA})
    assert not guard(Service.WRITE_MEMORY_BY_ADDRESS)
    assert not guard(Service.TRANSFER_DATA)


# -------------------------------------------------------------- audit

def test_every_control_decision_is_audited(profile, gate):
    ready(gate)
    gate.evaluate_actuator(profile, profile.actuator("fuel_pump"))
    gate.evaluate("flash", Risk.IRREVERSIBLE, profile=profile)
    operations = [entry["operation"] for entry in gate.audit_log]
    assert "actuator:fuel_pump" in operations and "flash" in operations


def test_reads_do_not_pollute_the_audit_log(gate):
    gate.evaluate("read", Risk.READ)
    assert gate.audit_log == []


def test_refusal_reasons_are_human_readable(profile):
    gate = SafetyGate(mode=Mode.SERVICE)
    decision = gate.evaluate_actuator(profile, profile.actuator("fuel_pump"))
    reason = decision.reason()
    assert "identified" in reason
    assert len(reason) > 30
