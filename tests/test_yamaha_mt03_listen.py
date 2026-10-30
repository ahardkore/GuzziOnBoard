"""Synthetic passive serial observation; not physical hardware validation."""
from types import SimpleNamespace
import sys

import pytest

from guzzionboard import yamaha_mt03_listen as yamaha
from guzzionboard.server import Api
from guzzionboard.workstation import Workstation
from guzzionboard.transports.base import TransportError, TransportUnavailable


def test_source_capture_frames_checksum_and_raw_values():
    source = bytes.fromhex('01 29 00 80 2E D7')
    assert yamaha.decode(source) == {'raw': '012900802ED7', 'rpm_candidate': 2050,
                                    'speed_byte_raw': 0, 'status_byte_raw': 128,
                                    'temperature_byte_raw': 46, 'temperature_ff_unavailable_candidate': False}
    assert yamaha.decode(source[1:])['rpm_candidate'] == 2050
    assert yamaha.decode(bytes.fromhex('01 29 00 80 2E D6')) is None
    assert yamaha.decode(bytes.fromhex('00 00 00 00 00')) is None
    assert yamaha.decode(bytes.fromhex('FF 00 00 00 FF')) is None
    assert yamaha.decode(bytes.fromhex('01 02 00 00 FF 01'))['temperature_ff_unavailable_candidate']


def test_checksum_stream_reassembles_partial_frames_and_noise():
    sync = yamaha.FrameSync()
    assert sync.feed(bytes.fromhex('AA 01 29 00')) == []
    assert sync.feed(bytes.fromhex('80 2E D7')) == [bytes.fromhex('01 29 00 80 2E D7')]
    assert len(sync.buffer) < 6


class FakeSerial:
    def __init__(self, chunks, fail=False):
        self.chunks, self.fail = list(chunks), fail
        self.closed, self.sent = False, []
    @property
    def in_waiting(self): return len(self.chunks[0]) if self.chunks else 0
    def read(self, size):
        if self.fail: raise OSError('bad read')
        if self.chunks: return self.chunks.pop(0)[:size]
        return b''
    def write(self, b): self.sent.append(b); raise AssertionError('must not send')
    def close(self): self.closed = True


def fake_serial(monkeypatch, conn):
    calls = []
    def open_port(**kwargs): calls.append(kwargs); return conn
    fake = SimpleNamespace(Serial=open_port, SerialException=OSError,
                           EIGHTBITS=8, PARITY_NONE='N', STOPBITS_ONE=1)
    monkeypatch.setitem(sys.modules, 'serial', fake)
    monkeypatch.setattr(yamaha.sys, 'platform', 'linux')
    times = iter([0.0, .1, .2, 2.1])
    monkeypatch.setattr(yamaha.time, 'monotonic', lambda: next(times, 2.1))
    return calls


def test_live_window_closes_and_never_writes(monkeypatch):
    conn = FakeSerial([bytes.fromhex('01 29 00'), bytes.fromhex('80 2E D7')])
    calls = fake_serial(monkeypatch, conn)
    result = yamaha.listen('/dev/ttyUSB0')
    assert calls[0]['baudrate'] == 16064 and calls[0]['exclusive'] is True
    assert result['latest']['rpm_candidate'] == 2050 and result['candidate_frames'] == 1
    assert conn.closed and not conn.sent


def test_empty_and_failed_windows_never_reuse_values(monkeypatch):
    conn = FakeSerial([]); fake_serial(monkeypatch, conn)
    assert yamaha.listen('/dev/ttyUSB0')['latest'] is None
    assert conn.closed
    conn = FakeSerial([], fail=True); fake_serial(monkeypatch, conn)
    with pytest.raises(TransportError, match='observation failed'): yamaha.listen('/dev/ttyUSB0')
    assert conn.closed and not conn.sent


def test_invalid_port_and_unsupported_platform_rejected_before_open(monkeypatch):
    conn = FakeSerial([]); calls = fake_serial(monkeypatch, conn)
    for port in (None, '', '/dev/ttyS0', '/dev/null', 'localhost', '/dev/ttyUSB0\x00'):
        with pytest.raises(ValueError): yamaha.listen(port)
    monkeypatch.setattr(yamaha.sys, 'platform', 'win32')
    with pytest.raises(TransportUnavailable): yamaha.listen('/dev/ttyUSB0')
    assert not calls


def test_api_confirm_lock_and_exception_release(monkeypatch):
    api = Api(Workstation(record=False)); calls = []
    monkeypatch.setattr(yamaha, 'listen', lambda port: calls.append(port) or {'latest': None})
    assert api.post_tools_yamaha_mt03_listen({'port': '/dev/ttyUSB0'})[0] == 400
    assert calls == []
    assert api.post_tools_yamaha_mt03_listen({'port': '/dev/ttyUSB0', 'confirm': True}) == (200, {'latest': None})
    assert calls == ['/dev/ttyUSB0']
    api._yamaha_observation_lock.acquire()
    try: assert api.post_tools_yamaha_mt03_listen({'confirm': True})[0] == 409
    finally: api._yamaha_observation_lock.release()
    def fail(_): raise TransportError('failure')
    monkeypatch.setattr(yamaha, 'listen', fail)
    with pytest.raises(TransportError): api.post_tools_yamaha_mt03_listen({'confirm': True})
    assert api._yamaha_observation_lock.acquire(blocking=False)
    api._yamaha_observation_lock.release()


def test_api_refuses_observation_while_any_ecu_session_is_connected(monkeypatch):
    ws = Workstation(record=False)
    ws.service = SimpleNamespace(connected=True)
    api = Api(ws); calls = []
    monkeypatch.setattr(yamaha, 'listen', lambda port: calls.append(port))
    status, body = api.post_tools_yamaha_mt03_listen({'port': '/dev/ttyUSB0', 'confirm': True})
    assert status == 409 and 'Disconnect' in body['error'] and not calls
