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
``fast``  pull K-Line low 25 ms (serial BREAK), release 25 ms, then send
          StartCommunication (0x81). Supported from roughly the IAW 15x
          generation onward and the default here.
``slow``  5-baud bit-banged address byte (0x33 for OBD, 0x10/0x11 for some
          IAW ECUs), then the ECU answers 0x55 KW1 KW2 at 10400 baud; the
          tester replies with the inverted KW2 and the ECU echoes the
          inverted address. Needed by the older P8/16M/15M generation.

``pyserial`` is imported lazily so the simulator and the test-suite keep
working on a machine with no drivers installed.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from ..protocol.kwp2000 import frame_length
from .base import Connection, InitResult, Transport, TransportError, TransportUnavailable

#: Baud rates worth probing when a vehicle's rate is not known from the catalog.
CANDIDATE_BAUDS = (10400, 9600, 15625, 19200, 4800)

#: ISO 9141 / KWP2000 wake-up addresses seen on Magneti Marelli IAW ECUs.
ADDRESS_OBD = 0x33
ADDRESS_IAW = 0x10


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
        **_,
    ) -> InitResult:
        if method == "fast":
            return self._fast_init(connection)
        if method == "slow":
            return self._slow_init(connection, address)
        if method == "auto":
            attempts: list[str] = []
            result = self._fast_init(connection)
            attempts.append(f"fast: {result.detail}")
            if result.ok:
                result.attempts = attempts
                return result
            time.sleep(0.3)
            result = self._slow_init(connection, address)
            attempts.append(f"slow: {result.detail}")
            result.attempts = attempts
            return result
        raise ValueError(f"unknown init method {method!r}")

    def _fast_init(self, connection: KLineConnection) -> InitResult:
        """25 ms low / 25 ms high, then StartCommunication."""
        port = connection.port
        port.reset_input_buffer()
        port.break_condition = True
        time.sleep(0.025)
        port.break_condition = False
        time.sleep(0.025)

        # StartCommunication, sent raw because the session is not up yet.
        request = bytes([0xC1, 0x33, 0xF1, 0x81])
        request += bytes([sum(request) & 0xFF])
        port.write(request)
        port.flush()
        if connection.echo:
            connection._consume_echo(request)

        reply = connection.read_frame(0.3)
        if reply and len(reply) >= 2:
            try:
                key_bytes = (reply[-3], reply[-2])
            except IndexError:
                key_bytes = ()
            return InitResult(
                ok=True,
                method="fast",
                key_bytes=key_bytes,
                baud=self.baud,
                detail=f"StartCommunication accepted: {reply.hex(' ')}",
            )
        return InitResult(
            ok=False, method="fast", baud=self.baud,
            detail="no answer to StartCommunication",
        )

    def _slow_init(self, connection: KLineConnection, address: int) -> InitResult:
        """Bit-bang the address byte at 5 baud using BREAK, then handshake."""
        port = connection.port
        port.reset_input_buffer()

        bit_time = 0.200  # 5 baud
        # start bit (low), 8 data bits LSB first, stop bit (high)
        pattern = [0] + [(address >> i) & 1 for i in range(8)] + [1]
        start = time.monotonic()
        for index, bit in enumerate(pattern):
            port.break_condition = bit == 0
            # Absolute scheduling: sleep() drift would break the 200 ms budget.
            target = start + (index + 1) * bit_time
            while True:
                remaining = target - time.monotonic()
                if remaining <= 0:
                    break
                time.sleep(min(remaining, 0.005))
        port.break_condition = False

        sync = b""
        deadline = time.monotonic() + 0.5
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
        time.sleep(0.030)  # W4
        port.write(bytes([(~kw2) & 0xFF]))
        port.flush()
        if connection.echo:
            port.read(1)

        confirm = port.read(1)
        expected = (~address) & 0xFF
        ok = bool(confirm) and confirm[0] == expected
        return InitResult(
            ok=ok,
            method="slow",
            key_bytes=(kw1, kw2),
            baud=self.baud,
            detail=(
                f"keybytes {kw1:02X} {kw2:02X}, address echo "
                f"{confirm.hex() or 'none'} (expected {expected:02X})"
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
