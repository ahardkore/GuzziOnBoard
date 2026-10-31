"""JetDrive tests use synthetic packets and sockets, not a physical dyno."""
import socket
import struct
from types import SimpleNamespace

import pytest
from guzzionboard import jetdrive as jd
from guzzionboard.server import Api
from guzzionboard.workstation import Workstation
from guzzionboard.transports.base import TransportError


def wire(key, payload, host=0x1234, seq=1):
    return jd.HEADER.pack(key, len(payload), host, seq, 0xffff) + payload


def info():
    return wire(1, b'TestProvider'.ljust(50, b'\0') + jd.INFO_BLOCK.pack(1, 0, b'RPM', 8))


def values():
    return wire(2, jd.VALUE_BLOCK.pack(1, 1000, 1600.0) + jd.VALUE_BLOCK.pack(2, 1001, 13.5))


def test_synthetic_source_format_and_strict_rejections():
    i = jd.decode(info()); v = jd.decode(values())
    assert i['provider'] == 0x1234 and i['name'] == 'TestProvider'
    assert i['channels'] == [{'id': 1, 'vendor': 0, 'name': 'RPM', 'unit_code': 8}]
    assert v['samples'] == [{'id': 1, 'timestamp_ms': 1000, 'value': 1600.0}, {'id': 2, 'timestamp_ms': 1001, 'value': 13.5}]
    assert jd.decode(values()[:-1]) is None
    assert jd.decode(values() + b'\0') is None
    assert jd.decode(wire(2, b'\0' * 11)) is None
    assert jd.decode(wire(1, b'\0' * 51)) is None
    assert jd.decode(wire(2, jd.VALUE_BLOCK.pack(3, 1, float('nan'))))['samples'] == []
    assert jd.decode(wire(3, b''))['key'] == 3
    assert jd.decode(wire(0x57, b'')) is None


class Sock:
    def __init__(self, packets=(), error=None): self.packets = list(packets); self.closed = False; self.sent = []; self.error = error
    def setsockopt(self, *args): pass
    def bind(self, address): self.address = address
    def settimeout(self, seconds): pass
    def sendto(self, data, addr): self.sent.append((data, addr)); return len(data)
    def recvfrom(self, size):
        if self.error: raise self.error
        if self.packets: return self.packets.pop(0)
        raise socket.timeout()
    def close(self): self.closed = True


def setup(monkeypatch, sock):
    monkeypatch.setattr(jd.socket, 'socket', lambda *args: sock)
    ticks = iter(i * 0.25 for i in range(1000))
    monkeypatch.setattr(jd.time, 'monotonic', lambda: next(ticks))


def test_passive_window_scopes_metadata_by_source_and_clears_it(monkeypatch):
    sock = Sock([(info(), ('192.168.0.2', 22344)), (values(), ('192.168.0.2', 22344)),
                 (values(), ('192.168.0.3', 22344)), (wire(3, b''), ('192.168.0.2', 22344)),
                 (values(), ('192.168.0.2', 22344))]); setup(monkeypatch, sock)
    result = jd.observe('224.0.2.10', '0.0.0.0')
    assert len(result['samples']) == 6 and result['samples'][0]['channel_name'] == 'RPM'
    assert result['samples'][2]['channel_name'] == '' and result['samples'][4]['channel_name'] == ''
    assert not result['metadata_requested'] and sock.sent == [] and sock.closed


def test_explicit_metadata_request_and_errors(monkeypatch):
    sock = Sock(); setup(monkeypatch, sock)
    result = jd.observe('239.255.60.60', '192.168.1.2', True)
    assert result['metadata_requested'] and len(sock.sent) == 1
    data, dest = sock.sent[0]; key, size, host, seq, target = jd.HEADER.unpack(data)
    assert (key, size, seq, target, dest) == (6, 0, 1, 0xffff, ('239.255.60.60', 22344))
    assert 1 <= host <= 65534 and sock.closed
    sock = Sock(error=OSError('receive failed')); setup(monkeypatch, sock)
    with pytest.raises(TransportError): jd.observe('224.0.2.10', '0.0.0.0')
    assert sock.closed


def test_validations_precede_opening_socket(monkeypatch):
    sock = Sock(); calls = []; monkeypatch.setattr(jd.socket, 'socket', lambda *x: calls.append(x) or sock)
    for args in [('8.8.8.8','0.0.0.0'), ('224.0.2.10','example.com'), ('224.0.2.10','224.1.2.3'), ('224.0.2.10','192.168.1.1','yes')]:
        with pytest.raises(ValueError): jd.observe(*args)
    assert not calls


def test_packet_and_sample_limits(monkeypatch):
    sock = Sock([(values(), ('10.0.0.2', 123))] * 20); setup(monkeypatch, sock)
    monkeypatch.setattr(jd, 'MAX_SAMPLES', 3)
    result = jd.observe('224.0.2.10', '0.0.0.0')
    assert len(result['samples']) == 3 and result['limit_reached'] and result['dropped'] == 1 and sock.closed


def test_api_confirmation_lock_and_release(monkeypatch):
    api = Api(Workstation(record=False)); calls = []
    monkeypatch.setattr(jd, 'observe', lambda *args: calls.append(args) or {'samples': []})
    assert api.post_tools_jetdrive({})[0] == 400 and not calls
    assert api.post_tools_jetdrive({'confirm': True, 'group': '224.0.2.10', 'interface': '0.0.0.0'})[0] == 200
    assert calls == [('224.0.2.10', '0.0.0.0', False)]
    api._jetdrive_lock.acquire()
    try: assert api.post_tools_jetdrive({'confirm': True})[0] == 409
    finally: api._jetdrive_lock.release()
