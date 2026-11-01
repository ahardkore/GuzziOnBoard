"""Experimental Harley Delphi CAN memory operations, synthetic-tested only.

Wire observations from rob9206/lawflo revision 6255518 (HarleyECUDump and
HarleyECUTool). No source capture or opaque authentication bytes are bundled.
Authentication itself performs an opaque download to address zero and may alter
ECU state. The source's apparent tune mapping, checksums, recovery and fitment
are not independently verified. Not a generic Delphi flasher.
"""
from __future__ import annotations

import hashlib
import os
import re
import secrets
import time
from dataclasses import dataclass
from pathlib import Path

from . import resources
from .protocol.isotp import Reassembler, IsoTpError
from .transports.base import TransportError
from .transports.can import CanConnection, CanTransport, validate_slcan_selection

AUTH_SIZE = 2006
BLOCK = 256
TUNE_SIZE = 0x4000
TUNE_READ_ADDRESS = 0x7F4000
REGIONS = {'config_low': (0x800, 0x800, 0xA0),
           'config_mid': (0x740000, 0x400, 0xB0),
           'calibration': (0x7D8000, 0x28000, 0xB0),
           'tune': (TUNE_READ_ADDRESS, TUNE_SIZE, 0xB0)}
AUTH_DOWNLOAD = bytes.fromhex('34004400000000000007D6')


def _read_file(path, max_bytes, label):
    if not isinstance(path, str) or not path or '\0' in path or len(path) > 4096:
        raise ValueError(f'Choose a local {label} path.')
    p = Path(path).expanduser()
    if not p.is_absolute():
        raise ValueError(f'{label} path must be absolute.')
    try:
        with p.open('rb') as f:
            result = f.read(max_bytes + 1)
    except OSError as exc:
        raise ValueError(f'Cannot read {label}: {exc}') from exc
    if len(result) > max_bytes:
        raise ValueError(f'{label} is too large.')
    return result


def auth_from_file(path):
    """Accept a 2006-byte payload or a captured CAN text log; no key generation.

    Require a complete, correctly sequenced ISO-TP transfer bracketed by the
    captured download acceptance and matching TransferData acknowledgement.
    Distinct accepted payloads in one capture are ambiguous and rejected.
    """
    data = _read_file(path, 16 * 1024 * 1024, 'authentication capture')
    if len(data) == AUTH_SIZE:
        return data
    try:
        text = data.decode('ascii')
    except UnicodeDecodeError as exc:
        raise ValueError('Authentication file must be a 2006-byte payload or ASCII CAN capture.') from exc
    rx = {i: Reassembler() for i in (0x7e0, 0x7e8)}
    state = 0
    candidate = None
    accepted = set()
    for line in text.splitlines():
        match = re.search(r'\b0x(7E0|7E8)\s+(\d+)\s+([0-9A-Fa-f]+)\b', line, re.I)
        if not match:
            continue
        arb = int(match[1], 16)
        try:
            frame = bytes.fromhex(match[3])
        except ValueError:
            raise ValueError('Malformed CAN capture frame.') from None
        if len(frame) != int(match[2]) or not frame or len(frame) > 8:
            raise ValueError('Invalid CAN capture frame length.')
        if frame[0] >> 4 == 3:
            continue
        try:
            p, _ = rx[arb].feed(frame)
        except IsoTpError as exc:
            raise ValueError(f'Invalid ISO-TP sequence in capture: {exc}') from exc
        if p is None:
            continue
        if arb == 0x7e0 and p[0] == 0x34:
            state = 1 if p == AUTH_DOWNLOAD else 0
            candidate = None
        elif arb == 0x7e8 and state == 1 and p[0] == 0x74:
            state = 2 if p == bytes.fromhex('74200802') else 0
        elif arb == 0x7e0 and p[0] == 0x36:
            if state == 2 and len(p) == AUTH_SIZE + 2 and p[:2] == b'\x36\x01':
                candidate, state = p[2:], 3
            else:
                candidate, state = None, 0
        elif arb == 0x7e8 and state == 3 and p[:2] == b'\x76\x01' and len(p) == 3:
            accepted.add(candidate)
            candidate, state = None, 0
        elif arb == 0x7e8 and p[0] == 0x7f and state:
            candidate, state = None, 0
    if len(accepted) != 1:
        raise ValueError('Capture must contain one unique complete, ECU-acknowledged 2006-byte auth transfer.')
    return accepted.pop()


def _channel(interface, channel):
    if interface == 'socketcan':
        if not isinstance(channel, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,15}', channel):
            raise ValueError('Enter a valid SocketCAN interface name.')
    elif interface == 'slcan':
        validate_slcan_selection(channel)
    elif interface == 'pcan':
        if not isinstance(channel, str) or not re.fullmatch(r'PCAN_USBBUS(?:[1-9]|1[0-6])', channel):
            raise ValueError('Enter an explicit PCAN USB channel, e.g. PCAN_USBBUS1.')
    else:
        raise ValueError('Choose SocketCAN, SLCAN or PCAN explicitly.')
    return channel


def _sha(data):
    return hashlib.sha256(data).hexdigest()


class Session:
    def __init__(self, conn, functional, auth):
        if len(auth) != AUTH_SIZE:
            raise ValueError('Authentication payload must be exactly 2006 bytes.')
        self.conn, self.functional, self.auth = conn, functional, auth
        self.reads = 0

    def _request(self, p, timeout=5):
        self.conn.write(p)
        reply = self.conn.read_frame(timeout)
        if not reply:
            raise TransportError(f'ECU timeout after service {p[0]:02X}.')
        if reply[0] == 0x7f:
            if len(reply) != 3 or reply[1] != p[0]:
                raise TransportError('Malformed or mismatched negative ECU reply.')
            raise TransportError(f'ECU rejected service {p[0]:02X} (NRC {reply[2]:02X}).')
        return reply

    def _download(self, address, size, minimum):
        p = b'\x34\x00\x44' + address.to_bytes(4, 'big') + size.to_bytes(4, 'big')
        r = self._request(p)
        if len(r) < 3 or r[0] != 0x74 or r[1] & 0x0f or not 1 <= r[1] >> 4 <= 4 or len(r) != 2 + (r[1] >> 4):
            raise TransportError('Malformed RequestDownload response; transfer aborted.')
        if int.from_bytes(r[2:], 'big') < minimum:
            raise TransportError('ECU maximum TransferData length is too small; transfer aborted.')

    def authenticate(self):
        r = self._request(b'\x3e\x00')
        if r[:2] != b'\x7e\x00':
            raise TransportError('Tester-present response mismatch.')
        # The source addresses 10 03 functionally, not on the physical ID.
        self.functional.write(b'\x10\x03')
        r = self.conn.read_frame(5)
        if not r or len(r) < 2 or r[:2] != b'\x50\x03':
            raise TransportError('Functional extended-session response missing or mismatched.')
        r = self._request(b'\x27\x01')
        if len(r) != 4 or r[:2] != b'\x67\x01':
            raise TransportError('Unexpected security seed response.')
        seed = int.from_bytes(r[2:], 'big')
        if seed:
            key = (seed ^ 0x9ae8).to_bytes(2, 'big')
            if self._request(b'\x27\x02' + key) != b'\x67\x02':
                raise TransportError('Security key response mismatch.')
        self._download(0, AUTH_SIZE, AUTH_SIZE + 2)
        r = self._request(b'\x36\x01' + self.auth, 8)
        if len(r) != 3 or r[:2] != b'\x76\x01':
            raise TransportError('Authentication transfer acknowledgement mismatch; ECU state uncertain.')
        self.reads = 0

    def identity(self):
        result = {}
        for did in (0xf1ea, 0xf1ed, 0xf1f5):
            p = b'\x22' + did.to_bytes(2, 'big')
            r = self._request(p)
            if not 4 <= len(r) <= 259 or r[:3] != b'\x62' + p[1:]:
                raise TransportError(f'Identity DID {did:04X} reply mismatch.')
            result[f'{did:04X}'] = r[3:].hex().upper()
        return result

    def read_region(self, region):
        if region not in REGIONS:
            raise ValueError('Unknown source-defined memory region.')
        start, length, fmt = REGIONS[region]
        out = bytearray()
        for addr in range(start, start + length, BLOCK):
            if self.reads >= 32:
                self.authenticate()
            p = bytes((0x35, fmt, 1)) + addr.to_bytes(4, 'big')
            r = self._request(p)
            # Captures: echoed format/address, 256 data bytes, two trailing
            # bytes of unknown meaning. Never mistake header/trailer for data.
            if len(r) != 265 or r[:7] != b'\x75' + p[1:]:
                raise TransportError(f'Upload length or address echo mismatch at 0x{addr:06X}; partial read discarded.')
            out.extend(r[7:263])
            self.reads += 1
        return bytes(out)

    def write_tune(self, data):
        if len(data) != TUNE_SIZE:
            raise ValueError('Tune must be exactly 16384 bytes.')
        self._download(0x4000, TUNE_SIZE, BLOCK + 2)
        for index in range(TUNE_SIZE // BLOCK):
            seq = index + 1
            r = self._request(bytes((0x36, seq)) + data[index*BLOCK:(index+1)*BLOCK], 8)
            if r != bytes((0x76, seq, 0)):
                raise TransportError(f'TransferData block {seq} acknowledgement mismatch.')
        # Source sends no transfer-exit command. Do not invent one.


def _open(interface, channel):
    channel = _channel(interface, channel)
    conn = CanTransport(interface=interface, channel=channel, bitrate=500000,
                        tx_id=0x7e0, rx_id=0x7e8).open()
    functional = CanConnection(bus=conn.bus, tx_id=0x7df, rx_id=0x7e8,
                               padding=conn.padding, st_min=conn.st_min)
    return conn, functional


@dataclass(frozen=True)
class ReadEvidence:
    """One bounded, session-local research read; not a verified backup."""
    interface: str
    channel: str
    auth: bytes
    identity: tuple
    tune: bytes
    backup_path: str
    read_at: float
    region: str


def read_with_evidence(interface, channel, capture_path, region, repeat=False):
    _channel(interface, channel)
    if region not in REGIONS or type(repeat) is not bool:
        raise ValueError('Choose a source-defined region and valid repeat option.')
    auth = auth_from_file(capture_path)
    conn, functional = _open(interface, channel)
    try:
        session = Session(conn, functional, auth)
        session.authenticate()
        identity = session.identity()
        data = session.read_region(region)
        if repeat and data != session.read_region(region):
            raise TransportError('Repeated memory reads differ; partial data discarded.')
        result = {'identity': identity, 'region': region, 'address': REGIONS[region][0],
                  'length': len(data), 'sha256': _sha(data), 'data_hex': data.hex().upper(),
                  'repeated_match': repeat, 'synthetic_tested': True}
        evidence = None
        if region in ('tune', 'calibration'):
            tune = data if region == 'tune' else data[0x1C000:0x20000]
            if len(tune) != TUNE_SIZE:
                raise TransportError('Source tune slice is incomplete.')
            # A single source-scoped read is preserved automatically, but it
            # remains research evidence, not an independently verified backup.
            try:
                backup_path = _backup(tune)
            except OSError as exc:
                result['write_review_unavailable'] = f'Could not save original tune: {exc}'
            else:
                evidence = ReadEvidence(interface, channel, auth, tuple(sorted(identity.items())),
                                        tune, backup_path, time.monotonic(), region)
                result.update({'original_tune_path': backup_path, 'original_tune_sha256': _sha(tune),
                               'original_tune_verified': False})
        return result, evidence
    except Exception as exc:
        raise TransportError(f'Memory read failed; authentication may have altered ECU state. {exc}') from exc
    finally:
        conn.close()


def read(interface, channel, capture_path, region, repeat=False):
    """Compatibility wrapper returning only the read result."""
    return read_with_evidence(interface, channel, capture_path, region, repeat)[0]


@dataclass(frozen=True)
class Plan:
    interface: str
    channel: str
    auth: bytes
    identity: tuple
    original: bytes
    target: bytes
    single_read_backup: str | None = None
    read_at: float | None = None
    read_region: str | None = None


def prepare(interface, channel, capture_path, identity, original_path, edited_path):
    _channel(interface, channel)
    auth = auth_from_file(capture_path)
    if not isinstance(identity, dict) or set(identity) != {'F1EA', 'F1ED', 'F1F5'}:
        raise ValueError('Read and select the three ECU identity DIDs first.')
    for value in identity.values():
        if not isinstance(value, str) or not re.fullmatch(r'(?:[0-9A-F]{2}){1,256}', value):
            raise ValueError('Invalid ECU identity DID values.')
    original = _read_file(original_path, TUNE_SIZE, 'original tune')
    target = _read_file(edited_path, TUNE_SIZE, 'edited tune')
    if len(original) != TUNE_SIZE or len(target) != TUNE_SIZE:
        raise ValueError('Both tune files must be exactly 16384 bytes.')
    if target == original:
        raise ValueError('The target tune contains no changes.')
    return Plan(interface, channel, auth, tuple(sorted(identity.items())), original, target)


def prepare_from_read(evidence: ReadEvidence, edited_path: str) -> Plan:
    if type(evidence) is not ReadEvidence:
        raise ValueError('A current successful tune or calibration read is required.')
    target = _read_file(edited_path, TUNE_SIZE, 'edited tune')
    if len(target) != TUNE_SIZE:
        raise ValueError('Edited tune must be exactly 16384 bytes.')
    if target == evidence.tune:
        raise ValueError('The target tune contains no changes.')
    if _read_file(evidence.backup_path, TUNE_SIZE, 'single-read original') != evidence.tune:
        raise ValueError('The saved single-read original is missing or changed; read again.')
    return Plan(evidence.interface, evidence.channel, evidence.auth, evidence.identity,
                evidence.tune, target, evidence.backup_path, evidence.read_at, evidence.region)


def describe(plan):
    changes = [(i, a, b) for i, (a,b) in enumerate(zip(plan.original, plan.target)) if a != b]
    return {'identity': dict(plan.identity), 'original_sha256': _sha(plan.original),
            'target_sha256': _sha(plan.target), 'changed_bytes': len(changes),
            'changes': [{'offset': i, 'before': a, 'after': b} for i,a,b in changes],
            'single_read': plan.single_read_backup is not None,
            'read_age_seconds': round(time.monotonic() - plan.read_at, 1) if plan.read_at is not None else None,
            'original_region': plan.read_region,
            'synthetic_tested': True}


def _backup(data):
    folder = resources.data_root() / 'harley-backups'
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = folder / f'delphi-prewrite-{int(time.time())}-{secrets.token_hex(8)}.bin'
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data); f.flush(); os.fsync(f.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return str(path)


def execute(plan):
    # Check the automatically saved original before opening a bus or sending
    # the opaque authentication download. A single read cannot prove the ECU
    # has not changed since then; the user must explicitly confirm that risk.
    if plan.single_read_backup is not None:
        if _read_file(plan.single_read_backup, TUNE_SIZE, 'single-read original') != plan.original:
            raise TransportError('Saved single-read original changed; no connection or tune download sent.')
    conn, functional = _open(plan.interface, plan.channel)
    backup = plan.single_read_backup
    started = False
    try:
        s = Session(conn, functional, plan.auth)
        s.authenticate()
        if s.identity() != dict(plan.identity):
            raise TransportError('Connected ECU identity differs from the reviewed identity.')
        if plan.single_read_backup is None:
            live = s.read_region('tune')
            if s.read_region('tune') != live:
                raise TransportError('Two pre-write tune reads differ.')
            backup = _backup(live)
            if live != plan.original:
                raise TransportError('Connected tune differs from original; no tune download sent.')
        else:
            live = plan.original
        # Download may begin altering flash as soon as the request is sent.
        started = True
        s.write_tune(plan.target)
        s.authenticate()
        if s.identity() != dict(plan.identity):
            raise TransportError('Identity changed during readback.')
        if s.read_region('tune') != plan.target:
            raise TransportError('Tune readback differs from requested bytes.')
        return {'backup_path': backup, 'backup_sha256': _sha(live),
                'target_sha256': _sha(plan.target), 'synthetic_tested': True,
                'single_read': plan.single_read_backup is not None,
                'note': ('Readback matched. Original was captured once, with no fresh pre-write comparison. '
                         if plan.single_read_backup is not None else 'Readback matched. ') +
                        'Checksum, target fitment, trailer integrity and recovery are not verified.'}
    except Exception as exc:
        state = 'Tune download attempted; ECU state is uncertain. Do not retry automatically.' if started else 'No tune download sent; authentication itself may alter ECU state.'
        raise TransportError(f'{state} Backup: {backup or "not saved"}. {exc}') from exc
    finally:
        conn.close()
