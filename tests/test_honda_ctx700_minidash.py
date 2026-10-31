"""Synthetic CTX700 table tests, not a test on a physical motorcycle."""
import pytest
from guzzionboard.catalog import load_catalog
from guzzionboard.diagnostics import DiagnosticsService
from guzzionboard.protocol.honda_cbr600rr import HondaCTX700Session
from guzzionboard.protocol.kwp2000 import ProtocolError
from guzzionboard.safety import Mode, SafetyGate
from guzzionboard.transports.base import TransportUnavailable
from guzzionboard.workstation import Workstation
from test_honda_cb500f_dash import FakeConnection, FakeTransport


def frame(table, data):
    body = bytes([2, len(data) + 5, 0x71, table]) + data
    return body + bytes([-sum(body) & 255])


def test_synthetic_live_table_and_status(monkeypatch):
    monkeypatch.setattr(DiagnosticsService, '_start_keepalive', lambda _: None)
    data = bytes([0x06,0xa2,0x1c,0x20,0xb8,0x50,0xb7,0x33,0x72,0x4c,0xff,0xff,0x8b,42,0x04,0x35,0,0,0,0])
    status = bytes([1,0,0,0,1,0])
    t = FakeTransport(frame(0x11, data) + frame(0xd1, status))
    s = DiagnosticsService(load_catalog().ecu('honda_ctx700_minidash'), t, SafetyGate(mode=Mode.READ_ONLY))
    s.connect()
    samples = s.read_parameters(['rpm','tps_ctx','coolant','airtemp','map','battery','speed','injector_raw','gear_status','engine_status'])
    assert [x.value for x in samples] == [1698,2.0,40,11,76,13.9,42,1077,1,1]
    assert t.conn.sent == [bytes.fromhex('72 05 71 11 07'),bytes.fromhex('72 05 71 d1 47')]
    assert not s.gate.state.identified and s.gate.state.battery_v is None
    s.disconnect()


def test_bad_lengths_and_unlisted_commands():
    c = FakeConnection(frame(0x11, bytes(19)))
    s = HondaCTX700Session(c)
    with pytest.raises(ProtocolError): s.read_snapshot()
    for payload in (b'\x71\x00', b'\x71\x10', b'\x27', b'\x23', b'\x14'):
        with pytest.raises(PermissionError): s.request(payload)
    assert len(c.sent) == 1


def test_ctx700_is_explicit_ecu_only_no_programming():
    p = load_catalog().ecu('honda_ctx700_minidash')
    assert p.capabilities == ('live',) and not p.memory['read_supported'] and not p.memory['write_supported']
    ws = Workstation(record=False)
    ws.select(ecu=p.id, transport='kline')
    with pytest.raises(TransportUnavailable, match='read-only'): ws.connect(mode='service')
    ws.select(ecu=p.id, transport='simulator')
    with pytest.raises(TransportUnavailable): ws.connect()
