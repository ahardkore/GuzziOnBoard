"""Core diagnostic domain for GuzziOnBoard.

This module deliberately contains no hardware access. Hardware transports can be
added behind the same interface once protocol fixtures and bench tests exist.
"""
from dataclasses import dataclass, asdict
from enum import Enum
import math
import time


class Mode(str, Enum):
    SIMULATOR = "simulator"
    READ_ONLY = "read_only"
    SERVICE = "service"


@dataclass(frozen=True)
class VehicleIdentity:
    make: str
    model: str
    year: int
    ecu_family: str
    firmware: str


@dataclass(frozen=True)
class LiveValues:
    timestamp: float
    rpm: float
    coolant_c: float
    battery_v: float
    throttle_pct: float
    intake_air_c: float
    lambda_correction: float

    def json_values(self):
        return {"timestamp": self.timestamp, "rpm": round(self.rpm),
                "coolant": round(self.coolant_c, 1), "battery": round(self.battery_v, 2),
                "throttle": round(self.throttle_pct, 2), "air": round(self.intake_air_c, 1),
                "lambda": round(self.lambda_correction, 3)}


@dataclass(frozen=True)
class DiagnosticCode:
    code: str
    title: str
    status: str
    severity: str


class SimulatorTransport:
    """Deterministic ECU simulator used by the UI and automated tests."""

    def __init__(self):
        self.started = time.monotonic()
        self.connected = False
        self.faults = [
            DiagnosticCode("P0130", "Lambda sensor circuit", "stored", "warning"),
            DiagnosticCode("P0505", "Idle control system", "historic", "info"),
        ]

    def connect(self):
        self.connected = True

    def disconnect(self):
        self.connected = False

    def values(self) -> LiveValues:
        t = time.monotonic() - self.started
        return LiveValues(time.time(), 1180 + 35 * math.sin(t * 1.4),
                          78 + 1.8 * math.sin(t / 4), 13.9 + .08 * math.sin(t / 3),
                          3.2 + .25 * math.sin(t * 1.1), 31 + 1.2 * math.sin(t / 5),
                          .98 + .025 * math.sin(t * 2.1))

    def clear_faults(self):
        self.faults.clear()


class SafetyGate:
    """Central policy for operations that could alter a vehicle.

    It intentionally rejects every write until the required evidence exists.
    """

    def __init__(self, mode=Mode.SIMULATOR):
        self.mode = Mode(mode)

    def allow_write(self, *, identified=False, stable_power=False,
                    verified_backup=False, compatible_image=False,
                    explicit_confirmation=False):
        checks = (identified, stable_power, verified_backup,
                  compatible_image, explicit_confirmation)
        return self.mode is not Mode.SIMULATOR and all(checks)


def identity_dict(identity: VehicleIdentity):
    return asdict(identity)
