"""Central safety policy.

Every operation that can change the state of a motorcycle passes through here.
The gate is wired into :class:`~guzzionboard.protocol.kwp2000.KWP2000Session`
as its ``write_guard``, so the check cannot be bypassed by calling a service
method directly - the frame simply never reaches the transport.

Design rules:

* Read-only is the default and needs no evidence.
* Every precondition is named, and a refusal says exactly which ones failed.
* Nothing is implicit: a confirmation token has to be minted per operation and
  is consumed on use.
"""
from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field
from enum import Enum

from .catalog import Actuator, EcuProfile, Routine, meets
from .firmware import hardware_family
from .protocol.kwp2000 import MUTATING_SERVICES, Service


class Mode(str, Enum):
    """How much the workstation is allowed to do."""

    SIMULATOR = "simulator"   # no hardware; writes are pointless but harmless
    READ_ONLY = "read_only"   # hardware attached, observation only
    SERVICE = "service"       # actuator tests and adaptation resets
    PROGRAMMING = "programming"  # memory writes; not enabled in this build


#: Risk classes, used to decide how much evidence an operation needs.
class Risk(str, Enum):
    READ = "read"
    REVERSIBLE = "reversible"      # an actuator pulse; stops when released
    ADAPTATION = "adaptation"      # changes learned values
    IRREVERSIBLE = "irreversible"  # memory write


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str = ""

    def as_dict(self) -> dict:
        return {"name": self.name, "passed": self.passed, "detail": self.detail}


@dataclass(frozen=True)
class Decision:
    allowed: bool
    operation: str
    risk: Risk
    checks: tuple[Check, ...]
    token: str | None = None

    @property
    def failures(self) -> tuple[Check, ...]:
        return tuple(c for c in self.checks if not c.passed)

    def reason(self) -> str:
        if self.allowed:
            return "all preconditions satisfied"
        return "; ".join(f"{c.name}: {c.detail or 'not satisfied'}" for c in self.failures)

    def as_dict(self) -> dict:
        return {
            "allowed": self.allowed,
            "operation": self.operation,
            "risk": self.risk.value,
            "checks": [c.as_dict() for c in self.checks],
            "reason": self.reason(),
            "token": self.token,
        }


class SafetyViolation(PermissionError):
    def __init__(self, decision: Decision):
        self.decision = decision
        super().__init__(f"{decision.operation} refused: {decision.reason()}")


#: The refusal wording every hardware-family mismatch shares.  The 7SM
#: documentation is blunt about the concrete case: *"Don't flash HW1xx
#: versions in a HW3xx ECU and vice versa. You will brick your ECU!"*
BRICK_WARNING = (
    "flashing an image from one hardware family into an ECU of another "
    "bricks the ECU - never flash HW1xx into HW3xx or vice versa"
)


@dataclass
class VehicleState:
    """What the workstation currently believes about the bike."""

    identified: bool = False
    ecu_confidence: str = "unknown"
    #: The hardware string the *identified* ECU reported (e.g. IAW7SMHW320).
    #: The write path compares its family digit against the candidate image's;
    #: flashing across hardware families bricks the ECU.
    ecu_hardware: str = ""
    engine_running: bool | None = None
    battery_v: float | None = None
    #: A verified ECU image exists for this exact ECU.
    verified_backup: bool = False
    backup_path: str = ""
    #: The user accepted the hardware checklist for this session.
    checklist_accepted: bool = False

    def as_dict(self) -> dict:
        return {
            "identified": self.identified,
            "ecu_confidence": self.ecu_confidence,
            "ecu_hardware": self.ecu_hardware,
            "engine_running": self.engine_running,
            "battery_v": self.battery_v,
            "verified_backup": self.verified_backup,
            "backup_path": self.backup_path,
            "checklist_accepted": self.checklist_accepted,
        }


@dataclass
class SafetyGate:
    """Policy object consulted before anything leaves the tester."""

    mode: Mode = Mode.SIMULATOR
    state: VehicleState = field(default_factory=VehicleState)
    #: Minimum battery voltage for an actuator test or adaptation.
    min_battery_v: float = 11.5
    #: Writing ECU memory is off until the operator turns it on through
    #: :meth:`enable_programming`. It is an opt-in, not a build-time block:
    #: the capability exists, but it will not arm itself by accident.
    allow_programming: bool = False
    #: What the operator acknowledged when enabling programming.
    programming_acknowledgement: str = ""
    #: Whether the operator accepts key providers that are not bench-verified
    #: on Guzzi-fitted hardware. Off by default because a wrong key can lock
    #: the ECU's security gate; enabled only through
    #: :meth:`accept_unverified_key_risk`. Memory read/write paths consult
    #: this when the caller passes no explicit flag.
    allow_unverified_keys: bool = False
    #: The mode a session was in before programming was enabled, so
    #: :meth:`disable_programming` can put it back.  Enabling programming is
    #: precisely the act that puts the session into programming mode.
    _pre_programming_mode: "Mode | None" = None

    _tokens: dict[str, tuple[str, float]] = field(default_factory=dict, init=False)
    _audit: list[dict] = field(default_factory=list, init=False)

    # -- evaluation -------------------------------------------------------
    def evaluate(
        self,
        operation: str,
        risk: Risk,
        *,
        profile: EcuProfile | None = None,
        requires_engine_off: bool = False,
        requires_engine_running: bool = False,
        capability: str | None = None,
        operation_confidence: str | None = None,
        image_hardware: str | None = None,
        image_embedded_hardware: "tuple[str, ...] | list[str] | None" = None,
    ) -> Decision:
        checks: list[Check] = []
        simulated = self.mode is Mode.SIMULATOR

        if risk is Risk.READ:
            decision = Decision(True, operation, risk, (Check("read-only", True),))
            self._record(decision)
            return decision

        # -- mode -------------------------------------------------------
        needed = {
            Risk.REVERSIBLE: (Mode.SIMULATOR, Mode.SERVICE, Mode.PROGRAMMING),
            Risk.ADAPTATION: (Mode.SIMULATOR, Mode.SERVICE, Mode.PROGRAMMING),
            Risk.IRREVERSIBLE: (Mode.PROGRAMMING,),
        }[risk]
        checks.append(
            Check(
                "mode",
                self.mode in needed,
                f"mode is {self.mode.value}, needs one of "
                f"{', '.join(m.value for m in needed)}",
            )
        )

        # -- capability declared and trustworthy ------------------------
        if profile is not None and capability is not None:
            declared = capability in profile.capabilities
            checks.append(
                Check(
                    "capability",
                    declared,
                    f"{profile.family} does not declare {capability!r}",
                )
            )
            checks.append(
                Check(
                    "definition-confidence",
                    meets(profile.confidence),
                    f"{profile.family} definition is {profile.confidence!r}; "
                    "control actions need 'documented' or better",
                )
            )
        if operation_confidence is not None:
            checks.append(
                Check(
                    "operation-confidence",
                    meets(operation_confidence),
                    f"operation definition is {operation_confidence!r}; "
                    "control actions need 'documented' or better",
                )
            )

        # -- identification ---------------------------------------------
        checks.append(
            Check(
                "identified",
                self.state.identified,
                "read the ECU identification block before commanding anything",
            )
        )

        # -- engine state -------------------------------------------------
        if requires_engine_off:
            known = self.state.engine_running is not None
            checks.append(
                Check(
                    "engine-off",
                    known and self.state.engine_running is False,
                    "engine must be stopped and its state must be observed first",
                )
            )
        if requires_engine_running:
            known = self.state.engine_running is not None
            checks.append(
                Check(
                    "engine-running",
                    known and self.state.engine_running is True,
                    "this operation only works with the engine running",
                )
            )

        # -- power --------------------------------------------------------
        if not simulated:
            volts = self.state.battery_v
            checks.append(
                Check(
                    "stable-power",
                    volts is not None and volts >= self.min_battery_v,
                    f"battery reads {volts if volts is not None else 'unknown'} V, "
                    f"needs >= {self.min_battery_v} V (put it on a charger)",
                )
            )
            checks.append(
                Check(
                    "checklist",
                    self.state.checklist_accepted,
                    "accept the hardware checklist for this session first",
                )
            )

        # -- irreversible extras -------------------------------------------
        if risk is Risk.IRREVERSIBLE:
            checks.append(
                Check(
                    "programming-enabled",
                    self.allow_programming,
                    "ECU programming has not been enabled for this session. "
                    "Call enable_programming() and acknowledge the risk first.",
                )
            )
            checks.append(
                Check(
                    "verified-backup",
                    self.state.verified_backup,
                    "take a full ECU backup and verify it by re-reading before writing",
                )
            )
            # The hardware-family gate.  It only runs when a concrete
            # candidate image is on the bench (check_write passes both the
            # provenance identity captured with the image and the hardware
            # strings embedded in its bytes); a decision made without an
            # image simply cannot speak to compatibility and says so by
            # omitting the check.
            if image_hardware is not None or image_embedded_hardware is not None:
                checks.append(
                    self._hardware_family_check(
                        image_hardware or "", image_embedded_hardware or ()
                    )
                )

        allowed = all(c.passed for c in checks)
        token = None
        if allowed:
            token = secrets.token_urlsafe(12)
            self._tokens[token] = (operation, time.monotonic())
        decision = Decision(allowed, operation, risk, tuple(checks), token)
        self._record(decision)
        return decision

    # -- the hardware-family gate ------------------------------------------
    def _hardware_family_check(
        self, image_hardware: str, image_embedded_hardware
    ) -> Check:
        """Refuse any image that does not belong to this ECU's family.

        Both pieces of evidence must agree with the identified ECU:

        * the provenance identity captured when the image was read or backed
          up (the strongest evidence - a file with none is refused, because
          "cannot confirm" must never mean "probably fine");
        * the ``IAW..HWnnn`` strings embedded in the image bytes, when any
          are present (the same check the validator reports).

        A mismatch on either one is fatal: this is the gate that keeps an
        HW1xx image out of an HW3xx ECU.
        """
        target = (self.state.ecu_hardware or "").strip()
        target_family = hardware_family(target)
        provenance = (image_hardware or "").strip()
        provenance_family = hardware_family(provenance)
        embedded = [str(h) for h in image_embedded_hardware if h]
        embedded_families = {hardware_family(h) for h in embedded}

        if not target_family:
            return Check(
                "hardware-family", False,
                f"the ECU reported no usable hardware identity "
                f"({target or 'none'}); identify it before writing anything",
            )
        if not provenance_family:
            return Check(
                "hardware-family", False,
                "the image carries no captured hardware identity, so "
                f"compatibility with the identified ECU ({target}) cannot be "
                "confirmed; writing is refused",
            )
        if provenance_family != target_family:
            return Check(
                "hardware-family", False,
                f"image provenance reports {provenance}, but the ECU reports "
                f"{target}; {BRICK_WARNING}",
            )
        if embedded and target_family not in embedded_families:
            return Check(
                "hardware-family", False,
                f"the image embeds {', '.join(embedded)}, but the ECU reports "
                f"{target}; {BRICK_WARNING}",
            )
        if embedded:
            return Check(
                "hardware-family", True,
                f"image matches the ECU's hardware family ({target})",
            )
        return Check(
            "hardware-family", True,
            f"image provenance matches the ECU's hardware family ({target}); "
            "the image embeds no hardware string of its own",
        )


    # -- convenience wrappers --------------------------------------------
    def evaluate_actuator(self, profile: EcuProfile, actuator: Actuator) -> Decision:
        return self.evaluate(
            f"actuator:{actuator.key}",
            Risk.REVERSIBLE,
            profile=profile,
            capability="actuators",
            operation_confidence=actuator.confidence,
            requires_engine_off=actuator.requires_engine_off,
            requires_engine_running=actuator.requires_engine_running,
        )

    def evaluate_routine(self, profile: EcuProfile, routine: Routine) -> Decision:
        return self.evaluate(
            f"routine:{routine.key}",
            Risk.REVERSIBLE if routine.reversible else Risk.ADAPTATION,
            profile=profile,
            capability=routine.key,
            operation_confidence=routine.confidence,
            requires_engine_off=routine.requires_engine_off,
            requires_engine_running=routine.requires_engine_running,
        )

    def evaluate_clear_dtcs(self, profile: EcuProfile) -> Decision:
        return self.evaluate(
            "clear-dtcs", Risk.ADAPTATION, profile=profile, capability="dtc_clear"
        )

    # -- tokens -----------------------------------------------------------
    def consume(self, token: str | None, operation: str, *, max_age: float = 120.0) -> None:
        """Spend a confirmation token. Raises if it is missing or stale."""
        if token is None or token not in self._tokens:
            raise PermissionError(
                f"{operation}: no valid confirmation token; re-run the safety check"
            )
        recorded, issued = self._tokens.pop(token)
        if recorded != operation:
            raise PermissionError(
                f"token was issued for {recorded!r}, not {operation!r}"
            )
        if time.monotonic() - issued > max_age:
            raise PermissionError(
                f"{operation}: confirmation expired after {max_age:.0f}s; check again"
            )

    # -- the guard handed to the KWP2000 session --------------------------
    # -- programming opt-in -----------------------------------------------
    #: The subset of mutating services that can alter ECU memory.
    PROGRAMMING_SERVICES = frozenset(
        {
            Service.REQUEST_DOWNLOAD,
            Service.TRANSFER_DATA,
            Service.REQUEST_TRANSFER_EXIT,
            Service.WRITE_MEMORY_BY_ADDRESS,
        }
    )

    #: What the operator has to type back, verbatim, to arm programming.
    PROGRAMMING_ACKNOWLEDGEMENT = "I have a verified backup and accept the risk"

    def enable_programming(self, acknowledgement: str) -> None:
        """Arm ECU memory writing for this session.

        Deliberately awkward. The operator must repeat
        :data:`PROGRAMMING_ACKNOWLEDGEMENT` exactly, the choice is recorded in
        the audit log, and it still only unlocks the *gate* - every individual
        write is evaluated on its own merits afterwards.
        """
        if acknowledgement.strip() != self.PROGRAMMING_ACKNOWLEDGEMENT:
            self._audit.append(
                {
                    "at": time.time(),
                    "event": "programming_enable_refused",
                    "reason": "acknowledgement did not match",
                }
            )
            raise SafetyViolation(
                Decision(
                    allowed=False,
                    operation="enable-programming",
                    risk=Risk.IRREVERSIBLE,
                    checks=(
                        Check(
                            "acknowledgement",
                            False,
                            "to enable ECU programming, repeat exactly: "
                            f"{self.PROGRAMMING_ACKNOWLEDGEMENT!r}",
                        ),
                    ),
                )
            )
        self.allow_programming = True
        self.programming_acknowledgement = acknowledgement.strip()
        # Irreversible operations require the programming mode; enabling
        # programming is the operator's way to enter it.  The original mode
        # is restored on disable so disabling really is "back to normal".
        self._pre_programming_mode = self.mode
        self.mode = Mode.PROGRAMMING
        self._audit.append(
            {"at": time.time(), "event": "programming_enabled"}
        )

    def disable_programming(self) -> None:
        self.allow_programming = False
        self.programming_acknowledgement = ""
        if self._pre_programming_mode is not None:
            self.mode = self._pre_programming_mode
            self._pre_programming_mode = None
        self._audit.append({"at": time.time(), "event": "programming_disabled"})

    def accept_unverified_key_risk(self, accept: bool = True) -> None:
        """Record the operator's decision on unverified key providers.

        No shipped key algorithm is bench-verified on Guzzi-fitted hardware,
        and a wrong key can lock the ECU's security gate, so these providers
        are refused unless the operator explicitly accepts the risk for this
        session. The choice is audited like every other gate decision.
        """
        self.allow_unverified_keys = bool(accept)
        self._audit.append(
            {
                "at": time.time(),
                "event": (
                    "unverified_keys_accepted"
                    if accept
                    else "unverified_keys_declined"
                ),
            }
        )

    def session_guard(self, armed_for: set[int] | None = None, *,
                      purpose: str = "write"):
        """Build a ``write_guard`` callable.

        Only the services explicitly armed for the current operation may be
        transmitted; everything else in :data:`MUTATING_SERVICES` is refused at
        the frame level.

        ``purpose="read"`` exists because the IAW families read their flash
        with TransferData (0x36), a nominally mutating service. Reading is not
        destructive, so an armed read does not require the programming opt-in -
        but it still may not send RequestDownload or WriteMemoryByAddress.
        """
        armed = armed_for or set()
        reading = purpose == "read"

        def guard(service: int) -> bool:
            if service not in MUTATING_SERVICES:
                return True
            if service not in armed:
                return False
            if service in self.PROGRAMMING_SERVICES:
                if reading and service in (
                    Service.TRANSFER_DATA,
                    Service.REQUEST_TRANSFER_EXIT,
                ):
                    return True
                return self.allow_programming
            return True

        return guard

    # -- audit ------------------------------------------------------------
    def _record(self, decision: Decision) -> None:
        if decision.risk is Risk.READ:
            return
        self._audit.append({"at": time.time(), **decision.as_dict()})

    @property
    def audit_log(self) -> list[dict]:
        return list(self._audit)
