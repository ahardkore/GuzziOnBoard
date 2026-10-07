"""Data-driven vehicle / ECU capability catalog.

Every ECU family is a versioned JSON document under ``ecus/``. Nothing in the
protocol or UI layers may hardcode a local identifier, a scaling factor or an
actuator number - it all comes from here, so adding a motorcycle is a data
change rather than a code change.

Each definition carries an explicit ``confidence`` level. Read operations are
available only when an evidence-backed capability is declared; control
operations additionally require ``documented`` confidence or better. Guessing
at an unknown byte is how tools brick ECUs.
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
    "unknown",          # placeholder; no operation unless separately evidenced
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
    #: Ordered one-byte legacy requests. Empty means use ``local_id`` once.
    request_ids: tuple[int, ...] = ()
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
            local_id=int(raw.get("local_id", (raw.get("request_ids") or [0])[0])),
            request_ids=tuple(int(i) for i in raw.get("request_ids", ())),
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
            "request_ids": list(self.request_ids),
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
    #: Per-capability confidence, set only by a verified protocol update.
    #: An entry here overrides ``confidence`` for that one capability, which
    #: is how a field-confirmed read surface can be enabled without claiming
    #: that the whole definition was bench-tested.
    capability_confidence: dict = field(default_factory=dict)
    #: Set when a verified protocol update promoted this family, carrying the
    #: pack id, the independent confirmations behind it and the pack digest.
    field_confirmation: dict = field(default_factory=dict)

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
            capability_confidence={
                str(k): str(v)
                for k, v in (raw.get("capability_confidence") or {}).items()
            },
            field_confirmation=dict(raw.get("field_confirmation") or {}),
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

    def capability_level(self, capability: str) -> str:
        """The confidence level that governs one capability."""
        return self.capability_confidence.get(capability, self.confidence)

    def supports(self, capability: str) -> bool:
        """A capability counts only if the definition is trustworthy enough."""
        if capability not in self.capabilities:
            return False
        if capability in ("identify", "live", "dtc_read"):
            return True
        return meets(self.capability_level(capability))

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
            "session": self.session,
            "actuators": [a.as_dict() for a in self.actuators],
            "routines": [r.as_dict() for r in self.routines],
            "capability_confidence": dict(self.capability_confidence),
            "field_confirmation": dict(self.field_confirmation),
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

    def __init__(
        self,
        ecus: dict[str, EcuProfile],
        vehicles: list[VehicleEntry],
        field_updates: dict | None = None,
    ):
        self.ecus = ecus
        self.vehicles = vehicles
        #: What a verified protocol update changed, if one is applied. Empty
        #: for a stock install; never silently populated.
        self.field_updates = field_updates or {"applied": False}

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
            "protocol_updates": self.field_updates,
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


def source_path(ecu_id: str) -> Path:
    """The definition file a family was loaded from."""
    return ECU_DIR / f"{ecu_id}.json"


def source_fingerprint(ecu_id: str) -> str:
    """SHA-256 of a family definition as shipped on disk.

    A protocol update names the exact definition revision it was reviewed
    against, so a promotion can never be applied to a definition that has
    changed underneath it.
    """
    import hashlib

    path = source_path(ecu_id)
    if not path.is_file():
        raise CatalogError(f"unknown ECU {ecu_id!r}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def apply_promotion(profile: EcuProfile, promotion: dict) -> EcuProfile:
    """Apply one reviewed promotion to a loaded profile.

    Only the fields a protocol update is allowed to touch are considered:
    confidence levels, the physical-session flag, read-level capabilities and
    provenance. Scalings, identifiers, actuators and routines are immutable
    here - a promotion that could rewrite those would be a way to smuggle a
    guessed byte through review.
    """
    from dataclasses import replace

    capabilities = list(profile.capabilities)
    for name in promotion.get("capabilities_add", ()):
        if name not in capabilities:
            capabilities.append(str(name))

    capability_confidence = dict(profile.capability_confidence)
    for name, level in (promotion.get("capability_confidence") or {}).items():
        capability_confidence[str(name)] = str(level)

    parameter_confidence = promotion.get("parameter_confidence") or {}
    parameters = profile.parameters
    if parameter_confidence:
        parameters = tuple(
            replace(param, confidence=str(parameter_confidence[param.key]))
            if param.key in parameter_confidence
            else param
            for param in parameters
        )

    session = dict(profile.session)
    if promotion.get("physical_supported"):
        session["physical_evidence_note"] = promotion.get("evidence_note", "")
        session["physical_supported"] = True
    memory = dict(profile.memory)
    if promotion.get("memory_read_supported"):
        memory["read_supported"] = True

    sources = tuple(profile.sources) + tuple(promotion.get("sources_add", ()))
    return replace(
        profile,
        capabilities=tuple(capabilities),
        capability_confidence=capability_confidence,
        parameters=parameters,
        session=session,
        memory=memory,
        sources=sources,
        field_confirmation=dict(promotion.get("field_confirmation") or {}),
    )


def _apply_field_updates(ecus: dict[str, EcuProfile]) -> dict:
    """Apply the locally stored, signature-verified protocol update."""
    from ..protocol_updates import load_applied_overlay

    overlay, status = load_applied_overlay()
    report = {"applied": bool(overlay), "status": status, "promotions": {}}
    if not overlay:
        return report
    for ecu_id, promotion in (overlay.get("promotions") or {}).items():
        profile = ecus.get(ecu_id)
        if profile is None:
            report["promotions"][ecu_id] = {
                "applied": False,
                "reason": "the promotion names an ECU this catalog does not have",
            }
            continue
        ecus[ecu_id] = apply_promotion(profile, promotion)
        report["promotions"][ecu_id] = {
            "applied": True,
            "pack": overlay.get("pack", {}).get("id", ""),
            "confirmations": len(promotion.get("references", [])),
            "effects": sorted(promotion.get("effects", {})),
        }
    return report


@lru_cache(maxsize=4)
def load_catalog(*, overlays: bool = True) -> Catalog:
    """Load and validate the catalog from disk (cached).

    ``overlays=False`` loads the definitions exactly as shipped, which is what
    the demo snapshot and the catalog conformance tests use: a promotion that
    exists only on the maintainer's machine must never leak into either.
    """
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

    field_updates = (
        _apply_field_updates(ecus) if overlays else {"applied": False, "status": {}}
    )
    return Catalog(ecus, vehicles, field_updates=field_updates)
