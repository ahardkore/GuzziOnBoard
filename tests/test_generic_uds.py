"""Synthetic generic UDS (ISO 14229) CAN tests; no claim of motorcycle compatibility."""
import pytest

from guzzionboard.catalog import load_catalog
from guzzionboard.diagnostics import DiagnosticsService
from guzzionboard.protocol.kwp2000 import NegativeResponse, ProtocolError
from guzzionboard.protocol.uds import UdsSession
from guzzionboard.safety import Mode, SafetyGate
from guzzionboard.transports.base import Connection, InitResult, Transport, TransportUnavailable
from guzzionboard.workstation import Workstation


class FakeConnection(Connection):
    def __init__(self, replies):
        self.replies, self.sent, self.closed = list(replies), [], False
    @property
    def is_open(self): return not self.closed
    def write(self, data): self.sent.append(bytes(data))
    def read_frame(self, timeout): return self.replies.pop(0) if self.replies else b''
    def close(self): self.closed = True


class FakeTransport(Transport):
    name, is_physical = 'can', True
    bitrate, tx_id, rx_id, padding = 500000, 0x7e0, 0x7e8, 0
    def __init__(self, replies): self.conn, self.opened = FakeConnection(replies), False
    def open(self): self.opened = True; return self.conn
    def initialize(self, connection, **kwargs):
        return InitResult(True, 'can', protocol='isotp', handshake_complete=True)


def service(transport, mode=Mode.READ_ONLY):
    return DiagnosticsService(load_catalog().ecu('generic_uds_can_11bit'), transport, SafetyGate(mode=mode))


VIN = b'JH4RC480000000001'  # 17 permitted uppercase VIN characters


def test_identify_and_stored_faults_with_only_readonly_requests():
    t = FakeTransport([bytes.fromhex('50 01 00 00 00 00 00 00'),          # 10 01 positive
                       bytes.fromhex('62 F1 90') + VIN,                   # 22 F190 VIN
                       bytes.fromhex('59 02 FF 01 22 41 11 41 11 42 22')]) # 19 02 FF, 2 records
    s = service(t); s.connect()
    ident = s.identify()
    assert ident.fields['Vehicle VIN (unverified UDS DID F190 response)'] == VIN.decode()
    assert [d['code'] for d in s.read_dtcs()['dtcs']] == ['P0122', 'C0111']
    assert t.conn.sent == [b'\x10\x01', b'\x22\xf1\x90', b'\x19\x02\xff']
    s.disconnect()
    assert t.conn.closed


def test_every_mutating_or_unknown_service_is_refused_before_transmission():
    t = FakeTransport([bytes.fromhex('50 01 00 00 00 00 00 00'),          # 10 01 at connect
                       bytes.fromhex('50 03 00 00 00 00 00 00'),          # 10 03 positive
                       b'\x7e'])                                          # 3E positive
    s = service(t); s.connect()
    before = t.conn.sent[:]
    for payload in (b'\x11\x01', b'\x14\xff', b'\x23\x00\x00', b'\x27\x01', b'\x2e\xf1\x90\x00',
                    b'\x31\x01\x02\x03', b'\x34\x00\x00', b'\x36\x01\x00', b'\x10\x02', b'\x85\x02',
                    b'\x22\xf1', b'\x19', b'\x99'):
        with pytest.raises(PermissionError): s.session.request(payload)
    # read-only services stay allowed
    s.session.request(b'\x10\x03'); s.session.request(b'\x3e')
    assert t.conn.sent[:len(before)] == before
    s.disconnect()


def test_negative_response_raises_with_the_decoded_reason():
    conn = FakeConnection([b'\x7f\x22\x31'])
    with pytest.raises(NegativeResponse):
        UdsSession(conn).read_did(0xF190)
    assert conn.sent == [b'\x22\xf1\x90']


@pytest.mark.parametrize('reply', [b'', b'\x62\xf1\x91' + VIN, b'\x7f\x22', b'\x7f\x10\x31'])
def test_invalid_replies_are_protocol_errors(reply):
    conn = FakeConnection([reply])
    with pytest.raises(ProtocolError):
        UdsSession(conn).read_did(0xF190)


def test_session_control_echo_mismatch_is_an_error():
    with pytest.raises(ProtocolError):
        UdsSession(FakeConnection([b'\x50\x03'])).request(b'\x10\x01')


def test_short_vin_is_an_error():
    with pytest.raises(ProtocolError):
        UdsSession(FakeConnection([b'\x62\xf1\x90' + b'TOOSHORT'])).read_vehicle_information()


@pytest.mark.parametrize('reply', [b'\x59\x02', b'\x59\x02\xff\x01\x22\x41', b'\x59\x02\xff\x00\x00\x00\x00'])
def test_invalid_dtc_lists_are_not_a_clean_bill(reply):
    with pytest.raises(ProtocolError):
        UdsSession(FakeConnection([reply])).read_stored_codes()


def test_empty_dtc_list_is_counted():
    assert UdsSession(FakeConnection([b'\x59\x02\xff'])).read_stored_codes() == []


@pytest.mark.parametrize('change', [dict(bitrate=250000), dict(tx_id=0x7df), dict(tx_id=0x7e8), dict(rx_id=0x7e9), dict(padding=0xaa), dict(is_physical=False)])
def test_invalid_transport_refused_before_open(change):
    t = FakeTransport([])
    for key, value in change.items(): setattr(t, key, value)
    with pytest.raises(TransportUnavailable): service(t).connect()
    assert not t.opened


def test_profile_only_mode_and_selection_boundaries():
    t = FakeTransport([])
    with pytest.raises(TransportUnavailable): service(t, Mode.SERVICE).connect()
    assert not t.opened
    ws = Workstation(record=False)
    ws.select(ecu='generic_uds_can_11bit', transport='simulator')
    with pytest.raises(TransportUnavailable): ws.connect()
    ws.select(ecu='generic_uds_can_11bit', transport='can', can_tx_id='0x7DF', can_rx_id='0x7E8')
    with pytest.raises(TransportUnavailable): ws.connect(mode='read_only')


def test_non_isotp_init_is_refused():
    class WrongInit(FakeTransport):
        def initialize(self, connection, **kwargs):
            return InitResult(True, 'can', protocol='can-raw', handshake_complete=True)
    t = WrongInit([])
    with pytest.raises(ProtocolError): service(t).connect()
    assert t.conn.closed
