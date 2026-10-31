"""Synthetic serial fixtures only; no Buell hardware was used."""
import sys
from types import SimpleNamespace
from functools import reduce
from operator import xor

import pytest
from guzzionboard import buell_ddfi as buell
from guzzionboard.server import Api
from guzzionboard.workstation import Workstation
from guzzionboard.transports.base import TransportError

VERSION = 'BUEIB310 12-11-03'  # public EcmDroid unit-test example


def reply(data, ecm=0x42, status=6):
    body = bytes((ecm, 0, len(data) + 2, 0xff, 2, status)) + data + b'\x03'
    return b'\x01' + body + bytes((reduce(xor, body, 0),))


class FakeSerial:
    def __init__(self, responses): self.responses, self.pending, self.sent, self.closed = list(responses), bytearray(), [], False
    def reset_input_buffer(self): pass
    def write(self, data):
        self.sent.append(data)
        if self.responses: self.pending.extend(self.responses.pop(0))
        return len(data)
    def read(self, count):
        n = min(count, 3, len(self.pending))
        data = bytes(self.pending[:n]); del self.pending[:n]; return data
    def close(self): self.closed = True


def install(monkeypatch, conn):
    calls = []
    def open_port(**kwargs): calls.append(kwargs); return conn
    monkeypatch.setattr(buell.sys, 'platform', 'linux')
    monkeypatch.setitem(sys.modules, 'serial', SimpleNamespace(Serial=open_port, SerialException=OSError))
    return calls


def test_public_source_request_vectors_and_limits():
    assert buell._request(0x42, b'V').hex() == '01004202ff025603e8'
    assert buell._request(0x42, b'C').hex() == '01004202ff024303fd'
    assert buell._request(0x42, bytes([0x52, 0, 1, 16])).hex() == '01004205ff025200011003fa'
    for payload in [b'W', bytes([0x57, 0, 0x20, 1]), bytes([0x52, 0, 0x20, 1]), bytes([0x52, 250, 1, 16]), bytes([0x52, 0, 1, 17])]:
        with pytest.raises(ValueError): buell._request(0x42, payload)


def test_identification_and_chunked_page_read(monkeypatch):
    conn = FakeSerial([reply(VERSION.encode()), reply(bytes(range(16))), reply(bytes(range(16, 20)))])
    calls = install(monkeypatch, conn)
    result = buell.run('/dev/ttyUSB0', 'stock', 'read', VERSION, 2, 30, 20)
    assert result['data_hex'] == bytes(range(20)).hex().upper()
    assert result['page'] == 2 and result['offset'] == 30 and result['synthetic_tested']
    assert calls[0]['baudrate'] == 9600 and calls[0]['exclusive'] is True
    assert conn.sent == [buell._request(0x42, b'V'), buell._request(0x42, bytes([0x52,30,2,16])), buell._request(0x42, bytes([0x52,46,2,4]))]
    assert conn.closed


def test_factory_race_and_runtime(monkeypatch):
    conn = FakeSerial([reply(VERSION.encode(), ecm=0x55), reply(b'\x11\x22', ecm=0x55)])
    calls = install(monkeypatch, conn)
    result = buell.run('/dev/rfcomm0', 'factory_race', 'runtime', VERSION)
    assert result['data_hex'] == '1122' and result['kind'] == 'runtime'
    assert calls[0]['baudrate'] == 19200
    assert conn.sent == [buell._request(0x55, b'V'), buell._request(0x55, b'C')]
    assert conn.closed


def test_mismatch_and_invalid_responses_abort(monkeypatch):
    conn = FakeSerial([reply(VERSION.encode())]); install(monkeypatch, conn)
    with pytest.raises(TransportError, match='version differs'):
        buell.run('/dev/ttyUSB0', 'stock', 'read', 'BUEIA', 1, 0, 1)
    assert len(conn.sent) == 1 and conn.closed
    good = reply(VERSION.encode())
    bad_checksum = good[:-1] + bytes([good[-1] ^ 1])
    for invalid in [bad_checksum, reply(VERSION.encode(), ecm=0x55), reply(b'', status=0x15), b'\x01\x42\x00\x00\xff\x02']:
        conn = FakeSerial([invalid]); install(monkeypatch, conn)
        with pytest.raises(TransportError): buell.run('/dev/ttyUSB0', 'stock', 'identify')
        assert conn.closed
    conn = FakeSerial([good, reply(b'\x01')]); install(monkeypatch, conn)
    with pytest.raises(TransportError, match='length mismatch'):
        buell.run('/dev/ttyUSB0', 'stock', 'read', VERSION, 1, 0, 2)
    assert conn.closed


def test_invalid_inputs_never_open(monkeypatch):
    conn = FakeSerial([]); calls = install(monkeypatch, conn)
    for args in [('/dev/ttyS0', 'stock', 'identify'), ('/dev/ttyUSB0', 'other', 'identify'), ('/dev/ttyUSB0', 'stock', 'read', VERSION, 32, 0, 1), ('/dev/ttyUSB0', 'stock', 'read', VERSION, 0, 0, 1), ('/dev/ttyUSB0', 'stock', 'read', VERSION, 1, 250, 10), ('/dev/ttyUSB0', 'stock', 'read', VERSION, 1, 0, True), ('/dev/ttyUSB0', 'stock', 'runtime')]:
        with pytest.raises(ValueError): buell.run(*args)
    assert calls == []


def test_api_confirmation_and_lock(monkeypatch):
    api = Api(Workstation(record=False)); called = []
    monkeypatch.setattr(buell, 'run', lambda *args: called.append(args) or {'version': VERSION})
    assert api.post_tools_buell_ddfi({'action': 'identify'})[0] == 400
    assert not called
    assert api.post_tools_buell_ddfi({'action': 'identify', 'mode': 'stock', 'port': '/dev/ttyUSB0', 'confirm': True})[0] == 200
    api._buell_lock.acquire()
    try: assert api.post_tools_buell_ddfi({'confirm': True})[0] == 409
    finally: api._buell_lock.release()


def test_bueia_runtime_adx_offsets_are_exact_and_scoped(monkeypatch):
    # Build a fully framed, entirely synthetic 100-byte response.
    data = bytearray(91)
    def field(offset, value): data[offset - 7:offset - 5] = value.to_bytes(2, 'little')
    field(0x0b, 2500); data[0x1b - 7] = 128
    field(0x1c, 1250); field(0x1e, 1250); field(0x20, 650)
    conn = FakeSerial([reply(b'BUEIA123'), reply(bytes(data))]); install(monkeypatch, conn)
    result = buell.run('/dev/ttyUSB0', 'stock', 'runtime', 'BUEIA123')
    assert result['bueia_candidates'] == {'rpm': 2500, 'throttle_percent': 50.196, 'battery_volts': 12.5, 'engine_temp_c': 85.0, 'air_temp_c': 25.0}
    assert buell._bueia_runtime('BUEIB310 12-11-03', bytes(data)) is None
    assert buell._bueia_runtime('BUEIA123', bytes(data[:-1])) is None
