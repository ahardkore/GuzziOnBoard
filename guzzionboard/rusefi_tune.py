"""Experimental rusEFI page-zero calibration read, reviewed RAM write and burn.

Protocol researched from rusEFI 5359cc971b60, including tunerstudio.cpp,
tunerstudio_io.cpp, ts_protocol.txt, and the Java ByteRange/BurnCommand.
Independently implemented; no upstream code or calibration bundled.
Synthetic tests only. Not a firmware flasher or a stock Harley Delphi protocol.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import secrets
import struct
import time
import zlib
from contextlib import contextmanager
from dataclasses import dataclass

from . import resources, rusefi_read as wire
from .transports.base import TransportError, TransportUnavailable

MAX_INI = 2 * 1024 * 1024
CHUNK = 128


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_ini(text: object) -> tuple[str, int]:
    """Accept only unambiguous, unconditional multi-page rusEFI page-zero metadata."""
    if not isinstance(text, str) or len(text.encode('utf-8')) > MAX_INI:
        raise ValueError('Select a matching INI no larger than 2 MiB.')
    wanted = {'signature', 'pagesize', 'pageidentifier', 'pagereadcommand',
              'pagechunkwrite', 'burncommand', 'crc32checkcommand'}
    fields = {}
    section, conditional = '', 0
    for line in text.lstrip('\ufeff').splitlines():
        stripped = line.strip()
        directive = re.match(r'^#\s*(if|ifdef|ifndef|endif)\b', stripped, re.I)
        if directive:
            conditional += -1 if directive.group(1).lower() == 'endif' else 1
            if conditional < 0:
                raise ValueError('Unbalanced INI conditional.')
            continue
        header = re.match(r'^\[([^\]]+)\]\s*(?:;.*)?$', stripped)
        if header:
            section = header.group(1).strip().lower()
            continue
        pair = re.match(r'^([a-zA-Z0-9_]+)\s*=\s*(.*)$', stripped)
        if not pair:
            continue
        key = pair.group(1).lower()
        if key not in wanted or (key == 'signature' and section != 'tunerstudio') or (key != 'signature' and section != 'constants'):
            continue
        if conditional:
            raise ValueError('Conditional INI tuning metadata is unsupported.')
        value = pair.group(2).split(';', 1)[0].strip()
        if key in fields and fields[key] != value:
            raise ValueError('Conflicting INI tuning metadata.')
        fields[key] = value
    if conditional or not wanted.issubset(fields):
        raise ValueError('INI needs unambiguous signature and page-zero command metadata.')
    sig = re.fullmatch(r'"(rusEFI [\x20-\x7e]{1,173})"', fields['signature'])
    size = re.fullmatch(r'(\d+)\s*(?:,.*)?', fields['pagesize'])
    if not sig or not size or not 1 <= int(size.group(1)) <= 65535:
        raise ValueError('Unsupported rusEFI INI signature or page-zero size.')
    for key, prefix in {
        'pageidentifier': '"\\x00\\x00"',
        'pagereadcommand': '"R%2i%2o%2c"',
        'pagechunkwrite': '"C%2i%2o%2c%v"',
        'burncommand': '"B%2i"',
        'crc32checkcommand': '"k%2i%2o%2c"',
    }.items():
        if fields[key].split(',', 1)[0].strip() != prefix:
            raise ValueError(f'Unsupported page-zero {key} in INI.')
    return sig.group(1), int(size.group(1))


@dataclass(frozen=True)
class Evidence:
    port: str
    baud: int
    signature: str
    ini_sha256: str
    original: bytes
    backup_path: str


@dataclass(frozen=True)
class Plan:
    evidence: Evidence
    target: bytes
    target_path: str
    ranges: tuple[tuple[int, int], ...]


def _check_baud(value: object) -> int:
    if type(value) is not int or value not in (115200, 230400, 460800, 921600):
        raise ValueError('Choose an explicit supported baud rate.')
    return value


@contextmanager
def _connection(port: str, baud: int):
    try:
        import serial
    except ImportError as exc:
        raise TransportUnavailable('pyserial is required; install the hardware extra.') from exc
    opts = dict(port=port, baudrate=baud, timeout=0.1, write_timeout=1)
    if wire.sys.platform != 'win32':
        opts['exclusive'] = True
    try:
        conn = serial.Serial(**opts)
        try:
            conn.reset_input_buffer()
            yield conn
        finally:
            conn.close()
    except (serial.SerialException, OSError) as exc:
        raise TransportError(f'rusEFI serial communication failed: {exc}') from exc


def _identify(conn, expected: str):
    result = wire._exchange(conn, b'S')
    if result != expected.encode('ascii') + b'\x00':
        raise TransportError('Connected signature does not match the INI; no write sent.')


def _read(conn, offset: int, size: int) -> bytes:
    result = wire._exchange(conn, b'R' + struct.pack('<HHH', 0, offset, size))
    if len(result) != size:
        raise TransportError('Unexpected rusEFI page read length.')
    return result


def _crc(conn, size: int) -> int:
    value = wire._exchange(conn, b'k' + struct.pack('<HHH', 0, 0, size))
    if len(value) != 4:
        raise TransportError('Unexpected rusEFI page CRC response.')
    return int.from_bytes(value, 'big')


def _save(data: bytes) -> str:
    folder = (resources.data_root() / 'rusefi-backups').resolve()
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = folder / f'rusefi-page0-{int(time.time())}-{secrets.token_hex(8)}.bin'
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, 'wb') as out:
            out.write(data); out.flush(); os.fsync(out.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return str(path)


def read_original(port: object, baud: object, ini: object) -> tuple[dict, Evidence | None]:
    device = wire.validate_port(port)
    rate = _check_baud(baud)
    signature, size = parse_ini(ini)
    with _connection(device, rate) as conn:
        _identify(conn, signature)
        data = b''.join(_read(conn, at, min(CHUNK, size-at)) for at in range(0, size, CHUNK))
    if not any(data):
        raise TransportError('Page is all zero: locked controllers can return zeros; no write evidence created.')
    result = {'signature': signature, 'length': size, 'sha256': _sha(data),
              'ini_sha256': _sha(ini.encode('utf-8')), 'synthetic_tested': True}
    try:
        path = _save(data)
    except OSError as exc:
        result['write_review_unavailable'] = f'Could not save original: {exc}'
        return result, None
    evidence = Evidence(device, rate, signature, result['ini_sha256'], data, path)
    result.update(original_path=path, original_verified=False)
    return result, evidence


def _file(path: object, size: int, label: str) -> bytes:
    if not isinstance(path, str) or not path or '\x00' in path or len(path) > 4096 or not Path(path).expanduser().is_absolute():
        raise ValueError(f'Choose an absolute {label} path.')
    try:
        with Path(path).expanduser().open('rb') as src:
            data = src.read(size + 1)
    except OSError as exc:
        raise ValueError(f'Cannot read {label}: {exc}') from exc
    if len(data) != size:
        raise ValueError(f'{label} must be exactly {size} bytes.')
    return data


def prepare(evidence: Evidence, target_path: object) -> Plan:
    if not isinstance(evidence, Evidence):
        raise ValueError('Read the original calibration page first.')
    if _file(evidence.backup_path, len(evidence.original), 'original') != evidence.original:
        raise ValueError('Saved original changed; read again.')
    target = _file(target_path, len(evidence.original), 'edited image')
    ranges = []
    i = 0
    while i < len(target):
        if target[i] == evidence.original[i]:
            i += 1; continue
        start = i
        while i < len(target) and target[i] != evidence.original[i] and i-start < CHUNK:
            i += 1
        ranges.append((start, i))
    if not ranges:
        raise ValueError('Edited image has no changes.')
    return Plan(evidence, target, str(Path(target_path).expanduser()), tuple(ranges))


def describe(plan: Plan) -> dict:
    e = plan.evidence
    return {'signature': e.signature, 'length': len(e.original), 'original_path': e.backup_path,
            'original_sha256': _sha(e.original), 'target_sha256': _sha(plan.target),
            'ini_sha256': e.ini_sha256, 'changed_bytes': sum(end-start for start, end in plan.ranges),
            'changes': [{'offset': start, 'before': e.original[start:end].hex().upper(),
                         'after': plan.target[start:end].hex().upper()} for start, end in plan.ranges],
            'synthetic_tested': True}


def execute(plan: Plan) -> dict:
    e = plan.evidence
    if _file(e.backup_path, len(e.original), 'original') != e.original:
        raise TransportError('Saved original changed; no write sent.')
    attempted = 0
    burn_attempted = False
    try:
        with _connection(e.port, e.baud) as conn:
            _identify(conn, e.signature)
            if _crc(conn, len(e.original)) != zlib.crc32(e.original):
                raise TransportError('Live page CRC differs from the original; no chunk or burn command sent.')
            for start, end in plan.ranges:
                if _read(conn, start, end-start) != e.original[start:end]:
                    raise TransportError(f'Live bytes at {start} differ from the original.')
                payload = b'C' + struct.pack('<HHH', 0, start, end-start) + plan.target[start:end]
                attempted += 1  # even a lost acknowledgement may mean it was applied
                if wire._exchange(conn, payload) != b'':
                    raise TransportError('Unexpected chunk write acknowledgement.')
                if _read(conn, start, end-start) != plan.target[start:end]:
                    raise TransportError(f'RAM readback mismatch at {start}.')
            if _crc(conn, len(e.original)) != zlib.crc32(plan.target):
                raise TransportError('Whole working-page CRC does not match edited image; burn not sent.')
            burn_attempted = True
            if wire._exchange(conn, b'B\x00\x00', expected_status=4) != b'':
                raise TransportError('Unexpected burn acknowledgement.')
            # A full-page CRC request completes the newer deferred settings burn;
            # older versions may instead complete asynchronously. Neither proves
            # physical flash persistence after power cycling.
            if _crc(conn, len(e.original)) != zlib.crc32(plan.target):
                raise TransportError('Working-page CRC mismatch after burn request.')
            time.sleep(2.1)
            if _crc(conn, len(e.original)) != zlib.crc32(plan.target):
                raise TransportError('Working-page CRC changed after burn request.')
    except Exception as exc:
        if attempted:
            raise TransportError(f'Uncertain calibration state after {attempted} RAM write attempt(s); '
                                 f'burn {"was attempted" if burn_attempted else "was not attempted"}. '
                                 f'Do not retry blindly. Original: {e.backup_path}. {exc}') from exc
        raise TransportError(f'No chunk or burn command sent; a CRC request may complete a previously pending burn. Original: {e.backup_path}. {exc}') from exc
    return {'original_path': e.backup_path, 'original_sha256': _sha(e.original),
            'target_sha256': _sha(plan.target), 'chunks_written': attempted,
            'changed_bytes': sum(end-start for start, end in plan.ranges), 'synthetic_tested': True,
            'note': 'Working-page CRC matched; flash persistence after power cycling was not verified. No physical ECU was tested.'}
