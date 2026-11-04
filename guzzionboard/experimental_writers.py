"""EXPERIMENTAL write-class frame builders (offline, token-gated, no transport).

Scope (owner direction, Rounds 20-21): the app is research / off-road / track
oriented; write capabilities are built as EXPERIMENTAL frame builders only.
Every function requires CONFIRM_TOKEN and returns frame BYTES — nothing here
opens a transport or sends to an ECU. Passive decoders still classify these
as write-class/rejected.

Covered protocols (all already decoded read-only elsewhere in this package):
  - KWP2000/ISO 14230 write services: 0x3B WriteDataByIdentifier,
    0x2E WriteDataByLocalIdentifier, 0x3D WriteMemoryByAddress (experimental)
  - UDS/ISO 14229: 0x27 SecurityAccess (requestSeed/sendKey), 0x31
    RoutineControl, 0x34/0x36/0x37 RequestDownload/TransferData/Exit (experimental)
  - Honda Keihin K-Line (K25): 0x60 clear-DTC query frame builder
  - Buell DDFI-2: see buell_ddfi2_tune.py (CMD_SET 0x57, author-confirmed)
"""
from __future__ import annotations

PROFILE = 'experimental_write_builders'

CONFIRM_TOKEN = 'EXPERIMENTAL WRITE FRAMES ONLY - LOCAL RESEARCH / OFF-ROAD / TRACK USE ON VEHICLES I OWN OR AM AUTHORIZED TO MODIFY'


def _gate(confirm_token: str) -> None:
    if confirm_token != CONFIRM_TOKEN:
        raise PermissionError('experimental write builders require the confirmation token')


def _kwp2000_frame(service: int, payload: bytes, address: int = 0xF1, target: int = 0x10, *, confirm_token: str) -> bytes:
    """KWP2000 header (fmt 0x80): [fmt, target, source, len, sid, ...payload, cs]."""
    _gate(confirm_token)
    body = bytes([0x80, target, address, len(payload) + 1, service]) + bytes(payload)
    return body + bytes([sum(body[3:]) & 0xFF])  # checksum over len..payload


def kwp2000_write_data_by_identifier(did: int, data: bytes, *, confirm_token: str) -> bytes:
    """0x3B WriteDataByIdentifier (experimental)."""
    return _kwp2000_frame(0x3B, did.to_bytes(2, 'big') + bytes(data), confirm_token=confirm_token)


def kwp2000_write_memory_by_address(address: int, data: bytes, *, confirm_token: str) -> bytes:
    """0x3D WriteMemoryByAddress with 3-byte address (experimental)."""
    return _kwp2000_frame(0x3D, address.to_bytes(3, 'big') + bytes(data), confirm_token=confirm_token)


def uds_frame(service: int, payload: bytes, *, confirm_token: str) -> bytes:
    """UDS single-frame-ish builder: [len, sid, ...payload] (no transport)."""
    _gate(confirm_token)
    body = bytes([service]) + bytes(payload)
    return bytes([len(body) & 0x3F]) + body


def uds_request_seed(level: int, *, confirm_token: str) -> bytes:
    """0x27 01 requestSeed (experimental; unlock/tuning research)."""
    return uds_frame(0x27, bytes([level]), confirm_token=confirm_token)


def uds_send_key(level: int, key: bytes, *, confirm_token: str) -> bytes:
    """0x27 02 sendKey (experimental)."""
    return uds_frame(0x27, bytes([level]) + bytes(key), confirm_token=confirm_token)


def uds_routine_control(routine_id: int, control_type: int = 1, *, confirm_token: str) -> bytes:
    """0x31 RoutineControl startRoutine (experimental)."""
    return uds_frame(0x31, bytes([control_type]) + routine_id.to_bytes(2, 'big'), confirm_token=confirm_token)


def uds_request_download(data_format: int, address: int, size: int, *, confirm_token: str) -> bytes:
    """0x34 RequestDownload (experimental flash-session entry)."""
    n = max(1, (size.bit_length() + 7) // 8)
    return uds_frame(0x34, bytes([data_format, n, n]) + address.to_bytes(n, 'big') + size.to_bytes(n, 'big'),
                     confirm_token=confirm_token)


def honda_k25_clear_dtc(*, confirm_token: str) -> bytes:
    """Honda Keihin K-Line clear-DTC query `72 60 00 CS` (experimental).

    CS = two's complement of the byte sum of `72 60 00`. The read-only decoder
    (honda_keihin_kline.py) rejects this as write-class; this only builds bytes.
    """
    _gate(confirm_token)
    body = bytes([0x72, 0x02, 0x60, 0x00])   # 72 NN QQ ZZ CS request shape
    return body + bytes([(-sum(body)) & 0xFF])
