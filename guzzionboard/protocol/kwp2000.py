"""KWP2000 / ISO 14230 application and data-link layer.

This module is transport agnostic: it encodes and decodes frames and knows the
service semantics, but it never touches a serial port or a CAN socket. The same
code therefore runs against :class:`~guzzionboard.transports.simulator.SimulatorTransport`
and against real hardware, which is the only way the protocol stack gets
exercised without a motorcycle on the bench.

References used while writing this (see docs/PROTOCOL_NOTES.md for provenance):

* ISO 14230-2 (data link) and ISO 14230-3 (application layer).
* A verified capture of a Magneti Marelli IAW 5AM (HW610) on a Moto Guzzi.

Frame format (addressed)::

    [FMT] [TGT] [SRC] [DATA ...] [CS]
    FMT = 0x80 | len     len = number of DATA bytes, 1..63
    TGT = 0x10 (ECU)     SRC = 0xF1 (tester)
    CS  = sum(preceding bytes) & 0xFF

When ``len`` does not fit in the six low bits of FMT an extra length byte is
inserted after SRC and the low bits of FMT are zero.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Callable, Iterable, Sequence

TESTER_ADDRESS = 0xF1
ECU_ADDRESS = 0x10


class Service(IntEnum):
    """KWP2000 service identifiers used by Magneti Marelli IAW ECUs."""

    START_DIAGNOSTIC_SESSION = 0x10
    ECU_RESET = 0x11
    CLEAR_DIAGNOSTIC_INFORMATION = 0x14
    READ_DTC_BY_STATUS = 0x18
    READ_ECU_IDENTIFICATION = 0x1A
    STOP_DIAGNOSTIC_SESSION = 0x20
    READ_DATA_BY_LOCAL_ID = 0x21
    READ_MEMORY_BY_ADDRESS = 0x23
    SECURITY_ACCESS = 0x27
    IO_CONTROL_BY_LOCAL_ID = 0x30
    START_ROUTINE_BY_LOCAL_ID = 0x31
    STOP_ROUTINE_BY_LOCAL_ID = 0x32
    REQUEST_ROUTINE_RESULTS = 0x33
    REQUEST_DOWNLOAD = 0x34
    REQUEST_UPLOAD = 0x35
    TRANSFER_DATA = 0x36
    REQUEST_TRANSFER_EXIT = 0x37
    WRITE_DATA_BY_LOCAL_ID = 0x3B
    WRITE_MEMORY_BY_ADDRESS = 0x3D
    TESTER_PRESENT = 0x3E
    ACCESS_TIMING_PARAMETER = 0x83
    START_COMMUNICATION = 0x81
    STOP_COMMUNICATION = 0x82


#: Services that can change persistent vehicle state. Every one of these has to
#: pass the safety gate before :class:`KWP2000Session` will transmit it.
MUTATING_SERVICES = frozenset(
    {
        Service.ECU_RESET,
        Service.CLEAR_DIAGNOSTIC_INFORMATION,
        Service.IO_CONTROL_BY_LOCAL_ID,
        Service.START_ROUTINE_BY_LOCAL_ID,
        Service.WRITE_DATA_BY_LOCAL_ID,
        Service.REQUEST_DOWNLOAD,
        Service.TRANSFER_DATA,
        Service.REQUEST_TRANSFER_EXIT,
        Service.WRITE_MEMORY_BY_ADDRESS,
    }
)

NEGATIVE_RESPONSE = 0x7F
RESPONSE_PENDING = 0x78


class NRC(IntEnum):
    """Negative response codes (ISO 14230-3 table 32)."""

    GENERAL_REJECT = 0x10
    SERVICE_NOT_SUPPORTED = 0x11
    SUB_FUNCTION_NOT_SUPPORTED = 0x12
    BUSY_REPEAT_REQUEST = 0x21
    CONDITIONS_NOT_CORRECT = 0x22
    REQUEST_OUT_OF_RANGE = 0x31
    SECURITY_ACCESS_DENIED = 0x33
    INVALID_KEY = 0x35
    EXCEEDED_ATTEMPTS = 0x36
    TIME_DELAY_NOT_EXPIRED = 0x37
    DOWNLOAD_NOT_ACCEPTED = 0x40
    UPLOAD_NOT_ACCEPTED = 0x50
    TRANSFER_SUSPENDED = 0x71
    RESPONSE_PENDING = 0x78
    SERVICE_NOT_SUPPORTED_IN_SESSION = 0x7F


NRC_TEXT = {
    0x10: "General reject",
    0x11: "Service not supported by this ECU",
    0x12: "Sub-function not supported",
    0x21: "ECU busy - repeat request",
    0x22: "Conditions not correct (check ignition, engine state)",
    0x31: "Request out of range",
    0x33: "Security access denied",
    0x35: "Invalid security key",
    0x36: "Exceeded number of security attempts",
    0x37: "Security time delay not expired",
    0x40: "Download not accepted",
    0x50: "Upload not accepted",
    0x71: "Transfer suspended",
    0x78: "Response pending",
    0x7F: "Service not supported in active session",
}


class ProtocolError(Exception):
    """Raised when a frame is malformed or the exchange breaks down."""


class ChecksumError(ProtocolError):
    """Raised when a received frame fails its checksum."""


class NegativeResponse(ProtocolError):
    """Raised when the ECU answers ``7F <sid> <nrc>``."""

    def __init__(self, service: int, code: int):
        self.service = service
        self.code = code
        text = NRC_TEXT.get(code, f"unknown NRC 0x{code:02X}")
        super().__init__(f"service 0x{service:02X} rejected: {text} (0x{code:02X})")


def checksum(data: Iterable[int]) -> int:
    """KWP2000 checksum: the low byte of the arithmetic sum."""
    return sum(data) & 0xFF


def encode_request(
    payload: Sequence[int],
    *,
    target: int = ECU_ADDRESS,
    source: int = TESTER_ADDRESS,
    addressed: bool = True,
) -> bytes:
    """Build a KWP2000 frame around ``payload`` (service id + parameters)."""
    if not payload:
        raise ProtocolError("payload must contain at least a service identifier")
    if len(payload) > 255:
        raise ProtocolError("payload exceeds the 255 byte KWP2000 limit")

    body = bytearray()
    if addressed:
        if len(payload) <= 63:
            body.append(0x80 | len(payload))
            body += bytes((target, source))
        else:
            body.append(0x80)
            body += bytes((target, source, len(payload)))
    else:
        if len(payload) <= 63:
            body.append(len(payload))
        else:
            body += bytes((0x00, len(payload)))
    body += bytes(payload)
    body.append(checksum(body))
    return bytes(body)


@dataclass(frozen=True)
class Frame:
    """A decoded KWP2000 frame."""

    format_byte: int
    target: int | None
    source: int | None
    payload: bytes
    raw: bytes

    @property
    def service(self) -> int:
        return self.payload[0] if self.payload else -1

    @property
    def is_negative(self) -> bool:
        return len(self.payload) >= 3 and self.payload[0] == NEGATIVE_RESPONSE

    @property
    def nrc(self) -> int | None:
        return self.payload[2] if self.is_negative else None

    @property
    def data(self) -> bytes:
        """Payload without the service identifier byte."""
        return self.payload[1:]

    def hex(self) -> str:
        return " ".join(f"{b:02X}" for b in self.raw)


def frame_length(buffer: Sequence[int]) -> int | None:
    """Total byte length of the frame at the head of ``buffer``.

    Returns ``None`` when more bytes are needed to decide. This lets a reader
    consume a stream without guessing timeouts for every frame.
    """
    if not buffer:
        return None
    fmt = buffer[0]
    addressed = bool(fmt & 0x80)
    header = 3 if addressed else 1
    length = fmt & 0x3F
    if length == 0:
        if len(buffer) < header + 1:
            return None
        length = buffer[header]
        header += 1
    return header + length + 1


def decode_frame(raw: Sequence[int], *, verify: bool = True) -> Frame:
    """Decode one complete frame. ``raw`` must be exactly one frame."""
    raw = bytes(raw)
    total = frame_length(raw)
    if total is None or len(raw) < total:
        raise ProtocolError(f"truncated frame: {raw.hex(' ')}")
    if len(raw) != total:
        raise ProtocolError(
            f"frame length mismatch: expected {total}, got {len(raw)} ({raw.hex(' ')})"
        )
    if verify and checksum(raw[:-1]) != raw[-1]:
        raise ChecksumError(
            f"checksum 0x{raw[-1]:02X}, computed 0x{checksum(raw[:-1]):02X} ({raw.hex(' ')})"
        )

    fmt = raw[0]
    addressed = bool(fmt & 0x80)
    header = 3 if addressed else 1
    length = fmt & 0x3F
    if length == 0:
        length = raw[header]
        header += 1
    payload = raw[header : header + length]
    return Frame(
        format_byte=fmt,
        target=raw[1] if addressed else None,
        source=raw[2] if addressed else None,
        payload=payload,
        raw=raw,
    )


# --------------------------------------------------------------------------
# Value decoding
# --------------------------------------------------------------------------


def decode_raw_value(
    data: bytes, *, offset: int = 0, length: int | None = None,
    endian: str = "big", signed: bool = False,
) -> int:
    """Pull an integer out of a response payload."""
    if length is None:
        length = len(data) - offset
    chunk = data[offset : offset + length]
    if len(chunk) != length or length <= 0:
        raise ProtocolError(
            f"cannot read {length} byte(s) at offset {offset} from {data.hex(' ')}"
        )
    return int.from_bytes(chunk, "big" if endian == "big" else "little", signed=signed)


def apply_scaling(
    raw: int, *, scale: float = 1.0, bias: float = 0.0, recip: float = 0.0
) -> float:
    """Convert a raw ECU integer into engineering units.

    ``recip`` handles period-style channels where ``value = recip / raw``.
    """
    if recip:
        return recip / raw if raw else 0.0
    return raw * scale + bias


# --------------------------------------------------------------------------
# DTC decoding
# --------------------------------------------------------------------------

_DTC_PREFIX = ("P", "C", "B", "U")


def decode_dtc_number(hi: int, lo: int) -> str:
    """Decode a 2-byte SAE J2012 DTC into its ``P0130`` style text."""
    prefix = _DTC_PREFIX[(hi >> 6) & 0x03]
    return f"{prefix}{(hi >> 4) & 0x03}{hi & 0x0F:X}{lo >> 4:X}{lo & 0x0F:X}"


@dataclass(frozen=True)
class DTCStatus:
    """Decoded DTC status byte (see ISO 14230-3 and the IAW capture notes)."""

    raw: int

    @property
    def stored(self) -> bool:
        """Bit 0x20 decides stored (history) versus current."""
        return bool(self.raw & 0x20)

    @property
    def current(self) -> bool:
        return not self.stored

    @property
    def warning_indicator(self) -> bool:
        return bool(self.raw & 0x40)

    @property
    def kind(self) -> int:
        """Fault kind in the low nibble (1/2/4/8 on IAW ECUs)."""
        return self.raw & 0x0F

    def describe(self) -> str:
        return "stored" if self.stored else "current"


@dataclass(frozen=True)
class DTC:
    code: str
    status: DTCStatus
    description: str = ""

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "status": self.status.describe(),
            "status_byte": self.status.raw,
            "warning_indicator": self.status.warning_indicator,
            "kind": self.status.kind,
            "description": self.description,
        }


def decode_dtc_response(payload: bytes, descriptions: dict | None = None) -> list[DTC]:
    """Decode a ``58 <count> [hi lo status] x count`` response body.

    ``payload`` is the full response payload including the 0x58 service echo.
    """
    descriptions = descriptions or {}
    if not payload or payload[0] != 0x58:
        raise ProtocolError(f"not a ReadDTCByStatus response: {payload.hex(' ')}")
    if len(payload) < 2:
        return []
    count = payload[1]
    body = payload[2:]
    found: list[DTC] = []
    for i in range(count):
        chunk = body[i * 3 : i * 3 + 3]
        if len(chunk) < 3:
            break  # truncated tail: report what was actually received
        code = decode_dtc_number(chunk[0], chunk[1])
        found.append(
            DTC(code=code, status=DTCStatus(chunk[2]), description=descriptions.get(code, ""))
        )
    return found


# --------------------------------------------------------------------------
# Session
# --------------------------------------------------------------------------


@dataclass
class TimingParameters:
    """ISO 14230-2 timing, in seconds."""

    p1_max: float = 0.020   # inter-byte time, ECU response
    p2_min: float = 0.025   # ECU wait before responding
    p2_max: float = 0.050   # tester wait for the start of a response
    p3_min: float = 0.055   # between end of response and next request
    p4_min: float = 0.005   # inter-byte time, tester request
    tester_present_interval: float = 2.0
    request_timeout: float = 1.0


@dataclass
class KWP2000Session:
    """Stateful KWP2000 conversation with one ECU.

    The session owns request/response correlation, negative-response handling,
    ``responsePending`` retries and the keep-alive clock. It delegates raw byte
    movement to a connection object exposing ``write(bytes)`` and
    ``read_frame(timeout) -> bytes``.
    """

    connection: object
    timing: TimingParameters = field(default_factory=TimingParameters)
    target: int = ECU_ADDRESS
    source: int = TESTER_ADDRESS
    addressed: bool = True
    #: Called with (direction, raw_bytes) for every frame; used for session logs.
    on_frame: Callable[[str, bytes], None] | None = None
    #: Guard consulted before any state-changing service is transmitted.
    write_guard: Callable[[int], bool] | None = None
    max_pending_retries: int = 5

    _last_activity: float = field(default=0.0, init=False)

    # -- plumbing ---------------------------------------------------------
    def _log(self, direction: str, raw: bytes) -> None:
        if self.on_frame:
            self.on_frame(direction, raw)

    def _check_guard(self, service: int) -> None:
        if service in MUTATING_SERVICES and self.write_guard is not None:
            if not self.write_guard(service):
                raise PermissionError(
                    f"service 0x{service:02X} blocked by the safety gate; "
                    "the required preconditions are not satisfied"
                )

    def request(self, payload: Sequence[int], *, timeout: float | None = None) -> Frame:
        """Send one request and return the matching positive response.

        Raises :class:`NegativeResponse` for ``7F`` answers other than
        ``responsePending``, which is retried transparently.
        """
        payload = bytes(payload)
        service = payload[0]
        self._check_guard(service)

        raw = encode_request(
            payload, target=self.target, source=self.source, addressed=self.addressed
        )
        self._log("tx", raw)
        self.connection.write(raw)

        deadline = timeout if timeout is not None else self.timing.request_timeout
        for _ in range(self.max_pending_retries + 1):
            data = self.connection.read_frame(deadline)
            if not data:
                raise ProtocolError(
                    f"no response to service 0x{service:02X} within {deadline:.3f}s"
                )
            self._log("rx", bytes(data))
            frame = decode_frame(data)
            if frame.is_negative:
                if frame.nrc == RESPONSE_PENDING:
                    continue  # ECU asked for more time
                raise NegativeResponse(frame.payload[1], frame.nrc or 0)
            if frame.service != (service | 0x40) and service not in (
                Service.START_COMMUNICATION,
                Service.STOP_COMMUNICATION,
            ):
                raise ProtocolError(
                    f"response service 0x{frame.service:02X} does not answer "
                    f"request 0x{service:02X}"
                )
            return frame
        raise ProtocolError(
            f"service 0x{service:02X} stayed in responsePending after "
            f"{self.max_pending_retries} retries"
        )

    def try_request(self, payload: Sequence[int], **kw) -> Frame | None:
        """Like :meth:`request` but returns ``None`` on a negative response.

        Used for capability probing, where a rejection is information rather
        than a failure.
        """
        try:
            return self.request(payload, **kw)
        except (NegativeResponse, ProtocolError):
            return None

    # -- services ---------------------------------------------------------
    def start_communication(self) -> Frame:
        return self.request([Service.START_COMMUNICATION])

    def stop_communication(self) -> Frame | None:
        return self.try_request([Service.STOP_COMMUNICATION])

    def access_timing_parameters(
        self, p2min=0x00, p2max=0xFF, p3min=0x00, p3max=0xFF, p4min=0x00
    ) -> Frame | None:
        """Sub-function 0x03: set the given timing values.

        The IAW 5AM accepts this and then ignores the answer; widening the
        windows makes polling tolerant of a slow USB serial stack.
        """
        return self.try_request(
            [Service.ACCESS_TIMING_PARAMETER, 0x03, p2min, p2max, p3min, p3max, p4min]
        )

    def start_diagnostic_session(self, session: int = 0x81) -> Frame | None:
        """Start a diagnostic session.

        Session 0x81 is the one the IAW 5AM accepts; 0x85 (programming) is
        rejected with ``conditionsNotCorrect`` outside the flashing flow.
        """
        return self.try_request([Service.START_DIAGNOSTIC_SESSION, session])

    def stop_diagnostic_session(self) -> Frame | None:
        return self.try_request([Service.STOP_DIAGNOSTIC_SESSION])

    def tester_present(self) -> Frame | None:
        return self.try_request([Service.TESTER_PRESENT])

    def read_ecu_identification(self, option: int = 0x80) -> bytes:
        frame = self.request([Service.READ_ECU_IDENTIFICATION, option])
        return frame.data[1:] if frame.data else b""

    def read_data_by_local_id(self, local_id: int) -> bytes:
        """``21 <rli>`` -> ``61 <rli> <value...>``; returns the value bytes."""
        frame = self.request([Service.READ_DATA_BY_LOCAL_ID, local_id])
        data = frame.data
        if not data or data[0] != local_id:
            raise ProtocolError(
                f"ReadDataByLocalId echoed 0x{data[0] if data else -1:02X}, "
                f"expected 0x{local_id:02X}"
            )
        return data[1:]

    def read_dtcs(self, descriptions: dict | None = None) -> list[DTC]:
        frame = self.request([Service.READ_DTC_BY_STATUS, 0x00, 0xFF, 0x00])
        return decode_dtc_response(frame.payload, descriptions)

    def clear_dtcs(self) -> Frame:
        return self.request([Service.CLEAR_DIAGNOSTIC_INFORMATION, 0xFF, 0x00])

    def io_control(self, local_id: int, command: int) -> Frame:
        """``30 <localid> <07 activate | 00 deactivate>``."""
        return self.request([Service.IO_CONTROL_BY_LOCAL_ID, local_id, command])

    def start_routine(self, local_id: int, *params: int) -> Frame:
        return self.request([Service.START_ROUTINE_BY_LOCAL_ID, local_id, *params])

    def stop_routine(self, local_id: int) -> Frame:
        return self.request([Service.STOP_ROUTINE_BY_LOCAL_ID, local_id])

    def routine_results(self, local_id: int) -> Frame | None:
        """Best-effort; many IAW families do not implement 0x33."""
        return self.try_request([Service.REQUEST_ROUTINE_RESULTS, local_id])

    def security_access(self, level: int, key_fn: Callable[[bytes], bytes]) -> bool:
        """Seed/key exchange. ``key_fn`` turns the seed into the key."""
        seed_frame = self.request([Service.SECURITY_ACCESS, level])
        seed = seed_frame.data[1:]
        if not any(seed):
            return True  # already unlocked: ECU returns an all-zero seed
        key = key_fn(bytes(seed))
        self.request([Service.SECURITY_ACCESS, level + 1, *key])
        return True

    def read_memory_by_address(self, address: int, size: int, *, addr_bytes: int = 3) -> bytes:
        """``23 <addr> <size>`` - the read side of the firmware path."""
        if size < 1 or size > 0xFF:
            raise ValueError("size must be 1..255 bytes per request")
        frame = self.request(
            [Service.READ_MEMORY_BY_ADDRESS, *address.to_bytes(addr_bytes, "big"), size]
        )
        return frame.data
