"""Synthetic tests only: no aftermarket ECU or motorcycle was connected."""
import struct
import sys
from types import SimpleNamespace
import zlib

import pytest

from guzzionboard import rusefi_read as mod
from guzzionboard.server import Api
from guzzionboard.workstation import Workstation
from guzzionboard.transports.base import TransportError

SIGNATURE = 'rusEFI synthetic.test.board.1234'


def response(payload):
    # Independent synthetic emulator: response status is part of the CRC.
    payload = b'\x00' + payload
    return len(payload).to_bytes(2, 'big') + payload + zlib.crc32(payload).to_bytes(4, 'big')


class Serial:
    def __init__(self, responses):
        self.replies = list(responses)
        self.pending = bytearray()
        self.sent = []
        self.closed = False
    def reset_input_buffer(self): pass
    def write(self, data):
        self.sent.append(data)
        if self.replies:
            self.pending.extend(self.replies.pop(0))
        return len(data)
    def read(self, count):
        # Fragment every packet to exercise partial reads.
        n = min(count, 3, len(self.pending))
        result = bytes(self.pending[:n])
        del self.pending[:n]
        return result
    def close(self): self.closed = True


def install(monkeypatch, conn):
    calls = []
    def open_port(**kwargs):
        calls.append(kwargs)
        return conn
    monkeypatch.setattr(mod.sys, 'platform', 'linux')
    monkeypatch.setitem(sys.modules, 'serial', SimpleNamespace(Serial=open_port, SerialException=OSError))
    return calls


def payload(frame):
    size = int.from_bytes(frame[:2], 'big')
    assert len(frame) == size + 6
    assert int.from_bytes(frame[-4:], 'big') == zlib.crc32(frame[2:-4])
    return frame[2:-4]


def test_signature_and_single_page_read_wire_format(monkeypatch):
    conn = Serial([response(SIGNATURE.encode() + b'\0'), response(b'\x01\x02\x03')])
    calls = install(monkeypatch, conn)
    result = mod.run('/dev/ttyACM0', 115200, SIGNATURE, 2, 258, 3)
    assert result == {'signature': SIGNATURE, 'synthetic_tested': True, 'kind': 'page', 'page': 2, 'offset': 258, 'length': 3, 'data_hex': '010203'}
    assert [payload(frame) for frame in conn.sent] == [b'S', b'R\x02\x00\x02\x01\x03\x00']
    assert calls[0]['exclusive'] is True and calls[0]['baudrate'] == 115200
    assert conn.closed


def test_identify_and_mismatch_never_read(monkeypatch):
    conn = Serial([response(SIGNATURE.encode() + b'\0')])
    install(monkeypatch, conn)
    assert mod.run('/dev/ttyUSB0', 115200)['signature'] == SIGNATURE
    assert [payload(x) for x in conn.sent] == [b'S'] and conn.closed
    conn = Serial([response(SIGNATURE.encode() + b'\0')]); install(monkeypatch, conn)
    with pytest.raises(TransportError, match='does not exactly match'):
        mod.run('/dev/ttyUSB0', 115200, 'rusEFI wrong', 0, 0, 3)
    assert [payload(x) for x in conn.sent] == [b'S'] and conn.closed


def test_protocol_errors_abort_and_close(monkeypatch):
    valid = response(SIGNATURE.encode() + b'\0')
    for bad in [valid[:-1] + bytes([valid[-1] ^ 1]), b'\x02\x01', response(b'not-rusefi\0'), response(b'rusEFI malformed')]:
        conn = Serial([bad]); install(monkeypatch, conn)
        with pytest.raises(TransportError): mod.run('/dev/ttyACM0', 115200)
        assert conn.closed and len(conn.sent) == 1
    conn = Serial([valid, response(b'\x01')]); install(monkeypatch, conn)
    with pytest.raises(TransportError, match='length'): mod.run('/dev/ttyACM0', 115200, SIGNATURE, 0, 0, 3)
    assert conn.closed


def test_invalid_input_never_opens_serial(monkeypatch):
    conn = Serial([]); calls = install(monkeypatch, conn)
    for args in [('/dev/ttyS0', 115200), ('/dev/ttyUSB0', True), ('/dev/ttyUSB0', 115200, SIGNATURE, 0, 65535, 2), ('/dev/ttyUSB0', 115200, SIGNATURE, 0, 0, 257), ('/dev/ttyUSB0', 115200, SIGNATURE, False, 0, 1), ('/dev/ttyUSB0', 115200, '', 0, 0, 1)]:
        with pytest.raises(ValueError): mod.run(*args)
    assert calls == []


def test_api_confirmation_concurrency_and_no_missing_signature(monkeypatch):
    api = Api(Workstation(record=False)); called = []
    monkeypatch.setattr(mod, 'run', lambda *args: called.append(args) or {'signature': SIGNATURE})
    assert api.post_tools_rusefi_read({'action': 'identify'})[0] == 400
    assert api.post_tools_rusefi_read({'action': 'read', 'confirm': True})[0] == 400
    assert called == []
    assert api.post_tools_rusefi_read({'action': 'identify', 'confirm': True, 'port': '/dev/ttyACM0', 'baud': 115200})[0] == 200
    api._rusefi_lock.acquire()
    try: assert api.post_tools_rusefi_read({'action': 'identify', 'confirm': True})[0] == 409
    finally: api._rusefi_lock.release()


def test_live_output_snapshot_uses_only_requested_range(monkeypatch):
    conn = Serial([response(SIGNATURE.encode() + b'\0'), response(b'\x12\x34')]); install(monkeypatch, conn)
    result = mod.run('/dev/ttyACM0', 115200, SIGNATURE, 0, 258, 2, kind='outputs')
    assert result['kind'] == 'outputs' and result['data_hex'] == '1234' and 'page' not in result
    assert [payload(frame) for frame in conn.sent] == [b'S', b'O\x02\x01\x02\x00']
    assert conn.closed


def test_fixed_framing_vector_and_transport_failures(monkeypatch):
    assert mod.packet(b'S').hex() == '0001532060efc3'
    conn = Serial([]); install(monkeypatch, conn)
    conn.write = lambda data: len(data) - 1
    with pytest.raises(TransportError, match='Incomplete serial write'):
        mod.run('/dev/ttyACM0', 115200)
    assert conn.closed
    valid = response(SIGNATURE.encode() + b'\0')
    bad_response = bytearray(response(b'\x12\x34'))
    bad_response[-1] ^= 1
    conn = Serial([valid, bytes(bad_response)]); install(monkeypatch, conn)
    with pytest.raises(TransportError, match='CRC mismatch'):
        mod.run('/dev/ttyACM0', 115200, SIGNATURE, 0, 0, 2)
    assert conn.closed
    conn = Serial([valid, response(bytes([0, 0]))]); install(monkeypatch, conn)
    assert mod.run('/dev/ttyACM0', 115200, SIGNATURE, 0, 0, 2)['data_hex'] == '0000'  # not proof of unlocked content


def test_ini_parser_and_lookup_synthetic():
    import shutil
    import subprocess
    from pathlib import Path
    if not shutil.which('node'):
        pytest.skip('Node.js required')
    harness = Path(__file__).with_name('rusefi-ini-harness.cjs')
    result = subprocess.run(['node', str(harness)], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert 'synthetic INI tests passed' in result.stdout
