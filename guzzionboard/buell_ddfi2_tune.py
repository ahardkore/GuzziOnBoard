"""Buell DDFI-2 EEPROM tune-write frame builder — EXPERIMENTAL, offline only.

Sources (author-indicated success, per the write-class policy):
- pacdavid1/buell-xb12x-logger @ 45a7624 (MIT, LICENSES/Buell-XB12X-Logger-MIT.txt):
  CMD_SET 0x57 payload `[0x57, offset&0xFF, page&0xFF] + data`, "confirmed
  2026-05-31: write EEPROM page".
- kz6fittycent/XBTune @ f474b9401bc4 (GPL-3.0, LICENSES/XBTune-GPL3.txt):
  Buell DDFI-2/DDFI-3 tune write-back, "Tested on a 2005 XB9SX".

This module BUILDS write frames and patches LOCAL EEPROM images only. It
never opens a transport and never sends anything to an ECU. Every public
function requires an explicit confirmation token; without it they raise.
The read-only decoder (buell_ddfi2_serial.py) still reports these frames as
0x57-SET-WRITE-REJECTED in passive captures.
"""
from __future__ import annotations

from .buell_ddfi2_serial import SOH, EOH, SOT, EOT, TESTER_ID, ECM_ID, CMD_SET, BUEIB_PAGES

PROFILE = 'buell_xb12x_ddfi2_tune_experimental'

#: Confirmation phrase required by every write-path function.
CONFIRM_TOKEN = 'I UNDERSTAND THIS WRITES A LOCAL BUELL DDFI-2 IMAGE ONLY'

MAX_PAGE_WRITE = 16  # matches the GET chunk limit of the source protocol


def _xor_cs(frame: bytes) -> int:
    cs = 0
    for b in frame[1:-1]:
        cs ^= b
    return cs


def build_set_pdu(offset: int, page: int, data: bytes, *, confirm_token: str) -> bytes:
    """Build one CMD_SET EEPROM-write PDU. Raises without the confirm token."""
    if confirm_token != CONFIRM_TOKEN:
        raise PermissionError('experimental write path requires the confirmation token')
    data = bytes(data)
    if not data or len(data) > MAX_PAGE_WRITE:
        raise ValueError(f'SET data must be 1..{MAX_PAGE_WRITE} bytes')
    if not 0 <= offset <= 0xFF or not 0 <= page <= 0xFF:
        raise ValueError('offset and page must fit one byte')
    payload = bytes([CMD_SET, offset & 0xFF, page & 0xFF]) + data
    body = bytes([SOH, TESTER_ID, ECM_ID, len(payload) + 1, EOH, SOT]) + payload + bytes([EOT])
    return body + bytes([_xor_cs(body + b'\x00')])  # CS over frame[1:-1] incl. EOT


def page_for_offset(offset: int) -> int:
    """Map an absolute EEPROM offset to its BUEIB page number."""
    for page, start, size in BUEIB_PAGES:
        if start <= offset < start + size:
            return page
    raise ValueError(f'offset {offset:#x} is outside the BUEIB EEPROM map')


def build_tune_frames(image: bytes, patches: dict, *, confirm_token: str) -> list:
    """Patch a LOCAL EEPROM image and return the list of SET PDUs that would
    apply the same changes on a bench. Chunks each page write to MAX_PAGE_WRITE."""
    if confirm_token != CONFIRM_TOKEN:
        raise PermissionError('experimental write path requires the confirmation token')
    image = bytearray(image)
    frames = []
    for off, val in sorted(patches.items()):
        if not 0 <= off < len(image):
            raise ValueError(f'patch offset {off:#x} outside image')
        page = page_for_offset(off)
        start = next(s for p, s, z in BUEIB_PAGES if p == page)
        rel = off - start
        image[off] = val & 0xFF
        frames.append(build_set_pdu(rel, page, bytes([val & 0xFF]), confirm_token=confirm_token))
    return frames
