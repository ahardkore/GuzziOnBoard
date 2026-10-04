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


@dataclass
class VehicleState:
    """What the workstation currently believes about the bike."""

    identified: bool = False
    ecu_confidence: str = "unknown"
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
    #: Writing ECU memory is a build-level switch, off by default.
    allow_programming: bool = False

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
                    "ECU programming is disabled in this build: there are no "
                    "protocol fixtures, no bench-tested recovery path and no "
                    "power-loss handling",
                )
            )
            checks.append(
                Check(
                    "verified-backup",
                    self.state.verified_backup,
                    "take a full ECU backup and verify it by re-reading before writing",
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

    # -- convenience wrappers --------------------------------------------
    def evaluate_actuator(self, profile: EcuProfile, actuator: Actuator) -> Decision:
        return self.evaluate(
            f"actuator:{actuator.key}",
            Risk.REVERSIBLE,
            profile=profile,
            capability="actuators",
            requires_engine_off=actuator.requires_engine_off,
            requires_engine_running=actuator.requires_engine_running,
        )

    def evaluate_routine(self, profile: EcuProfile, routine: Routine) -> Decision:
        return self.evaluate(
            f"routine:{routine.key}",
            Risk.REVERSIBLE if routine.reversible else Risk.ADAPTATION,
            profile=profile,
            capability=routine.key,
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
    def session_guard(self, armed_for: set[int] | None = None):
        """Build a ``write_guard`` callable.

        Only the services explicitly armed for the current operation may be
        transmitted; everything else in :data:`MUTATING_SERVICES` is refused at
        the frame level.
        """
        armed = armed_for or set()

        def guard(service: int) -> bool:
            if service not in MUTATING_SERVICES:
                return True
            if service in (
                Service.REQUEST_DOWNLOAD,
                Service.TRANSFER_DATA,
                Service.REQUEST_TRANSFER_EXIT,
                Service.WRITE_MEMORY_BY_ADDRESS,
            ) and not self.allow_programming:
                return False
            return service in armed

        return guard

    # -- audit ------------------------------------------------------------
    def _record(self, decision: Decision) -> None:
        if decision.risk is Risk.READ:
            return
        self._audit.append({"at": time.time(), **decision.as_dict()})

    @property
    def audit_log(self) -> list[dict]:
        return list(self._audit)
