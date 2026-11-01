"""Experimental DDFI fuel/spark EEPROM SET and readback (synthetic-tested).

SET framing, normal-page chunking and RPM field follow EcmDroid, Copyright
(C) 2012 Michel Marti, GPL-3.0-or-later, and XBTune, GPL-3.0-or-later.
See docs/BUELL_DDFI_RESEARCH.md and LICENSES/EcmDroid-GPL-3.0.txt.
This is not a firmware flasher; only map/axis differences are accepted, but
SET resends entire affected normal-page chunks, including unchanged neighbors.
It does not write page zero or service/actuator commands.
"""
from __future__ import annotations

import hashlib
import os
import secrets
import time
from dataclasses import dataclass, replace
from functools import reduce
from operator import xor
from pathlib import Path

from . import buell_ddfi, resources
from .maps import BUNDLED_XDF_DIR, XdfFile
from .transports.base import TransportError, TransportUnavailable

# Each ID is mapped only to the source definition with its own geometry.
MAP_DEFINITIONS = {
    'BUEGC': 'BUEGC', 'BUEIA': 'BUEIA', 'BUEJA': 'BUEJA', 'BUEKA': 'BUEJA',
    'BUECB': 'BUECB', 'BUEGB': 'BUEGB', 'B2RIB': 'BUEIB', 'BUEIB': 'BUEIB', 'BUEIC': 'BUEIB',
    'B3R1D': 'B3R1D', 'BUE1D': 'B3R1D', 'B3R2D': 'B3R2D', 'BUE2D': 'B3R2D',
    'B3R3D': 'B3R3D', 'BUE3D': 'B3R3D', 'BUEOD': 'BUEOD', 'BUEWD': 'BUEWD',
    'BUEYD': 'BUEYD', 'BUEZD': 'BUEZD',
}
# Source runtime_len is a complete frame, including seven bytes before data
# and the EOT/checksum bytes. RPM is unsigned little endian at frame 11.
RUNTIME_LENGTHS = dict.fromkeys(('BUEGC', 'BUEJA', 'BUEKA'), 99)
RUNTIME_LENGTHS.update({'BUEIA': 100, 'BUECB': 103})
RUNTIME_LENGTHS.update(dict.fromkeys(('B2RIB', 'BUEGB', 'BUEIB', 'BUEIC'), 107))
RUNTIME_LENGTHS.update(dict.fromkeys(('B3R1D', 'B3R2D', 'B3R3D', 'BUE1D', 'BUE2D',
                                      'BUE3D', 'BUEOD', 'BUEWD', 'BUEYD', 'BUEZD'), 135))


@dataclass(frozen=True)
class Plan:
    port: str
    mode: str
    version: str
    base_path: str
    target_path: str
    base: bytes
    target: bytes
    changes: tuple[int, ...]
    xdf: str
    single_read_backup: str | None = None


@dataclass(frozen=True)
class ReadEvidence:
    port: str
    mode: str
    version: str
    original: bytes
    backup_path: str


def _file(value: object, size: int, label: str) -> tuple[str, bytes]:
    if not isinstance(value, str) or not value or '\x00' in value or len(value) > 4096:
        raise ValueError(f'Choose a local {label} file.')
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError(f'The {label} path must be absolute.')
    try:
        with path.open('rb') as handle:
            data = handle.read(size + 1)
    except OSError as exc:
        raise ValueError(f'Cannot read {label}: {exc}') from exc
    if len(data) != size:
        raise ValueError(f'{label} must be exactly {size} bytes for this ECM ID.')
    return str(path), data


def _allowed(ecm_id: str) -> tuple[str, set[int]]:
    name = MAP_DEFINITIONS[ecm_id] + '_source_research.xdf'
    xdf = XdfFile.from_file(BUNDLED_XDF_DIR / 'buell' / name)
    allowed: set[int] = set()
    for table in xdf.tables:
        for embedded in (table.embedded, table.x.embedded, table.y.embedded):
            if embedded is not None:
                for start, length in embedded.positions(embedded.address):
                    allowed.update(range(start, start + length))
    return name, allowed


def prepare(port: object, mode: object, version: object, base_path: object, target_path: object) -> Plan:
    device = buell_ddfi._port(port)
    if mode not in ('stock', 'factory_race'):
        raise ValueError('Choose stock/P&A or factory-race protocol explicitly.')
    if not isinstance(version, str) or not 5 <= len(version) <= 64 or version[:5] not in MAP_DEFINITIONS:
        raise ValueError('Identify a supported ECM and enter the exact version.')
    ecm_id = version[:5]
    size = sum(n for _, n in buell_ddfi.IMAGE_LAYOUTS[ecm_id])
    base_name, base = _file(base_path, size, 'original EEPROM image')
    target_name, target = _file(target_path, size, 'edited EEPROM image')
    # XPR has no embedded identity. This binds the normal read/export workflow
    # to the identified prefix; the operator must still check actual fitment.
    if not Path(base_name).name.upper().startswith(ecm_id):
        raise ValueError(f'The original EEPROM filename must begin with {ecm_id}; XPR has no embedded ID.')
    xdf, allowed = _allowed(ecm_id)
    changed = tuple(i for i, (a, b) in enumerate(zip(base, target)) if a != b)
    if not changed:
        raise ValueError('The edited image has no changes.')
    if any(i not in allowed for i in changed):
        raise ValueError('Only this ECM ID’s source-defined fuel/spark map and axis bytes may be written; other bytes differ.')
    page0 = next((n for p, n in buell_ddfi.IMAGE_LAYOUTS[ecm_id] if p == 0), 0)
    if page0 and any(i >= size - page0 for i in changed):
        raise ValueError('Page zero is not written by this integration.')
    return Plan(device, mode, version, base_name, target_name, base, target, changed, xdf)


def capture_original(port: object, mode: object, result: dict) -> ReadEvidence:
    """Save one successful source-layout image as unverified research evidence."""
    device = buell_ddfi._port(port)
    version = result.get('version')
    if mode not in ('stock', 'factory_race') or not isinstance(version, str) or version[:5] not in MAP_DEFINITIONS:
        raise ValueError('A supported exact ECM version and protocol are required.')
    if result.get('kind') != 'eeprom-image' or result.get('layout') != version[:5]:
        raise ValueError('A complete source-layout image read is required.')
    size = sum(length for _, length in buell_ddfi.IMAGE_LAYOUTS[version[:5]])
    try:
        raw = bytes.fromhex(result.get('data_hex', ''))
    except (ValueError, TypeError) as exc:
        raise ValueError('Invalid source image data.') from exc
    if len(raw) != size or result.get('length') != size or result.get('sha256') != hashlib.sha256(raw).hexdigest():
        raise ValueError('Source image length or digest mismatch.')
    path = _backup(version, raw)
    return ReadEvidence(device, mode, version, raw, path)


def prepare_from_read(evidence: ReadEvidence, target_path: object) -> Plan:
    if type(evidence) is not ReadEvidence:
        raise ValueError('A current source-layout EEPROM read is required.')
    _, stored = _file(evidence.backup_path, len(evidence.original), 'single-read original')
    if stored != evidence.original:
        raise ValueError('The saved single-read original changed; read again.')
    plan = prepare(evidence.port, evidence.mode, evidence.version, evidence.backup_path, target_path)
    if plan.base != evidence.original:
        raise ValueError('The saved single-read original changed; read again.')
    return replace(plan, single_read_backup=evidence.backup_path)


def describe(plan: Plan) -> dict:
    return {'version': plan.version, 'xdf': plan.xdf, 'base_path': plan.base_path,
            'target_path': plan.target_path, 'base_sha256': hashlib.sha256(plan.base).hexdigest(),
            'target_sha256': hashlib.sha256(plan.target).hexdigest(),
            'changes': [{'offset': i, 'before': plan.base[i], 'after': plan.target[i]} for i in plan.changes],
            'synthetic_tested': True, 'single_read': plan.single_read_backup is not None,
            'warning': 'Live EEPROM writing can permanently damage an ECM. Synthetic-tested only; verify ID, fuel/spark values, adapter and stable power.'}


def _set_request(ecm: int, page: int, offset: int, data: bytes) -> bytes:
    if ecm not in (0x42, 0x55) or not 1 <= page <= 31 or not 0 <= offset <= 255 or offset % 16 or not 1 <= len(data) <= 16 or offset + len(data) > 256:
        raise ValueError('Invalid normal-page EEPROM SET.')
    payload = bytes((0x57, offset, page)) + data
    body = bytes((0, ecm, len(payload) + 1, 0xff, 2)) + payload + b'\x03'
    return b'\x01' + body + bytes((reduce(xor, body, 0),))


def _chunks(plan: Plan) -> list[tuple[int, int, int, int, tuple[int, ...]]]:
    """Page, wire offset, flat offset, size and changed positions per chunk."""
    output = []
    start = 0
    for page, size in buell_ddfi.IMAGE_LAYOUTS[plan.version[:5]]:
        if page == 0:
            continue
        for at in range(0, size, 16):
            length = min(16, size - at)
            indices = tuple(i for i in plan.changes if start + at <= i < start + at + length)
            if indices:
                output.append((page, at, start + at, length, indices))
        start += size
    if sum(len(item[4]) for item in output) != len(plan.changes):
        raise ValueError('Some changes are not in a normal EEPROM page.')
    return output


def _backup(version: str, data: bytes) -> str:
    folder = (resources.data_root() / 'buell-backups').resolve()
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = folder / f'{version[:5]}-prewrite-{int(time.time())}-{secrets.token_hex(8)}.xpr'
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'wb') as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return str(path)


def _engine_stopped(conn, ecm: int, ecm_id: str) -> None:
    runtime = buell_ddfi._exchange(conn, ecm, b'C')
    if len(runtime) + 9 != RUNTIME_LENGTHS[ecm_id]:
        raise TransportError('Unexpected runtime frame length; engine state cannot be checked.')
    rpm = int.from_bytes(runtime[4:6], 'little')
    if rpm:
        raise TransportError(f'Engine reports {rpm} RPM; stop it before writing.')


def execute(plan: Plan) -> dict:
    """Preserve the original, then SET only changed chunks and verify.

    The single-read path rechecks each affected chunk but does not reread the
    whole image; it cannot detect an ECU swap or unrelated intervening changes.
    Any communication failure after a SET is an uncertain partial write; never
    automatically retry a SET or claim the ECU was restored.
    """
    if plan.single_read_backup is not None:
        _, stored = _file(plan.single_read_backup, len(plan.base), 'single-read original')
        if stored != plan.base:
            raise TransportError('Saved single-read original changed; no connection or SET sent.')
    try:
        import serial
    except ImportError as exc:
        raise TransportUnavailable('pyserial is required; install the hardware extra.') from exc
    ecm, baud = (0x42, 9600) if plan.mode == 'stock' else (0x55, 19200)
    opts = dict(port=plan.port, baudrate=baud, timeout=.1, write_timeout=1, bytesize=8,
                parity='N', stopbits=1, xonxoff=False, rtscts=False, dsrdtr=False)
    if buell_ddfi.sys.platform != 'win32':
        opts['exclusive'] = True
    backup = plan.single_read_backup
    attempted = 0
    try:
        conn = serial.Serial(**opts)
        try:
            conn.reset_input_buffer()
            version = buell_ddfi._exchange(conn, ecm, b'V').decode('ascii', 'strict').strip()
            if version != plan.version:
                raise TransportError('Connected ECM version changed; no write sent.')
            _engine_stopped(conn, ecm, plan.version[:5])
            if plan.single_read_backup is None:
                live = buell_ddfi._read_image(conn, ecm, buell_ddfi.IMAGE_LAYOUTS[plan.version[:5]])
                backup = _backup(plan.version, live)
                if any(live[i] != plan.base[i] for i in plan.changes):
                    raise TransportError('Live ECM bytes no longer match the original at one or more edited cells; no write sent.')
            else:
                live = plan.base
            chunks = _chunks(plan)
            if plan.single_read_backup is not None:
                # Check all affected chunks before the first SET, then check each
                # again immediately before writing to narrow (not remove) races.
                for page, offset, start, size, _ in chunks:
                    current = buell_ddfi._exchange(conn, ecm, bytes((0x52, offset, page, size)))
                    if len(current) != size or current != plan.base[start:start + size]:
                        raise TransportError(f'Page {page} offset {offset} differs from the single-read original; no write sent.')
            for page, offset, start, size, indices in chunks:
                current = buell_ddfi._exchange(conn, ecm, bytes((0x52, offset, page, size)))
                if len(current) != size or current != live[start:start + size]:
                    raise TransportError(f'Page {page} offset {offset} changed since the backup; stopped.')
                _engine_stopped(conn, ecm, plan.version[:5])
                target = bytearray(current)
                for pos in indices:
                    target[pos - start] = plan.target[pos]
                attempted += 1  # ACK failure may mean the SET took effect.
                buell_ddfi._exchange_wire(conn, ecm, _set_request(ecm, page, offset, target))
                actual = buell_ddfi._exchange(conn, ecm, bytes((0x52, offset, page, size)))
                if actual != target:
                    raise TransportError(f'Readback mismatch for page {page}, offset {offset}.')
            return {'version': plan.version, 'backup_path': backup, 'backup_sha256': hashlib.sha256(live).hexdigest(),
                    'target_sha256': hashlib.sha256(plan.target).hexdigest(), 'chunks_written': len(chunks),
                    'edited_bytes': len(plan.changes), 'synthetic_tested': True,
                    'single_read': plan.single_read_backup is not None,
                    'note': ('Single original image read; only affected chunks were checked before SET. Unrelated changes or an ECM swap may go undetected. '
                             if plan.single_read_backup is not None else '') +
                            'Each written chunk was read back. Target SHA-256 is the input file, not a final ECU hash. Responses do not echo addresses. Not hardware-validated.'}
        finally:
            conn.close()
    except Exception as exc:  # any failure after SET means uncertain ECU state
        if attempted:
            raise TransportError(f'EEPROM state is uncertain after {attempted} SET attempt(s); do not retry blindly. Backup: {backup}. {exc}') from exc
        suffix = f' {"Single-read original" if plan.single_read_backup else "Fresh backup"}: {backup}.' if backup else ' No write sent.'
        raise TransportError(f'Buell write stopped before SET: {exc}.{suffix}') from exc
