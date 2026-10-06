"""Marelli's pre-KWP single-byte diagnostic protocol.

The recovered automotive IAW-04K implementation and documented 16F/1.6M
controllers do not exchange ISO 14230 frames. Once the physical link is
initialised, the tester sends one identifier byte, the
K-Line interface echoes that byte, and the ECU returns exactly one data byte.
The transport consumes the echo; this class owns the remaining request/answer
exchange.

This intentionally exposes reads only.  The same identifier space also
contains self-timed actuator tests and reset commands, but those are not an
on/off KWP control and must not be routed through the workstation's actuator
API without a separately bounded and bench-validated execution model.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from .kwp2000 import ProtocolError
from ..transports.base import Connection


@dataclass
class LegacyIAWSession:
    """Read-only session for the legacy echoed one-byte Marelli protocol."""

    connection: Connection
    timeout: float = 0.5
    inter_request_delay: float = 0.005
    on_frame: Callable[[str, bytes], None] | None = None

    def query(self, identifier: int) -> int:
        """Read one legacy register and return its one-byte value."""
        if not 0 <= int(identifier) <= 0xFF:
            raise ValueError("legacy IAW identifier must be one byte")
        request = bytes([int(identifier)])
        if self.on_frame:
            self.on_frame("tx", request)
        self.connection.write(request)
        response = self.connection.read_bytes(1, self.timeout)
        if self.on_frame and response:
            self.on_frame("rx", response)
        if len(response) != 1:
            got = response.hex(" ") if response else "no response"
            raise ProtocolError(
                f"legacy IAW request 0x{identifier:02X}: expected one byte, got {got}"
            )
        return response[0]

    def query_many(self, identifiers) -> bytes:
        """Read identifiers in order and concatenate their one-byte answers."""
        values = bytearray()
        for index, identifier in enumerate(identifiers):
            if index and self.inter_request_delay:
                time.sleep(self.inter_request_delay)
            values.append(self.query(int(identifier)))
        return bytes(values)

    def read_data_by_local_id(self, local_id: int) -> bytes:
        """Compatibility name used by read-only discovery."""
        return bytes([self.query(local_id)])

    def close(self) -> None:
        """There is no framed stop-session command in this protocol."""
        return
