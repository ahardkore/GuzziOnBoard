"""Experimental read-only Buell DDFI serial research.

Protocol framing and GET behavior adapted from EcmDroid PDU.java and ECM.java,
Copyright (C) 2012 Michel Marti, GPL-3.0-or-later, at commit
2f17d29f5b08f67fb357ee8f2ec21e7ae930343e. See LICENSES/EcmDroid-GPL-3.0.txt.
Only version, runtime and bounded page GET are implemented; never SET.
Synthetic tests only. Do not confuse TTL serial with Harley J1850 or K-Line.
"""
from __future__ import annotations

import os
import re
import sys
import time
from functools import reduce
from operator import xor

from .transports.base import TransportError, TransportUnavailable

TIMEOUT = 2.5
MAX_FRAME = 262


def _port(value: object) -> str:
    if not isinstance(value, str) or len(value) > 255 or '\x00' in value:
        raise ValueError('Choose an explicit Buell-compatible TTL serial device.')
    if sys.platform == 'win32' and re.fullmatch(r'COM[1-9][0-9]{0,2}', value.upper()):
        return value.upper()
    if sys.platform.startswith('linux'):
        device = os.path.realpath(value)
        if re.fullmatch(r'/dev/(?:ttyUSB|ttyACM|rfcomm)[0-9]+', device):
            return device
    if sys.platform == 'darwin' and re.fullmatch(r'/dev/cu\.[A-Za-z0-9._-]+', value):
        return value
    raise ValueError('Choose an explicit USB/Bluetooth serial port on this computer.')


def _request(ecm: int, payload: bytes) -> bytes:
    # These are the only opcodes this integration is allowed to transmit.
    if payload not in (b'V', b'C') and not (len(payload) == 4 and payload[0] == 0x52
                                                 and 1 <= payload[2] <= 31 and 1 <= payload[3] <= 16
                                                 and payload[1] + payload[3] <= 256):
        raise ValueError('Only version, runtime and bounded page GET requests are allowed.')
    body = bytes((0, ecm, len(payload) + 1, 0xff, 2)) + payload + b'\x03'
    return b'\x01' + body + bytes((reduce(xor, body, 0),))


def _exact(connection, count: int, deadline: float) -> bytes:
    result = bytearray()
    while len(result) < count:
        if time.monotonic() >= deadline:
            raise TransportError('Buell ECM response timed out.')
        result.extend(connection.read(count - len(result)))
    return bytes(result)


def _exchange(connection, ecm: int, payload: bytes) -> bytes:
    wire = _request(ecm, payload)
    if connection.write(wire) != len(wire):
        raise TransportError('Incomplete Buell serial request.')
    deadline = time.monotonic() + TIMEOUT
    header = _exact(connection, 6, deadline)
    size = header[3]
    if header[:3] != bytes((1, ecm, 0)) or header[4:] != b'\xff\x02' or not 2 <= size <= 255:
        raise TransportError('Invalid Buell response header, address or length.')
    rest = _exact(connection, size + 1, deadline)
    frame = header + rest
    if len(frame) > MAX_FRAME or frame[-2] != 3 or reduce(xor, frame[1:-1], 0) != frame[-1]:
        raise TransportError('Invalid Buell response checksum or framing.')
    if frame[6] != 6:
        raise TransportError(f'Buell ECM rejected request (status 0x{frame[6]:02X}).')
    return frame[7:-2]


def _bueia_runtime(version: str, data: bytes) -> dict | None:
    """ADX candidate fields; offsets are in a 100-byte framed response."""
    if not version.startswith('BUEIA') or len(data) != 91:
        return None
    # The ECM response framing uses 6 header bytes and an ACK byte before
    # data. The ADX offsets refer to the complete 100-byte response.
    def u16(frame_offset):
        i = frame_offset - 7
        return int.from_bytes(data[i:i + 2], 'little')
    return {'rpm': u16(0x0b), 'throttle_percent': round(data[0x1b - 7] * 0.392157, 3),
            'battery_volts': round(u16(0x1c) * 0.01, 2),
            'engine_temp_c': round(u16(0x1e) * 0.1 - 40, 1),
            'air_temp_c': round(u16(0x20) * 0.1 - 40, 1)}


def _integer(value: object, field: str, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f'{field} must be an integer from {low} to {high}.')
    return value


def run(port: object, mode: object, action: object, expected: object = None,
        page: object = None, offset: object = None, length: object = None) -> dict:
    device = _port(port)
    if mode not in ('stock', 'factory_race'):
        raise ValueError('Choose stock/P&A or factory-race protocol explicitly.')
    if action not in ('identify', 'runtime', 'read'):
        raise ValueError('Choose identify, runtime or EEPROM read.')
    if action != 'identify' and (not isinstance(expected, str) or not 5 <= len(expected) <= 64):
        raise ValueError('Enter the exact ECM version reported by identify.')
    if action == 'read':
        page = _integer(page, 'page', 1, 31)  # exclude page zero and the known virtual/service page 0x20 and above
        offset = _integer(offset, 'offset', 0, 255)
        length = _integer(length, 'length', 1, 256)
        if offset + length > 256:
            raise ValueError('Read cannot cross a page boundary.')
    ecm, baud = (0x42, 9600) if mode == 'stock' else (0x55, 19200)
    try:
        import serial
    except ImportError as exc:
        raise TransportUnavailable('pyserial is required; install the hardware extra.') from exc
    opts = dict(port=device, baudrate=baud, timeout=0.1, write_timeout=1,
                bytesize=8, parity='N', stopbits=1, xonxoff=False, rtscts=False, dsrdtr=False)
    if sys.platform != 'win32':
        opts['exclusive'] = True
    try:
        conn = serial.Serial(**opts)
        try:
            conn.reset_input_buffer()
            version_bytes = _exchange(conn, ecm, b'V')
            if not 5 <= len(version_bytes) <= 64 or not all(32 <= b <= 126 for b in version_bytes):
                raise TransportError('Unrecognized ECM version response.')
            version = version_bytes.decode('ascii').strip()
            if not re.fullmatch(r'[A-Z0-9]{5}[A-Za-z0-9 ./_-]*', version):
                raise TransportError('Unrecognized ECM version response.')
            result = {'version': version, 'mode': mode, 'synthetic_tested': True}
            if action != 'identify' and expected != version:
                raise TransportError('ECM version differs from the selected version; no data request sent.')
            if action == 'runtime':
                data = _exchange(conn, ecm, b'C')
                if not data:
                    raise TransportError('Empty runtime response.')
                result.update(kind='runtime', data_hex=data.hex().upper(), length=len(data),
                              bueia_candidates=_bueia_runtime(version, data))
            if action == 'read':
                data = bytearray()
                while len(data) < length:
                    n = min(16, length - len(data))
                    chunk = _exchange(conn, ecm, bytes((0x52, offset + len(data), page, n)))
                    if len(chunk) != n:
                        raise TransportError('EEPROM response length mismatch; partial data discarded.')
                    data.extend(chunk)
                result.update(kind='page', page=page, offset=offset, length=length, data_hex=data.hex().upper())
            return result
        finally:
            conn.close()
    except (serial.SerialException, OSError) as exc:
        raise TransportError(f'Buell serial communication failed: {exc}') from exc
