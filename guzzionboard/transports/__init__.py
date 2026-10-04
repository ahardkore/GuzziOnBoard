"""Transports: simulator, K-Line serial, CAN."""
from .base import Connection, InitResult, Transport, TransportError, TransportUnavailable
from .simulator import EngineModel, SimulatedEcu, SimulatorTransport

__all__ = [
    "Connection", "InitResult", "Transport", "TransportError",
    "TransportUnavailable", "EngineModel", "SimulatedEcu", "SimulatorTransport",
]


def kline_transport(**kw):
    """Lazy factory so pyserial stays optional."""
    from .kline import KLineTransport
    return KLineTransport(**kw)


def can_transport(**kw):
    """Lazy factory so python-can stays optional."""
    from .can import CanTransport
    return CanTransport(**kw)
