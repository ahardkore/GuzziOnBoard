"""K-Line (ISO 9141 / ISO 14230) transport over an FTDI-style USB serial cable.

Hardware expectations
---------------------
The cable must contain an L9637D-class K-Line transceiver; the FTDI TXD pin
never drives K-Line directly. On the Moto Guzzi 3-pin or OBD-style diagnostic
connector, K-Line is a single bidirectional wire, so *everything the tester
sends is echoed back on RX before the ECU answers*. That echo is read and
discarded here, which is the single most common reason a hand-rolled K-Line
tool "sees no response".

Initialisation
--------------
``fast``  idle high, pull K-Line low 25 ms (serial BREAK), release at the
          50 ms mark, then send and validate StartCommunication (0x81).
``slow``  idle high, bit-bang a 5-baud address byte (0x33 for the catalogued
          IAW ECUs), then complete the 0x55/KW1/KW2/complement handshake.
``auto``  try fast first; after failure wait long enough for a slow-init ECU
          to abandon the partial address it may have seen, then try slow.

The application above this transport speaks KWP2000. A slow-init response with
ISO 9141-2 keywords is identified and reported, but deliberately not accepted
as a KWP link: ISO 9141 uses a different header and application service set.

``pyserial`` is imported lazily so the simulator and the test-suite keep
working on a machine with no drivers installed.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from ..protocol.kwp2000 import ProtocolError, decode_frame, frame_length
from .base import Connection, InitResult, Transport, TransportError, TransportUnavailable

#: Baud rates worth probing when a vehicle's rate is not known from the catalog.
CANDIDATE_BAUDS = (10400, 9600, 15625, 19200, 4800)

#: ISO 9141 / KWP2000 wake-up addresses seen on Magneti Marelli IAW ECUs.
ADDRESS_OBD = 0x33
ADDRESS_IAW = 0x10

# ISO 14230-2 initialisation timing.  See docs/HANDSHAKE_PROTOCOLS.md.
W5_IDLE_S = 0.300
FAST_LOW_S = 0.025
FAST_TOTAL_S = 0.050
FAST_RESPONSE_TIMEOUT_S = 1.000
SLOW_BIT_S = 0.200
SLOW_SYNC_TIMEOUT_S = 0.600
W4_REPLY_S = 0.030
# If fast init wakes a 5-baud-only ECU, it can spend two seconds trying to
# parse the pulse as an address, then W1 + W5.  Starting slow init after only
# 300 ms (the old behaviour) can therefore fail forever.
AUTO_FALLBACK_DELAY_S = 2.600

# ISO 9141-2's two legislated keyword pairs.  Every other keyword pair is
# reported as KWP2000 here; the Marelli pair observed by this project is EA 8F.
_ISO9141_KEYWORDS = {(0x08, 0x08), (0x94, 0x94)}


def keyword_protocol(kw1: int, kw2: int) -> str:
    """Classify the protocol selected by a 5-baud keyword exchange."""
    return "iso9141-2" if (kw1, kw2) in _ISO9141_KEYWORDS else "iso14230"


def _require_serial():
    try:
        import serial  # type: ignore
    except ImportError as exc:  # pragma: no cover - depends on the host
        raise TransportUnavailable(
            "pyserial is not installed. Install the hardware extra:\n"
            "    pip install -e '.[hardware]'"
        ) from exc
    return serial


@dataclass
class KLineConnection(Connection):
    """A framed, echo-cancelling view of one serial port."""

    port: object                     # serial.Serial
    echo: bool = True
    inter_byte_delay: float = 0.005  # P4min, ISO 14230-2
    #: Collected for the session log: bytes the cable echoed back at us.
    last_echo: bytes = b""

    def write(self, data: bytes) -> None:
        self.port.reset_input_buffer()
        if self.inter_byte_delay > 0:
            # Some IAW ECUs drop bytes sent back-to-back by a fast USB UART.
            for byte in data:
                self.port.write(bytes([byte]))
                self.port.flush()
                time.sleep(self.inter_byte_delay)
        else:
            self.port.write(data)
            self.port.flush()
        if self.echo:
            self._consume_echo(data)

    def _consume_echo(self, sent: bytes) -> None:
        deadline = time.monotonic() + 0.5 + len(sent) * self.inter_byte_delay
        seen = bytearray()
        while len(seen) < len(sent) and time.monotonic() < deadline:
            chunk = self.port.read(len(sent) - len(seen))
            if chunk:
                seen += chunk
        self.last_echo = bytes(seen)
        if seen and seen != sent:
            raise TransportError(
                f"K-Line echo mismatch: sent {sent.hex(' ')}, echoed {seen.hex(' ')}. "
                "Check the transceiver and the ground connection."
            )

    def read_frame(self, timeout: float) -> bytes:
        """Read exactly one KWP2000 frame using its own length field."""
        deadline = time.monotonic() + timeout
        buffer = bytearray()
        while time.monotonic() < deadline:
            needed = frame_length(buffer)
            if needed is not None and len(buffer) >= needed:
                return bytes(buffer[:needed])
            want = 1 if needed is None else needed - len(buffer)
            chunk = self.port.read(max(1, want))
            if chunk:
                buffer += chunk
            else:
                time.sleep(0.002)
        needed = frame_length(buffer)
        if needed is not None and len(buffer) >= needed:
            return bytes(buffer[:needed])
        return bytes(buffer) if buffer else b""

    def close(self) -> None:
        try:
            self.port.close()
        except Exception:  # pragma: no cover - best effort on teardown
            pass

    @property
    def is_open(self) -> bool:
        return bool(getattr(self.port, "is_open", False))


@dataclass
class KLineTransport(Transport):
    """Serial K-Line transport."""

    device: str = "/dev/ttyUSB0"
    baud: int = 10400
    echo: bool = True
    inter_byte_delay: float = 0.005
    read_timeout: float = 0.1
    name: str = field(default="kline", init=False)
    is_physical: bool = field(default=True, init=False)

    def open(self) -> KLineConnection:
        serial = _require_serial()
        try:
            port = serial.Serial(
                self.device,
                baudrate=self.baud,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=self.read_timeout,
                write_timeout=2.0,
            )
        except Exception as exc:
            raise TransportError(f"cannot open {self.device}: {exc}") from exc
        return KLineConnection(
            port=port, echo=self.echo, inter_byte_delay=self.inter_byte_delay
        )

    # -- wake-up ----------------------------------------------------------
    def initialize(
        self,
        connection: KLineConnection,
        *,
        method: str = "fast",
        address: int = ADDRESS_OBD,
        fast_target: int | None = None,
        tester_address: int = 0xF1,
        fast_functional: bool = True,
        **_,
    ) -> InitResult:
        """Run one of the standard K-Line handshakes.

        The aliases are accepted for API clients, while result names remain the
        stable ``fast``/``slow`` vocabulary used by the UI and session logs.
        """
        aliases = {
            "fast": "fast", "kwp-fast": "fast", "iso14230-fast": "fast",
            "slow": "slow", "5baud": "slow", "5-baud": "slow",
            "kwp-slow": "slow", "iso14230-slow": "slow",
            "auto": "auto",
        }
        selected = aliases.get(str(method).strip().lower())
        if selected is None:
            raise ValueError(
                f"unknown init method {method!r}; use auto, fast or slow"
            )
        for value, label in ((address, "5-baud address"),
                             (fast_target if fast_target is not None else address,
                              "fast-init target"),
                             (tester_address, "tester address")):
            if not 0 <= int(value) <= 0xFF:
                raise ValueError(f"{label} must be one byte")

        target = address if fast_target is None else fast_target
        if selected == "fast":
            return self._fast_init(
                connection, target=target, source=tester_address,
                functional=fast_functional,
            )
        if selected == "slow":
            return self._slow_init(connection, address)

        attempts: list[str] = []
        result = self._fast_init(
            connection, target=target, source=tester_address,
            functional=fast_functional,
        )
        attempts.append(f"fast: {result.detail}")
        if result.ok:
            result.attempts = attempts
            return result

        # A 25 ms low pulse also looks like the beginning of a 5-baud address.
        # Some slow-only ECUs do not reject it until a full 2 s address window
        # has elapsed.  ISO/VW guidance therefore requires 2.6 s before the
        # fallback, not the 300 ms W5 wait alone.
        time.sleep(AUTO_FALLBACK_DELAY_S)
        result = self._slow_init(connection, address)
        attempts.append(f"slow: {result.detail}")
        result.attempts = attempts
        return result

    @staticmethod
    def _request_start_communication(target: int, source: int, functional: bool) -> bytes:
        # Fast init's first message must have target + source and no extra
        # length byte.  C1 is functional addressing; 81 is physical.
        request = bytes([0xC1 if functional else 0x81, target, source, 0x81])
        return request + bytes([sum(request) & 0xFF])

    def _fast_init(
        self,
        connection: KLineConnection,
        *,
        target: int = ADDRESS_OBD,
        source: int = 0xF1,
        functional: bool = True,
    ) -> InitResult:
        """Idle, send the 25/25 ms wake pattern, then validate 0xC1."""
        port = connection.port
        port.break_condition = False
        port.reset_input_buffer()
        time.sleep(W5_IDLE_S)

        # Schedule the two edges against one clock.  Chaining two relative
        # sleeps lets scheduler delay accumulate and can move tWUP outside its
        # narrow 49..51 ms standard window.
        start = time.monotonic()
        port.break_condition = True
        time.sleep(max(0.0, start + FAST_LOW_S - time.monotonic()))
        port.break_condition = False
        time.sleep(max(0.0, start + FAST_TOTAL_S - time.monotonic()))

        request = self._request_start_communication(target, source, functional)
        port.write(request)
        port.flush()
        if connection.echo:
            connection._consume_echo(request)

        reply = connection.read_frame(FAST_RESPONSE_TIMEOUT_S)
        if not reply:
            return InitResult(
                ok=False, method="fast", baud=self.baud, protocol="iso14230",
                detail="no answer to StartCommunication",
                request=request,
            )

        try:
            frame = decode_frame(reply)
        except ProtocolError as exc:
            return InitResult(
                ok=False, method="fast", baud=self.baud, protocol="iso14230",
                detail=f"invalid StartCommunication response: {exc}",
                request=request, response=reply,
            )

        if frame.is_negative:
            nrc = frame.nrc if frame.nrc is not None else 0
            return InitResult(
                ok=False, method="fast", baud=self.baud, protocol="iso14230",
                detail=f"StartCommunication rejected with NRC 0x{nrc:02X}",
                request=request, response=reply,
            )
        if frame.service != 0xC1 or len(frame.payload) < 3:
            return InitResult(
                ok=False, method="fast", baud=self.baud, protocol="iso14230",
                detail=(
                    "expected StartCommunication positive response C1 + two "
                    f"key bytes, got {frame.payload.hex(' ') or 'empty payload'}"
                ),
                request=request, response=reply,
            )
        if frame.target is not None and frame.target != source:
            return InitResult(
                ok=False, method="fast", baud=self.baud, protocol="iso14230",
                detail=(
                    f"StartCommunication response targets 0x{frame.target:02X}, "
                    f"not tester 0x{source:02X}"
                ),
                request=request, response=reply,
            )

        keys = (frame.payload[1], frame.payload[2])
        protocol = keyword_protocol(*keys)
        if protocol != "iso14230":
            return InitResult(
                ok=False, method="fast", key_bytes=keys, baud=self.baud,
                protocol=protocol,
                detail=(
                    f"ECU selected {protocol} with keywords {keys[0]:02X} "
                    f"{keys[1]:02X}; this workstation speaks KWP2000"
                ),
                request=request, response=reply,
            )
        return InitResult(
            ok=True,
            method="fast",
            key_bytes=keys,
            baud=self.baud,
            protocol=protocol,
            handshake_complete=True,
            detail=f"validated StartCommunication response: {reply.hex(' ')}",
            request=request,
            response=reply,
        )

    def _slow_init(self, connection: KLineConnection, address: int) -> InitResult:
        """Bit-bang the address at 5 baud and validate every handshake byte."""
        port = connection.port
        port.break_condition = False
        port.reset_input_buffer()
        time.sleep(W5_IDLE_S)

        # Start bit (low), 8 data bits LSB first, stop bit (high).
        pattern = [0] + [(address >> i) & 1 for i in range(8)] + [1]
        start = time.monotonic()
        for index, bit in enumerate(pattern):
            port.break_condition = bit == 0
            # Absolute scheduling: sleep() drift would break the 200 ms budget.
            target = start + (index + 1) * SLOW_BIT_S
            while True:
                remaining = target - time.monotonic()
                if remaining <= 0:
                    break
                time.sleep(min(remaining, 0.005))
        port.break_condition = False

        sync = b""
        deadline = time.monotonic() + SLOW_SYNC_TIMEOUT_S
        while time.monotonic() < deadline and len(sync) < 3:
            chunk = port.read(3 - len(sync))
            if chunk:
                sync += chunk
        if len(sync) < 3 or sync[0] != 0x55:
            return InitResult(
                ok=False, method="slow", baud=self.baud,
                detail=f"no 0x55 sync (got {sync.hex(' ') or 'nothing'})",
            )

        kw1, kw2 = sync[1], sync[2]
        protocol = keyword_protocol(kw1, kw2)
        inverted_kw2 = bytes([(~kw2) & 0xFF])
        time.sleep(W4_REPLY_S)
        port.write(inverted_kw2)
        port.flush()
        if connection.echo:
            echoed = port.read(1)
            if echoed and echoed != inverted_kw2:
                return InitResult(
                    ok=False, method="slow", key_bytes=(kw1, kw2),
                    baud=self.baud, protocol=protocol,
                    detail=(
                        f"inverted-key echo mismatch: sent {inverted_kw2.hex()}, "
                        f"got {echoed.hex()}"
                    ),
                )

        confirm = port.read(1)
        expected = (~address) & 0xFF
        if not confirm or confirm[0] != expected:
            return InitResult(
                ok=False,
                method="slow",
                key_bytes=(kw1, kw2),
                baud=self.baud,
                protocol=protocol,
                detail=(
                    f"keybytes {kw1:02X} {kw2:02X}, address echo "
                    f"{confirm.hex() or 'none'} (expected {expected:02X})"
                ),
            )
        if protocol != "iso14230":
            return InitResult(
                ok=False,
                method="slow",
                key_bytes=(kw1, kw2),
                baud=self.baud,
                protocol=protocol,
                detail=(
                    f"valid {protocol} 5-baud handshake ({kw1:02X} {kw2:02X}), "
                    "but this workstation's message layer is KWP2000/ISO 14230"
                ),
            )
        return InitResult(
            ok=True,
            method="slow",
            key_bytes=(kw1, kw2),
            baud=self.baud,
            protocol=protocol,
            handshake_complete=True,
            detail=(
                f"validated 5-baud handshake: keybytes {kw1:02X} {kw2:02X}, "
                f"address complement {confirm.hex()}"
            ),
        )

    # -- discovery --------------------------------------------------------
    @staticmethod
    def list_ports() -> list[dict]:
        """Enumerate candidate serial adapters, newest FTDI first."""
        try:
            from serial.tools import list_ports  # type: ignore
        except ImportError:
            return []
        found = []
        for port in list_ports.comports():
            found.append(
                {
                    "device": port.device,
                    "description": port.description,
                    "manufacturer": port.manufacturer or "",
                    "serial_number": port.serial_number or "",
                    "vid": port.vid,
                    "pid": port.pid,
                    "likely_kline": bool(
                        port.manufacturer and "FTDI" in port.manufacturer.upper()
                    ),
                }
            )
        found.sort(key=lambda p: not p["likely_kline"])
        return found
