"""Transport behaviour that can be checked without hardware."""
import pytest

from guzzionboard.catalog import load_catalog
from guzzionboard.diagnostics import DiagnosticsService
from guzzionboard.protocol.kwp2000 import ProtocolError, decode_frame, encode_request
from guzzionboard.safety import Mode, SafetyGate
from guzzionboard.transports.base import (
    Connection, InitResult, Transport, TransportUnavailable,
)
from guzzionboard.transports.simulator import (
    EngineModel, SimulatedEcu, SimulatorTransport,
)


@pytest.fixture
def profile():
    return load_catalog().ecu("5am")


def test_hardware_transports_fail_with_an_actionable_message(monkeypatch):
    import guzzionboard.transports.kline as kline
    monkeypatch.setattr(kline, "_require_serial", lambda: (_ for _ in ()).throw(
        TransportUnavailable("pyserial is not installed. Install the hardware extra")))
    with pytest.raises(TransportUnavailable, match="hardware extra"):
        kline.KLineTransport().open()


def test_listing_ports_degrades_to_empty_without_pyserial():
    from guzzionboard.transports.kline import KLineTransport
    assert isinstance(KLineTransport.list_ports(), list)


def test_physical_can_transport_has_no_generic_motorcycle_defaults():
    from guzzionboard.transports.can import CanTransport

    with pytest.raises(TransportUnavailable, match="generic defaults are not used"):
        CanTransport().open()


class _SilentCanConnection(Connection):
    def __init__(self):
        self.writes = []
        self.closed = False

    def write(self, data):
        self.writes.append(bytes(data))

    def read_frame(self, timeout):
        return b""

    def close(self):
        self.closed = True


class _UnvalidatedPhysicalCan(Transport):
    name = "test-can"
    is_physical = True

    def __init__(self):
        self.connection = _SilentCanConnection()
        self.open_count = 0

    def open(self):
        self.open_count += 1
        return self.connection

    def initialize(self, connection, **kwargs):
        return InitResult(True, "can", protocol="isotp", handshake_complete=True)


def test_unvalidated_can_application_is_blocked_before_any_request():
    transport = _UnvalidatedPhysicalCan()
    service = DiagnosticsService(
        load_catalog().ecu("11mp"), transport, SafetyGate(mode=Mode.READ_ONLY)
    )

    with pytest.raises(TransportUnavailable, match="no request was sent"):
        service.connect()

    assert transport.open_count == 0
    assert transport.connection.writes == []
    assert not transport.connection.closed


@pytest.mark.parametrize(
    ("operation", "message"),
    [
        (lambda service: service.identify(), "identification request"),
        (lambda service: service.read_dtcs(), "fault-memory request"),
        (lambda service: service.discover_identifiers(), "identifier discovery"),
    ],
)
def test_unknown_profile_refuses_unvalidated_read_operations(operation, message):
    service = DiagnosticsService(
        load_catalog().ecu("11mp"), _UnvalidatedPhysicalCan(),
        SafetyGate(mode=Mode.READ_ONLY),
    )

    with pytest.raises(ProtocolError, match=message):
        operation(service)


def test_simulator_validates_the_checksum_of_what_it_receives(profile):
    conn = SimulatorTransport(profile=profile).open()
    bad = bytearray(encode_request([0x21, 0x30]))
    bad[-1] ^= 0x01
    with pytest.raises(Exception):
        conn.write(bytes(bad))


def test_programming_session_is_refused_once_diagnostics_are_running(profile):
    """Both observed 5AM behaviours, and the state that distinguishes them.

    The flashing tools open ``10 85`` straight after StartCommunication and it
    is accepted. The live-data tools, already inside a ``10 81`` session, get
    NRC 0x22 for the same request.
    """
    ecu = SimulatedEcu(profile)
    assert ecu.handle(bytes([0x10, 0x85]))[0] == 0x50

    ecu = SimulatedEcu(profile)
    assert ecu.handle(bytes([0x10, 0x81]))[0] == 0x50
    response = ecu.handle(bytes([0x10, 0x85]))
    assert response[0] == 0x7F and response[2] == 0x22


def test_baud_switch_requires_the_programming_session_first(profile):
    ecu = SimulatedEcu(profile)
    refused = ecu.handle(bytes([0x10, 0x0C, 0x0C, 0x09]))
    assert refused[0] == 0x7F and refused[2] == 0x22

    ecu = SimulatedEcu(profile)
    ecu.handle(bytes([0x10, 0x85]))
    assert ecu.handle(bytes([0x10, 0x0C, 0x0C, 0x09]))[0] == 0x50
    assert ecu.baud_switched


def test_simulator_rejects_an_unknown_service(profile):
    response = SimulatedEcu(profile).handle(bytes([0xAA]))
    assert response[0] == 0x7F and response[2] == 0x11


def test_simulator_answers_identification_in_the_catalog_layout(profile):
    payload = SimulatedEcu(profile).handle(bytes([0x1A, 0x80]))
    assert payload[0] == 0x5A
    block = payload[2:]
    assert block[0:11].decode().strip() == "CM071201"
    assert block[11:22].decode().strip() == "IAW5AMHW610"


def test_simulator_refuses_identification_with_the_wrong_option(profile):
    response = SimulatedEcu(profile).handle(bytes([0x1A, 0x99]))
    assert response[0] == 0x7F and response[2] == 0x31


def test_engine_model_warms_up_and_settles(profile):
    cold = EngineModel()
    warm = EngineModel()
    warm.advance(600)              # ten minutes in
    assert cold.coolant_c < warm.coolant_c
    assert warm.coolant_c == pytest.approx(92, abs=3.0)
    assert warm.closed_loop and not cold.closed_loop


def test_engine_model_reports_a_stopped_engine_honestly():
    stopped = EngineModel(running=False)
    assert stopped.rpm == 0
    assert stopped.injection_ms == 0
    assert 12 < stopped.battery_v < 13


def test_simulator_wraps_responses_with_the_addresses_swapped(profile):
    conn = SimulatorTransport(profile=profile).open()
    conn.write(encode_request([0x21, 0x30]))
    frame = decode_frame(conn.read_frame(1.0))
    assert frame.target == 0xF1 and frame.source == 0x10
