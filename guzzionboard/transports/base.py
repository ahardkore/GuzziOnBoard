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
    """Outcome of an ECU wake-up."""

    ok: bool
    method: str
    key_bytes: tuple[int, ...] = ()
    baud: int = 0
    detail: str = ""
    attempts: list[str] = field(default_factory=list)


class Connection(abc.ABC):
    """An open link to one ECU."""

    @abc.abstractmethod
    def write(self, data: bytes) -> None:
        """Transmit a complete frame."""

    @abc.abstractmethod
    def read_frame(self, timeout: float) -> bytes:
        """Read one complete frame, or return ``b""`` on timeout."""

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
