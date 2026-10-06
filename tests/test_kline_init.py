"""K-Line handshake negotiation and the standards-derived edge cases."""
from __future__ import annotations

from dataclasses import replace

import pytest

from guzzionboard.catalog import load_catalog
from guzzionboard.diagnostics import DiagnosticsService
from guzzionboard.protocol.kwp2000 import encode_request
from guzzionboard.safety import Mode, SafetyGate, VehicleState
from guzzionboard.transports.base import Connection, InitResult, Transport
from guzzionboard.transports.kline import (
    AUTO_FALLBACK_DELAY_S,
    KLineConnection,
    KLineTransport,
    keyword_protocol,
)


class Clock:
    """A deterministic clock so a 5-baud unit test does not take 2 seconds."""

    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        seconds = max(0.0, float(seconds))
        self.sleeps.append(seconds)
        self.now += seconds


class FakePort:
    def __init__(self, response: bytes = b"", *, queue_on_write: bool = True):
        self.response = bytes(response)
        self.queue_on_write = queue_on_write
        self.rx = bytearray(response if not queue_on_write else b"")
        self.writes = []
        self.break_condition = False
        self.is_open = True

    def reset_input_buffer(self):
        # A hardware buffer starts empty and receives the reply after write.
        # Slow-init tests pre-load bytes as if the ECU sends them after W1.
        pass

    def write(self, data):
        self.writes.append(bytes(data))
        if self.queue_on_write and self.response:
            self.rx.extend(self.response)
            self.response = b""
        return len(data)

    def flush(self):
        pass

    def read(self, size=1):
        out = bytes(self.rx[:size])
        del self.rx[:size]
        return out

    def close(self):
        self.is_open = False


def _clock(monkeypatch):
    clock = Clock()
    import guzzionboard.transports.kline as kline
    monkeypatch.setattr(kline.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(kline.time, "sleep", clock.sleep)
    return clock


def _start_positive(*keys: int) -> bytes:
    return encode_request([0xC1, *keys], target=0xF1, source=0x10)


def test_fast_init_requires_a_valid_positive_response(monkeypatch):
    clock = _clock(monkeypatch)
    reply = _start_positive(0xEA, 0x8F)
    port = FakePort(reply)
    conn = KLineConnection(port=port, echo=False)

    result = KLineTransport()._fast_init(conn)

    assert result.ok
    assert result.protocol == "iso14230"
    assert result.key_bytes == (0xEA, 0x8F)
    assert result.handshake_complete
    assert result.request == bytes.fromhex("C1 33 F1 81 66")
    assert result.response == reply
    assert clock.now >= 0.350  # W5 idle + the complete 50 ms wake-up pattern


@pytest.mark.parametrize("kind", ["checksum", "wrong_service", "wrong_target"])
def test_fast_init_rejects_any_bytes_that_are_not_its_handshake(kind, monkeypatch):
    _clock(monkeypatch)
    if kind == "checksum":
        raw = bytearray(_start_positive(0xEA, 0x8F))
        raw[-1] ^= 1
        reply = bytes(raw)
    elif kind == "wrong_target":
        reply = encode_request([0xC1, 0xEA, 0x8F], target=0x22, source=0x10)
    else:
        reply = encode_request([0x50, 0x81], target=0xF1, source=0x10)

    result = KLineTransport()._fast_init(
        KLineConnection(port=FakePort(reply), echo=False)
    )

    assert not result.ok
    assert result.response == reply


def test_slow_init_validates_keywords_and_both_complements(monkeypatch):
    _clock(monkeypatch)
    # 55, KW1, KW2, then the ECU's complement of address 0x33.
    port = FakePort(bytes.fromhex("55 EA 8F CC"), queue_on_write=False)
    result = KLineTransport()._slow_init(
        KLineConnection(port=port, echo=False), 0x33
    )

    assert result.ok
    assert result.key_bytes == (0xEA, 0x8F)
    assert result.protocol == "iso14230"
    assert port.writes == [bytes([~0x8F & 0xFF])]
    assert result.handshake_complete


def test_iso9141_keywords_are_detected_but_not_misrepresented_as_kwp(monkeypatch):
    _clock(monkeypatch)
    port = FakePort(bytes.fromhex("55 08 08 CC"), queue_on_write=False)
    result = KLineTransport()._slow_init(
        KLineConnection(port=port, echo=False), 0x33
    )

    assert not result.ok
    assert result.protocol == "iso9141-2"
    assert "message layer is KWP2000" in result.detail
    assert keyword_protocol(0x94, 0x94) == "iso9141-2"
    assert keyword_protocol(0xEA, 0x8F) == "iso14230"


def test_auto_waits_for_a_slow_ecu_to_abandon_the_failed_fast_attempt(monkeypatch):
    transport = KLineTransport()
    sleeps = []

    monkeypatch.setattr(
        transport,
        "_fast_init",
        lambda *a, **kw: InitResult(False, "fast", detail="silence"),
    )
    monkeypatch.setattr(
        transport,
        "_slow_init",
        lambda *a, **kw: InitResult(
            True, "slow", detail="connected", protocol="iso14230",
            handshake_complete=True,
        ),
    )
    import guzzionboard.transports.kline as kline
    monkeypatch.setattr(kline.time, "sleep", lambda seconds: sleeps.append(seconds))

    result = transport.initialize(object(), method="auto")

    assert result.ok and result.method == "slow"
    assert sleeps == [AUTO_FALLBACK_DELAY_S]
    assert result.attempts == ["fast: silence", "slow: connected"]


class CaptureConnection(Connection):
    def __init__(self):
        self.writes = []

    def write(self, data: bytes) -> None:
        self.writes.append(bytes(data))

    def read_frame(self, timeout: float) -> bytes:
        return b""

    def close(self) -> None:
        pass


class CompletedFastTransport(Transport):
    name = "completed-fast"
    is_physical = True

    def __init__(self):
        self.connection = CaptureConnection()

    def open(self):
        return self.connection

    def initialize(self, connection, **kwargs):
        return InitResult(
            True, "fast", key_bytes=(0xEA, 0x8F), protocol="iso14230",
            handshake_complete=True,
        )


def test_diagnostics_does_not_send_start_communication_twice():
    profile = load_catalog().ecu("16m")  # access_timing is false
    transport = CompletedFastTransport()
    service = DiagnosticsService(
        profile,
        transport,
        SafetyGate(mode=Mode.READ_ONLY, state=VehicleState()),
    )

    service.connect(init_method="fast")
    try:
        assert transport.connection.writes == []
    finally:
        service.disconnect()
