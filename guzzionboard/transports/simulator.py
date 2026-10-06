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
from typing import ClassVar

from ..catalog import EcuProfile
from ..firmware import IAW5AM_CHECKSUM_LEN, iaw5am_decode, iaw5am_decode_byte
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


#: Seedable faults. Each one changes what the channels report *and* what
#: eventually appears in fault memory, so a practice session looks like the
#: real thing: the numbers go wrong first, the code arrives later.
@dataclass(frozen=True)
class SimulatedFault:
    key: str
    name: str
    description: str
    dtc: str = ""
    teaches: str = ""

    def as_dict(self) -> dict:
        return {
            "key": self.key, "name": self.name, "description": self.description,
            "dtc": self.dtc, "teaches": self.teaches,
        }


FAULTS: tuple[SimulatedFault, ...] = (
    SimulatedFault(
        "coolant_sensor_open", "Head sensor, open circuit",
        "The head temperature sensor reads the bottom rail (-40 C). The ECU "
        "fuels for a frozen engine, so it runs rich and never closes the loop.",
        "P0117", "A railed sensor reading, and what the rest of the channels "
        "do when the ECU believes it.",
    ),
    SimulatedFault(
        "coolant_sensor_short", "Head sensor, shorted",
        "The head temperature sensor pins at 135 C. The ECU pulls fuelling "
        "back and the temperature lamp comes on.",
        "P0118", "The other rail - same sensor, opposite failure.",
    ),
    SimulatedFault(
        "tps_fault", "Throttle position sensor dead",
        "The throttle angle stays at zero no matter what the rider does.",
        "P0120", "A channel that disagrees with the engine speed next to it.",
    ),
    SimulatedFault(
        "lambda_dead_front", "Lambda sensor lazy (front)",
        "The front sensor sits at 450 mV instead of switching. The ECU has "
        "not noticed yet and is still in closed loop.",
        "P0130", "What a dead narrowband sensor looks like before the ECU "
        "gives up on it - the plausibility check sees it first.",
    ),
    SimulatedFault(
        "charging_failure", "Charging system down",
        "The alternator is not contributing. Bus voltage sits around 12.1 V "
        "and sags as the ride goes on.",
        "P0562", "Why every other reading drifts when the volts go away.",
    ),
    SimulatedFault(
        "air_leak", "Air leak after the throttle",
        "Unmetered air raises idle, the stepper closes down to compensate and "
        "both lambda integrators go positive.",
        "P0505", "The classic Guzzi idle complaint, with the three channels "
        "that prove it.",
    ),
    SimulatedFault(
        "stepper_stuck", "Idle stepper jammed",
        "The stepper no longer moves. Idle sits well off target and the "
        "position never tracks the base.",
        "P0505", "Same stored code as the air leak, different fingerprint in "
        "the live data.",
    ),
    SimulatedFault(
        "injector_blocked_front", "Front injector partially blocked",
        "The front cylinder runs lean and its integrator climbs while the "
        "rear stays put.",
        "P0201", "A bank split: one map, two cylinders, very different "
        "corrections.",
    ),
    SimulatedFault(
        "misfire_rear", "Rear cylinder misfire",
        "Combustion drops out intermittently on the rear cylinder. Speed gets "
        "rough and the rear mixture goes rich with unburnt oxygen.",
        "P0302", "Roughness you can see in the rpm trace.",
    ),
)

FAULTS_BY_KEY = {f.key: f for f in FAULTS}


@dataclass
class EngineModel:
    """A small physical model behind the simulated channels.

    It is deliberately controllable: ignition, throttle, ambient temperature
    and a set of seeded faults are all inputs, so the workstation can drive
    the engine the same way a rider would and practise on failures that are
    inconvenient to arrange on a real motorcycle.

    Temperatures are integrated rather than evaluated from a formula, so
    stopping the engine really does let it cool, and changing the ambient
    temperature moves the whole model.
    """

    ambient_c: float = 18.0
    started_at: float = field(default_factory=time.monotonic)
    running: bool = True
    #: Set non-zero to make the simulation repeatable across runs.
    seed: int | None = 7
    #: Rider inputs.
    throttle_pct: float = 0.0
    in_gear: bool = False
    #: Blip the throttle by itself when nobody is driving, so the stock demo
    #: still shows moving needles.
    auto_blip: bool = True
    #: 1.0 is a healthy battery; lower is a tired one.
    battery_health: float = 1.0
    #: Seeded fault keys, from :data:`FAULTS`.
    faults: set = field(default_factory=set)

    IDLE_RPM: ClassVar[float] = 1250.0
    REDLINE_RPM: ClassVar[float] = 8500.0

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)
        self._coolant = float(self.ambient_c)
        self._last_tick = time.monotonic()
        self._stepper_frozen: float | None = None

    @property
    def t(self) -> float:
        return time.monotonic() - self.started_at

    def noise(self, amplitude: float) -> float:
        return self._rng.uniform(-amplitude, amplitude)

    def has(self, fault: str) -> bool:
        return fault in self.faults

    # -- controls ---------------------------------------------------------
    def set_faults(self, keys) -> set:
        """Replace the seeded fault set, ignoring anything unknown."""
        self.faults = {k for k in keys if k in FAULTS_BY_KEY}
        if not self.has("stepper_stuck"):
            self._stepper_frozen = None
        return set(self.faults)

    def advance(self, seconds: float) -> None:
        """Fast-forward the model.

        Wall-clock time drives the simulation, so tests and demos need a way
        to say "pretend ten minutes went by" without waiting for them.
        """
        self._tick()
        self.started_at -= seconds
        step = 5.0
        remaining = float(seconds)
        while remaining > 0:
            dt = min(step, remaining)
            remaining -= dt
            if self.running:
                self._coolant += (92.0 - self._coolant) * (dt / 180.0)
            else:
                self._coolant += (self.ambient_c - self._coolant) * (dt / 900.0)

    def start(self) -> None:
        self.running = True

    def stop(self) -> None:
        self.running = False
        self.throttle_pct = 0.0

    # -- thermal integration ----------------------------------------------
    def _tick(self) -> None:
        now = time.monotonic()
        dt = max(0.0, min(30.0, now - self._last_tick))
        self._last_tick = now
        if dt == 0.0:
            return
        # Warm-up towards 92 C with a 180 s time constant; cooling back to
        # ambient is much slower.
        if self.running:
            self._coolant += (92.0 - self._coolant) * (dt / 180.0)
        else:
            self._coolant += (self.ambient_c - self._coolant) * (dt / 900.0)

    # -- channels ---------------------------------------------------------
    @property
    def true_coolant_c(self) -> float:
        """What the metal is actually doing, before any sensor fault."""
        self._tick()
        return self._coolant

    @property
    def coolant_c(self) -> float:
        """What the sensor reports - which is not always the truth."""
        truth = self.true_coolant_c
        if self.has("coolant_sensor_open"):
            return -40.0
        if self.has("coolant_sensor_short"):
            return 135.0
        return truth

    @property
    def air_c(self) -> float:
        return self.ambient_c + self.noise(0.4)

    @property
    def idle_target_rpm(self) -> float:
        """Fast idle when cold, settling as the head warms."""
        cold = max(0.0, min(1.0, (70.0 - self.true_coolant_c) / 55.0))
        return self.IDLE_RPM + 320.0 * cold

    @property
    def rpm(self) -> float:
        if not self.running:
            return 0.0
        target = self.idle_target_rpm

        # Idle disturbances from seeded faults.
        if self.has("air_leak"):
            target += 380
        if self.has("stepper_stuck"):
            target -= 260
        if self.has("coolant_sensor_open"):
            target += 180      # the ECU thinks it is -40 C and fast-idles

        if self.throttle_pct > 0:
            target += self.throttle_pct / 100.0 * (self.REDLINE_RPM - target) * 1.02
        elif self.auto_blip:
            target += 1400 * max(0.0, math.sin(self.t / 23.0) ** 8)

        hunt = 28 * math.sin(self.t * 1.7) + self.noise(12)
        if self.has("misfire_rear"):
            hunt += self.noise(160)
        return max(0.0, min(self.REDLINE_RPM, target + hunt))

    @property
    def throttle_deg(self) -> float:
        if self.has("tps_fault"):
            return 0.0
        if not self.running:
            return 1.6
        base = 4.7 + self.throttle_pct * 0.85
        if self.throttle_pct == 0 and self.auto_blip:
            base += 42 * max(0.0, math.sin(self.t / 23.0) ** 8)
        return base + self.noise(0.05)

    @property
    def battery_v(self) -> float:
        rest = 12.4 * self.battery_health + 0.2
        if self.has("charging_failure"):
            # Running off the battery: it falls away as the minutes pass.
            return max(10.8, 12.3 * self.battery_health
                       - 0.004 * self.t + self.noise(0.04))
        if not self.running:
            return rest + self.noise(0.05)
        return 14.1 - 0.0004 * self.rpm + self.noise(0.04)

    @property
    def injection_ms(self) -> float:
        if not self.running:
            return 0.0
        enrich = 1.0 + 0.9 * max(0.0, min(1.0, (70.0 - self.coolant_c) / 70.0))
        if self.has("coolant_sensor_open"):
            enrich = 2.0        # fuelling for a frozen engine
        if self.has("coolant_sensor_short"):
            enrich = 0.8
        load = 1.0 + self.throttle_pct / 55.0
        return (1.35 + 0.0008 * (self.rpm - 1200)) * enrich * load + self.noise(0.02)

    @property
    def advance_deg(self) -> float:
        if not self.running:
            return 8.0
        return 20.0 + 0.0035 * (self.rpm - 1200) + self.noise(0.1)

    @property
    def closed_loop(self) -> bool:
        if self.has("coolant_sensor_open"):
            return False        # the ECU never thinks it is warm
        return self.running and self.coolant_c > 45

    def lambda_mv(self, bank: int = 0) -> float:
        if bank == 0 and self.has("lambda_dead_front"):
            return 450 + self.noise(6)
        if not self.closed_loop:
            return 450 + self.noise(5)
        if bank == 1 and self.has("misfire_rear"):
            return 180 + self.noise(20)     # unburnt oxygen reads lean
        return 450 + 380 * math.sin(self.t * (2.1 + 0.3 * bank) + bank)

    def lambda_integrator(self, bank: int = 0) -> float:
        if not self.closed_loop:
            return 0.0
        base = 3.0 * math.sin(self.t / 9.0 + bank) + self.noise(0.3)
        if self.has("air_leak"):
            base += 9.0
        if bank == 0 and self.has("injector_blocked_front"):
            base += 18.0
        if bank == 1 and self.has("misfire_rear"):
            base += 12.0
        return base

    @property
    def road_speed(self) -> float:
        if not self.in_gear or not self.running:
            return 0.0
        return max(0.0, (self.rpm - 1100) / 7400 * 180.0)

    @property
    def stepper_base(self) -> int:
        """Where the ECU's map says the stepper should sit."""
        cold = max(0.0, min(1.0, (70.0 - self.true_coolant_c) / 55.0))
        return int(100 + 17 * cold)

    @property
    def stepper_position(self) -> int:
        """Where it actually is after the idle controller has had its say."""
        if self.has("stepper_stuck"):
            if self._stepper_frozen is None:
                self._stepper_frozen = self.stepper_base + 25
            return int(self._stepper_frozen)
        position = self.stepper_base + 2
        if self.has("air_leak"):
            position -= 24      # closing down to claw back the extra air
        return int(max(0, position))

    @property
    def stepper(self) -> int:
        """Backwards-compatible alias for :attr:`stepper_base`."""
        return self.stepper_base

    # -- reporting ---------------------------------------------------------
    def as_dict(self) -> dict:
        return {
            "running": self.running,
            "throttle_pct": round(self.throttle_pct, 1),
            "ambient_c": round(self.ambient_c, 1),
            "in_gear": self.in_gear,
            "auto_blip": self.auto_blip,
            "battery_health": round(self.battery_health, 2),
            "coolant_c": round(self.true_coolant_c, 1),
            "rpm": round(self.rpm),
            "battery_v": round(self.battery_v, 2),
            "road_speed": round(self.road_speed),
            "closed_loop": self.closed_loop,
            "faults": sorted(self.faults),
            "seconds_since_start": round(self.t, 1),
        }


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
        self.programming_mode = False
        self.baud_switched = False
        self.active_outputs: dict[int, float] = {}
        self.routine_log: list[tuple[float, int, int]] = []
        self.cleared_at: float | None = None
        #: Fault maturation. A seeded fault does not appear in memory the
        #: instant it starts: it matures to "pending" and only later to
        #: "confirmed", exactly like the thing being simulated. Clearing the
        #: memory while the cause is still there restarts the clock, so the
        #: code comes back - which is the lesson.
        self.dtc_pending_after = 2.0
        self.dtc_confirm_after = 8.0
        self._fault_since: dict[str, float] = {}
        self.security_unlocked = False
        self._pending_remaining = 0
        self._last_seed = b""
        #: Simulator-only key routine. None means "accept any key", which is
        #: how the programming path is exercised without pretending to know
        #: the real proprietary algorithm.
        self.key_algorithm = None
        #: Sparse overlay of bytes written by a programming session.
        self.written: dict[int, int] = {}
        self.erased = False
        self.programmed = False
        #: The 5AM-style write path: 0x3B records, routine arms and the raw
        #: (encoded) upload blob, tracked so the documented sequence is
        #: actually enforced rather than merely tolerated.
        self.records_written: list[bytes] = []
        self.erase_armed = False
        self.program_armed = False
        self.download_pending = False
        self.upload_blob = bytearray()
        self.last_program_checksum: int | None = None
        self.last_program_checksum_ok: bool | None = None
        #: Set a byte offset here to corrupt one byte of every write, which
        #: is how the read-back verification failure path is tested.
        self.corrupt_write_at: int | None = None

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
            "air_temp": lambda: int(e.air_c + 40),
            "coolant_temp": lambda: int(e.coolant_c + 40),
            "throttle": lambda: int(e.throttle_deg * 10),
            "advance": lambda: int(e.advance_deg * 10),
            "advance_latched": lambda: int(e.advance_deg * 10),
            "injection_ms": lambda: int(e.injection_ms * 1000),
            "idle_target": lambda: int(e.idle_target_rpm),
            "battery": lambda: int(e.battery_v * 10),
            "lambda_f": lambda: int(max(0, e.lambda_mv(0))),
            "lambda_r": lambda: int(max(0, e.lambda_mv(1))),
            "lambda_int_f": lambda: int(e.lambda_integrator(0) * 10),
            "lambda_int_r": lambda: int(e.lambda_integrator(1) * 10),
            "lambda_loop": lambda: 2 if e.closed_loop else 0,
            "lambda_phase_f": lambda: (5 if e.closed_loop else 2),
            "road_speed": lambda: int(e.road_speed),
            "stepper_base": lambda: e.stepper_base,
            "stepper_position": lambda: e.stepper_position,
            "stepper_trim": lambda: e.stepper_position - e.stepper_base,
            "engine_state": lambda: (0x04 | 0x02 | 0x01) if e.running else 0x00,
            "stop_state": lambda: 4 if e.running else 8,
            "throttle_closed": lambda: 1 if e.throttle_deg < 5 else 4,
            "engine_run_flag": lambda: 4 if e.running else 0,
            "neutral": lambda: 0 if e.in_gear else 1,
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
            return self._start_session(payload)
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
            # Restart maturation: a cause that is still present will set its
            # code again, after the same delay it took the first time.
            self._fault_since = {
                key: time.monotonic()
                for key in getattr(self.engine, "faults", set())
            }
            return bytes([0x54])
        if service == Service.IO_CONTROL_BY_LOCAL_ID:
            return self._io_control(payload)
        if service == Service.WRITE_DATA_BY_LOCAL_ID:
            return self._write_data_by_id(payload)
        if service == Service.START_ROUTINE_BY_LOCAL_ID:
            return self._start_routine(payload)
        if service == Service.REQUEST_ROUTINE_RESULTS:
            return self._routine_results(payload)
        if service == Service.SECURITY_ACCESS:
            return self._security(payload)
        if service == Service.READ_MEMORY_BY_ADDRESS:
            return self._read_memory(payload)
        if service == Service.TRANSFER_DATA:
            return self._transfer_data(payload)
        if service == Service.REQUEST_DOWNLOAD:
            return self._request_download(payload)
        if service == Service.REQUEST_TRANSFER_EXIT:
            self.download_pending = False
            self.programmed = True
            return bytes([0x77])

        return self._nrc(service, NRC.SERVICE_NOT_SUPPORTED)

    def _start_session(self, payload: bytes) -> bytes:
        """Session rules as observed on a real IAW 5AM.

        ``10 85`` (programming) is accepted immediately after
        StartCommunication, which is what the 5am_util flashing transcript
        does. Once the ordinary ``10 81`` diagnostic session is running, the
        same request is refused with conditionsNotCorrect - which is what the
        live-data tooling sees. Both behaviours are real; the difference is
        the state the ECU is already in.
        """
        service = payload[0]
        wanted = payload[1] if len(payload) > 1 else 0x81
        diagnostic = self.profile.session.get("diagnostic_session", 0x81)
        programming = (self.profile.memory or {}).get("programming", {})
        prog_session = programming.get("session")
        baud = programming.get("baud_switch", {}).get("session")

        if prog_session is not None and wanted == prog_session:
            if self.session_started:
                return self._nrc(service, NRC.CONDITIONS_NOT_CORRECT)
            self.programming_mode = True
            # Only the in-flight transfer state is dropped here. The
            # uploaded image, routine arms and records deliberately persist:
            # real flash keeps what was written, and the read-back
            # verification re-enters this session before reading.
            self.download_pending = False
            return bytes([0x50, wanted])

        if baud is not None and wanted == baud:
            if not self.programming_mode:
                return self._nrc(service, NRC.CONDITIONS_NOT_CORRECT)
            self.baud_switched = True
            return bytes([0x50, wanted])

        if diagnostic is None:
            return self._nrc(service, NRC.SERVICE_NOT_SUPPORTED)
        if wanted != diagnostic:
            return self._nrc(service, NRC.CONDITIONS_NOT_CORRECT)
        self.session_started = True
        return bytes([0x50, wanted])

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

    #: Status bytes used for matured faults.
    PENDING_STATUS = 0x24
    CONFIRMED_STATUS = 0x2A

    def _mature_faults(self) -> None:
        """Let seeded faults age into fault memory."""
        now = time.monotonic()
        active = set(getattr(self.engine, "faults", set()))
        for key in active:
            self._fault_since.setdefault(key, now)
        for key in list(self._fault_since):
            if key not in active:
                # The cause went away; whatever was stored stays stored until
                # somebody clears it, which is how fault memory works.
                self._fault_since.pop(key)

        stored = {code: i for i, (code, _) in enumerate(self.dtcs)}
        for key, since in self._fault_since.items():
            fault = FAULTS_BY_KEY.get(key)
            if fault is None or not fault.dtc:
                continue
            age = now - since
            if age < self.dtc_pending_after:
                continue
            status = (self.CONFIRMED_STATUS if age >= self.dtc_confirm_after
                      else self.PENDING_STATUS)
            if fault.dtc in stored:
                index = stored[fault.dtc]
                if self.dtcs[index][1] < status:
                    self.dtcs[index] = (fault.dtc, status)
            else:
                stored[fault.dtc] = len(self.dtcs)
                self.dtcs.append((fault.dtc, status))

    def _read_dtcs(self) -> bytes:
        self._mature_faults()
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

    def _write_spec(self) -> dict:
        return (self.profile.memory or {}).get("programming", {}).get(
            "write", {}
        )

    def _programming_spec(self) -> dict:
        return (self.profile.memory or {}).get("programming", {})

    def _write_data_by_id(self, payload: bytes) -> bytes:
        """Service 0x3B: the writer and reflash-date records.

        5am_util: without these records RequestDownload fails, so the
        simulator enforces them the same way.
        """
        records = self._write_spec().get("records", [])
        if not records:
            return self._nrc(payload[0], NRC.SERVICE_NOT_SUPPORTED)
        if len(payload) < 3:
            return self._nrc(payload[0], NRC.REQUEST_OUT_OF_RANGE)
        did = bytes(payload[1:3])
        for record in records:
            if bytes(record["did"]) == did:
                self.records_written.append(did)
                return bytes([0x7B]) + payload[1:]
        return self._nrc(payload[0], NRC.REQUEST_OUT_OF_RANGE)

    def _programming_routine(self, local_id: int) -> str | None:
        """Which write phase, if any, a routine local id belongs to."""
        erase = self._write_spec().get("erase")
        program = self._write_spec().get("program")
        if isinstance(erase, dict) and local_id == erase.get("start", [0, 0])[1]:
            return "erase"
        if (isinstance(program, dict)
                and local_id == program.get("start", [0, 0])[1]):
            return "program"
        return None

    def _start_routine(self, payload: bytes) -> bytes:
        if len(payload) < 2:
            return self._nrc(payload[0], NRC.REQUEST_OUT_OF_RANGE)
        local_id = payload[1]

        # The write path: 0x31 arms the erase/program routines the catalog
        # documents. The program arm also validates the uploaded checksum
        # the way the real ECU is believed to.
        phase = self._programming_routine(local_id)
        if phase is not None:
            if self._programming_spec().get("security", {}).get("required") \
                    and not self.security_unlocked:
                return self._nrc(payload[0], NRC.SECURITY_ACCESS_DENIED)
            if phase == "erase":
                if not self.records_written:
                    return self._nrc(payload[0], NRC.CONDITIONS_NOT_CORRECT)
                self.erase_armed = True
                self.routine_log.append((time.time(), local_id, payload[0]))
                return bytes([0x71, local_id])
            if not self.erased:
                # Programming arms only after an erase actually ran.
                return self._nrc(payload[0], NRC.CONDITIONS_NOT_CORRECT)
            sent = int.from_bytes(bytes(payload[-2:]), "big")
            self.last_program_checksum = sent
            self.last_program_checksum_ok = (sent == self._flash_checksum())
            self.program_armed = True
            self.routine_log.append((time.time(), local_id, payload[0]))
            return bytes([0x71, local_id])

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

    def _routine_results(self, payload: bytes) -> bytes:
        """Service 0x33: on the 5AM this is what *runs* the armed phase."""
        if len(payload) < 2:
            return self._nrc(payload[0], NRC.REQUEST_OUT_OF_RANGE)
        local_id = payload[1]
        erase = self._write_spec().get("erase")
        program = self._write_spec().get("program")

        if isinstance(erase, dict) and local_id == erase.get("trigger", [0, 0])[1]:
            if not self.erase_armed:
                return self._nrc(payload[0], NRC.CONDITIONS_NOT_CORRECT)
            self.erase_armed = False
            self.erased = True
            self.routine_log.append((time.time(), local_id, payload[0]))
            return bytes([0x73, local_id])
        if (isinstance(program, dict)
                and local_id == program.get("trigger", [0, 0])[1]):
            if not self.program_armed or not self.erased:
                return self._nrc(payload[0], NRC.CONDITIONS_NOT_CORRECT)
            self.program_armed = False
            self.programmed = True
            self.routine_log.append((time.time(), local_id, payload[0]))
            return bytes([0x73, local_id])

        # Most IAW families do not implement 0x33 at all, which the
        # diagnostics layer treats as best-effort.
        return self._nrc(payload[0], NRC.SERVICE_NOT_SUPPORTED)

    def _security(self, payload: bytes) -> bytes:
        level = payload[1] if len(payload) > 1 else 0x01
        if level % 2 == 1:
            # Seeds on the IAW 5AM are a 16-bit value X followed by X+1.
            x = 0x2788
            self._last_seed = x.to_bytes(2, "big") + (x + 1).to_bytes(2, "big")
            return bytes([0x67, level]) + self._last_seed
        if self.key_algorithm is not None:
            expected = self.key_algorithm(self._last_seed)
            if bytes(payload[2:]) != bytes(expected):
                return self._nrc(payload[0], NRC.INVALID_KEY)
        self.security_unlocked = True
        return bytes([0x67, level])

    # -- programming ------------------------------------------------------
    def _request_download(self, payload: bytes) -> bytes:
        spec = self._programming_spec()
        if spec.get("security", {}).get("required") and not self.security_unlocked:
            return self._nrc(payload[0], NRC.SECURITY_ACCESS_DENIED)
        # 5am_util: the download is refused unless the writer and date
        # records were written first.
        expected = [bytes(r["did"]) for r in self._write_spec().get("records", [])]
        if expected and any(did not in self.records_written for did in expected):
            return self._nrc(payload[0], NRC.CONDITIONS_NOT_CORRECT)
        # A new download is a fresh transfer of the upload blob.
        self.erased = True
        self.written.clear()
        self.upload_blob.clear()
        self.download_pending = True
        return bytes([0x74, 0x00, 0x80])

    def _flash_checksum(self) -> int:
        """The sum16 the program routine is sent, over the decoded flash."""
        if len(self.upload_blob) <= 8:
            return 0
        decoded = iaw5am_decode(bytes(self.upload_blob))[8:]
        return sum(decoded[:IAW5AM_CHECKSUM_LEN]) & 0xFFFF

    def _flash_byte(self, address: int) -> int:
        """Deterministic pseudo-image with a plausible IAW vector table.

        Anything written during a programming session shadows it, so a write
        followed by a read-back behaves the way real flash does.
        """
        if address in self.written:
            return self.written[address]
        region = (self.profile.memory or {}).get("regions", {}).get("flash", {})
        start = int(region.get("start", 0))
        offset = address - start
        # An uploaded (encoded) blob shadows the image too; the ECU decodes
        # it into flash, so that is what a read must return.
        if 0 <= offset < len(self.upload_blob) - 8:
            return iaw5am_decode_byte(self.upload_blob[8 + offset], 8 + offset)
        if 0 <= offset < 64:                 # FA 00 xx 40 vector entries
            return (0xFA, 0x00, (offset // 4) * 4, 0x40)[offset % 4]
        return (address * 31 + 7) & 0xFF

    def _transfer_data(self, payload: bytes) -> bytes:
        spec = self._programming_spec()
        if spec.get("protocol") != "iaw_transfer":
            return self._nrc(payload[0], NRC.SERVICE_NOT_SUPPORTED)
        if spec.get("security", {}).get("required") and not self.security_unlocked:
            return self._nrc(payload[0], NRC.SECURITY_ACCESS_DENIED)
        if len(payload) < 2:
            return self._nrc(payload[0], NRC.REQUEST_OUT_OF_RANGE)

        subfn = payload[1]
        write_spec = self._write_spec()
        read_spec = spec.get("read", {})
        setup_subfn = (read_spec.get("setup") or [None])[0]

        # Raw upload mode: once RequestDownload has been accepted, every 0x36
        # frame streams the encoded blob with no sub-function at all - this
        # is the 5am_util write path. The state is what disambiguates it
        # from reads: an upload chunk whose first byte happens to be 0x11 or
        # 0x21 is still an upload, and no read can occur between
        # RequestDownload and RequestTransferExit.
        if self.download_pending and write_spec.get("chunk") is not None:
            if not self.erased:
                return self._nrc(payload[0], NRC.CONDITIONS_NOT_CORRECT)
            region = (self.profile.memory or {}).get("regions", {}).get(
                "flash", {}
            )
            start = int(region.get("start", 0))
            data = payload[1:]
            base = len(self.upload_blob)
            for k, byte in enumerate(data):
                blob_pos = base + k
                if blob_pos >= 8:            # past the magic: real flash bytes
                    if self.corrupt_write_at == start + blob_pos - 8:
                        byte ^= 0xFF
                self.upload_blob.append(byte)
            return bytes([0x76, len(data)])

        if subfn == setup_subfn:
            return bytes([0x76, subfn, 0x02])
        write_subfn = write_spec.get("block_subfn")
        if write_subfn is not None and subfn == write_subfn:
            if not self.erased:
                return self._nrc(payload[0], NRC.CONDITIONS_NOT_CORRECT)
            if len(payload) < 6:
                return self._nrc(payload[0], NRC.REQUEST_OUT_OF_RANGE)
            address = (payload[2] << 16) | (payload[3] << 8) | payload[4]
            length = payload[5]
            data = payload[6 : 6 + length]
            for offset, byte in enumerate(data):
                if self.corrupt_write_at == address + offset:
                    byte ^= 0xFF
                self.written[address + offset] = byte
            return bytes([0x76, subfn, length])

        if subfn == spec.get("read", {}).get("block_subfn", 0x21):
            if len(payload) < 6:
                return self._nrc(payload[0], NRC.REQUEST_OUT_OF_RANGE)
            address = (payload[2] << 16) | (payload[3] << 8) | payload[4]
            length = payload[5] or 0x20
            data = bytes(self._flash_byte(address + i) for i in range(length))
            return (bytes([0x76, subfn, (address >> 8) & 0xFF, address & 0xFF])
                    + length.to_bytes(2, "big") + data)
        return self._nrc(payload[0], NRC.SUB_FUNCTION_NOT_SUPPORTED)

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
        requested = kwargs.get("method", self.profile.kline.get("init", "fast"))
        # The simulated ECU supports both handshakes.  Resolve auto to fast so
        # the normal StartCommunication frame still traverses the real stack.
        method = "fast" if requested == "auto" else requested
        return InitResult(
            ok=True,
            method=f"simulated-{method}",
            key_bytes=(0xEA, 0x8F),
            baud=self.profile.kline.get("baud", 0),
            detail=f"simulated {self.profile.family}",
            protocol="iso14230",
            # Slow init establishes communication itself.  Fast init leaves
            # 0x81 to DiagnosticsService so simulator tests exercise it.
            handshake_complete=method == "slow",
        )
