"""GuzziOnBoard - a diagnostic workstation for Moto Guzzi motorcycles."""

__version__ = "0.3.0"

from .catalog import Catalog, EcuProfile, load_catalog
from .diagnostics import DiagnosticsService
from .firmware import FirmwareImage
from .programming import ProgrammingService
from .safety import Mode, Risk, SafetyGate, SafetyViolation, VehicleState
from .sessionlog import SessionLog

__all__ = [
    "Catalog", "EcuProfile", "load_catalog", "DiagnosticsService",
    "Mode", "Risk", "SafetyGate",
    "FirmwareImage",
    "ProgrammingService", "SafetyViolation", "VehicleState",
    "SessionLog", "__version__",
]
