"""Data-driven vehicle / ECU capability catalog.

Every ECU family is a versioned JSON document under ``ecus/``. Nothing in the
protocol or UI layers may hardcode a local identifier, a scaling factor or an
actuator number - it all comes from here, so adding a motorcycle is a data
change rather than a code change.

Each definition carries an explicit ``confidence`` level, and the diagnostics
service degrades to read-only identification for anything below
``documented``. Guessing at an unknown byte is how tools brick ECUs.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

CATALOG_DIR = Path(__file__).parent
ECU_DIR = CATALOG_DIR / "ecus"

#: Ordered from most to least trustworthy.
CONFIDENCE_LEVELS = (
    "verified-bench",   # exercised against this ECU on a bench or a bike
    "verified-capture", # decoded from a real K-Line/CAN capture
    "documented",       # from a service manual or a mature open-source tool
    "inferred",         # pattern-matched from a sibling ECU, unproven
    "unknown",          # placeholder; read-only identification only
)

#: Capabilities below this confidence are not offered to the user.
MIN_CONFIDENCE_FOR_CONTROL = "documented"


class CatalogError(Exception):
    pass


def confidence_rank(level: str) -> int:
    try:
        return CONFIDENCE_LEVELS.index(level)
    except ValueError:
        return len(CONFIDENCE_LEVELS)


def meets(level: str, minimum: str = MIN_CONFIDENCE_FOR_CONTROL) -> bool:
    return confidence_rank(level) <= confidence_rank(minimum)


@dataclass(frozen=True)
class Parameter:
    """One live-data channel."""

    key: str
    name: str
    local_id: int
    unit: str = ""
    offset: int = 0
    length: int | None = None
    endian: str = "big"
    signed: bool = False
    scale: float = 1.0
    bias: float = 0.0
    recip: float = 0.0
    digits: int = 1
    group: str = "engine"
    default: bool = False
    dead: bool = False
    states: dict = field(default_factory=dict)
    min: float | None = None
    max: float | None = None
    confidence: str = "documented"

    @classmethod
    def from_dict(cls, raw: dict) -> "Parameter":
        states = {str(k): v for k, v in (raw.get("states") or {}).items()}
        return cls(
            key=raw["key"],
            name=raw["name"],
            local_id=int(raw["local_id"]),
            unit=raw.get("unit", ""),
            offset=int(raw.get("offset", 0)),
            length=raw.get("length"),
            endian=raw.get("endian", "big"),
            signed=bool(raw.get("signed", False)),
            scale=float(raw.get("scale", 1.0)),
            bias=float(raw.get("bias", 0.0)),
            recip=float(raw.get("recip", 0.0)),
            digits=int(raw.get("digits", 1)),
            group=raw.get("group", "engine"),
            default=bool(raw.get("default", False)),
            dead=bool(raw.get("dead", False)),
            states=states,
            min=raw.get("min"),
            max=raw.get("max"),
            confidence=raw.get("confidence", "documented"),
        )

    def as_dict(self) -> dict:
        return {
            "key": self.key, "name": self.name, "local_id": self.local_id,
            "unit": self.unit, "group": self.group, "digits": self.digits,
            "default": self.default, "states": self.states,
            "min": self.min, "max": self.max, "confidence": self.confidence,
        }


@dataclass(frozen=True)
class Actuator:
    """One commandable output."""

    key: str
    name: str
    local_id: int
    on_command: int = 0x07
    off_command: int = 0x00
    #: Maximum energised time the application will allow, in seconds.
    max_pulse_s: float = 5.0
    #: Preconditions, checked by the safety gate before the command goes out.
    requires_engine_off: bool = True
    requires_engine_running: bool = False
    group: str = "actuator"
    confidence: str = "documented"
    warning: str = ""

    @classmethod
    def from_dict(cls, raw: dict) -> "Actuator":
        return cls(
            key=raw["key"], name=raw["name"], local_id=int(raw["local_id"]),
            on_command=int(raw.get("on_command", 0x07)),
            off_command=int(raw.get("off_command", 0x00)),
            max_pulse_s=float(raw.get("max_pulse_s", 5.0)),
            requires_engine_off=bool(raw.get("requires_engine_off", True)),
            requires_engine_running=bool(raw.get("requires_engine_running", False)),
            group=raw.get("group", "actuator"),
            confidence=raw.get("confidence", "documented"),
            warning=raw.get("warning", ""),
        )

    def as_dict(self) -> dict:
        return {
            "key": self.key, "name": self.name, "local_id": self.local_id,
            "max_pulse_s": self.max_pulse_s, "group": self.group,
            "requires_engine_off": self.requires_engine_off,
            "requires_engine_running": self.requires_engine_running,
            "confidence": self.confidence, "warning": self.warning,
        }


@dataclass(frozen=True)
class Routine:
    """An adaptation or service routine (TPS reset, self-learning, ...)."""

    key: str
    name: str
    service: int          # 0x31 StartRoutine or 0x30 IOControl
    local_id: int
    params: tuple[int, ...] = ()
    expect: int | None = None
    description: str = ""
    requires_engine_off: bool = True
    requires_engine_running: bool = False
    follow_up: str = ""
    reversible: bool = False
    confidence: str = "documented"
    warning: str = ""

    @classmethod
    def from_dict(cls, raw: dict) -> "Routine":
        return cls(
            key=raw["key"], name=raw["name"],
            service=int(raw["service"]), local_id=int(raw["local_id"]),
            params=tuple(int(p) for p in raw.get("params", ())),
            expect=raw.get("expect"),
            description=raw.get("description", ""),
            requires_engine_off=bool(raw.get("requires_engine_off", True)),
            requires_engine_running=bool(raw.get("requires_engine_running", False)),
            follow_up=raw.get("follow_up", ""),
            reversible=bool(raw.get("reversible", False)),
            confidence=raw.get("confidence", "documented"),
            warning=raw.get("warning", ""),
        )

    def as_dict(self) -> dict:
        return {
            "key": self.key, "name": self.name, "service": self.service,
            "local_id": self.local_id, "description": self.description,
            "requires_engine_off": self.requires_engine_off,
            "requires_engine_running": self.requires_engine_running,
            "follow_up": self.follow_up, "reversible": self.reversible,
            "confidence": self.confidence, "warning": self.warning,
        }


@dataclass(frozen=True)
class EcuProfile:
    """Everything the toolchain knows about one ECU family."""

    id: str
    family: str
    display_name: str
    transport: str
    confidence: str
    years: str = ""
    notes: str = ""
    kline: dict = field(default_factory=dict)
    can: dict = field(default_factory=dict)
    session: dict = field(default_factory=dict)
    identification: dict = field(default_factory=dict)
    memory: dict = field(default_factory=dict)
    parameters: tuple[Parameter, ...] = ()
    actuators: tuple[Actuator, ...] = ()
    routines: tuple[Routine, ...] = ()
    dtc_descriptions: dict = field(default_factory=dict)
    capabilities: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, raw: dict) -> "EcuProfile":
        return cls(
            id=raw["id"], family=raw["family"],
            display_name=raw.get("display_name", raw["family"]),
            transport=raw.get("transport", "kline"),
            confidence=raw.get("confidence", "unknown"),
            years=raw.get("years", ""),
            notes=raw.get("notes", ""),
            kline=raw.get("kline", {}),
            can=raw.get("can", {}),
            session=raw.get("session", {}),
            identification=raw.get("identification", {}),
            memory=raw.get("memory", {}),
            parameters=tuple(Parameter.from_dict(p) for p in raw.get("parameters", [])),
            actuators=tuple(Actuator.from_dict(a) for a in raw.get("actuators", [])),
            routines=tuple(Routine.from_dict(r) for r in raw.get("routines", [])),
            dtc_descriptions=raw.get("dtc_descriptions", {}),
            capabilities=tuple(raw.get("capabilities", [])),
            sources=tuple(raw.get("sources", [])),
        )

    # -- lookups ----------------------------------------------------------
    def parameter(self, key: str) -> Parameter:
        for p in self.parameters:
            if p.key == key:
                return p
        raise CatalogError(f"{self.id}: no parameter {key!r}")

    def actuator(self, key: str) -> Actuator:
        for a in self.actuators:
            if a.key == key:
                return a
        raise CatalogError(f"{self.id}: no actuator {key!r}")

    def routine(self, key: str) -> Routine:
        for r in self.routines:
            if r.key == key:
                return r
        raise CatalogError(f"{self.id}: no routine {key!r}")

    @property
    def live_parameters(self) -> tuple[Parameter, ...]:
        return tuple(p for p in self.parameters if not p.dead)

    @property
    def default_parameters(self) -> tuple[Parameter, ...]:
        return tuple(p for p in self.live_parameters if p.default)

    def supports(self, capability: str) -> bool:
        """A capability counts only if the definition is trustworthy enough."""
        if capability not in self.capabilities:
            return False
        if capability in ("identify", "live", "dtc_read"):
            return True
        return meets(self.confidence)

    def as_dict(self, *, include_parameters: bool = True) -> dict:
        data = {
            "id": self.id, "family": self.family, "display_name": self.display_name,
            "transport": self.transport, "confidence": self.confidence,
            "years": self.years, "notes": self.notes,
            "capabilities": list(self.capabilities),
            "effective_capabilities": [c for c in self.capabilities if self.supports(c)],
            "sources": list(self.sources),
            "memory": self.memory,
            "kline": self.kline,
            "can": self.can,
            "actuators": [a.as_dict() for a in self.actuators],
            "routines": [r.as_dict() for r in self.routines],
        }
        if include_parameters:
            data["parameters"] = [p.as_dict() for p in self.live_parameters]
        return data


@dataclass(frozen=True)
class VehicleEntry:
    """One motorcycle variant mapped to an ECU family."""

    model: str
    year_from: int
    year_to: int | None
    ecu: str
    make: str = "Moto Guzzi"
    displacement: str = ""
    tps: str = ""
    notes: str = ""
    confidence: str = "documented"
    #: Per-model CAN overrides; merged over the ECU-level spec.
    can: dict = field(default_factory=dict)

    @property
    def label(self) -> str:
        end = self.year_to or "present"
        return f"{self.model} ({self.year_from}-{end})"

    def covers(self, year: int) -> bool:
        return self.year_from <= year and (self.year_to is None or year <= self.year_to)

    def as_dict(self) -> dict:
        return {
            "make": self.make,
            "model": self.model, "year_from": self.year_from, "year_to": self.year_to,
            "ecu": self.ecu, "displacement": self.displacement, "tps": self.tps,
            "notes": self.notes, "confidence": self.confidence, "label": self.label,
            "can": self.can,
        }


class Catalog:
    """Loaded view of the whole catalog."""

    def __init__(self, ecus: dict[str, EcuProfile], vehicles: list[VehicleEntry]):
        self.ecus = ecus
        self.vehicles = vehicles

    # -- access -----------------------------------------------------------
    def ecu(self, ecu_id: str) -> EcuProfile:
        try:
            return self.ecus[ecu_id]
        except KeyError:
            raise CatalogError(
                f"unknown ECU {ecu_id!r}; known: {', '.join(sorted(self.ecus))}"
            ) from None

    def makes(self) -> list[str]:
        return sorted({v.make for v in self.vehicles})

    def models(self, make: str = "") -> list[str]:
        if make:
            return sorted({v.model for v in self.vehicles
                           if v.make.lower() == make.lower()})
        return sorted({v.model for v in self.vehicles})

    def find(
        self, model: str, year: int | None = None, make: str = ""
    ) -> list[VehicleEntry]:
        matches = [v for v in self.vehicles if v.model.lower() == model.lower()]
        if make:
            matches = [v for v in matches if v.make.lower() == make.lower()]
        if year is not None:
            matches = [v for v in matches if v.covers(year)]
        return matches

    def resolve(
        self, model: str, year: int, make: str = ""
    ) -> tuple[VehicleEntry, EcuProfile]:
        matches = self.find(model, year, make)
        if not matches:
            scope = f" in {make}" if make else ""
            raise CatalogError(f"no catalog entry{scope} for {model} {year}")
        if len(matches) > 1:
            # Overlapping running changes exist (Guzzi changed ECUs mid-year).
            # Prefer the entry with the narrower window, then the later start.
            matches.sort(
                key=lambda v: (
                    (v.year_to or 9999) - v.year_from, -v.year_from
                )
            )
        entry = matches[0]
        return entry, self.ecu(entry.ecu)

    def ambiguous(self, model: str, year: int) -> bool:
        return len(self.find(model, year)) > 1

    def summary(self) -> dict:
        return {
            "ecu_count": len(self.ecus),
            "vehicle_count": len(self.vehicles),
            "model_count": len(self.models()),
            "year_range": [
                min(v.year_from for v in self.vehicles),
                max((v.year_to or 2026) for v in self.vehicles),
            ],
            "ecus": [e.as_dict(include_parameters=False) for e in self.ecus.values()],
        }


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CatalogError(f"{path.name}: {exc}") from exc


@lru_cache(maxsize=1)
def load_catalog() -> Catalog:
    """Load and validate the catalog from disk (cached)."""
    shared_dtc = _load_json(CATALOG_DIR / "dtc_sae.json")["codes"]

    ecus: dict[str, EcuProfile] = {}
    for path in sorted(ECU_DIR.glob("*.json")):
        raw = _load_json(path)
        # Shared SAE table first so a family-specific entry can override it.
        raw["dtc_descriptions"] = {**shared_dtc, **raw.get("dtc_descriptions", {})}
        profile = EcuProfile.from_dict(raw)
        if profile.id in ecus:
            raise CatalogError(f"duplicate ECU id {profile.id!r} in {path.name}")
        ecus[profile.id] = profile

    raw_vehicles = _load_json(CATALOG_DIR / "vehicles.json")
    vehicles = [VehicleEntry(**v) for v in raw_vehicles["vehicles"]]

    unknown = {v.ecu for v in vehicles} - set(ecus)
    if unknown:
        raise CatalogError(f"vehicles.json references unknown ECUs: {sorted(unknown)}")

    return Catalog(ecus, vehicles)
