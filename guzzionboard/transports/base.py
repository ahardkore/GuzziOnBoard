"""Transport interface.

A transport moves framed bytes. It knows nothing about screens or motorcycle
semantics, and nothing above it may assume a particular physical layer.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field


class TransportError(Exception):
    pass


class TransportUnavailable(TransportError):
    """The backing hardware or driver package is not present."""


@dataclass
class InitResult:
    """Outcome of an ECU wake-up.

    ``handshake_complete`` distinguishes a physical K-Line transport (which
    must send and validate StartCommunication as part of fast init) from a
    simulator that only models the wake-up and leaves StartCommunication to
    the protocol session.  Keeping that fact explicit prevents the same 0x81
    request being sent twice on real hardware.

    ``request`` and ``response`` retain the otherwise pre-session handshake
    frames so they can be written to the normal raw-frame log.
    """

    ok: bool
    method: str
    key_bytes: tuple[int, ...] = ()
    baud: int = 0
    detail: str = ""
    attempts: list[str] = field(default_factory=list)
    protocol: str = ""
    handshake_complete: bool = False
    request: bytes = b""
    response: bytes = b""


class Connection(abc.ABC):
    """An open link to one ECU."""

    @abc.abstractmethod
    def write(self, data: bytes) -> None:
        """Transmit a complete frame."""

    @abc.abstractmethod
    def read_frame(self, timeout: float) -> bytes:
        """Read one complete frame, or return ``b""`` on timeout."""

    def read_bytes(self, size: int, timeout: float) -> bytes:
        """Read an exact-size unframed reply when a protocol requires it.

        Framed transports may use the default implementation. Byte-stream
        transports should override it so a one-byte legacy answer is not
        mistaken for the first byte of a KWP header.
        """
        return self.read_frame(timeout)[:size]

    @abc.abstractmethod
    def close(self) -> None: ...

    @property
    def is_open(self) -> bool:
        return True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


class Transport(abc.ABC):
    """Factory for connections, plus whatever wake-up the physical layer needs."""

    #: Short stable name used by the catalog and the UI.
    name: str = "transport"
    #: True when this transport can reach a real motorcycle.
    is_physical: bool = False

    @abc.abstractmethod
    def open(self) -> Connection: ...

    @abc.abstractmethod
    def initialize(self, connection: Connection, **kwargs) -> InitResult:
        """Wake the ECU so that diagnostic requests are accepted."""

    def describe(self) -> dict:
        return {"name": self.name, "physical": self.is_physical}
