"""Workstation: the single stateful object the API drives.

Holds the catalog, the currently selected vehicle, the live diagnostics
session and the safety gate. Kept separate from the HTTP layer so a desktop
shell (or a test) can drive exactly the same surface.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field, replace
from pathlib import Path

from . import __version__
from .catalog import Catalog, EcuProfile, VehicleEntry, load_catalog
from .diagnostics import DiagnosticsService, NotConnected
from .safety import Mode, SafetyGate, VehicleState
from .sessionlog import DEFAULT_DIR, SessionLog
from .derived import Analyzer
from .transports.base import Transport, TransportUnavailable
from .transports.simulator import EngineModel, SimulatedEcu, SimulatorTransport

#: Unit strings the catalog uses for a Celsius channel.
_CELSIUS_UNITS = {"\u00b0c", "c", "deg c", "degc", "celsius"}


def _is_celsius(unit: str | None) -> bool:
    return str(unit or "").strip().lower() in _CELSIUS_UNITS


def _is_celsius_like(unit: str | None) -> bool:
    """True for "\u00b0C" and for rates built on it such as "\u00b0C/min"."""
    return "\u00b0c" in str(unit or "").lower()


@dataclass
class Selection:
    """What the operator picked in the UI."""

    model: str = ""
    year: int = 0
    make: str = ""
    entry: VehicleEntry | None = None
    profile: EcuProfile | None = None
    transport_kind: str = "simulator"
    device: str = ""
    #: CAN identifier overrides for this session (the catalog pair is
    #: unconfirmed on the CAN families, so the operator can try another).
    can_overrides: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "make": self.make,
            "model": self.model,
            "year": self.year,
            "entry": self.entry.as_dict() if self.entry else None,
            "ecu": self.profile.as_dict() if self.profile else None,
            "transport": self.transport_kind,
            "device": self.device,
            "can_overrides": self.can_overrides,
        }

    def can_spec(self) -> dict:
        """The CAN spec in force: ECU defaults <- vehicle entry <- operator."""
        spec = dict(self.profile.can) if self.profile else {}
        if self.entry and self.entry.can:
            spec.update(self.entry.can)
        spec.update(self.can_overrides)
        return spec


def _parse_id(value: str | int, what: str) -> int:
    """A CAN identifier: 0x7E0, 2016 or 0x18DA10F1 all accepted."""
    if isinstance(value, int):
        ident = value
    else:
        try:
            ident = int(str(value).strip(), 0)
        except ValueError:
            raise ValueError(f"{what} {value!r} is not a number") from None
    if not 0 <= ident <= 0x1FFFFFFF:
        raise ValueError(f"{what} 0x{ident:X} is outside the 29-bit id range")
    return ident


def _effective_profile(entry: VehicleEntry | None, profile: EcuProfile) -> EcuProfile:
    """The profile with the vehicle's own honesty applied.

    A Ducati 748 and a Guzzi V11 Sport share the 16M, but every identifier
    table in this catalog was captured in a Moto Guzzi context. When the
    *vehicle* entry is less confident than the ECU definition - which is how
    every cross-brand entry is marked - the worse level wins and the note
    says why. Control actions gate off this, so a cross-brand bike is
    read-only until someone confirms the identifiers on the real machine.
    """
    if entry is None or entry.confidence == profile.confidence:
        return profile
    from .catalog import confidence_rank

    if confidence_rank(entry.confidence) > confidence_rank(profile.confidence):
        note = (
            f"Selected as {entry.make} {entry.model}: this vehicle mapping is "
            f"'{entry.confidence}' while the {profile.family} definition is "
            f"'{profile.confidence}'. The stricter level applies - the "
            "identifier tables below were captured on another make and are "
            "unverified here, so control actions stay disabled. A single "
            "recorded session on this bike promotes the whole family."
        )
        return replace(profile, confidence=entry.confidence, notes=note)
    return profile


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
        # The profile in force for the *session*.  Ordinary sessions see the
        # catalogue profile; simulated sessions see the simulation-capability
        # clone (see _simulated_capable_profile).  The catalogue object is
        # never mutated.
        self._session_profile: EcuProfile | None = None

    # -- selection --------------------------------------------------------
    def select(
        self,
        *,
        model: str = "",
        year: int = 0,
        ecu: str = "",
        make: str = "",
        transport: str = "simulator",
        device: str = "",
        can_tx_id: str | int = "",
        can_rx_id: str | int = "",
    ) -> dict:
        with self._lock:
            entry = None
            if ecu:
                profile = self.catalog.ecu(ecu)
            elif model and year:
                entry, profile = self.catalog.resolve(model, year, make)
            else:
                raise ValueError("select needs either an ecu id or a model and year")

            overrides = {}
            for key, value in (("tx_id", can_tx_id), ("rx_id", can_rx_id)):
                if value not in ("", None):
                    overrides[key] = _parse_id(value, key)

            profile = _effective_profile(entry, profile)
            self.selection = Selection(
                model=model or profile.family,
                year=year,
                make=make or (entry.make if entry else ""),
                entry=entry,
                profile=profile,
                transport_kind=transport,
                device=device,
                can_overrides=overrides,
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
        if transport not in ("simulator", "cansim"):
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
    # Transports that run against the built-in simulated ECU rather than a
    # physical motorcycle.  For these, capability honesty flips direction:
    # the simulator *is* the hardware, and everything it speaks is proven.
    _SIM_TRANSPORTS = ("simulator", "cansim")

    @staticmethod
    def _simulated_capable_profile(profile) -> "EcuProfile":
        """The capability set actually proven against the simulated ECU.

        A catalogue profile answers for the real controller, so it
        deliberately under-declares whatever never met a bench - which is
        why ``write_supported`` stays false for every shipped ECU.  The
        simulator is under our own roof: the full flash cycle (unlock,
        request-download, transfer, checksum, read-back) it implements is
        exercised by the test suite, so inside a simulated session those
        capabilities are true - and are flagged as simulated everywhere
        they are reported.
        """
        from dataclasses import replace

        memory = dict(profile.memory or {})
        regions = {
            name: dict(spec) for name, spec in (memory.get("regions") or {}).items()
        }
        flipped = []
        for name, spec in regions.items():
            if int(spec.get("size") or 0) and not spec.get("writable"):
                spec["writable"] = True
                flipped.append(name)
        hardware_reason = memory.get("write_blocked_reason") or ""
        memory["regions"] = regions
        if flipped:
            memory["write_supported"] = True
        memory["write_blocked_reason"] = ""
        memory["simulated"] = True
        memory["simulation_note"] = (
            "Simulated ECU: these capabilities are proven against the "
            "built-in protocol simulation, not against hardware."
            + (
                f" Against a real {profile.family}, writing stays refused: "
                f"{hardware_reason}"
                if hardware_reason
                else ""
            )
        )
        capabilities = tuple(profile.capabilities)
        if flipped and "memory_write" not in capabilities:
            capabilities += ("memory_write",)
        return replace(profile, memory=memory, capabilities=capabilities)

    def _build_transport(self) -> Transport:
        profile = self._session_profile or self.selection.profile
        assert profile is not None
        kind = self.selection.transport_kind

        if kind == "simulator":
            engine = EngineModel(ambient_c=18.0)
            return SimulatorTransport(ecu=SimulatedEcu(profile, engine=engine))
        if kind == "cansim":
            from .transports.cansim import VirtualCanTransport

            spec = self.selection.can_spec()
            return VirtualCanTransport(
                profile=profile,
                tx_id=spec.get("tx_id", 0x7E0),
                rx_id=spec.get("rx_id", 0x7E8),
                padding=spec.get("padding", 0xAA),
            )
        if kind == "kline":
            from .transports.kline import KLineTransport

            return KLineTransport(
                device=self.selection.device or "/dev/ttyUSB0",
                baud=profile.kline.get("baud", 10400),
                inter_byte_delay=profile.kline.get("inter_byte_delay", 0.005),
            )
        if kind == "can":
            from .transports.can import CanTransport

            spec = self.selection.can_spec()
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
            found.append(
                {"id": "cansim", "name": "CAN rehearsal (virtual)",
                 "available": True,
                 "detail": "The full ISO-TP framing path, flow control and all, "
                           "against the simulated ECU on a virtual bus - and it "
                           "uses the CAN ids you set, so the pair you are "
                           "confirming can be dry-run first."}
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
            profile = self.selection.profile
            if self.selection.transport_kind in self._SIM_TRANSPORTS:
                # Simulated session: present the capability set we have
                # actually proven against the simulation, labelled as such.
                profile = self._simulated_capable_profile(profile)
            self._session_profile = profile
            self.service = DiagnosticsService(
                profile,
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
            self._session_profile = None
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
                "simulated": self.selection.transport_kind in ("simulator", "cansim"),
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
                report["dtcs"] = service.read_dtcs()["dtcs"]
            except Exception as exc:
                report["dtcs_error"] = str(exc)

        # Derived channels and findings are the workstation's arithmetic and
        # the workstation's opinion. They are kept in their own sections so a
        # reader never mistakes them for something the ECU said.
        analysis = Analyzer(profile).update(report["samples"])
        report["derived"] = analysis["derived"]
        report["findings"] = analysis["findings"]
        return report

    def report_text(
        self, report: dict | None = None, temp_unit: str = "C"
    ) -> str:
        """Render the report. ``temp_unit`` is display only: "C" (what the
        ECU actually sends) or "F" for riders who think in Fahrenheit."""
        r = report or self.build_report()
        fahrenheit = str(temp_unit).strip().upper().startswith("F")
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
                value, unit = s["value"], s["unit"]
                if fahrenheit and _is_celsius(unit) and isinstance(value, (int, float)):
                    value = round(value * 9 / 5 + 32, 1)
                    if isinstance(s["value"], int):
                        value = int(round(value))
                    unit = "\u00b0F"
                shown = s.get("text") or f"{value} {unit}".strip()
                lines.append(
                    f"{s['name']:<30} {shown:<18} raw={s['raw']}  (0x{s['local_id']:02X})"
                )

        if r.get("derived"):
            lines += ["", "Derived by the workstation (not read from the ECU)", "-" * 60]
            for c in r["derived"]:
                value, unit = c["value"], c["unit"]
                if fahrenheit and _is_celsius_like(unit):
                    # A split or a rate is a difference: scale it, do not
                    # shift it by 32 degrees.
                    value = round(value * 9 / 5, 1) if c.get("delta") else \
                        round(value * 9 / 5 + 32, 1)
                    unit = unit.replace("\u00b0C", "\u00b0F")
                shown = f"{value} {unit}".strip()
                lines.append(
                    f"{c['name']:<30} {shown:<18} from {', '.join(c['sources'])}"
                )

        if r.get("findings"):
            lines += ["", "Plausibility checks (interpretation, not measurement)", "-" * 60]
            for f in r["findings"]:
                lines.append(f"[{f['level'].upper():<4}] {f['title']}")
                lines.append(f"        {f['detail']}")
                if f["suspects"]:
                    lines.append(f"        Usual suspects: {'; '.join(f['suspects'])}")

        if r["safety_audit"]:
            lines += ["", "Safety decisions and gate events", "-" * 60]
            for entry in r["safety_audit"]:
                if "event" in entry:
                    # Gate state changes are events, not allow/refuse
                    # decisions: programming armed/disarmed, the unverified
                    # key risk accepted or declined.
                    lines.append(f"{'EVENT':<8} {entry['event']}")
                    continue
                verdict = "ALLOWED" if entry["allowed"] else "REFUSED"
                lines.append(
                    f"{verdict:<8} {entry['operation']:<28} {entry['reason']}"
                )

        lines += [
            "",
            "-" * 60,
            r["trust"]["caveat"],
            "Not affiliated with Piaggio or the GuzziDiag author.",
        ]
        return "\n".join(lines)
