"""Synthetic generic OBD CAN tests; no claim of motorcycle compatibility."""
import pytest

from guzzionboard.catalog import load_catalog
from guzzionboard.diagnostics import DiagnosticsService
from guzzionboard.protocol.kwp2000 import ProtocolError
from guzzionboard.protocol.obd_can import ObdCanSession
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
    return DiagnosticsService(load_catalog().ecu('generic_obd_can_11bit'), transport, SafetyGate(mode=mode))


def test_live_and_iso15765_stored_faults_without_other_requests():
    t = FakeTransport([bytes.fromhex('41 00 FF FF FF FF'), bytes.fromhex('41 0C 3E 80'),
                       bytes.fromhex('41 05 5A'), bytes.fromhex('43 02 01 22 41 11')])
    s = service(t); s.connect()
    samples = s.read_parameters(['rpm', 'coolant'])
    assert [(p.value, p.raw) for p in samples] == [(4000, b'\x3e\x80'), (50, b'\x5a')]
    assert [d['code'] for d in s.read_dtcs()['dtcs']] == ['P0122', 'C0111']
    assert t.conn.sent == [b'\x01\x00', b'\x01\x0c', b'\x01\x05', b'\x03']
    before = t.conn.sent[:]
    for payload in (b'\x04', b'\x27\x01', b'\x23\x00', b'\x01\x43', b'\x10\x03'):
        with pytest.raises(PermissionError): s.session.request(payload)
    s.disconnect()
    assert t.conn.sent == before and t.conn.closed


def test_unsupported_pid_is_not_transmitted():
    t = FakeTransport([bytes.fromhex('41 00 00 00 00 00')]); s = service(t); s.connect()
    sample = s.read_parameters(['rpm'])[0]
    assert sample.value is None and 'support bitmap' in sample.error
    assert t.conn.sent == [b'\x01\x00']
    s.disconnect()


@pytest.mark.parametrize('reply', [b'', b'\x41\x00', b'\x41\x01\x00\x00\x00\x00', b'\x7f\x01', b'\x7f\x03\x11'])
def test_invalid_support_reply_closes_connection(reply):
    t = FakeTransport([reply]); s = service(t)
    with pytest.raises(ProtocolError): s.connect()
    assert t.conn.closed and not s.connected


@pytest.mark.parametrize('reply', [b'\x43', b'\x43\x01\x01', b'\x43\x00\x00', b'\x43\x01\x00\x00'])
def test_invalid_or_ambiguous_dtc_response_is_not_a_clean_bill(reply):
    s = ObdCanSession(FakeConnection([reply])); s.supported = set()
    with pytest.raises(ProtocolError): s.read_stored_codes()


def test_empty_dtc_response_is_counted():
    assert ObdCanSession(FakeConnection([b'\x43\x00'])).read_stored_codes() == []


@pytest.mark.parametrize('change', [dict(bitrate=250000), dict(tx_id=0x7df), dict(rx_id=0x7e9), dict(padding=0xaa), dict(is_physical=False)])
def test_invalid_transport_refused_before_open(change):
    t = FakeTransport([])
    for key, value in change.items(): setattr(t, key, value)
    with pytest.raises(TransportUnavailable): service(t).connect()
    assert not t.opened


def test_profile_only_and_mode_boundaries():
    t = FakeTransport([])
    with pytest.raises(TransportUnavailable): service(t, Mode.SERVICE).connect()
    assert not t.opened
    ws = Workstation(record=False)
    ws.select(ecu='generic_obd_can_11bit', transport='simulator')
    with pytest.raises(TransportUnavailable): ws.connect()
    ws.select(ecu='generic_obd_can_11bit', transport='can', can_tx_id='0x7DF', can_rx_id='0x7E8')
    with pytest.raises(TransportUnavailable): ws.connect(mode='read_only')


def test_end_to_end_virtual_can_isotp_multiframe():
    import threading
    import uuid
    import can
    from guzzionboard.protocol.isotp import segment
    from guzzionboard.transports.can import CanTransport
    channel = 'obd-test-' + uuid.uuid4().hex
    ecu = can.Bus(interface='virtual', channel=channel)
    transport = CanTransport(channel=channel, interface='virtual', bitrate=500000, tx_id=0x7e0, rx_id=0x7e8, padding=0)
    failures = []
    def respond():
        try:
            for request, reply in ((b'\x01\x00', bytes.fromhex('41 00 FF FF FF FF')),
                                   (b'\x01\x0c', bytes.fromhex('41 0C 3E 80')),
                                   (b'\x03', bytes.fromhex('43 03 01 22 41 11 02 34')),
                                   (b'\x09\x00', bytes.fromhex('49 00 50 00 00 00')),
                                   (b'\x09\x02', b'\x49\x02\x01' + b'1M8GDM9AXKP042788'),
                                   (b'\x09\x04', b'\x49\x04\x01' + b'312J6000'.ljust(16, b'\x00'))):
                msg = ecu.recv(2)
                assert msg and msg.arbitration_id == 0x7e0 and bytes(msg.data)[1:1+len(request)] == request
                frames = segment(reply, padding=0)
                ecu.send(can.Message(arbitration_id=0x7e8, is_extended_id=False, data=frames[0]))
                if len(frames) > 1:
                    flow = ecu.recv(2)
                    assert flow and flow.arbitration_id == 0x7e0 and bytes(flow.data) == bytes.fromhex('30 00 00 00 00 00 00 00')
                    for frame in frames[1:]:
                        ecu.send(can.Message(arbitration_id=0x7e8, is_extended_id=False, data=frame))
        except BaseException as exc:
            failures.append(exc)
    thread = threading.Thread(target=respond, daemon=True); thread.start()
    s = service(transport)
    try:
        s.connect()
        assert s.read_parameters(['rpm'])[0].value == 4000
        assert [d['code'] for d in s.read_dtcs()['dtcs']] == ['P0122', 'C0111', 'P0234']
        identity = s.identify()
        assert identity.fields['Vehicle VIN (unverified OBD response)'] == '1M8GDM9AXKP042788'
        assert identity.fields['Calibration IDs (unverified OBD response)'] == '312J6000'
        assert not s.gate.state.identified
    finally:
        s.disconnect(); thread.join(3); ecu.shutdown()
    assert not thread.is_alive() and not failures


def test_workstation_opens_opt_in_profile_and_keeps_memory_locked(monkeypatch):
    ws = Workstation(record=False)
    ws.select(ecu='generic_obd_can_11bit', transport='can', device='can0')
    t = FakeTransport([bytes.fromhex('41 00 FF FF FF FF'), bytes.fromhex('41 0C 3E 80')])
    monkeypatch.setattr(ws, '_build_transport', lambda: t)
    status = ws.connect(mode='read_only')
    assert status['connected']
    assert ws.require_service().read_parameters(['rpm'])[0].value == 4000
    assert not ws.require_service().profile.memory['read_supported']
    assert not ws.require_service().check_clear_dtcs().allowed
    ws.disconnect()


def test_mode09_optional_vin_is_not_ecu_identity_or_write_evidence():
    t = FakeTransport([bytes.fromhex('41 00 FF FF FF FF'), bytes.fromhex('49 00 40 00 00 00'),
                       b'\x49\x02\x01' + b'1M8GDM9AXKP042788'])
    s = service(t); s.connect()
    identity = s.identify()
    assert identity.fields['Vehicle VIN (unverified OBD response)'] == '1M8GDM9AXKP042788'
    assert identity.ecu_id == '' and not s.gate.state.identified and not s.gate.state.ecu_hardware
    assert t.conn.sent == [b'\x01\x00', b'\x09\x00', b'\x09\x02']
    s.disconnect()


def test_mode09_unsupported_and_malformed_vin_fail_closed():
    s = ObdCanSession(FakeConnection([bytes.fromhex('49 00 00 00 00 00')]))
    with pytest.raises(ProtocolError, match='neither VIN nor calibration ID'): s.read_vehicle_information()
    assert s.connection.sent == [b'\x09\x00']
    for reply in (b'\x49\x02\x01SHORT', b'\x49\x02\x02' + b'1M8GDM9AXKP042788',
                  b'\x49\x02\x01' + b'1M8GDM9AXKP04278I'):
        s = ObdCanSession(FakeConnection([bytes.fromhex('49 00 40 00 00 00'), reply]))
        with pytest.raises(ProtocolError): s.read_vehicle_information()
    s = ObdCanSession(FakeConnection([]))
    with pytest.raises(PermissionError): s.request(b'\x09\x06')


def test_failed_mode09_reidentification_clears_stale_state():
    t = FakeTransport([bytes.fromhex('41 00 FF FF FF FF'), bytes.fromhex('49 00 00 00 00 00')])
    s = service(t); s.connect()
    s.gate.state.identified = True
    s.gate.state.ecu_hardware = 'stale'
    with pytest.raises(ProtocolError, match='neither VIN nor calibration ID'): s.identify()
    assert s.identity is None and not s.gate.state.identified and not s.gate.state.ecu_hardware
    s.disconnect()


def test_mode09_calibration_ids_without_vin_and_invalid_replies():
    reply = b'\x49\x04\x02' + b'312J6000'.ljust(16, b'\x00') + b'A4701000'.ljust(16, b'\x00')
    s = ObdCanSession(FakeConnection([bytes.fromhex('49 00 10 00 00 00'), reply]))
    fields, raw = s.read_vehicle_information()
    assert fields['Calibration IDs (unverified OBD response)'] == '312J6000, A4701000'
    assert len(raw) == 32 and s.connection.sent == [b'\x09\x00', b'\x09\x04']
    for bad in (b'\x49\x04\x00', b'\x49\x04\x05', b'\x49\x04\x01short',
                b'\x49\x04\x01' + bytes(16), b'\x49\x04\x01' + b'A\x01'.ljust(16, b'\x00')):
        s = ObdCanSession(FakeConnection([bytes.fromhex('49 00 10 00 00 00'), bad]))
        with pytest.raises(ProtocolError): s.read_vehicle_information()


def test_extended_standard_pids_query_only_advertised_bitmap_pages():
    t = FakeTransport([bytes.fromhex('41 00 00 00 00 03'), # 1F + 20
                       bytes.fromhex('41 1F 01 2C'),
                       bytes.fromhex('41 20 00 02 20 01'), # 2F, 33, 40
                       bytes.fromhex('41 2F 80'), bytes.fromhex('41 33 64'),
                       bytes.fromhex('41 40 40 00 00 14'), # 42, 5C, 5E
                       bytes.fromhex('41 42 30 39'), bytes.fromhex('41 5C 5A'),
                       bytes.fromhex('41 5E 00 64')])
    s = service(t); s.connect()
    data = s.read_parameters(['engine_runtime', 'fuel_level', 'barometric', 'control_voltage', 'oil_temp', 'fuel_rate'])
    assert [sample.value for sample in data] == [300, 50.2, 100, 12.35, 50, 5]
    assert t.conn.sent == [bytes.fromhex(x) for x in ('01 00','01 1F','01 20','01 2F','01 33','01 40','01 42','01 5C','01 5E')]
    s.disconnect()


def test_extended_pids_never_request_unadvertised_page_or_pid():
    t = FakeTransport([bytes.fromhex('41 00 00 00 00 00')]); s = service(t); s.connect()
    samples = s.read_parameters(['fuel_level', 'oil_temp'])
    assert all(sample.value is None for sample in samples)
    assert t.conn.sent == [bytes.fromhex('01 00')]
    s.disconnect()
    t = FakeTransport([bytes.fromhex('41 00 00 00 00 01'), bytes.fromhex('41 20 00 02 00 00')]); s = service(t); s.connect()
    samples = s.read_parameters(['oil_temp', 'barometric'])
    assert all(sample.value is None for sample in samples)
    assert t.conn.sent == [bytes.fromhex('01 00'), bytes.fromhex('01 20')]
    s.disconnect()


def test_malformed_extended_support_bitmap_does_not_authorize_or_cache():
    t = FakeTransport([bytes.fromhex('41 00 00 00 00 01'), bytes.fromhex('41 20 00')])
    s = service(t); s.connect()
    sample = s.read_parameters(['fuel_level'])[0]
    assert sample.value is None and 'length mismatch' in sample.error
    assert t.conn.sent == [bytes.fromhex('01 00'), bytes.fromhex('01 20')]
    assert 0x20 not in s.session.support_pages
    s.disconnect()
