"""CAN transport for the newer Moto Guzzi ECUs (MIU G4, Marelli 11MP).

Diagnostics on these bikes run KWP2000/UDS payloads inside ISO-TP over CAN, so
the application layer above is unchanged - only the framing differs. The
``python-can`` import is lazy so the rest of the toolchain works without it.

Request/response identifiers default to the ISO 15765-4 11-bit physical pair
(0x7E0 / 0x7E8). Per-vehicle overrides live in the capability catalog, because
Piaggio-group bikes do not always sit on the standard pair.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from ..protocol.isotp import Reassembler, segment
from .base import Connection, InitResult, Transport, TransportError, TransportUnavailable


def _require_can():
    try:
        import can  # type: ignore
    except ImportError as exc:  # pragma: no cover - depends on the host
        raise TransportUnavailable(
            "python-can is not installed. Install the hardware extra:\n"
            "    pip install -e '.[hardware]'"
        ) from exc
    return can


@dataclass
class CanConnection(Connection):
    """ISO-TP framed view of a CAN bus."""

    bus: object                  # can.BusABC
    tx_id: int = 0x7E0
    rx_id: int = 0x7E8
    dlc: int = 8
    padding: int = 0xAA
    st_min: float = 0.001
    _rx: Reassembler = field(default_factory=Reassembler)

    def write(self, data: bytes) -> None:
        can = _require_can()
        frames = segment(data, dlc=self.dlc, padding=self.padding)
        for index, payload in enumerate(frames):
            msg = can.Message(
                arbitration_id=self.tx_id, data=payload, is_extended_id=self.tx_id > 0x7FF
            )
            try:
                self.bus.send(msg)
            except Exception as exc:
                raise TransportError(f"CAN send failed: {exc}") from exc
            if index == 0 and len(frames) > 1:
                self._await_flow_control()
            elif self.st_min:
                time.sleep(self.st_min)

    def _await_flow_control(self, timeout: float = 0.5) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            msg = self.bus.recv(timeout=0.05)
            if msg is None or msg.arbitration_id != self.rx_id:
                continue
            if (msg.data[0] >> 4) == 0x3:
                status = msg.data[0] & 0x0F
                if status == 0x1:      # WAIT
                    deadline = time.monotonic() + timeout
                    continue
                if status == 0x2:      # OVERFLOW
                    raise TransportError("ECU reported an ISO-TP buffer overflow")
                st_min_raw = msg.data[2]
                self.st_min = (
                    st_min_raw / 1000.0 if st_min_raw <= 0x7F else 0.0001
                )
                return
        raise TransportError("timed out waiting for an ISO-TP flow-control frame")

    def read_frame(self, timeout: float) -> bytes:
        deadline = time.monotonic() + timeout
        self._rx.reset()
        while time.monotonic() < deadline:
            msg = self.bus.recv(timeout=max(0.01, deadline - time.monotonic()))
            if msg is None or msg.arbitration_id != self.rx_id:
                continue
            payload, reply = self._rx.feed(bytes(msg.data))
            if reply is not None:
                can = _require_can()
                self.bus.send(
                    can.Message(
                        arbitration_id=self.tx_id,
                        data=reply,
                        is_extended_id=self.tx_id > 0x7FF,
                    )
                )
            if payload is not None:
                return payload
        return b""

    def close(self) -> None:
        try:
            self.bus.shutdown()
        except Exception:  # pragma: no cover
            pass


@dataclass
class CanTransport(Transport):
    """SocketCAN or any python-can supported adapter."""

    channel: str = "can0"
    interface: str = "socketcan"
    bitrate: int = 500000
    tx_id: int = 0x7E0
    rx_id: int = 0x7E8
    name: str = field(default="can", init=False)
    is_physical: bool = field(default=True, init=False)

    def open(self) -> CanConnection:
        can = _require_can()
        try:
            bus = can.interface.Bus(
                channel=self.channel, interface=self.interface, bitrate=self.bitrate
            )
        except Exception as exc:
            raise TransportError(
                f"cannot open CAN {self.interface}:{self.channel}: {exc}"
            ) from exc
        return CanConnection(bus=bus, tx_id=self.tx_id, rx_id=self.rx_id)

    def initialize(self, connection: CanConnection, **_) -> InitResult:
        """CAN needs no K-Line wake-up; ISO-TP is ready once the bus is open."""
        return InitResult(
            ok=True,
            method="can",
            baud=self.bitrate,
            protocol="isotp",
            handshake_complete=True,
            detail=f"{self.interface}:{self.channel} tx=0x{self.tx_id:03X} rx=0x{self.rx_id:03X}",
        )
