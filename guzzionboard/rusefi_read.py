"""Read-only rusEFI/TunerStudio serial research, not stock Harley Delphi.

Wire behavior researched from rusEFI at 5359cc971b60a9a0ee3f0f2a870dbb64f0ad36ef:
firmware/console/binary/tunerstudio.cpp and tunerstudio_io.cpp;
java_console/io/.../binaryprotocol/IoHelper.java and io/commands/ByteRange.java.
No source code or calibration is bundled. Synthetic tests only, no hardware test.
"""
from __future__ import annotations

import os
import re
import struct
import sys
import time
import zlib

from .transports.base import TransportError, TransportUnavailable

MAX_READ = 256
MAX_RESPONSE = 512
TIMEOUT = 3.0


def validate_port(port: object) -> str:
    if not isinstance(port, str) or len(port) > 255 or '\x00' in port:
        raise ValueError('Select an explicit rusEFI USB serial device.')
    if sys.platform == 'win32':
        if not re.fullmatch(r'COM[1-9][0-9]{0,2}', port.upper()):
            raise ValueError('Select an explicit Windows COM port.')
        return port.upper()
    if sys.platform.startswith('linux'):
        device = os.path.realpath(port)
        if not re.fullmatch(r'/dev/tty(?:USB|ACM)[0-9]+', device):
            raise ValueError('Select an explicit /dev/ttyUSB or /dev/ttyACM port.')
        return device
    if sys.platform == 'darwin' and re.fullmatch(r'/dev/cu\.(?:usbmodem|usbserial)[A-Za-z0-9._-]+', port):
        return port
    raise TransportUnavailable('Use an explicit USB serial port on Linux, Windows, or macOS.')


def packet(payload: bytes) -> bytes:
    return struct.pack('>H', len(payload)) + payload + struct.pack('>I', zlib.crc32(payload))


def _read_exact(connection, count: int, deadline: float) -> bytes:
    data = bytearray()
    while len(data) < count:
        if time.monotonic() >= deadline:
            raise TransportError('Timed out waiting for the rusEFI response.')
        chunk = connection.read(count - len(data))
        if chunk:
            data.extend(chunk)
    return bytes(data)


def _exchange(connection, payload: bytes) -> bytes:
    wire = packet(payload)
    if connection.write(wire) != len(wire):
        raise TransportError('Incomplete serial write; session stopped.')
    end = time.monotonic() + TIMEOUT
    size = struct.unpack('>H', _read_exact(connection, 2, end))[0]
    if not 1 <= size <= MAX_RESPONSE:
        raise TransportError('Invalid or oversized rusEFI response.')
    data = _read_exact(connection, size, end)
    checksum = struct.unpack('>I', _read_exact(connection, 4, end))[0]
    if zlib.crc32(data) != checksum:
        raise TransportError('rusEFI response CRC mismatch; no data accepted.')
    if data[0] != 0:
        raise TransportError(f'rusEFI returned an error status 0x{data[0]:02X}.')
    return data[1:]


def _int(value: object, name: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f'{name} must be an integer from {minimum} to {maximum}.')
    return value


def run(port: object, baud: object, expected: object = None, page: object = None,
        offset: object = None, count: object = None, *, kind: str = 'page') -> dict:
    """Identify, or identify and read one bounded explicitly selected page range."""
    device = validate_port(port)
    if baud not in (115200, 230400, 460800, 921600) or type(baud) is not int:
        raise ValueError('Choose one of the supported explicit serial baud rates.')
    if kind not in ('page', 'outputs'):
        raise ValueError('Choose page or outputs.')
    reading = expected is not None
    if reading:
        if not isinstance(expected, str) or not 1 <= len(expected) <= 180 or not expected.startswith('rusEFI '):
            raise ValueError('Enter the exact rusEFI signature from your matching INI definition.')
        page = _int(page, 'page', 0, 65535)
        offset = _int(offset, 'offset', 0, 65535)
        count = _int(count, 'length', 1, MAX_READ)
        if offset + count > 65536:
            raise ValueError('The requested range crosses the 16-bit page boundary.')
    try:
        import serial
    except ImportError as exc:
        raise TransportUnavailable('pyserial is not installed; install the hardware extra.') from exc
    options = dict(port=device, baudrate=baud, timeout=0.1, write_timeout=1)
    if sys.platform != 'win32':
        options['exclusive'] = True
    try:
        connection = serial.Serial(**options)
        try:
            # Discard stale bytes before sending; this does not prove identity.
            connection.reset_input_buffer()
            signature_bytes = _exchange(connection, b'S')
            if not signature_bytes.endswith(b'\x00') or b'\x00' in signature_bytes[:-1]:
                raise TransportError('Invalid rusEFI signature response.')
            try:
                signature = signature_bytes[:-1].decode('ascii')
            except UnicodeDecodeError as exc:
                raise TransportError('Invalid rusEFI signature response.') from exc
            if not signature.startswith('rusEFI ') or len(signature) > 180 or not all(32 <= ord(c) < 127 for c in signature):
                raise TransportError('Unrecognized signature; not a supported rusEFI controller.')
            result = {'signature': signature, 'synthetic_tested': True}
            if reading:
                if signature != expected:
                    raise TransportError('The connected signature does not exactly match the supplied INI signature; no page read sent.')
                if kind == 'page':
                    request = b'R' + struct.pack('<HHH', page, offset, count)
                else:
                    request = b'O' + struct.pack('<HH', offset, count)
                response = _exchange(connection, request)
                if len(response) != count:
                    raise TransportError('Unexpected read response length; no data accepted.')
                result.update(kind=kind, offset=offset, length=count, data_hex=response.hex().upper())
                if kind == 'page':
                    result['page'] = page
            return result
        finally:
            connection.close()
    except (serial.SerialException, OSError) as exc:
        raise TransportError(f'rusEFI serial communication failed: {exc}') from exc
