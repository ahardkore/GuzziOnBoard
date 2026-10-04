"""A simulated ECU that speaks the real KWP2000 wire protocol.

This is deliberately *not* a mock of the application layer. The simulator
accepts encoded KWP2000 frames, validates their checksums, and answers with
encoded frames - including negative responses, ``responsePending`` and
configurable fault injection. Everything above the transport therefore runs the
exact same code path against the simulator and against a motorcycle, which is
the only way to develop protocol work without a bike on the bench.

It is driven by the capability catalog: whichever ECU profile you hand it, it
answers that profile's local identifiers, actuators and routines, and rejects
anything the profile does not declare.
"""
from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field

from ..catalog import EcuProfile
from ..protocol.kwp2000 import (
    ECU_ADDRESS,
    NEGATIVE_RESPONSE,
    NRC,
    TESTER_ADDRESS,
    Service,
    checksum,
    decode_frame,
    encode_request,
)
from .base import Connection, InitResult, Transport


@dataclass
class EngineModel:
    """A small deterministic physical model behind the simulated channels."""

    ambient_c: float = 18.0
    started_at: float = field(default_factory=time.monotonic)
    running: bool = True
    #: Set non-zero to make the simulation repeatable across runs.
    seed: int | None = 7

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)

    @property
    def t(self) -> float:
        return time.monotonic() - self.started_at

    def noise(self, amplitude: float) -> float:
        return self._rng.uniform(-amplitude, amplitude)

    # -- channels ---------------------------------------------------------
    @property
    def coolant_c(self) -> float:
        """Exponential warm-up from ambient towards 92 C."""
        return self.ambient_c + (92.0 - self.ambient_c) * (1 - math.exp(-self.t / 180.0))

    @property
    def rpm(self) -> float:
        if not self.running:
            return 0.0
        # Idle settles as the engine warms, with a slow hunt and a blip cycle.
        target = 1250 - 120 * (1 - math.exp(-self.t / 180.0))
        blip = 1400 * max(0.0, math.sin(self.t / 23.0) ** 8)
        return target + blip + 28 * math.sin(self.t * 1.7) + self.noise(12)

    @property
    def throttle_deg(self) -> float:
        if not self.running:
            return 1.6
        blip = 42 * max(0.0, math.sin(self.t / 23.0) ** 8)
        return 4.7 + blip + self.noise(0.05)

    @property
    def battery_v(self) -> float:
        if not self.running:
            return 12.4 + self.noise(0.05)
        return 14.1 - 0.0004 * self.rpm + self.noise(0.04)

    @property
    def injection_ms(self) -> float:
        if not self.running:
            return 0.0
        enrich = 1.0 + 0.9 * math.exp(-self.t / 120.0)   # cold enrichment
        return (1.35 + 0.0008 * (self.rpm - 1200)) * enrich + self.noise(0.02)

    @property
    def advance_deg(self) -> float:
        if not self.running:
            return 8.0
        return 20.0 + 0.0035 * (self.rpm - 1200) + self.noise(0.1)

    @property
    def closed_loop(self) -> bool:
        return self.running and self.coolant_c > 45

    def lambda_mv(self, bank: int = 0) -> float:
        if not self.closed_loop:
            return 450 + self.noise(5)
        return 450 + 380 * math.sin(self.t * (2.1 + 0.3 * bank) + bank)

    def lambda_integrator(self, bank: int = 0) -> float:
        if not self.closed_loop:
            return 0.0
        return 3.0 * math.sin(self.t / 9.0 + bank) + self.noise(0.3)

    @property
    def road_speed(self) -> float:
        return 0.0

    @property
    def stepper(self) -> int:
        return int(117 - 17 * (1 - math.exp(-self.t / 180.0)))


class SimulatedEcu:
    """Answers KWP2000 payloads for one catalog ECU profile."""

    def __init__(
        self,
        profile: EcuProfile,
        *,
        identity: dict | None = None,
        dtcs: list[tuple[str, int]] | None = None,
        engine: EngineModel | None = None,
    ):
        self.profile = profile
        self.engine = engine or EngineModel()
        self.identity = identity or self._default_identity()
        self.dtcs = list(
            dtcs if dtcs is not None else [("P0130", 0x2A), ("P0505", 0x24)]
        )
        self.communication_open = False
        self.session_started = False
        self.active_outputs: dict[int, float] = {}
        self.routine_log: list[tuple[float, int, int]] = []
        self.cleared_at: float | None = None
        self.security_unlocked = False
        self._pending_remaining = 0

        # -- fault injection, for exercising the error paths --------------
        self.drop_rate = 0.0        # fraction of requests that get no answer
        self.corrupt_rate = 0.0     # fraction answered with a bad checksum
        self.pending_rate = 0.0     # fraction answered with responsePending first
        self.extra_latency = 0.0    # seconds added before each answer

    def _default_identity(self) -> dict:
        base = {
            "5am": {"Drawing": "CM071201", "Hardware": "IAW5AMHW610",
                    "Omologation": "5AM2EC", "Software": "1206LA02",
                    "Tester": "D30073"},
            "7sm": {"Drawing": "CM281703", "Hardware": "IAW7SMHW320",
                    "Omologation": "7SM2EC", "Software": "7614LA20",
                    "Serial": "E6MNBGS4T", "Tester": "D30073"},
        }
        return base.get(
            self.profile.id,
            {
                "Drawing": "CM000000",
                "Hardware": f"{self.profile.family.replace(' ', '')}HW000",
                "Omologation": "SIMULATED",
                "Software": "0000SIM0",
                "Tester": "D00000",
            },
        )

    # -- channel values ---------------------------------------------------
    def _raw_for(self, local_id: int) -> bytes | None:
        """Return the raw bytes this ECU would report for ``local_id``."""
        param = next(
            (p for p in self.profile.parameters if p.local_id == local_id), None
        )
        if param is None:
            return None
        if param.dead:
            return b"\x00\x00"

        e = self.engine
        inverse = {
            "rpm": lambda: int(max(0, e.rpm)),
            "air_temp": lambda: int(e.ambient_c + 40 + e.noise(0.4)),
            "coolant_temp": lambda: int(e.coolant_c + 40),
            "throttle": lambda: int(e.throttle_deg * 10),
            "advance": lambda: int(e.advance_deg * 10),
            "advance_latched": lambda: int(e.advance_deg * 10),
            "injection_ms": lambda: int(e.injection_ms * 1000),
            "idle_target": lambda: int(1571 - 170 * (1 - math.exp(-e.t / 180.0))),
            "battery": lambda: int(e.battery_v * 10),
            "lambda_f": lambda: int(max(0, e.lambda_mv(0))),
            "lambda_r": lambda: int(max(0, e.lambda_mv(1))),
            "lambda_int_f": lambda: int(e.lambda_integrator(0) * 10),
            "lambda_int_r": lambda: int(e.lambda_integrator(1) * 10),
            "lambda_loop": lambda: 2 if e.closed_loop else 0,
            "lambda_phase_f": lambda: (5 if e.closed_loop else 2),
            "road_speed": lambda: int(e.road_speed),
            "stepper_base": lambda: e.stepper,
            "stepper_position": lambda: e.stepper + 2,
            "stepper_trim": lambda: 2,
            "engine_state": lambda: (0x04 | 0x02 | 0x01) if e.running else 0x00,
            "stop_state": lambda: 4 if e.running else 8,
            "throttle_closed": lambda: 1 if e.throttle_deg < 5 else 4,
            "engine_run_flag": lambda: 4 if e.running else 0,
            "neutral": lambda: 1,
            "sidestand": lambda: 1,
            "clutch": lambda: 0,
            "kill_run": lambda: 1 if e.running else 0,
            "kill_stop": lambda: 0 if e.running else 1,
            "starter": lambda: 1 if e.running else 0,
            "dwell_f": lambda: 120,
            "dwell_r": lambda: 120,
        }
        producer = inverse.get(param.key)
        value = producer() if producer else 0

        length = param.length or (2 if abs(value) > 0xFF or param.signed else 1)
        try:
            return int(value).to_bytes(length, "big", signed=param.signed)
        except OverflowError:
            return int(value).to_bytes(length + 1, "big", signed=param.signed)

    # -- request handling -------------------------------------------------
    def handle(self, payload: bytes) -> bytes | None:
        """Process one request payload and return the response payload."""
        self._expire_outputs()
        service = payload[0]

        if service == Service.START_COMMUNICATION:
            self.communication_open = True
            return bytes([0xC1, 0xEA, 0x8F])
        if service == Service.STOP_COMMUNICATION:
            self.communication_open = False
            return bytes([0xC2])
        if service == Service.ACCESS_TIMING_PARAMETER:
            if not self.profile.session.get("access_timing", True):
                return self._nrc(service, NRC.SERVICE_NOT_SUPPORTED)
            return bytes([0xC3, payload[1] if len(payload) > 1 else 0x03])
        if service == Service.START_DIAGNOSTIC_SESSION:
            wanted = payload[1] if len(payload) > 1 else 0x81
            allowed = self.profile.session.get("diagnostic_session", 0x81)
            if allowed is None:
                return self._nrc(service, NRC.SERVICE_NOT_SUPPORTED)
            if wanted != allowed:
                # Real 5AM behaviour: 0x85 is refused outside programming.
                return self._nrc(service, NRC.CONDITIONS_NOT_CORRECT)
            self.session_started = True
            return bytes([0x50, wanted])
        if service == Service.STOP_DIAGNOSTIC_SESSION:
            self.session_started = False
            return bytes([0x60])
        if service == Service.TESTER_PRESENT:
            return bytes([0x7E])

        if service == Service.READ_ECU_IDENTIFICATION:
            return self._identification(payload)
        if service == Service.READ_DATA_BY_LOCAL_ID:
            return self._read_local_id(payload)
        if service == Service.READ_DTC_BY_STATUS:
            return self._read_dtcs()
        if service == Service.CLEAR_DIAGNOSTIC_INFORMATION:
            if "dtc_clear" not in self.profile.capabilities:
                return self._nrc(service, NRC.SERVICE_NOT_SUPPORTED)
            self.dtcs.clear()
            self.cleared_at = time.time()
            return bytes([0x54])
        if service == Service.IO_CONTROL_BY_LOCAL_ID:
            return self._io_control(payload)
        if service == Service.START_ROUTINE_BY_LOCAL_ID:
            return self._start_routine(payload)
        if service == Service.REQUEST_ROUTINE_RESULTS:
            return self._nrc(service, NRC.SERVICE_NOT_SUPPORTED)
        if service == Service.SECURITY_ACCESS:
            return self._security(payload)
        if service == Service.READ_MEMORY_BY_ADDRESS:
            return self._read_memory(payload)

        return self._nrc(service, NRC.SERVICE_NOT_SUPPORTED)

    @staticmethod
    def _nrc(service: int, code: int) -> bytes:
        return bytes([NEGATIVE_RESPONSE, service, int(code)])

    def _identification(self, payload: bytes) -> bytes:
        option = payload[1] if len(payload) > 1 else 0x80
        spec = self.profile.identification
        if option != spec.get("option", 0x80):
            return self._nrc(payload[0], NRC.REQUEST_OUT_OF_RANGE)
        body = bytearray()
        for field_spec in spec.get("fields", []):
            text = str(self.identity.get(field_spec["name"], ""))
            body += text.encode("ascii", "replace").ljust(field_spec["length"], b" ")[
                : field_spec["length"]
            ]
        return bytes([0x5A, option]) + bytes(body)

    def _read_local_id(self, payload: bytes) -> bytes:
        if len(payload) < 2:
            return self._nrc(payload[0], NRC.REQUEST_OUT_OF_RANGE)
        local_id = payload[1]
        raw = self._raw_for(local_id)
        if raw is None:
            # An IAW ECU answers a contiguous block and rejects the rest;
            # the discovery scan depends on getting a real rejection here.
            if 0x30 <= local_id <= 0x7F and self.profile.transport == "kline":
                return bytes([0x61, local_id, 0x00, 0x00])
            return self._nrc(payload[0], NRC.REQUEST_OUT_OF_RANGE)
        return bytes([0x61, local_id]) + raw

    def _read_dtcs(self) -> bytes:
        from ..protocol.kwp2000 import _DTC_PREFIX

        body = bytearray([0x58, len(self.dtcs)])
        for code, status in self.dtcs:
            prefix = _DTC_PREFIX.index(code[0])
            hi = (prefix << 6) | (int(code[1]) << 4) | int(code[2], 16)
            lo = (int(code[3], 16) << 4) | int(code[4], 16)
            body += bytes([hi, lo, status])
        return bytes(body)

    def _io_control(self, payload: bytes) -> bytes:
        if len(payload) < 3:
            return self._nrc(payload[0], NRC.REQUEST_OUT_OF_RANGE)
        local_id, command = payload[1], payload[2]

        routine = next(
            (r for r in self.profile.routines
             if r.service == Service.IO_CONTROL_BY_LOCAL_ID and r.local_id == local_id),
            None,
        )
        if routine is not None:
            self.routine_log.append((time.time(), local_id, command))
            return bytes([0x70, local_id])

        actuator = next(
            (a for a in self.profile.actuators if a.local_id == local_id), None
        )
        if actuator is None:
            return self._nrc(payload[0], NRC.REQUEST_OUT_OF_RANGE)
        if actuator.requires_engine_running and not self.engine.running:
            return self._nrc(payload[0], NRC.CONDITIONS_NOT_CORRECT)
        if actuator.requires_engine_off and self.engine.running:
            return self._nrc(payload[0], NRC.CONDITIONS_NOT_CORRECT)

        if command == actuator.on_command:
            # There is no ECU-side timer: the output stays on until told off.
            self.active_outputs[local_id] = time.monotonic()
        else:
            self.active_outputs.pop(local_id, None)
        return bytes([0x70, local_id])

    def _start_routine(self, payload: bytes) -> bytes:
        if len(payload) < 2:
            return self._nrc(payload[0], NRC.REQUEST_OUT_OF_RANGE)
        local_id = payload[1]
        routine = next(
            (r for r in self.profile.routines
             if r.service == Service.START_ROUTINE_BY_LOCAL_ID and r.local_id == local_id),
            None,
        )
        if routine is None:
            return self._nrc(payload[0], NRC.REQUEST_OUT_OF_RANGE)
        if routine.requires_engine_off and self.engine.running:
            return self._nrc(payload[0], NRC.CONDITIONS_NOT_CORRECT)
        self.routine_log.append((time.time(), local_id, payload[0]))
        return bytes([0x71, local_id])

    def _security(self, payload: bytes) -> bytes:
        level = payload[1] if len(payload) > 1 else 0x01
        if level % 2 == 1:
            return bytes([0x67, level, 0x12, 0x34])
        self.security_unlocked = True
        return bytes([0x67, level])

    def _read_memory(self, payload: bytes) -> bytes:
        if not self.profile.memory.get("read_supported"):
            return self._nrc(payload[0], NRC.SERVICE_NOT_SUPPORTED)
        if len(payload) < 5:
            return self._nrc(payload[0], NRC.REQUEST_OUT_OF_RANGE)
        address = int.from_bytes(payload[1:4], "big")
        size = payload[4]
        # Deterministic pseudo-image so a read can be verified byte for byte.
        data = bytes(((address + i) * 31 + 7) & 0xFF for i in range(size))
        return bytes([0x63]) + data

    def _expire_outputs(self) -> None:
        """Mirror the real ECU: outputs stay on. Used by the UI to warn."""
        return


@dataclass
class SimulatorConnection(Connection):
    ecu: SimulatedEcu
    target: int = ECU_ADDRESS
    source: int = TESTER_ADDRESS
    addressed: bool = True
    _outbox: bytes = b""
    _closed: bool = False

    def write(self, data: bytes) -> None:
        if self._closed:
            raise RuntimeError("connection is closed")
        ecu = self.ecu

        if ecu.drop_rate and random.random() < ecu.drop_rate:
            self._outbox = b""
            return

        frame = decode_frame(data)  # validates the checksum, like real hardware
        if ecu.pending_rate and random.random() < ecu.pending_rate:
            self._outbox = self._wrap(
                bytes([NEGATIVE_RESPONSE, frame.service, int(NRC.RESPONSE_PENDING)])
            )
            ecu._pending_remaining = 1
            return

        response = ecu.handle(frame.payload)
        if response is None:
            self._outbox = b""
            return
        raw = self._wrap(response)
        if ecu.corrupt_rate and random.random() < ecu.corrupt_rate:
            raw = raw[:-1] + bytes([(raw[-1] + 1) & 0xFF])
        self._outbox = raw

    def _wrap(self, payload: bytes) -> bytes:
        return encode_request(
            payload, target=self.source, source=self.target, addressed=self.addressed
        )

    def read_frame(self, timeout: float) -> bytes:
        if self.ecu.extra_latency:
            time.sleep(min(self.ecu.extra_latency, timeout))
        if self.ecu._pending_remaining:
            # Serve the pending frame, then the real answer on the next read.
            self.ecu._pending_remaining = 0
            out, self._outbox = self._outbox, b""
            return out
        out, self._outbox = self._outbox, b""
        return out

    def close(self) -> None:
        self._closed = True

    @property
    def is_open(self) -> bool:
        return not self._closed


@dataclass
class SimulatorTransport(Transport):
    """Transport that hands out connections to a :class:`SimulatedEcu`."""

    profile: EcuProfile = None  # type: ignore[assignment]
    ecu: SimulatedEcu = None    # type: ignore[assignment]
    name: str = field(default="simulator", init=False)
    is_physical: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.ecu is None:
            if self.profile is None:
                raise ValueError("SimulatorTransport needs a profile or an ecu")
            self.ecu = SimulatedEcu(self.profile)
        if self.profile is None:
            self.profile = self.ecu.profile

    def open(self) -> SimulatorConnection:
        return SimulatorConnection(ecu=self.ecu)

    def initialize(self, connection: SimulatorConnection, **kwargs) -> InitResult:
        method = kwargs.get("method", self.profile.kline.get("init", "fast"))
        return InitResult(
            ok=True,
            method=f"simulated-{method}",
            key_bytes=(0xEA, 0x8F),
            baud=self.profile.kline.get("baud", 0),
            detail=f"simulated {self.profile.family}",
        )
