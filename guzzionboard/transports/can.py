"""Generic ISO-TP transport over CAN.

ISO-TP segmentation does not establish any motorcycle's CAN identifiers,
bitrate, addressing mode, or diagnostic application. Callers must supply those
values from an evidence-backed family profile; this module deliberately has no
physical-hardware defaults. The ``python-can`` import is lazy so the rest of
the toolchain works without it.
"""
from __future__ import annotations

import time
import re
from dataclasses import dataclass, field

from ..protocol.isotp import Reassembler, segment
from .base import Connection, InitResult, Transport, TransportError, TransportUnavailable


# Network identifiers from the pinned Intrepid icsnVC40.h. Reject ISO9141,
# J1850, LIN, Ethernet and device-control network IDs before opening hardware.
NEOVI_CAN_NETWORKS = {
    "HSCAN": 1, "MSCAN": 2, "SWCAN": 3, "LSFTCAN": 4,
    "HSCAN2": 42, "HSCAN3": 44, "HSCAN4": 61, "HSCAN5": 62,
    "SWCAN2": 68, "HSCAN6": 96, "HSCAN7": 97, "LSFTCAN2": 99,
    **{f"DWCAN_{n:02d}": v for n, v in enumerate(
        (1, 42, 44, 61, 62, 96, 97, 2, 534, 535, 536, 537, 538, 539, 540, 541), 1)},
}


def validate_neovi_selection(channel, serial):
    """Validate a single CAN network and serial without touching any device."""
    if (not isinstance(serial, str) or not re.fullmatch(r"[A-Za-z0-9]{1,16}", serial)
            or not isinstance(channel, str) or not re.fullmatch(r"[A-Za-z0-9_]{1,32}", channel)):
        raise ValueError("Intrepid neoVI requires an explicit serial number and one supported CAN network")
    name = channel.upper()
    if name.isdecimal():
        if int(name) not in NEOVI_CAN_NETWORKS.values():
            raise ValueError("Intrepid network ID is not a supported CAN network")
    elif name not in NEOVI_CAN_NETWORKS:
        raise ValueError("Intrepid network name is not a supported CAN network")
    return name, serial.upper()


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
    tx_id: int
    rx_id: int
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
            if (msg is None or msg.arbitration_id != self.rx_id
                    or getattr(msg, "is_extended_id", self.rx_id > 0x7FF) != (self.rx_id > 0x7FF)
                    or getattr(msg, "is_remote_frame", False) or getattr(msg, "is_error_frame", False)):
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
            if (msg is None or msg.arbitration_id != self.rx_id
                    or getattr(msg, "is_extended_id", self.rx_id > 0x7FF) != (self.rx_id > 0x7FF)
                    or getattr(msg, "is_remote_frame", False) or getattr(msg, "is_error_frame", False)):
                continue
            payload, reply = self._rx.feed(bytes(msg.data))
            if reply is not None:
                can = _require_can()
                self.bus.send(
                    can.Message(
                        arbitration_id=self.tx_id,
                        data=reply[:3] + bytes([self.padding]) * (len(reply) - 3),
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
    bitrate: int | None = None
    tx_id: int | None = None
    rx_id: int | None = None
    padding: int = 0xAA
    serial: str = ""
    name: str = field(default="can", init=False)
    is_physical: bool = field(default=True, init=False)

    def open(self) -> CanConnection:
        missing = [
            name for name, value in (
                ("bitrate", self.bitrate), ("tx_id", self.tx_id), ("rx_id", self.rx_id)
            ) if value is None
        ]
        if missing:
            raise TransportUnavailable(
                "CAN hardware needs evidence-backed " + ", ".join(missing)
                + "; generic defaults are not used"
            )
        kwargs = dict(channel=self.channel, interface=self.interface, bitrate=self.bitrate)
        if self.interface == "neovi":
            # The upstream backend otherwise opens the first device it finds,
            # and accepts comma-separated channel lists. Require an explicit
            # device and a single network before opening any hardware.
            try:
                channel, serial = validate_neovi_selection(self.channel, self.serial)
            except ValueError as exc:
                raise TransportUnavailable(str(exc)) from exc
            kwargs["channel"] = channel
            try:
                import ics  # type: ignore
                if not callable(getattr(ics, "find_devices", None)):
                    raise ImportError("python_ics native module did not load")
            except (ImportError, OSError) as exc:
                raise TransportUnavailable("Intrepid neoVI requires python_ics in this Python environment; packaged builds do not bundle it. On Linux, an externally configured Intrepid SocketCAN interface is another option.") from exc
            kwargs.update(serial=serial, receive_own_messages=False, ignore_config=True)
        can = _require_can()
        try:
            bus = can.interface.Bus(**kwargs)
        except Exception as exc:
            raise TransportError(
                f"cannot open CAN {self.interface}:{self.channel}: {exc}"
            ) from exc
        # Values were validated above; keep the connection type strictly int.
        return CanConnection(
            bus=bus, tx_id=int(self.tx_id), rx_id=int(self.rx_id), padding=self.padding
        )

    def initialize(self, connection: CanConnection, **_) -> InitResult:
        """CAN needs no K-Line wake-up; ISO-TP is ready once the bus is open."""
        if self.bitrate is None or self.tx_id is None or self.rx_id is None:
            raise TransportUnavailable("CAN hardware profile is incomplete")
        return InitResult(
            ok=True,
            method="can",
            baud=self.bitrate,
            protocol="isotp",
            handshake_complete=True,
            detail=f"{self.interface}:{self.channel} tx=0x{self.tx_id:03X} rx=0x{self.rx_id:03X}",
        )
