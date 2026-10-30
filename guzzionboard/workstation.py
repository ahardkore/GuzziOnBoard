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


def _field_confirmation_notice(profile: EcuProfile) -> dict | None:
    """Say, in the operator's face, why a family is more capable than shipped.

    A promotion is a real change to what this software will do to somebody's
    motorcycle, so it is announced wherever the selection is announced - never
    quietly absorbed into the capability list.
    """
    promotion = profile.field_confirmation or {}
    if not promotion:
        return None
    sessions = promotion.get("independent_sessions") or 0
    return {
        "level": "info",
        "text": (
            f"{profile.family}: {profile.confidence} as shipped. Signed protocol update "
            f"{promotion.get('pack') or 'unknown'} includes {sessions} reported "
            "field session(s); hardware origin is not independently verified. Check the "
            "update's effects for its scope. Writing and control actions are unchanged."
        ),
    }


def _effective_profile(entry: VehicleEntry | None, profile: EcuProfile) -> EcuProfile:
    """The profile with the vehicle's own honesty applied.

    A Ducati 748 and a Guzzi V11 Sport share the 16M, but every identifier
    table in this catalog was captured in a Moto Guzzi context. When the
    *vehicle* entry is less confident than the ECU definition - which is how
    every cross-brand entry is marked - the worse level wins and the note
    says why. Control actions gate off this; cross-brand assumptions are not
    handed to an owner for confirmation on a motorcycle.
    """
    if entry is None or entry.confidence == profile.confidence:
        return profile
    from .catalog import confidence_rank

    if confidence_rank(entry.confidence) > confidence_rank(profile.confidence):
        note = (
            f"Selected as {entry.make} {entry.model}: this vehicle mapping is "
            f"'{entry.confidence}' while the {profile.family} definition is "
            f"'{profile.confidence}'. The stricter level applies - the "
            "identifier tables below were established on another make and are "
            "unverified here, so control actions stay disabled. The workstation "
            "does not ask the owner to validate cross-brand protocol assumptions."
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
            if self.service is not None and self.service.connected:
                raise ValueError("disconnect the current session before selecting another vehicle or ECU")
            entry = None
            if model and year:
                # Keep vehicle confidence even when an ECU override is supplied.
                # An unrelated profile must not inherit a different bike's identity.
                matches = self.catalog.find(model, year, make)
                if not make and len({v.make.casefold() for v in matches}) > 1:
                    raise ValueError(f"{model} {year} exists under multiple makes; specify make")
                if ecu:
                    candidates = [v for v in matches if v.ecu == ecu]
                    if not candidates:
                        raise ValueError("ECU override is not cataloged for this make, model and year; verify the ECU label")
                    candidates.sort(key=lambda v: ((v.year_to or 9999) - v.year_from, -v.year_from))
                    entry = candidates[0]
                    profile = self.catalog.ecu(ecu)
                else:
                    entry, profile = self.catalog.resolve(model, year, make)
            elif ecu:
                if make or model or year:
                    raise ValueError("ECU-only selection cannot include a partial vehicle identity; specify make, model and year together")
                profile = self.catalog.ecu(ecu)
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
        if entry and self.catalog.ambiguous(entry.model, self.selection.year, entry.make):
            notices.append(
                {
                    "level": "warn",
                    "text": (
                        f"{entry.model} spans more than one ECU family in this year. "
                        "Some models have overlapping fitments - read the label "
                        "on your ECU and override the selection if it disagrees."
                    ),
                }
            )
        if profile.confidence in ("inferred", "unknown"):
            readable = [
                label for capability, label in (
                    ("identify", "identification"),
                    ("dtc_read", "fault reading"),
                    ("live", "live data"),
                    ("discover", "identifier discovery"),
                )
                if capability in profile.capabilities
            ]
            availability = (
                f" Available operations: {', '.join(readable)}."
                if readable
                else " No diagnostic operations are exposed."
            )
            notices.append(
                {
                    "level": "warn",
                    "text": (
                        f"The {profile.family} definition is marked "
                        f"'{profile.confidence}'. Control actions are disabled."
                        f"{availability}"
                    ),
                }
            )
        if entry and entry.notes:
            notices.append({"level": "info", "text": entry.notes})
        evidence = profile.session.get("physical_evidence_note")
        if evidence:
            notices.append({"level": "info", "text": f"Validation: {evidence}"})
        promotion = _field_confirmation_notice(profile)
        if promotion:
            notices.append(promotion)
        if transport not in ("simulator", "cansim"):
            if profile.session.get("physical_supported") is False:
                detail = profile.session.get(
                    "physical_blocked_reason", "Protocol evidence is incomplete."
                )
                text = (
                    "Physical use is blocked before the adapter is opened. "
                    f"{detail} Customers are not used to validate protocol guesses."
                )
            else:
                text = (
                    "Hardware transport selected. Only the explicitly listed, "
                    "evidence-backed capabilities are available; all other "
                    "operations remain blocked."
                )
            notices.append({"level": "danger", "text": text})
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

        if kind in self._SIM_TRANSPORTS and profile.session.get("simulator_supported") is False:
            raise TransportUnavailable(f"{profile.family}: no matching simulator is implemented")
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
        if kind in ("kline", "can") and profile.session.get("physical_supported") is False:
            reason = profile.session.get(
                "physical_blocked_reason",
                "the physical diagnostic protocol is not validated",
            )
            raise TransportUnavailable(
                f"{profile.family}: {reason} The safety boundary stopped here: "
                "no transport was constructed, no port was opened, and no request was sent."
            )
        if kind == "elm_j1850":
            if profile.session.get("protocol") != "harley-j1850-harleydroid":
                raise TransportUnavailable("ELM J1850 is restricted to the HarleyDroid profile")
            from .transports.elm_j1850 import ElmJ1850Transport
            return ElmJ1850Transport(self.selection.device)
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
            required = ("bitrate", "tx_id", "rx_id")
            missing = [key for key in required if spec.get(key) is None]
            if missing:
                raise TransportUnavailable(
                    f"{profile.family}: the evidence-backed CAN profile is missing "
                    f"{', '.join(missing)}; generic defaults are not used on hardware"
                )
            return CanTransport(
                channel=self.selection.device or spec.get("channel", "can0"),
                interface=("pcan" if profile.id == "harley_delphi_can_uds" and self.selection.device.upper().startswith("PCAN_") else spec.get("interface", "socketcan")),
                bitrate=spec["bitrate"],
                tx_id=spec["tx_id"],
                rx_id=spec["rx_id"],
                padding=0 if profile.session.get("protocol") in ("kawasaki-ninja7-can", "generic-obd-can-11bit", "harley-delphi-can-identity") else 0xAA,
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
            import serial  # noqa: F401
            found.append({"id": "elm_j1850", "name": "Harley J1850 (ELM327 serial)",
                          "available": True, "detail": "ELM327 serial at 38400 baud; read-only HarleyDroid profile only."})
        except ImportError:
            found.append({"id": "elm_j1850", "name": "Harley J1850 (ELM327 serial)",
                          "available": False, "detail": "pyserial is not installed (pip install -e '.[hardware]')."})
        try:
            import can  # noqa: F401

            found.append(
                {"id": "can", "name": "CAN (ISO-TP)", "available": True,
                 "detail": "python-can is installed."}
            )
            found.append(
                {"id": "cansim", "name": "CAN rehearsal (virtual)",
                 "available": True,
                 "detail": "The full generic ISO-TP framing path, flow control "
                           "and all, against the simulated ECU on a virtual bus. "
                           "Its explicit lab ids are not a motorcycle protocol claim."}
            )
        except ImportError:
            found.append(
                {"id": "can", "name": "CAN (ISO-TP)", "available": False,
                 "detail": "python-can is not installed (pip install -e '.[hardware]')."}
            )
        return found

    # -- lifecycle --------------------------------------------------------
    def reload_catalog(self) -> dict:
        """Re-read the catalog after a protocol update was applied or reverted.

        A live session keeps the profile it connected with - changing the rules
        under a conversation with an ECU is exactly the kind of surprise this
        project does not do. The new definition is in force for the next
        connection.
        """
        with self._lock:
            load_catalog.cache_clear()
            self.catalog = load_catalog()
            selected = self.selection.profile
            if selected is not None and selected.id in self.catalog.ecus:
                refreshed = self.catalog.ecu(selected.id)
                self.selection.profile = _effective_profile(
                    self.selection.entry, refreshed
                )
                self.notices = self._selection_notices(
                    self.selection.entry,
                    self.selection.profile,
                    self.selection.transport_kind,
                )
            return {
                "catalog_reloaded": True,
                "field_updates": self.catalog.field_updates,
                "session_unchanged": bool(self.service and self.service.connected),
                "note": (
                    "A connected session keeps the definition it started with; "
                    "the update applies to the next connection."
                ),
            }

    def connect(self, *, mode: str = "simulator", init_method: str | None = None) -> dict:
        with self._lock:
            if self.selection.profile is None:
                raise ValueError("select a vehicle before connecting")
            if self.service is not None and self.service.connected:
                return self.status()

            profile = self.selection.profile
            if profile.session.get("protocol") == "harley-delphi-can-identity":
                spec = self.selection.can_spec()
                if (self.selection.entry is not None and (self.selection.make.casefold() != "harley-davidson"
                        or self.selection.entry.ecu != profile.id)):
                    raise TransportUnavailable("Harley Delphi research requires an ECU-only or source-listed Harley selection")
                if (self.selection.transport_kind != "can" or mode != "read_only" or not self.selection.device.strip()
                        or (spec.get("bitrate"), spec.get("tx_id"), spec.get("rx_id")) != (500000, 0x7e0, 0x7e8)):
                    raise TransportUnavailable("Harley Delphi identity research requires an explicit CAN device and fixed 500 kbit/s IDs in read-only mode")
            if profile.session.get("protocol") == "generic-obd-can-11bit":
                spec = self.selection.can_spec()
                tx = spec.get("tx_id")
                if (self.selection.entry is not None or self.selection.transport_kind != "can"
                        or mode != "read_only" or spec.get("bitrate") != 500000
                        or type(tx) is not int or not 0x7E0 <= tx <= 0x7E7
                        or spec.get("rx_id") != tx + 8):
                    raise TransportUnavailable("Generic OBD requires ECU-only selection, read-only CAN and an 11-bit physical OBD ID pair at 500 kbit/s")
            if profile.session.get("protocol") == "harley-j1850-harleydroid":
                if (self.selection.entry is not None and (self.selection.make.casefold() != "harley-davidson"
                        or self.selection.entry.ecu != profile.id)):
                    raise TransportUnavailable("Harley J1850 requires an ECU-only or source-listed Harley selection")
                if self.selection.transport_kind != "elm_j1850" or mode != "read_only":
                    raise TransportUnavailable("Harley J1850 requires the ELM327 serial transport in read-only mode")
                if not self.selection.device.strip():
                    raise TransportUnavailable("Harley J1850 requires an explicit ELM327 serial device")
            elif self.selection.transport_kind == "elm_j1850":
                raise TransportUnavailable("ELM J1850 is restricted to the HarleyDroid profile")
            if profile.session.get("protocol") == "kawasaki-ninja7-can":
                if (self.selection.entry is None or self.selection.make.casefold() != "kawasaki"
                        or self.selection.model.casefold() != "ninja 7 hybrid" or self.selection.year < 2024):
                    raise TransportUnavailable("Ninja 7 CAN requires the Kawasaki Ninja 7 Hybrid 2024+ vehicle selection")
                spec = self.selection.can_spec()
                if (self.selection.transport_kind != "can" or mode != "read_only"
                        or (spec.get("bitrate"), spec.get("tx_id"), spec.get("rx_id")) != (500000, 0x764, 0x746)):
                    raise TransportUnavailable("Ninja 7 requires source-scoped CAN IDs and read-only mode")
            if profile.session.get("protocol") == "honda-cb500f-dashble":
                if self.selection.entry is not None:
                    raise TransportUnavailable("Honda CB500F DashBle requires an explicit ECU-only selection; source year and ECU are unspecified")
                if self.selection.transport_kind != "kline" or mode != "read_only":
                    raise TransportUnavailable("Honda CB500F DashBle supports physical K-Line and read-only mode only")
            if profile.session.get("protocol") == "honda-cbr600rr-2005":
                if (self.selection.entry is None or
                        (self.selection.make.casefold(), self.selection.model.casefold(), self.selection.year)
                        != ("honda", "cbr600rr", 2005)):
                    raise TransportUnavailable("Honda K-Line requires the exact Honda CBR600RR 2005 selection")
                if self.selection.transport_kind != "kline" or mode != "read_only":
                    raise TransportUnavailable("Honda K-Line supports physical K-Line and read-only mode only")
            if profile.session.get("protocol") == "honda-pgmfi-research":
                if (self.selection.entry is None or self.selection.make.casefold() != "honda"
                        or self.selection.entry.ecu != profile.id):
                    raise TransportUnavailable("Honda PGM-FI research requires a source-listed Honda selection")
                if self.selection.transport_kind != "kline" or mode != "read_only":
                    raise TransportUnavailable("Honda PGM-FI research supports physical K-Line and read-only mode only")
            if profile.session.get("protocol") == "kawasaki-kds-research":
                if (self.selection.entry is None or self.selection.make.casefold() != "kawasaki"
                        or self.selection.entry.ecu != profile.id):
                    raise TransportUnavailable("Kawasaki KDS research requires a source-listed vehicle")
                if self.selection.transport_kind != "kline" or mode != "read_only":
                    raise TransportUnavailable("Kawasaki KDS research supports physical K-Line and read-only mode only")
            if profile.session.get("protocol") == "suzuki-sds-gsxr-research":
                ranges = {"gsx-r600": (2006, 2016), "gsx-r750": (2006, 2016),
                          "gsx-r1000": (2005, 2016), "gsx-r1300 hayabusa": (2008, 2016)}
                bounds = ranges.get(self.selection.model.casefold())
                if (self.selection.entry is None or self.selection.make.casefold() != "suzuki"
                        or self.selection.entry.ecu != profile.id or bounds is None
                        or self.selection.year is None or not bounds[0] <= self.selection.year <= bounds[1]):
                    raise TransportUnavailable("Suzuki SDS research requires a source-listed model and year")
                if self.selection.transport_kind != "kline" or mode != "read_only":
                    raise TransportUnavailable("Suzuki SDS research supports physical K-Line and read-only mode only")
            if profile.session.get("protocol") in ("aster-versys-2012", "aster-gsxr600-2011", "suzuki-gsxr1000-2004", "suzuki-sv650ak7-2007", "suzuki-sv650-2003"):
                expected = {"aster-versys-2012": ("kawasaki", "versys 650", 2012),
                            "aster-gsxr600-2011": ("suzuki", "gsx-r600", 2011),
                            "suzuki-gsxr1000-2004": ("suzuki", "gsx-r1000", 2004),
                            "suzuki-sv650ak7-2007": ("suzuki", "sv650ak7", 2007),
                            "suzuki-sv650-2003": ("suzuki", "sv650", (2003, 2004, 2005))}[profile.session["protocol"]]
                make, model, year = expected
                years = year if isinstance(year, tuple) else (year,)
                if (self.selection.entry is None or
                        (self.selection.make.casefold(), self.selection.model.casefold()) != (make, model) or
                        self.selection.year not in years):
                    raise TransportUnavailable("Source-scoped K-Line requires the exact tested model and year")
                if self.selection.transport_kind != "kline" or mode != "read_only":
                    raise TransportUnavailable("Source-scoped K-Line supports physical K-Line and read-only mode only")
            if profile.session.get("protocol") == "kawasaki-er6n":
                if (self.selection.entry is None or self.selection.make.casefold() != "kawasaki"
                        or self.selection.model.casefold() != "er-6n" or self.selection.year != 2006):
                    raise TransportUnavailable("ER-6n KDS requires the exact Kawasaki ER-6n 2006 vehicle selection")
                if self.selection.transport_kind != "kline" or mode != "read_only":
                    raise TransportUnavailable("ER-6n KDS supports K-Line in read-only mode only; no simulator or CAN session")
            if profile.session.get("protocol") == "triumph-daytona-2012":
                if (self.selection.entry is None or self.selection.make.casefold() != "triumph"
                        or self.selection.model.casefold() != "daytona 675" or self.selection.year != 2012):
                    raise TransportUnavailable("Daytona OBD requires the exact Triumph Daytona 675 2012 vehicle selection")
                if self.selection.transport_kind != "kline" or mode != "read_only":
                    raise TransportUnavailable("Daytona OBD supports K-Line in read-only mode only; no simulator or CAN session")
            if (self.selection.transport_kind in self._SIM_TRANSPORTS
                    and profile.session.get("simulator_supported") is False):
                raise TransportUnavailable(f"{profile.family}: no matching simulator is implemented")
            if (
                self.selection.transport_kind not in self._SIM_TRANSPORTS
                and profile.session.get("physical_supported") is False
            ):
                reason = profile.session.get(
                    "physical_blocked_reason",
                    "the physical diagnostic protocol is not validated",
                )
                raise TransportUnavailable(
                    f"{profile.family}: {reason} The safety boundary stopped here: "
                    "no transport was constructed, no port was opened, and no "
                    "request was sent."
                )

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
            try:
                self.service.connect(init_method=init_method)
            except Exception:
                self.service.disconnect()
                self.service = None
                self._session_profile = None
                if self.log is not None:
                    self.log.close()
                    self.log = None
                raise
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
            "field_updates": self.catalog.field_updates,
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
