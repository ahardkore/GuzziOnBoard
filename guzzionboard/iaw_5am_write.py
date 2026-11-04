"""IAW 5AM experimental write builders (offline, token-gated, no transport).

Source: denandz/5am_util main.c (write path + SecurityAccess algorithm),
transcribed in docs/PRIOR_ART.md §1.1-1.3; encoder/checksum in firmware.py.
The upstream author reports successful IAW 5AM writes (incl. a Guzzi 5AM),
so per the write-class rule this is adopted as [experimental] frame builders.

Every function requires CONFIRM_TOKEN and returns frame BYTES or a patched
LOCAL IMAGE — nothing here opens a transport, talks to an ECU, or erases
anything. The immobilizer is NOT in this ECU (it lives in the dash on
5AM-era Guzzis) and is not touched by any of this; immobilizer material
remains citation-only with a legal-use-only disclaimer.

Documented write sequence (5AM, KWP2000, ECU 0x10 / tester 0xF1):
  85 03 session -> 38400 baud -> 03 1E 02 0A 14 00 timing -> 27 01/02 key
  -> 3B 98 20 (writer id) -> 3B 99 20 <date> -> 31 02 erase arm -> 33 02 erase
  -> 34 RequestDownload -> 36 chunks (254 B) -> 37 exit
  -> 31 01 program arm + checksum16 -> 33 01 program
"""
from __future__ import annotations

from .experimental_writers import CONFIRM_TOKEN, _gate, _kwp2000_frame
from . import firmware, security

PROFILE = 'iaw_5am_experimental_write'

ECU_ADDRESS = 0x10
TESTER_ADDRESS = 0xF1
# single-byte KWP length field caps payload at 254 incl. SID: 2 hdr bytes -> 252 data bytes per 36 frame
TRANSFER_CHUNK = 252


def iaw5am_key_from_seed(seed: bytes, *, confirm_token: str) -> bytes:
    """SecurityAccess key for a 4-byte seed, via the cited 5am_util algorithm."""
    _gate(confirm_token)
    provider = security.best_provider('5am', allow_unverified=True)
    return provider(bytes(seed))


def write_session_frames(*, confirm_token: str) -> list[bytes]:
    """Start write diagnostic session + access-timing parameters."""
    _gate(confirm_token)
    return [
        _kwp2000_frame(0x85, b'\x03', address=TESTER_ADDRESS, target=ECU_ADDRESS, confirm_token=confirm_token),
        _kwp2000_frame(0x83, b'\x1E\x02\x0A\x14\x00', address=TESTER_ADDRESS, target=ECU_ADDRESS, confirm_token=confirm_token),
    ]


def security_access_frames(seed: bytes, *, confirm_token: str) -> list[bytes]:
    """27 01 requestSeed / 27 02 sendKey (key derived by iaw5am_key_from_seed)."""
    _gate(confirm_token)
    key = iaw5am_key_from_seed(seed, confirm_token=confirm_token)
    return [
        _kwp2000_frame(0x27, b'\x01', address=0x01, target=ECU_ADDRESS, confirm_token=confirm_token),
        _kwp2000_frame(0x27, b'\x02' + key, address=0x01, target=ECU_ADDRESS, confirm_token=confirm_token),
    ]


def identification_frames(tester_code: bytes, reflash_date: bytes, *, confirm_token: str) -> list[bytes]:
    """3B 98 20 writer identification + 3B 99 20 reflash date (e.g. b'20180101')."""
    _gate(confirm_token)
    return [
        _kwp2000_frame(0x3B, b'\x98\x20' + bytes(tester_code), address=TESTER_ADDRESS, target=ECU_ADDRESS, confirm_token=confirm_token),
        _kwp2000_frame(0x3B, b'\x99\x20' + bytes(reflash_date), address=TESTER_ADDRESS, target=ECU_ADDRESS, confirm_token=confirm_token),
    ]


def erase_frames(*, confirm_token: str) -> list[bytes]:
    """31 02 erase-routine arm + 33 02 execute (physical erase NOT performed here)."""
    _gate(confirm_token)
    return [
        _kwp2000_frame(0x31, b'\x02\x00\x40\x00\x04\xFF\xFF', address=TESTER_ADDRESS, target=ECU_ADDRESS, confirm_token=confirm_token),
        _kwp2000_frame(0x33, b'\x02', address=TESTER_ADDRESS, target=ECU_ADDRESS, confirm_token=confirm_token),
    ]


def download_frame(address: int, size: int, *, confirm_token: str) -> bytes:
    """34 RequestDownload for the flash region (default 0x4000, 0x4C000)."""
    _gate(confirm_token)
    return _kwp2000_frame(0x34, b'\x00\x40\x00' + address.to_bytes(3, 'big') + size.to_bytes(3, 'big'),
                          address=TESTER_ADDRESS, target=ECU_ADDRESS, confirm_token=confirm_token)


def transfer_data_frames(blob: bytes, *, confirm_token: str) -> list[bytes]:
    """36 TransferData frames, chunked with block counters (252 data bytes each to fit the length byte)."""
    _gate(confirm_token)
    blob = bytes(blob)
    frames = []
    counter = 1
    for off in range(0, len(blob), TRANSFER_CHUNK):
        chunk = blob[off:off + TRANSFER_CHUNK]
        frames.append(_kwp2000_frame(0x36, bytes([len(chunk) + 1, counter & 0xFF]) + chunk,
                                     address=TESTER_ADDRESS, target=ECU_ADDRESS, confirm_token=confirm_token))
        counter += 1
    return frames


def program_frames(checksum16: int, *, confirm_token: str) -> list[bytes]:
    """31 01 program-routine arm with checksum16 + 33 01 execute."""
    _gate(confirm_token)
    return [
        _kwp2000_frame(0x31, b'\x01\x00\x40\x00\x04\xFF\xFF' + checksum16.to_bytes(2, 'big'),
                       address=TESTER_ADDRESS, target=ECU_ADDRESS, confirm_token=confirm_token),
        _kwp2000_frame(0x33, b'\x01', address=TESTER_ADDRESS, target=ECU_ADDRESS, confirm_token=confirm_token),
    ]


def patch_local_image(image: bytes, offset: int, data: bytes, *, confirm_token: str) -> dict:
    """Patch bytes into a LOCAL IAW 5AM image copy and recompute the upload
    checksum. Returns dict; never touches an ECU. Image must be >= 0x50000."""
    _gate(confirm_token)
    image = bytes(image)
    if len(image) < firmware.IAW5AM_DEVICE_SIZE:
        raise ValueError('image too small for IAW 5AM flash region')
    if not (0 <= offset and offset + len(data) <= len(image)):
        raise ValueError('patch outside image bounds')
    patched = bytearray(image)
    patched[offset:offset + len(data)] = data
    patched = bytes(patched)
    return {'image': patched, 'upload_blob': firmware.iaw5am_upload_blob(patched),
            'checksum16': firmware.iaw5am_upload_checksum(patched), 'offset': offset, 'length': len(data)}


def full_write_plan(image: bytes, seed: bytes, tester_code: bytes = b'GuzziOnBoard',
                    reflash_date: bytes = b'20180101', *, confirm_token: str) -> list[bytes]:
    """Ordered experimental frame list for the documented 5AM write sequence."""
    _gate(confirm_token)
    blob = firmware.iaw5am_upload_blob(image)
    frames = write_session_frames(confirm_token=confirm_token)
    frames += security_access_frames(seed, confirm_token=confirm_token)
    frames += identification_frames(tester_code, reflash_date, confirm_token=confirm_token)
    frames += erase_frames(confirm_token=confirm_token)
    frames.append(download_frame(0x4000, 0x4C000, confirm_token=confirm_token))
    frames += transfer_data_frames(blob, confirm_token=confirm_token)
    frames.append(_kwp2000_frame(0x37, b'', address=TESTER_ADDRESS, target=ECU_ADDRESS, confirm_token=confirm_token))
    frames += program_frames(firmware.iaw5am_upload_checksum(image), confirm_token=confirm_token)
    return frames
