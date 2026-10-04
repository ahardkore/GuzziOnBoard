"""Workstation: the single stateful object the API drives.

Holds the catalog, the currently selected vehicle, the live diagnostics
session and the safety gate. Kept separate from the HTTP layer so a desktop
shell (or a test) can drive exactly the same surface.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import __version__
from .catalog import Catalog, EcuProfile, VehicleEntry, load_catalog
from .diagnostics import DiagnosticsService, NotConnected
from .safety import Mode, SafetyGate, VehicleState
from .sessionlog import DEFAULT_DIR, SessionLog
from .transports.base import Transport, TransportUnavailable
from .transports.simulator import EngineModel, SimulatedEcu, SimulatorTransport


@dataclass
class Selection:
    """What the operator picked in the UI."""

    model: str = ""
    year: int = 0
    entry: VehicleEntry | None = None
    profile: EcuProfile | None = None
    transport_kind: str = "simulator"
    device: str = ""

    def as_dict(self) -> dict:
        return {
            "model": self.model,
            "year": self.year,
            "entry": self.entry.as_dict() if self.entry else None,
            "ecu": self.profile.as_dict() if self.profile else None,
            "transport": self.transport_kind,
            "device": self.device,
        }


class Workstation:
    def __init__(self, *, session_dir: Path | str = DEFAULT_DIR, record: bool = True):
        self.catalog: Catalog = load_catalog()
        self.selection = Selection()
        self.gate = SafetyGate(mode=Mode.SIMULATOR, state=VehicleState())
        self.service: DiagnosticsService | None = None
        self.log: SessionLog | None = None
        self.session_dir = Path(session_dir)
        self.record = record
        self.notices: list[dict] = []
        self._lock = threading.RLock()

    # -- selection --------------------------------------------------------
    def select(
        self,
        *,
        model: str = "",
        year: int = 0,
        ecu: str = "",
        transport: str = "simulator",
        device: str = "",
    ) -> dict:
        with self._lock:
            entry = None
            if ecu:
                profile = self.catalog.ecu(ecu)
            elif model and year:
                entry, profile = self.catalog.resolve(model, year)
            else:
                raise ValueError("select needs either an ecu id or a model and year")

            self.selection = Selection(
                model=model or profile.family,
                year=year,
                entry=entry,
                profile=profile,
                transport_kind=transport,
                device=device,
            )
            self.notices = self._selection_notices(entry, profile, transport)
            return self.describe_selection()

    def _selection_notices(
        self, entry: VehicleEntry | None, profile: EcuProfile, transport: str
    ) -> list[dict]:
        notices: list[dict] = []
        if entry and self.catalog.ambiguous(entry.model, entry.year_from):
            notices.append(
                {
                    "level": "warn",
                    "text": (
                        f"{entry.model} spans more than one ECU family in this year. "
                        "Moto Guzzi changed ECUs as running changes - read the label "
                        "on your ECU and override the selection if it disagrees."
                    ),
                }
            )
        if profile.confidence in ("inferred", "unknown"):
            notices.append(
                {
                    "level": "warn",
                    "text": (
                        f"The {profile.family} definition is marked "
                        f"'{profile.confidence}'. Control actions are disabled; "
                        "identification, fault codes and the read-only discovery "
                        "scan are available."
                    ),
                }
            )
        if entry and entry.notes:
            notices.append({"level": "info", "text": entry.notes})
        if transport != "simulator":
            notices.append(
                {
                    "level": "danger",
                    "text": (
                        "Hardware transport selected. Nothing here has been "
                        "validated against a motorcycle. Accept the checklist and "
                        "understand that you are the test."
                    ),
                }
            )
        return notices

    def describe_selection(self) -> dict:
        data = self.selection.as_dict()
        data["notices"] = self.notices
        return data

    # -- transports -------------------------------------------------------
    def _build_transport(self) -> Transport:
        profile = self.selection.profile
        assert profile is not None
        kind = self.selection.transport_kind

        if kind == "simulator":
            engine = EngineModel(ambient_c=18.0)
            return SimulatorTransport(ecu=SimulatedEcu(profile, engine=engine))
        if kind == "kline":
            from .transports.kline import KLineTransport

            return KLineTransport(
                device=self.selection.device or "/dev/ttyUSB0",
                baud=profile.kline.get("baud", 10400),
                inter_byte_delay=profile.kline.get("inter_byte_delay", 0.005),
            )
        if kind == "can":
            from .transports.can import CanTransport

            spec = profile.can or {}
            return CanTransport(
                channel=self.selection.device or spec.get("channel", "can0"),
                interface=spec.get("interface", "socketcan"),
                bitrate=spec.get("bitrate", 500000),
                tx_id=spec.get("tx_id", 0x7E0),
                rx_id=spec.get("rx_id", 0x7E8),
            )
        raise ValueError(f"unknown transport {kind!r}")

    @staticmethod
    def available_transports() -> list[dict]:
        found = [
            {
                "id": "simulator",
                "name": "Simulator",
                "available": True,
                "detail": "Deterministic ECU that speaks the real KWP2000 wire protocol.",
            }
        ]
        try:
            from .transports.kline import KLineTransport

            ports = KLineTransport.list_ports()
            found.append(
                {
                    "id": "kline",
                    "name": "K-Line (USB serial)",
                    "available": True,
                    "detail": f"{len(ports)} serial adapter(s) detected.",
                    "ports": ports,
                }
            )
        except TransportUnavailable as exc:
            found.append(
                {"id": "kline", "name": "K-Line (USB serial)", "available": False,
                 "detail": str(exc).splitlines()[0]}
            )
        try:
            import can  # noqa: F401

            found.append(
                {"id": "can", "name": "CAN (ISO-TP)", "available": True,
                 "detail": "python-can is installed."}
            )
        except ImportError:
            found.append(
                {"id": "can", "name": "CAN (ISO-TP)", "available": False,
                 "detail": "python-can is not installed (pip install -e '.[hardware]')."}
            )
        return found

    # -- lifecycle --------------------------------------------------------
    def connect(self, *, mode: str = "simulator", init_method: str | None = None) -> dict:
        with self._lock:
            if self.selection.profile is None:
                raise ValueError("select a vehicle before connecting")
            if self.service is not None and self.service.connected:
                return self.status()

            self.gate = SafetyGate(mode=Mode(mode), state=VehicleState())
            self.log = SessionLog(
                directory=self.session_dir,
                enabled=self.record,
                meta={
                    "app_version": __version__,
                    "model": self.selection.model,
                    "year": self.selection.year,
                    "ecu": self.selection.profile.id,
                    "ecu_family": self.selection.profile.family,
                    "transport": self.selection.transport_kind,
                    "mode": mode,
                },
            )
            self.service = DiagnosticsService(
                self.selection.profile,
                self._build_transport(),
                self.gate,
                log=self.log,
                catalog=self.catalog,
            )
            self.service.connect(init_method=init_method)
            return self.status()

    def disconnect(self) -> dict:
        with self._lock:
            if self.service is not None:
                self.service.disconnect()
                self.service = None
            if self.log is not None:
                self.log.close()
            return self.status()

    def require_service(self) -> DiagnosticsService:
        if self.service is None or not self.service.connected:
            raise NotConnected("connect to an ECU first")
        return self.service

    # -- checklist --------------------------------------------------------
    HARDWARE_CHECKLIST = [
        "The motorcycle is on a stand, in neutral, and cannot roll or fall.",
        "The battery is healthy or on a charger - an ECU brown-out mid-operation is how ECUs die.",
        "Fuel lines, the tank and the airbox are intact and there is no fuel pooling anywhere.",
        "You know how to disconnect the diagnostic cable in a hurry.",
        "You accept that this software has not been validated against a motorcycle.",
    ]

    def accept_checklist(self, accepted: bool) -> dict:
        self.gate.state.checklist_accepted = bool(accepted)
        if self.log:
            self.log.action("checklist", {"accepted": bool(accepted)})
        return self.gate.state.as_dict()

    # -- status -----------------------------------------------------------
    def status(self) -> dict:
        base = {
            "version": __version__,
            "selection": self.describe_selection(),
            "mode": self.gate.mode.value,
            "connected": bool(self.service and self.service.connected),
            "checklist": self.HARDWARE_CHECKLIST,
            "vehicle_state": self.gate.state.as_dict(),
            "session": self.log.summary() if self.log else None,
            "audit": self.gate.audit_log[-20:],
            "transports": self.available_transports(),
        }
        if self.service is not None:
            base["diagnostics"] = self.service.status()
        return base

    # -- report -----------------------------------------------------------
    def build_report(self) -> dict:
        """A shareable snapshot: what was found, how, and how much to trust it."""
        service = self.service
        profile = self.selection.profile
        report = {
            "generated_at": time.time(),
            "generated_at_text": time.strftime("%Y-%m-%d %H:%M:%S"),
            "tool": {"name": "GuzziOnBoard", "version": __version__},
            "vehicle": self.selection.as_dict(),
            "mode": self.gate.mode.value,
            "trust": {
                "ecu_definition_confidence": profile.confidence if profile else "unknown",
                "transport": self.selection.transport_kind,
                "simulated": self.selection.transport_kind == "simulator",
                "caveat": (
                    "Values are decoded with catalog scalings. Anything below "
                    "'documented' confidence is an interpretation, not a measurement."
                ),
            },
            "identity": (
                service.identity.as_dict() if service and service.identity else None
            ),
            "samples": (
                [s.as_dict() for s in service.last_samples.values()] if service else []
            ),
            "dtcs": [],
            "safety_audit": self.gate.audit_log,
            "session": self.log.summary() if self.log else None,
        }
        if service and service.connected:
            try:
                report["dtcs"] = service.read_dtcs()
            except Exception as exc:
                report["dtcs_error"] = str(exc)
        return report

    def report_text(self, report: dict | None = None) -> str:
        r = report or self.build_report()
        lines = [
            "GuzziOnBoard diagnostic report",
            "=" * 60,
            f"Generated : {r['generated_at_text']}",
            f"Tool      : {r['tool']['name']} {r['tool']['version']}",
            f"Mode      : {r['mode']}"
            + ("   *** SIMULATED - NOT A REAL MOTORCYCLE ***" if r["trust"]["simulated"] else ""),
            "",
            "Vehicle",
            "-" * 60,
        ]
        sel = r["vehicle"]
        lines.append(f"Model     : {sel.get('model') or 'n/a'} {sel.get('year') or ''}")
        if sel.get("ecu"):
            lines.append(f"ECU       : {sel['ecu']['display_name']} ({sel['ecu']['years']})")
            lines.append(f"Confidence: {sel['ecu']['confidence']}")
        lines.append(f"Transport : {r['trust']['transport']}")

        if r.get("identity"):
            lines += ["", "ECU identification", "-" * 60]
            for key, value in r["identity"]["fields"].items():
                lines.append(f"{key:<12}: {value}")

        lines += ["", "Fault codes", "-" * 60]
        if r["dtcs"]:
            for d in r["dtcs"]:
                flag = "!" if d.get("warning_indicator") else " "
                lines.append(
                    f"{flag} {d['code']}  {d['status']:<8} {d.get('description', '')}"
                )
        else:
            lines.append("None reported.")

        lines += ["", "Live values at capture", "-" * 60]
        for s in r["samples"]:
            if s.get("error"):
                lines.append(f"{s['name']:<30} ERROR {s['error']}")
            else:
                shown = s.get("text") or f"{s['value']} {s['unit']}".strip()
                lines.append(
                    f"{s['name']:<30} {shown:<18} raw={s['raw']}  (0x{s['local_id']:02X})"
                )

        if r["safety_audit"]:
            lines += ["", "Safety decisions", "-" * 60]
            for entry in r["safety_audit"]:
                verdict = "ALLOWED" if entry["allowed"] else "REFUSED"
                lines.append(f"{verdict:<8} {entry['operation']:<28} {entry['reason']}")

        lines += [
            "",
            "-" * 60,
            r["trust"]["caveat"],
            "Not affiliated with Piaggio or the GuzziDiag author.",
        ]
        return "\n".join(lines)
