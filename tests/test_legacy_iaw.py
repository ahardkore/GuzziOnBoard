"""The pre-KWP Marelli byte protocol stays separate and read-only."""
from collections import deque

import pytest

from guzzionboard.catalog import load_catalog
from guzzionboard.diagnostics import DiagnosticsService
from guzzionboard.protocol.kwp2000 import ProtocolError
from guzzionboard.protocol.legacy_iaw import LegacyIAWSession
from guzzionboard.safety import Mode, SafetyGate
from guzzionboard.transports.base import Connection, InitResult, Transport
from guzzionboard.transports.simulator import SimulatorTransport


class ByteConnection(Connection):
    def __init__(self, answers=()):
        self.answers = deque(bytes([answer]) for answer in answers)
        self.writes = []
        self.closed = False

    def write(self, data: bytes) -> None:
        self.writes.append(bytes(data))

    def read_bytes(self, size: int, timeout: float) -> bytes:
        return self.answers.popleft() if self.answers else b""

    def read_frame(self, timeout: float) -> bytes:
        raise AssertionError("legacy byte exchanges must not use KWP framing")

    def close(self) -> None:
        self.closed = True


class LegacyTransport(Transport):
    name = "legacy-test"
    is_physical = True

    def __init__(self, answers=(), wake=bytes.fromhex("55 B0 80 80 80 85")):
        self.connection = ByteConnection(answers)
        self.wake = wake

    def open(self):
        return self.connection

    def initialize(self, connection, **kwargs):
        return InitResult(
            True,
            "legacy-iaw-16m",
            baud=7680,
            protocol="legacy-iaw",
            handshake_complete=True,
            request=bytes.fromhex("0F AA CC"),
            response=self.wake,
        )


def test_one_byte_query_uses_raw_io_and_concatenates_in_order(monkeypatch):
    connection = ByteConnection([0x12, 0x34])
    session = LegacyIAWSession(connection, inter_request_delay=0)

    assert session.query_many([0x01, 0x02]) == bytes.fromhex("12 34")
    assert connection.writes == [b"\x01", b"\x02"]


def test_one_byte_query_rejects_silence():
    session = LegacyIAWSession(ByteConnection(), inter_request_delay=0)
    with pytest.raises(ProtocolError, match="expected one byte"):
        session.query(0x01)


def test_16m_identity_uses_part_number_registers_not_kwp_1a80():
    part = b"61600123456"
    transport = LegacyTransport(part)
    service = DiagnosticsService(
        load_catalog().ecu("16m"), transport, SafetyGate(mode=Mode.READ_ONLY)
    )

    service.connect()
    identity = service.identify()

    assert identity.fields["ISO key-on code"] == "55 B0 80 80 80 85"
    assert identity.fields["ECU part number"] == "61600123456"
    assert transport.connection.writes == [bytes([i]) for i in range(0x17, 0x22)]
    service.disconnect()


def test_simulator_uses_the_legacy_protocol_for_16m():
    profile = load_catalog().ecu("16m")
    service = DiagnosticsService(
        profile, SimulatorTransport(profile=profile), SafetyGate(mode=Mode.SIMULATOR)
    )

    result = service.connect()
    identity = service.identify()
    rpm = service.read_parameter(profile.parameter("rpm"))

    assert result.protocol == "legacy-iaw"
    assert identity.fields["ECU part number"] == "61600123456"
    assert rpm.value > 0
    service.disconnect()


def test_16m_two_request_parameter_is_decoded_after_concatenation():
    # 15,000,000 / 10,000 = 1,500 rpm.
    transport = LegacyTransport([0x27, 0x10])
    service = DiagnosticsService(
        load_catalog().ecu("16m"), transport, SafetyGate(mode=Mode.READ_ONLY)
    )
    service.connect()

    sample = service.read_parameter(service.profile.parameter("rpm"))

    assert sample.raw == bytes.fromhex("27 10")
    assert sample.value == 1500
    assert transport.connection.writes == [b"\x01", b"\x02"]
    service.disconnect()


def test_legacy_faults_are_reported_as_raw_bits_not_kwp_dtcs():
    # One value for each of the 12 documented fault registers.
    transport = LegacyTransport([0x05] + [0x00] * 11)
    service = DiagnosticsService(
        load_catalog().ecu("16m"), transport, SafetyGate(mode=Mode.READ_ONLY)
    )
    service.connect()

    result = service.read_dtcs()

    assert result["format"] == "legacy-fault-bitfields"
    assert result["registers"][0] == {
        "request": 0x10,
        "hex_request": "0x10",
        "value": 0x05,
        "hex_value": "0x05",
        "set_bits": [0, 2],
    }
    assert [item["code"] for item in result["dtcs"]] == [
        "REG-10-BIT-0",
        "REG-10-BIT-2",
    ]
    assert all(item["kind"] == "legacy-raw-bit" for item in result["dtcs"])
    service.disconnect()
