"""Synthetic generic ISO 9141-2 OBD tests; no claim of motorcycle compatibility."""
import pytest

from guzzionboard.catalog import load_catalog
from guzzionboard.diagnostics import DiagnosticsService
from guzzionboard.protocol.iso9141 import (
    Iso9141ObdSession,
    build_frame,
    parse_iso9141_burst,
)
from guzzionboard.protocol.kwp2000 import NegativeResponse, ProtocolError, checksum
from guzzionboard.safety import Mode, SafetyGate
from guzzionboard.transports.base import Connection, InitResult, Transport, TransportUnavailable


def iso(*payload):
    body = bytes([0x48, 0x6B, 0xD1, *payload])
    return body + bytes([sum(body) & 255])


class FakeConnection(Connection):
    def __init__(self, replies):
        self.replies, self.sent, self.closed = list(replies), [], False

    @property
    def is_open(self):
        return not self.closed

    def write(self, data):
        self.sent.append(bytes(data))

    def read_frame(self, timeout):
        raise AssertionError('ISO 9141-2 frames are bursts, not KWP length-framed')

    def read_iso9141_burst(self, timeout, *, gap=0.060, limit=512):
        return self.replies.pop(0) if self.replies else b''

    def close(self):
        self.closed = True


class FakeTransport(Transport):
    name, is_physical = 'kline', True
    baud = 10400

    def __init__(self, replies, keys=(0x08, 0x08), protocol='iso9141-2'):
        self.conn = FakeConnection(replies)
        self.keys, self.protocol, self.opened = keys, protocol, False

    def open(self):
        self.opened = True
        return self.conn

    def initialize(self, connection, **kw):
        assert kw['method'] == 'generic-obd-iso9141-kline'
        return InitResult(True, 'slow', key_bytes=self.keys, protocol=self.protocol,
                          handshake_complete=True)


def service(transport, mode=Mode.READ_ONLY):
    return DiagnosticsService(load_catalog().ecu('generic_obd_iso9141_kline'),
                              transport, SafetyGate(mode=mode))


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr('guzzionboard.protocol.iso9141.time.sleep', lambda _: None)


# ------------------------------------------------------------- framing units

def test_build_frame_is_header_payload_checksum():
    raw = build_frame(b'\x01\x00')
    assert raw == bytes.fromhex('68 6A F1 01 00 C4')
    assert raw[-1] == checksum(raw[:-1])


@pytest.mark.parametrize('payload', [b'', b'\x01' * 256])
def test_build_frame_rejects_bad_payload_sizes(payload):
    with pytest.raises(ProtocolError):
        build_frame(payload)


def test_parse_burst_splits_multiple_checksummed_frames():
    burst = iso(0x41, 0x0C, 0x3E, 0x80) + iso(0x41, 0x05, 0x5A)
    assert parse_iso9141_burst(burst) == [bytes([0x41, 0x0C, 0x3E, 0x80]),
                                          bytes([0x41, 0x05, 0x5A])]


@pytest.mark.parametrize('burst', [
    b'',
    bytes([0x48, 0x6B, 0xD1, 0x41, 0x00, 0x00]),          # bad checksum
    bytes([0x68, 0x6A, 0xF1, 0x41, 0x00, 0xC4]),          # wrong (request) header
    bytes([0x48, 0x6B, 0xD1]),                            # truncated
])
def test_parse_burst_rejects_malformed_input(burst):
    with pytest.raises(ProtocolError):
        parse_iso9141_burst(burst)


# ------------------------------------------------------------ session level

def test_live_and_stored_faults_with_exact_wire_bytes():
    t = FakeTransport([iso(0x41, 0x00, 0xFF, 0xFF, 0xFF, 0xFF),
                       iso(0x41, 0x0C, 0x3E, 0x80),
                       iso(0x41, 0x05, 0x5A),
                       iso(0x43, 0x01, 0x22, 0x41, 0x11)])
    s = service(t)
    s.connect()
    assert t.conn.sent[0] == bytes.fromhex('68 6A F1 01 00 C4')
    samples = s.read_parameters(['rpm', 'coolant'])
    assert [(p.value, p.raw) for p in samples] == [(4000, b'\x3e\x80'), (50, b'\x5a')]
    assert [d['code'] for d in s.read_dtcs()['dtcs']] == ['P0122', 'C0111']
    assert t.conn.sent[-1] == bytes.fromhex('68 6A F1 03 C6')
    before = t.conn.sent[:]
    for payload in (b'\x04', b'\x27\x01', b'\x3b\x01', b'\x21\x01', b'\x01\x50', b'\x10\x03'):
        with pytest.raises(PermissionError):
            s.session.request(payload)
    s.disconnect()
    assert t.conn.sent == before and t.conn.closed


def test_unsupported_pid_is_not_transmitted():
    t = FakeTransport([iso(0x41, 0x00, 0x00, 0x00, 0x00, 0x00)])
    s = service(t)
    s.connect()
    sample = s.read_parameters(['rpm'])[0]
    assert sample.value is None and 'support bitmap' in sample.error
    assert t.conn.sent == [bytes.fromhex('68 6A F1 01 00 C4')]
    s.disconnect()


def test_negative_response_raises():
    s = Iso9141ObdSession(FakeConnection([iso(0x7F, 0x01, 0x11)]))
    s.supported = {0x0C}
    with pytest.raises(NegativeResponse):
        s.request([1, 0x0C])


@pytest.mark.parametrize('reply', [b'', iso(0x41, 0x00), iso(0x41, 0x01, 0, 0, 0, 0),
                                   iso(0x7F, 0x01), iso(0x43, 0x01)])
def test_invalid_support_or_dtc_reply_is_refused(reply):
    t = FakeTransport([reply])
    s = service(t)
    with pytest.raises(ProtocolError):
        s.connect()
    assert t.conn.closed and not s.connected


def test_empty_dtc_response_is_counted():
    s = Iso9141ObdSession(FakeConnection([iso(0x43)]))
    assert s.read_stored_codes() == []


def test_vin_and_calibration_id_read():
    vin = b'1HGBH41JXMN109186'
    cal = b'CAL-0001        '
    t = FakeTransport([iso(0x41, 0x00, 0xFF, 0xFF, 0xFF, 0xFF),
                       iso(0x49, 0x00, 0x50, 0x00, 0x00, 0x00),
                       iso(0x49, 0x02, 0x01, *vin),
                       iso(0x49, 0x04, 0x01, *cal)])
    s = service(t)
    s.connect()
    identity = s.identify()
    assert identity.fields['Vehicle VIN (unverified OBD response)'] == vin.decode()
    assert 'CAL-0001' in identity.fields['Calibration IDs (unverified OBD response)']
    s.disconnect()


# ------------------------------------------------------- transport gating

@pytest.mark.parametrize('change', [dict(is_physical=False), dict(baud=9600),
                                    dict(keys=(0xEA, 0x8F)), dict(protocol='iso14230')])
def test_unvalidated_handshake_or_transport_is_refused(change):
    t = FakeTransport([], keys=change.get('keys', (0x08, 0x08)),
                      protocol=change.get('protocol', 'iso9141-2'))
    if 'is_physical' in change:
        t.is_physical = False
    if 'baud' in change:
        t.baud = change['baud']
    with pytest.raises((TransportUnavailable, ProtocolError)):
        service(t).connect()
    if not t.opened:
        return
    assert t.conn.closed and not service(t).connected


def test_non_read_only_mode_is_refused_before_open():
    t = FakeTransport([])
    with pytest.raises(TransportUnavailable):
        service(t, mode=Mode.SERVICE).connect()
    assert not t.opened


def test_wrong_transport_kind_is_refused_before_open():
    class CanNamed(FakeTransport):
        name = 'can'
    t = CanNamed([])
    with pytest.raises(TransportUnavailable):
        service(t).connect()
    assert not t.opened


def test_keyword_94_94_handshake_is_accepted():
    t = FakeTransport([iso(0x41, 0x00, 0xFF, 0xFF, 0xFF, 0xFF),
                       iso(0x41, 0x0C, 0x1F, 0xE0)], keys=(0x94, 0x94))
    s = service(t)
    result = s.connect()
    assert result.protocol == 'iso9141-2'
    assert result.key_bytes == (0x94, 0x94)
    assert s.read_parameters(['rpm'])[0].value == 2040  # 0x1FE0 * 0.25
    s.disconnect()
