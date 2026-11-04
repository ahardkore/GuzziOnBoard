"""Delphi MT05 / MT05.2 K-Line session decoder (offline, read-only research).

Sources (cited, Round 25 in docs/CAPTURE_SEARCH_2026-11-03.md):
- netcult.ch/elmue "HUD ECU Hacker" docs: MT05/MT05.2 speak ISO 14230
  (KWP2000) over K-Line at 10400 baud 8N1 with fast init; ECU address 0x11,
  tester 0xF1; init key bytes EF 8F; 6-pin under-seat diagnostic plug.
- Njavris/m05.2 (MIT): MT05.2 also exposes CAN diag 0x7E0/0x7E4 and documents
  a fixed seed 0x1234 -> key 0x8474 (cited only; no unlock implemented).

This module parses KWP2000 frames using the MT05 addressing (TGT 0x11 /
SRC 0xF1, FMT 0x80|len, sum checksum) and flags the EF 8F key-byte init
reply. Read-only; no diagnostic session is opened.
"""
from __future__ import annotations

PROFILE = 'delphi_mt05_kline'

BAUD = 10400
ECU_ADDR, TESTER_ADDR = 0x11, 0xF1
KEY_BYTES = (0xEF, 0x8F)


def checksum(body: bytes) -> int:
    return sum(bytes(body)) & 0xFF


def parse_frame(frame: bytes) -> dict:
    """Parse one addressed KWP2000 frame [FMT TGT SRC LEN DATA... CS]."""
    frame = bytes(frame)
    if len(frame) < 5:
        raise ValueError('frame too short')
    fmt, tgt, src, length = frame[0], frame[1], frame[2], frame[3]
    if fmt & 0xC0 != 0x80:
        raise ValueError('not an addressed (0x80) frame')
    if len(frame) != length + 5:
        raise ValueError('length mismatch')
    if checksum(frame[:-1]) != frame[-1]:
        raise ValueError('sum checksum mismatch')
    data = frame[4:-1]
    out = {'target': tgt, 'source': src, 'service': data[0] if data else None,
           'payload': data[1:].hex().upper(), 'mt05_addressing': (tgt, src) in ((ECU_ADDR, TESTER_ADDR), (TESTER_ADDR, ECU_ADDR))}
    if data and data[0] == 0x83 and data[1:3] == bytes(KEY_BYTES):
        out['init_key_bytes'] = 'EF 8F'
    return out


def decode_capture(frames) -> dict:
    recognized = invalid = 0
    mt05_frames = 0
    last = None
    for frame in frames:
        try:
            parsed = parse_frame(frame)
        except ValueError:
            invalid += 1
            continue
        recognized += 1
        if parsed['mt05_addressing']:
            mt05_frames += 1
        last = parsed
    return {'profile': PROFILE, 'recognized': recognized, 'invalid': invalid,
            'mt05_addressed_frames': mt05_frames, 'last_frame': last}
