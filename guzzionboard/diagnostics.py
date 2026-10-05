"""Diagnostics service: the layer the UI talks to.

It owns one ECU conversation and enforces the order of operations:

    connect -> identify -> (live data | DTCs | discovery) -> service actions

Nothing that can change the motorcycle happens without a
:class:`~guzzionboard.safety.Decision` and the single-use token it mints.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from .catalog import Catalog, EcuProfile, Parameter, load_catalog
from .protocol.kwp2000 import (
    KWP2000Session,
    NegativeResponse,
    ProtocolError,
    Service,
    TimingParameters,
    apply_scaling,
    decode_raw_value,
)
from .safety import Decision, Risk, SafetyGate, SafetyViolation
from .sessionlog import NullSessionLog, SessionLog
from .transports.base import Connection, InitResult, Transport, TransportError


@dataclass
class Sample:
    """One decoded live value, with the bytes it came from."""

    key: str
    name: str
    local_id: int
    raw: bytes
    value: float | int | None
    unit: str
    text: str = ""
    at: float = field(default_factory=time.time)
    error: str = ""

    def as_dict(self) -> dict:
        return {
            "key": self.key, "name": self.name, "local_id": self.local_id,
            "raw": self.raw.hex(" "), "value": self.value, "unit": self.unit,
            "text": self.text, "at": self.at, "error": self.error,
        }


@dataclass
class Identity:
    fields: dict = field(default_factory=dict)
    raw: bytes = b""
    ecu_id: str = ""
    family: str = ""

    def as_dict(self) -> dict:
        return {
            "fields": self.fields, "raw": self.raw.hex(" "),
            "ecu_id": self.ecu_id, "family": self.family,
        }


class NotConnected(RuntimeError):
    pass


class DiagnosticsService:
    """One ECU conversation."""

    def __init__(
        self,
        profile: EcuProfile,
        transport: Transport,
        gate: SafetyGate,
        *,
        log: SessionLog | None = None,
        catalog: Catalog | None = None,
    ):
        self.profile = profile
        self.transport = transport
        self.gate = gate
        self.log = log or NullSessionLog()
        self.catalog = catalog or load_catalog()

        self.connection: Connection | None = None
        self.session: KWP2000Session | None = None
        self.init_result: InitResult | None = None
        self.identity: Identity | None = None
        self.last_samples: dict[str, Sample] = {}
        self.discovered: dict[int, dict] = {}
        #: Actuators currently energised -> deadline (monotonic).
        self.active_outputs: dict[str, float] = {}

        self._lock = threading.RLock()
        self._last_tx = 0.0
        self._stop = threading.Event()
        self._keepalive: threading.Thread | None = None

    # -- lifecycle --------------------------------------------------------
    @property
    def connected(self) -> bool:
        return self.session is not None and self.connection is not None

    def connect(self, *, init_method: str | None = None) -> InitResult:
        with self._lock:
            if self.connected:
                return self.init_result  # type: ignore[return-value]

            self.connection = self.transport.open()
            method = init_method or self.profile.kline.get("init", "fast")
            self.init_result = self.transport.initialize(
                self.connection,
                method=method,
                address=self.profile.kline.get("address", 0x33),
            )
            self.log.action(
                "connect",
                {
                    "transport": self.transport.name,
                    "ecu": self.profile.id,
                    "init": self.init_result.method,
                    "ok": self.init_result.ok,
                    "detail": self.init_result.detail,
                },
            )
            if not self.init_result.ok:
                self.connection.close()
                self.connection = None
                raise TransportError(f"ECU wake-up failed: {self.init_result.detail}")

            timing = TimingParameters(
                tester_present_interval=self.profile.session.get(
                    "tester_present_interval", 2.0
                )
            )
            self.session = KWP2000Session(
                connection=self.connection,
                timing=timing,
                target=self.profile.kline.get("ecu_address", 0x10),
                source=self.profile.kline.get("tester_address", 0xF1),
                addressed=self.profile.kline.get("addressed", True),
                on_frame=self.log.frame,
                write_guard=self.gate.session_guard(),
            )

            if self.transport.is_physical or self.transport.name == "simulator":
                if self.init_result.method.endswith("fast"):
                    self.session.try_request([Service.START_COMMUNICATION])
            if self.profile.session.get("access_timing"):
                self.session.access_timing_parameters()

            self._touch()
            self._start_keepalive()
            return self.init_result

    def disconnect(self) -> None:
        with self._lock:
            self._stop.set()
            if self._keepalive:
                self._keepalive.join(timeout=1.0)
                self._keepalive = None
            if self.session is not None:
                self.release_all_outputs()
                try:
                    self.session.stop_diagnostic_session()
                    self.session.stop_communication()
                except Exception:
                    pass
            if self.connection is not None:
                self.connection.close()
            self.log.action("disconnect", {})
            self.session = None
            self.connection = None
            self.identity = None

    def _require(self) -> KWP2000Session:
        if self.session is None:
            raise NotConnected("not connected to an ECU")
        return self.session

    def _touch(self) -> None:
        self._last_tx = time.monotonic()

    def _start_keepalive(self) -> None:
        self._stop.clear()

        def run() -> None:
            interval = self.profile.session.get("tester_present_interval", 2.0)
            while not self._stop.wait(0.25):
                if time.monotonic() - self._last_tx < interval:
                    continue
                with self._lock:
                    if self.session is None:
                        return
                    try:
                        self.session.tester_present()
                        self._touch()
                    except Exception as exc:
                        self.log.error("keepalive", str(exc))
                        return
                self._release_expired()

        self._keepalive = threading.Thread(
            target=run, name="guzzionboard-keepalive", daemon=True
        )
        self._keepalive.start()

    # -- identification ---------------------------------------------------
    def identify(self) -> Identity:
        with self._lock:
            session = self._require()
            spec = self.profile.identification
            raw = session.read_ecu_identification(spec.get("option", 0x80))
            self._touch()

            fields = {}
            for field_spec in spec.get("fields", []):
                chunk = raw[
                    field_spec["offset"] : field_spec["offset"] + field_spec["length"]
                ]
                fields[field_spec["name"]] = (
                    chunk.decode("ascii", "replace").strip().strip("\x00").strip()
                )
            self.identity = Identity(
                fields=fields, raw=raw, ecu_id=self.profile.id, family=self.profile.family
            )
            self.gate.state.identified = True
            self.gate.state.ecu_confidence = self.profile.confidence
            self.log.action("identify", self.identity.as_dict())
            return self.identity

    # -- live data --------------------------------------------------------
    def read_parameter(self, param: Parameter) -> Sample:
        session = self._require()
        try:
            raw = session.read_data_by_local_id(param.local_id)
            self._touch()
        except (NegativeResponse, ProtocolError) as exc:
            sample = Sample(
                param.key, param.name, param.local_id, b"", None, param.unit,
                error=str(exc),
            )
            self.last_samples[param.key] = sample
            return sample

        try:
            value_raw = decode_raw_value(
                raw,
                offset=param.offset,
                length=param.length,
                endian=param.endian,
                signed=param.signed,
            )
        except ProtocolError as exc:
            sample = Sample(
                param.key, param.name, param.local_id, raw, None, param.unit,
                error=str(exc),
            )
            self.last_samples[param.key] = sample
            return sample

        value = apply_scaling(
            value_raw, scale=param.scale, bias=param.bias, recip=param.recip
        )
        value = round(value, param.digits) if param.digits else int(round(value))
        text = param.states.get(str(int(value_raw)), "") if param.states else ""

        sample = Sample(
            param.key, param.name, param.local_id, raw, value, param.unit, text=text
        )
        self.last_samples[param.key] = sample
        self.log.sample(param.key, param.local_id, raw, value, param.unit)
        self._update_inferred_state(param.key, value, text)
        return sample

    def read_parameters(self, keys: list[str] | None = None) -> list[Sample]:
        with self._lock:
            if keys is None:
                params = self.profile.default_parameters or self.profile.live_parameters
            else:
                params = [self.profile.parameter(k) for k in keys]
            return [self.read_parameter(p) for p in params]

    def _update_inferred_state(self, key: str, value, text: str) -> None:
        """Feed the safety gate from observed values, never from assumptions."""
        state = self.gate.state
        if key == "battery" and isinstance(value, (int, float)):
            state.battery_v = float(value)
        elif key == "rpm" and isinstance(value, (int, float)):
            state.engine_running = value > 200
        elif key == "stop_state" and text:
            state.engine_running = text == "Running"

    # -- DTCs -------------------------------------------------------------
    def read_dtcs(self) -> dict:
        """Codes plus the context the workstation observed when it read them.

        An IAW ECU of this era does not hand over an ECU-stored freeze frame,
        and this project will not pretend it does. What the workstation *can*
        do honestly is read the default live channels at the same moment and
        keep them next to the codes: the engine state the fault was read in,
        labelled as exactly that.
        """
        with self._lock:
            session = self._require()
            dtcs = session.read_dtcs(self.profile.dtc_descriptions)
            self._touch()
            payload = [d.as_dict() for d in dtcs]
            context = self._read_context()
            self.log.action(
                "read_dtcs",
                {"count": len(payload), "dtcs": payload, "context": context},
            )
            return {"dtcs": payload, "context": context}

    def _read_context(self, limit: int = 8) -> dict[str, dict]:
        """A handful of default channels, best effort, honestly labelled."""
        out: dict[str, dict] = {}
        for param in self.profile.default_parameters[:limit]:
            try:
                sample = self.read_parameter(param)
            except Exception:
                continue          # a channel that fails is skipped, not faked
            out[param.key] = {
                "name": param.name,
                "value": sample.value,
                "unit": param.unit,
            }
        return out

    def check_clear_dtcs(self) -> Decision:
        decision = self.gate.evaluate_clear_dtcs(self.profile)
        self.log.decision(decision.as_dict())
        return decision

    def clear_dtcs(self, token: str) -> dict:
        with self._lock:
            session = self._require()
            self.gate.consume(token, "clear-dtcs")
            session.write_guard = self.gate.session_guard(
                {Service.CLEAR_DIAGNOSTIC_INFORMATION}
            )
            try:
                session.clear_dtcs()
                self._touch()
            finally:
                session.write_guard = self.gate.session_guard()
            self.log.action("clear_dtcs", {"result": "ok"})
            remaining = [
                d.as_dict() for d in session.read_dtcs(self.profile.dtc_descriptions)
            ]
            return {"ok": True, "remaining": remaining}

    # -- actuators --------------------------------------------------------
    def check_actuator(self, key: str) -> Decision:
        actuator = self.profile.actuator(key)
        decision = self.gate.evaluate_actuator(self.profile, actuator)
        self.log.decision(decision.as_dict())
        return decision

    def pulse_actuator(self, key: str, token: str, seconds: float | None = None) -> dict:
        """Energise an output for a bounded time.

        IAW ECUs have no output timer: once commanded on, an output stays on
        until something turns it off. The deadline is therefore owned here, and
        release also happens on disconnect and on keep-alive ticks, so a closed
        browser tab cannot leave a fuel pump running.
        """
        with self._lock:
            session = self._require()
            actuator = self.profile.actuator(key)
            self.gate.consume(token, f"actuator:{key}")

            duration = min(
                float(seconds or actuator.max_pulse_s), actuator.max_pulse_s
            )
            duration = max(0.2, duration)

            session.write_guard = self.gate.session_guard(
                {Service.IO_CONTROL_BY_LOCAL_ID}
            )
            try:
                session.io_control(actuator.local_id, actuator.on_command)
                self._touch()
            finally:
                session.write_guard = self.gate.session_guard()

            self.active_outputs[key] = time.monotonic() + duration
            self.log.action(
                "actuator_on",
                {"key": key, "local_id": actuator.local_id, "duration_s": duration},
            )
            return {"ok": True, "key": key, "duration_s": duration}

    def release_actuator(self, key: str) -> dict:
        with self._lock:
            if self.session is None:
                self.active_outputs.pop(key, None)
                return {"ok": False, "reason": "not connected"}
            actuator = self.profile.actuator(key)
            self.session.write_guard = self.gate.session_guard(
                {Service.IO_CONTROL_BY_LOCAL_ID}
            )
            try:
                self.session.io_control(actuator.local_id, actuator.off_command)
                self._touch()
            except Exception as exc:
                self.log.error("actuator_off", f"{key}: {exc}")
                return {"ok": False, "reason": str(exc)}
            finally:
                self.session.write_guard = self.gate.session_guard()
            self.active_outputs.pop(key, None)
            self.log.action("actuator_off", {"key": key})
            return {"ok": True, "key": key}

    def _release_expired(self) -> None:
        now = time.monotonic()
        for key, deadline in list(self.active_outputs.items()):
            if now >= deadline:
                self.release_actuator(key)

    def release_all_outputs(self) -> None:
        for key in list(self.active_outputs):
            self.release_actuator(key)

    # -- routines ---------------------------------------------------------
    def check_routine(self, key: str) -> Decision:
        routine = self.profile.routine(key)
        decision = self.gate.evaluate_routine(self.profile, routine)
        self.log.decision(decision.as_dict())
        return decision

    def run_routine(self, key: str, token: str) -> dict:
        with self._lock:
            session = self._require()
            routine = self.profile.routine(key)
            self.gate.consume(token, f"routine:{key}")

            service = Service(routine.service)
            session.write_guard = self.gate.session_guard({service})
            try:
                if self.profile.session.get("lazy_session"):
                    session.start_diagnostic_session(
                        self.profile.session.get("diagnostic_session", 0x81)
                    )
                if service is Service.START_ROUTINE_BY_LOCAL_ID:
                    frame = session.start_routine(routine.local_id, *routine.params)
                else:
                    frame = session.io_control(
                        routine.local_id,
                        routine.params[0] if routine.params else 0x07,
                    )
                self._touch()
            finally:
                session.write_guard = self.gate.session_guard()

            result = {
                "ok": True,
                "key": key,
                "name": routine.name,
                "response": frame.hex(),
                "follow_up": routine.follow_up,
            }
            # Best effort: many IAW families do not implement 0x33 at all.
            results = session.routine_results(routine.local_id)
            if results is not None:
                result["routine_results"] = results.hex()
            self.log.action("routine", result)
            return result

    # -- discovery --------------------------------------------------------
    def discover_identifiers(
        self, start: int = 0x30, end: int = 0x7F, *, settle: float = 0.0
    ) -> dict:
        """Read-only sweep of ``21 <rli>`` across a range.

        This is how an unmapped ECU family gets characterised: the sweep is
        pure reads, so it is safe on any bike, and the output is a contribution
        ready to be turned into a catalog definition.
        """
        with self._lock:
            session = self._require()
            found: dict[int, dict] = {}
            for local_id in range(start, end + 1):
                try:
                    raw = session.read_data_by_local_id(local_id)
                    found[local_id] = {
                        "local_id": local_id,
                        "hex_id": f"0x{local_id:02X}",
                        "length": len(raw),
                        "raw": raw.hex(" "),
                        "int_be": int.from_bytes(raw, "big") if raw else None,
                        "answered": True,
                    }
                except NegativeResponse as exc:
                    found[local_id] = {
                        "local_id": local_id, "hex_id": f"0x{local_id:02X}",
                        "answered": False, "nrc": exc.code,
                    }
                except ProtocolError as exc:
                    found[local_id] = {
                        "local_id": local_id, "hex_id": f"0x{local_id:02X}",
                        "answered": False, "error": str(exc),
                    }
                self._touch()
                if settle:
                    time.sleep(settle)

            self.discovered = found
            answered = [f for f in found.values() if f.get("answered")]
            summary = {
                "range": [start, end],
                "answered": len(answered),
                "scanned": len(found),
                "identifiers": list(found.values()),
            }
            self.log.action("discover", {"range": [start, end], "answered": len(answered)})
            return summary

    def discovery_delta(self, before: dict, after: dict) -> list[dict]:
        """Identifiers whose value changed between two sweeps.

        Sweep with the engine off, then with it running: whatever moved is a
        live channel and whatever did not is probably a shared zero slot.
        """
        changed = []
        for local_id, first in before.items():
            second = after.get(local_id)
            if not (first.get("answered") and second and second.get("answered")):
                continue
            if first.get("raw") != second.get("raw"):
                changed.append(
                    {
                        "local_id": local_id,
                        "hex_id": f"0x{local_id:02X}",
                        "before": first.get("raw"),
                        "after": second.get("raw"),
                    }
                )
        return changed

    # -- memory -----------------------------------------------------------
    def check_memory_read(self) -> Decision:
        return self.gate.evaluate(
            "memory-read", Risk.READ, profile=self.profile, capability="memory_read"
        )

    def read_memory(
        self, start: int = 0, size: int | None = None, *, block: int = 0x80,
        progress=None,
    ) -> bytes:
        """Read an ECU image. Read-only, but slow (tens of minutes on a 5AM)."""
        with self._lock:
            session = self._require()
            if not self.profile.memory.get("read_supported"):
                raise SafetyViolation(
                    self.gate.evaluate(
                        "memory-read", Risk.READ, profile=self.profile,
                        capability="memory_read",
                    )
                )
            total = size or self.profile.memory.get("image_size") or 0
            if not total:
                raise ValueError(
                    f"{self.profile.family}: image size is unknown, pass an explicit size"
                )

            out = bytearray()
            address = start
            while len(out) < total:
                chunk = min(block, total - len(out))
                out += session.read_memory_by_address(address, chunk)
                address += chunk
                self._touch()
                if progress:
                    progress(len(out), total)
            self.log.action(
                "memory_read", {"start": start, "size": len(out)}
            )
            return bytes(out)

    # -- status -----------------------------------------------------------
    def status(self) -> dict:
        return {
            "connected": self.connected,
            "transport": self.transport.describe(),
            "ecu": self.profile.as_dict(include_parameters=False),
            "init": (
                {
                    "ok": self.init_result.ok,
                    "method": self.init_result.method,
                    "detail": self.init_result.detail,
                    "key_bytes": list(self.init_result.key_bytes),
                }
                if self.init_result
                else None
            ),
            "identity": self.identity.as_dict() if self.identity else None,
            "mode": self.gate.mode.value,
            "vehicle_state": self.gate.state.as_dict(),
            "active_outputs": {
                k: round(max(0.0, v - time.monotonic()), 1)
                for k, v in self.active_outputs.items()
            },
            "samples": {k: s.as_dict() for k, s in self.last_samples.items()},
        }
