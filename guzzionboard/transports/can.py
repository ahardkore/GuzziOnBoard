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

from ..protocol.isotp import IsoTpError, Reassembler, segment
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


def validate_slcan_selection(channel):
    """Require one explicit local serial port, optionally with a bounded baud."""
    if not isinstance(channel, str) or len(channel) > 255:
        raise ValueError("SLCAN requires an explicit local serial port")
    path, marker, speed = channel.partition('@')
    valid_port = bool(re.fullmatch(r"COM[1-9][0-9]{0,3}", path, re.IGNORECASE))
    if path.startswith('/dev/'):
        valid_port = bool(re.fullmatch(r"/dev/[A-Za-z0-9._/-]+", path)) and all(
            part not in ('', '.', '..') for part in path.split('/')[1:])
    if not valid_port or (marker and (not speed.isascii() or not speed.isdecimal()
                                     or not 9600 <= int(speed) <= 4000000)):
        raise ValueError("SLCAN requires a local COM or /dev port, optionally @9600–4000000 baud")
    return channel


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
        # Flow control behavior informed by EcuBus-Pro cantp.ts (Apache-2.0),
        # revision ca3207801b34ded99b67b8b12b5d4547b5a868e8. This adaptation
        # is classic CAN only and has synthetic tests, not hardware validation.
        can = _require_can()
        try:
            frames = segment(data, dlc=self.dlc, padding=self.padding)
        except IsoTpError as exc:
            raise TransportError(f"invalid ISO-TP payload: {exc}") from exc

        def send(payload):
            msg = can.Message(arbitration_id=self.tx_id, data=payload,
                              is_extended_id=self.tx_id > 0x7FF)
            try:
                self.bus.send(msg)
            except Exception as exc:
                raise TransportError(f"CAN send failed: {exc}") from exc

        send(frames[0])
        if len(frames) == 1:
            return
        index = 1
        while index < len(frames):
            block_size, ecu_st_min = self._await_flow_control()
            stop = len(frames) if block_size == 0 else min(len(frames), index + block_size)
            delay = max(self.st_min, ecu_st_min)
            while index < stop:
                # Delay also before the first CF after each FC, conservatively.
                if delay:
                    time.sleep(delay)
                send(frames[index])
                index += 1

    def _await_flow_control(self, timeout: float = 0.5) -> tuple[int, float]:
        """Return the ECU's block size and separation time, with bounded WAITs."""
        deadline = time.monotonic() + timeout
        waits = 0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TransportError("timed out waiting for an ISO-TP flow-control frame")
            try:
                msg = self.bus.recv(timeout=min(0.05, remaining))
            except Exception as exc:
                raise TransportError(f"CAN receive failed while waiting for flow control: {exc}") from exc
            if (msg is None or msg.arbitration_id != self.rx_id
                    or getattr(msg, "is_extended_id", self.rx_id > 0x7FF) != (self.rx_id > 0x7FF)
                    or getattr(msg, "is_remote_frame", False) or getattr(msg, "is_error_frame", False)
                    or getattr(msg, "is_fd", False) or getattr(msg, "is_rx", True) is False):
                continue
            raw = bytes(msg.data)
            if not raw or raw[0] >> 4 != 0x3:
                continue
            if len(raw) < 3 or len(raw) > 8:
                raise TransportError("malformed ISO-TP flow-control frame")
            status = raw[0] & 0x0F
            if status == 1:
                waits += 1
                if waits > 8:
                    raise TransportError("too many ISO-TP WAIT flow-control frames")
                # No deadline extension: cap total time even for WAIT floods.
                continue
            if status == 2:
                raise TransportError("ECU reported an ISO-TP buffer overflow")
            if status != 0:
                raise TransportError("invalid ISO-TP flow-control status")
            encoded = raw[2]
            if encoded <= 0x7F:
                separation = encoded / 1000.0
            elif 0xF1 <= encoded <= 0xF9:
                separation = (encoded - 0xF0) / 10000.0
            else:
                # Reserved values use the conservative maximum 127 ms.
                separation = 0.127
            return raw[1], separation

    def read_frame(self, timeout: float) -> bytes:
        deadline = time.monotonic() + timeout
        self._rx.reset()
        while time.monotonic() < deadline:
            try:
                msg = self.bus.recv(timeout=max(0.01, deadline - time.monotonic()))
            except Exception as exc:
                raise TransportError(f"CAN receive failed: {exc}") from exc
            if (msg is None or msg.arbitration_id != self.rx_id
                    or getattr(msg, "is_extended_id", self.rx_id > 0x7FF) != (self.rx_id > 0x7FF)
                    or getattr(msg, "is_remote_frame", False) or getattr(msg, "is_error_frame", False)
                    or getattr(msg, "is_fd", False) or getattr(msg, "is_rx", True) is False):
                continue
            try:
                payload, reply = self._rx.feed(bytes(msg.data))
            except IsoTpError as exc:
                raise TransportError(f"invalid ISO-TP response: {exc}") from exc
            if reply is not None:
                can = _require_can()
                try:
                    self.bus.send(
                        can.Message(
                            arbitration_id=self.tx_id,
                            data=reply[:3] + bytes([self.padding]) * (len(reply) - 3),
                            is_extended_id=self.tx_id > 0x7FF,
                        )
                    )
                except Exception as exc:
                    raise TransportError(f"CAN flow-control send failed: {exc}") from exc
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
        if self.interface == "slcan":
            try:
                validate_slcan_selection(self.channel)
            except ValueError as exc:
                raise TransportUnavailable(str(exc)) from exc
            # Avoid unrelated python-can configuration changing adapter selection.
            kwargs["ignore_config"] = True
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
