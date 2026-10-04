"""ISO 15765-2 (ISO-TP) segmentation for KWP2000/UDS over CAN.

Used by the CAN transport for the newer Moto Guzzi ECUs (MIU G4, Marelli 11MP).
Kept free of any CAN library import so it can be unit tested on its own.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class PCIType(IntEnum):
    SINGLE = 0x0
    FIRST = 0x1
    CONSECUTIVE = 0x2
    FLOW_CONTROL = 0x3


class FlowStatus(IntEnum):
    CONTINUE = 0x0
    WAIT = 0x1
    OVERFLOW = 0x2


class IsoTpError(Exception):
    pass


def encode_single(payload: bytes, *, dlc: int = 8, padding: int = 0xAA) -> bytes:
    if len(payload) > dlc - 1:
        raise IsoTpError(f"{len(payload)} bytes do not fit in a single frame")
    frame = bytes([len(payload)]) + payload
    return frame.ljust(dlc, bytes([padding]))


def segment(payload: bytes, *, dlc: int = 8, padding: int = 0xAA) -> list[bytes]:
    """Split ``payload`` into ISO-TP frames (single, or first + consecutive)."""
    if len(payload) <= dlc - 1:
        return [encode_single(payload, dlc=dlc, padding=padding)]
    if len(payload) > 0xFFF:
        raise IsoTpError("payload exceeds the 4095 byte classic ISO-TP limit")

    frames = [
        bytes([0x10 | (len(payload) >> 8), len(payload) & 0xFF]) + payload[: dlc - 2]
    ]
    rest = payload[dlc - 2 :]
    index = 1
    while rest:
        chunk = rest[: dlc - 1]
        rest = rest[dlc - 1 :]
        frames.append((bytes([0x20 | (index & 0x0F)]) + chunk).ljust(dlc, bytes([padding])))
        index += 1
    return frames


def flow_control(
    status: FlowStatus = FlowStatus.CONTINUE,
    block_size: int = 0,
    st_min: int = 0,
    *,
    dlc: int = 8,
    padding: int = 0xAA,
) -> bytes:
    return bytes([0x30 | int(status), block_size, st_min]).ljust(dlc, bytes([padding]))


@dataclass
class Reassembler:
    """Accumulates incoming ISO-TP frames into complete payloads."""

    expected: int = 0
    buffer: bytearray = None  # type: ignore[assignment]
    index: int = 0

    def __post_init__(self) -> None:
        self.buffer = bytearray()

    @property
    def active(self) -> bool:
        return self.expected > 0

    def feed(self, frame: bytes) -> tuple[bytes | None, bytes | None]:
        """Feed one CAN frame.

        Returns ``(payload, reply)``: ``payload`` once a message is complete,
        and ``reply`` when the transport must send a flow-control frame.
        """
        if not frame:
            raise IsoTpError("empty CAN frame")
        pci = (frame[0] >> 4) & 0x0F

        if pci == PCIType.SINGLE:
            length = frame[0] & 0x0F
            if length == 0 or length > len(frame) - 1:
                raise IsoTpError(f"bad single-frame length {length}")
            return bytes(frame[1 : 1 + length]), None

        if pci == PCIType.FIRST:
            self.expected = ((frame[0] & 0x0F) << 8) | frame[1]
            self.buffer = bytearray(frame[2:])
            self.index = 0
            return None, flow_control()

        if pci == PCIType.CONSECUTIVE:
            if not self.active:
                raise IsoTpError("consecutive frame without a first frame")
            self.index = (self.index + 1) & 0x0F
            if (frame[0] & 0x0F) != self.index:
                raise IsoTpError(
                    f"ISO-TP sequence error: got {frame[0] & 0x0F}, expected {self.index}"
                )
            self.buffer += frame[1:]
            if len(self.buffer) >= self.expected:
                payload = bytes(self.buffer[: self.expected])
                self.reset()
                return payload, None
            return None, None

        if pci == PCIType.FLOW_CONTROL:
            return None, None

        raise IsoTpError(f"unknown ISO-TP PCI 0x{pci:X}")

    def reset(self) -> None:
        self.expected = 0
        self.buffer = bytearray()
        self.index = 0
