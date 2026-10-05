"""A virtual CAN bus with the simulated ECU on the other end.

The CAN transport's framing path - ISO-TP segmentation, flow control, the
timing rules - had only ever been exercised by protocol unit tests, because
there was no ECU to talk to. This module puts a :class:`SimulatedEcu` behind
a python-can *virtual bus* so the exact code that will talk to a motorcycle
( :class:`~guzzionboard.transports.can.CanConnection` ) runs against the
exact code that simulates one, with real flow-control handshakes and real
sequence numbers, and no hardware.

The bridge honours the protocol honestly rather than blasting frames:

* a first frame from the tester is answered with a flow control, and the
  following consecutive frames are reassembled;
* a long answer is sent as first frame, then the bridge *waits* for the
  tester's flow control before sending consecutive frames, pacing them by
  the block size and separation time the tester granted.

Because the request/response identifiers come from the same place as the
real CAN transport (the catalog spec, the vehicle entry, the operator's
session overrides), a 29-bit rehearsal is just selecting the ids in the
Garage - the pair being confirmed on a real bike can be dry-run here first.
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field

from ..catalog import EcuProfile
from ..protocol.isotp import Reassembler, segment
from ..protocol.kwp2000 import (
    ECU_ADDRESS,
    TESTER_ADDRESS,
    decode_frame,
    encode_request,
)
from .base import InitResult, Transport, TransportError, TransportUnavailable
from .can import CanConnection
from .simulator import SimulatedEcu


def _require_can():
    try:
        import can  # type: ignore
    except ImportError as exc:  # pragma: no cover - depends on the host
        raise TransportUnavailable(
            "python-can is not installed. Install the hardware extra:\n"
            "    pip install -e '.[hardware]'"
        ) from exc
    return can


class VirtualCanEcu:
    """ISO-TP bridge between a virtual bus and a :class:`SimulatedEcu`.

    Listens on ``rx_id`` (the tester's request id), reassembles requests,
    hands the payload to the simulator, and segments answers back onto the
    bus from ``tx_id`` - flow control and all.
    """

    def __init__(
        self,
        ecu: SimulatedEcu,
        *,
        bus,
        tx_id: int,
        rx_id: int,
        dlc: int = 8,
        padding: int = 0xAA,
    ):
        self.ecu = ecu
        self.bus = bus
        self.tx_id = tx_id
        self.rx_id = rx_id
        self.dlc = dlc
        self.padding = padding
        self._rx = Reassembler()
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="virtual-can-ecu"
        )
        self._thread.start()

    # -- bus helpers -------------------------------------------------------
    def _send_raw(self, payload: bytes) -> None:
        can = _require_can()
        self.bus.send(
            can.Message(
                arbitration_id=self.tx_id,
                data=payload,
                is_extended_id=self.tx_id > 0x7FF,
            )
        )

    def _await_flow_control(self, timeout: float = 1.0) -> float:
        """Wait for the tester's flow control; returns the separation time."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            msg = self.bus.recv(timeout=max(0.01, deadline - time.monotonic()))
            if msg is None or msg.arbitration_id != self.rx_id:
                continue
            data = bytes(msg.data)
            if (data[0] >> 4) == 0x3:
                st_min_raw = data[2] if len(data) > 2 else 0
                return (
                    st_min_raw / 1000.0 if st_min_raw <= 0x7F else 0.0001
                )
        raise TimeoutError("tester sent no flow control for a first frame")

    def _send(self, data: bytes) -> None:
        """One payload, segmented, honouring the tester's flow control."""
        frames = segment(data, dlc=self.dlc, padding=self.padding)
        if len(frames) == 1:
            self._send_raw(frames[0])
            return
        self._send_raw(frames[0])                    # first frame
        st_min = self._await_flow_control()          # protocol, not optimism
        for frame in frames[1:]:
            time.sleep(st_min)
            self._send_raw(frame)

    # -- main loop ---------------------------------------------------------
    def _run(self) -> None:
        while not self._stop.is_set():
            msg = self.bus.recv(timeout=0.05)
            if msg is None or msg.arbitration_id != self.rx_id:
                continue
            payload, reply = self._rx.feed(bytes(msg.data))
            if reply is not None:                    # first frame -> FC
                self._send_raw(reply)
            if payload is not None:
                self._handle_wire(payload)

    def _handle_wire(self, data: bytes) -> None:
        """One complete message off the bus, framed the way this project's
        sessions frame them (KWP header + checksum, like the K-Line wire).

        Note: whether a real Marelli CAN bike expects this framing stripped
        inside ISO-TP (the ISO 15765-3 convention) is exactly what the first
        real capture will tell; the rehearsal exercises the framing
        mechanics, not that convention.
        """
        frame = decode_frame(data)          # validates the checksum
        response = self.ecu.handle(frame.payload)
        if response is None:
            return
        wire = encode_request(
            response, target=TESTER_ADDRESS, source=ECU_ADDRESS, addressed=True
        )
        self._send(wire)

    def shutdown(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2.0)
        try:
            self.bus.shutdown()
        except Exception:  # pragma: no cover
            pass


@dataclass
class VirtualCanConnection(CanConnection):
    """A tester-side CAN connection whose ECU is the bridge."""

    bridge: VirtualCanEcu | None = None

    def close(self) -> None:
        try:
            super().close()
        finally:
            if self.bridge is not None:
                self.bridge.shutdown()


@dataclass
class VirtualCanTransport(Transport):
    """The full ISO-TP path against the simulated ECU, over a virtual bus."""

    profile: EcuProfile = None  # type: ignore[assignment]
    ecu: SimulatedEcu = None    # type: ignore[assignment]
    tx_id: int = 0x7E0
    rx_id: int = 0x7E8
    dlc: int = 8
    padding: int = 0xAA
    name: str = field(default="cansim", init=False)
    is_physical: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.ecu is None:
            if self.profile is None:
                raise ValueError("VirtualCanTransport needs a profile or an ecu")
            self.ecu = SimulatedEcu(self.profile)
        if self.profile is None:
            self.profile = self.ecu.profile

    def open(self) -> VirtualCanConnection:
        can = _require_can()
        channel = f"guzzionboard-cansim-{uuid.uuid4().hex[:10]}"
        try:
            ecu_bus = can.interface.Bus(interface="virtual", channel=channel)
            tester_bus = can.interface.Bus(interface="virtual", channel=channel)
        except Exception as exc:
            raise TransportError(f"cannot open the virtual CAN bus: {exc}") from exc
        bridge = VirtualCanEcu(
            self.ecu,
            bus=ecu_bus,
            tx_id=self.rx_id,          # the ECU answers from the rx id
            rx_id=self.tx_id,          # ... and listens on the tx id
            dlc=self.dlc,
            padding=self.padding,
        )
        return VirtualCanConnection(
            bus=tester_bus,
            tx_id=self.tx_id,
            rx_id=self.rx_id,
            dlc=self.dlc,
            padding=self.padding,
            bridge=bridge,
        )

    def initialize(self, connection, **kwargs) -> InitResult:
        return InitResult(
            ok=True,
            method="virtual-can",
            key_bytes=(),
            baud=500000,
            detail=(
                f"virtual CAN bus, tester 0x{self.tx_id:X} "
                f"<-> ECU 0x{self.rx_id:X}, {self.profile.family}"
            ),
        )

    def describe(self) -> dict:
        return {
            "name": self.name,
            "physical": self.is_physical,
            "tx_id": self.tx_id,
            "rx_id": self.rx_id,
        }

