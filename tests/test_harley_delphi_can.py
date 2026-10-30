"""Synthetic Harley Delphi CAN identity research; no physical validation."""
from __future__ import annotations

import pytest

from guzzionboard.catalog import load_catalog
from guzzionboard.diagnostics import DiagnosticsService
from guzzionboard.protocol.harley_delphi_can import HarleyDelphiCanSession
from guzzionboard.protocol.kwp2000 import ProtocolError
from guzzionboard.safety import Mode, SafetyGate
from guzzionboard.transports.base import Connection, InitResult, Transport, TransportUnavailable
from guzzionboard.workstation import Workstation


class FakeConnection(Connection):
    def __init__(self, replies): self.replies, self.sent, self.closed = list(replies), [], False
    @property
    def is_open(self): return not self.closed
    def write(self, data): self.sent.append(bytes(data))
    def read_frame(self, timeout): return self.replies.pop(0) if self.replies else b''
    def close(self): self.closed = True


class FakeCan(Transport):
    name, is_physical = 'can', True
    bitrate, tx_id, rx_id, padding = 500000, 0x7e0, 0x7e8, 0
    def __init__(self, replies): self.conn, self.opened = FakeConnection(replies), False
    def open(self): self.opened = True; return self.conn
    def initialize(self, conn, **kwargs): return InitResult(True, 'can', protocol='isotp', handshake_complete=True)


def service(t, mode=Mode.READ_ONLY):
    return DiagnosticsService(load_catalog().ecu('harley_delphi_can_uds'), t, SafetyGate(mode=mode))


def test_identity_probes_only_fixed_dids_without_safety_identity():
    t = FakeCan([bytes.fromhex('7e 00'), bytes.fromhex('7f 22 31'), b'',
                 bytes.fromhex('62 f1 f5 12 34'), bytes.fromhex('62 f1 f2 01 02 03 04'),
                 bytes.fromhex('7f 22 33')])
    s = service(t); s.connect(); identity = s.identify()
    assert identity.fields == {'Calibration-ID DID F1F5 (raw candidate)': '12 34',
                               'Checksum DID F1F2 (raw candidate)': '01 02 03 04'}
    assert identity.ecu_id == '' and not s.gate.state.identified and not s.gate.state.ecu_hardware
    assert t.conn.sent == [bytes.fromhex(x) for x in ('3e 00','22 f1 ea','22 f1 ed','22 f1 f5','22 f1 f2','22 f1 ef')]
    for payload in (bytes.fromhex(x) for x in ('10 03','27 01','23 00','34 00','35 b0 01 00 7d 80 00','36 01','14 ff ff ff','22 f1 90')):
        with pytest.raises(PermissionError): s.session.request(payload)
    assert len(t.conn.sent) == 6
    s.disconnect(); assert t.conn.closed


@pytest.mark.parametrize('reply', [b'', b'\x7e', b'\x7e\x80', b'\x7f\x22\x31', b'\x7f\x3e'])
def test_bad_tester_present_closes_transport(reply):
    t = FakeCan([reply]); s = service(t)
    with pytest.raises(ProtocolError): s.connect()
    assert t.conn.closed and not s.connected and t.conn.sent == [b'\x3e\x00']


def test_did_mismatch_fails_closed_and_clears_stale_evidence():
    t = FakeCan([b'\x7e\x00', b'\x62\xf1\xed\x01']); s = service(t); s.connect()
    s.gate.state.identified = True; s.gate.state.ecu_hardware = 'stale'
    with pytest.raises(ProtocolError, match='identifier or length'): s.identify()
    assert s.identity is None and not s.gate.state.identified and not s.gate.state.ecu_hardware
    s.disconnect()


def test_no_did_results_are_not_confirmed_identity():
    t = FakeCan([b'\x7e\x00'] + [b'\x7f\x22\x33'] * 5); s = service(t); s.connect()
    with pytest.raises(ProtocolError, match='require authentication'): s.identify()
    assert not s.gate.state.identified and s.identity is None
    s.disconnect()


@pytest.mark.parametrize('changes', [dict(bitrate=250000), dict(tx_id=0x7df), dict(rx_id=0x7e9), dict(padding=0xaa), dict(is_physical=False)])
def test_wrong_can_settings_refused_before_open(changes):
    t = FakeCan([])
    for key, value in changes.items(): setattr(t, key, value)
    with pytest.raises(TransportUnavailable): service(t).connect()
    assert not t.opened


def test_workstation_requires_ecu_only_read_only_and_explicit_device():
    w = Workstation(record=False)
    w.select(ecu='harley_delphi_can_uds', transport='can')
    with pytest.raises(TransportUnavailable, match='explicit CAN device'): w.connect(mode='read_only')
    w.select(ecu='harley_delphi_can_uds', transport='can', device='can0', can_tx_id='0x7df')
    with pytest.raises(TransportUnavailable, match='fixed 500'): w.connect(mode='read_only')
    w.select(ecu='harley_delphi_can_uds', transport='can', device='can0')
    with pytest.raises(TransportUnavailable): w.connect(mode='service')
    w.select(ecu='harley_delphi_can_uds', transport='simulator')
    with pytest.raises(TransportUnavailable): w.connect(mode='simulator')
    w.select(ecu='harley_delphi_can_uds', transport='can', device='PCAN_USBBUS1')
    transport = w._build_transport()
    assert (transport.interface, transport.channel, transport.padding) == ('pcan', 'PCAN_USBBUS1', 0)
    w.select(ecu='harley_delphi_can_uds', transport='can', device='can0')
    assert w._build_transport().interface == 'socketcan'


def test_live_raw_dids_are_unscaled_and_do_not_authorize_identity():
    t = FakeCan([bytes.fromhex('7e 00'), bytes.fromhex('62 01 00 12 34'),
                 bytes.fromhex('62 01 01 aa'), bytes.fromhex('62 01 02 01 02 03'),
                 bytes.fromhex('62 01 03 07')])
    s = service(t); s.connect()
    samples = s.read_parameters(['raw_did_0100', 'raw_did_0101', 'raw_did_0102', 'raw_did_0103'])
    assert [sample.value for sample in samples] == [0x1234, 0xaa, 0x010203, 7]
    assert [sample.raw.hex() for sample in samples] == ['1234','aa','010203','07']
    assert all(sample.unit == 'raw' for sample in samples)
    assert not s.gate.state.identified and not s.gate.state.ecu_hardware
    assert t.conn.sent == [bytes.fromhex(x) for x in ('3e 00', '22 01 00', '22 01 01', '22 01 02', '22 01 03')]
    s.disconnect()


def test_live_raw_did_refuses_mismatched_length_and_unauthorized_id():
    conn = FakeConnection([bytes.fromhex('62 01 00 12')]); s = HarleyDelphiCanSession(conn)
    with pytest.raises(ProtocolError, match='source capture'): s.read_data_by_local_id(0x0100)
    with pytest.raises(PermissionError): s.read_data_by_local_id(0x0104)
    assert conn.sent == [bytes.fromhex('22 01 00')]


def test_virtual_can_isotp_live_multiframe_candidate_identity():
    import threading
    import uuid
    import can
    from guzzionboard.protocol.isotp import segment
    from guzzionboard.transports.can import CanTransport
    channel = 'harley-delphi-' + uuid.uuid4().hex
    ecu = can.Bus(interface='virtual', channel=channel)
    transport = CanTransport(channel=channel, interface='virtual', bitrate=500000, tx_id=0x7e0, rx_id=0x7e8, padding=0)
    exchanges = [(b'\x3e\x00', b'\x7e\x00'),
                 (bytes.fromhex('22 f1 ea'), b'\x62\xf1\xeaTEST-PART-123'),
                 (bytes.fromhex('22 f1 ed'), bytes.fromhex('7f 22 31')),
                 (bytes.fromhex('22 f1 f5'), bytes.fromhex('62 f1 f5 12 34')),
                 (bytes.fromhex('22 f1 f2'), bytes.fromhex('62 f1 f2 00 00 00 01')),
                 (bytes.fromhex('22 f1 ef'), bytes.fromhex('7f 22 31')),
                 (bytes.fromhex('22 01 00'), bytes.fromhex('62 01 00 12 34'))]
    failures = []
    def respond():
        try:
            for request, reply in exchanges:
                message = ecu.recv(2)
                assert message and message.arbitration_id == 0x7e0
                assert bytes(message.data)[1:1+len(request)] == request
                frames = segment(reply, padding=0)
                ecu.send(can.Message(arbitration_id=0x7e8, is_extended_id=False, data=frames[0]))
                if len(frames) > 1:
                    flow = ecu.recv(2)
                    assert flow and flow.arbitration_id == 0x7e0 and bytes(flow.data) == bytes.fromhex('30 00 00 00 00 00 00 00')
                    for frame in frames[1:]: ecu.send(can.Message(arbitration_id=0x7e8, is_extended_id=False, data=frame))
        except BaseException as exc: failures.append(exc)
    thread = threading.Thread(target=respond, daemon=True); thread.start()
    s = service(transport)
    try:
        s.connect()
        fields = s.identify().fields
        assert fields['Part-number DID F1EA (raw candidate)'] == b'TEST-PART-123'.hex(' ').upper()
        assert s.read_parameters(['raw_did_0100'])[0].value == 0x1234
        assert not s.gate.state.identified
    finally:
        s.disconnect(); thread.join(3); ecu.shutdown()
    assert not thread.is_alive() and not failures
