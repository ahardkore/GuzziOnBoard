"""Yamaha YDS K-Line broadcast decoder (offline, read-only research).

Source: terrafirma2021/Yamaha-DataLogger @ pinned commit (see
docs/CAPTURE_SEARCH_2026-11-03.md Round 15); no license stated — treated as
open per the project license policy (modifiable/removable later if the
author advises otherwise). Facts reimplemented from yamaha/src/main.cpp and
YDS_Emulator.ino, cited only.

Wire: K-Line at 16040 baud 8N1. Startup/IMMO burst: 0x3E followed by ~60
bytes; if the last byte is 0xCD the ECU enters a diagnostic menu, otherwise
normal mode. Normal broadcast frames are 5 bytes with a trailing sum
checksum:

    [rpm_raw, speed_raw, error_raw, coolant_raw, csum]
    csum = (sum of the four data bytes) & 0xFF

    rpm     = rpm_raw * 50            (up to 12500 rpm)
    speed   = speed_raw               (km/h)
    coolant = coolant_raw - 30        (degC)
    error   = error_raw               (manufacturer code, raw)

The same firmware emulates ELM327/OBD-II mode 01 for apps: 010C RPM
(int16), 010D speed, 0105 coolant, 01A4 gear, plus custom 1001-1006 —
recorded here as ELM_PID_MAP for reference only.

Broadcast only — this is NOT the SDS diagnostic session and unlocks no
physical profile. Synthetic tests only.
"""
from __future__ import annotations

PROFILE = 'yamaha_yds_kline_broadcast'

BAUD = 16040
IMMO_START_BYTE = 0x3E
DIAG_MENU_END_BYTE = 0xCD
NORMAL_END_BYTE = 0xFE
FRAME_LEN = 5

#: ELM327-emulated mode-01 PID map exposed by the source firmware.
ELM_PID_MAP = {
    '010C': 'rpm int16(a:b), raw*50',
    '010D': 'vehicle speed km/h (A)',
    '0105': 'coolant degC (A), raw-30',
    '01A4': 'gear 0-6 (A)',
    '1001': 'yamaha error code (A)',
    '1002': 'MCU temp (A)', '1003': 'MCU MHz (A)', '1004': 'free RAM kb (A)',
    '1005': 'top speed (A)', '1006': 'MCU uptime s int16(a:b)',
}


def frame_checksum(data: bytes) -> int:
    return sum(bytes(data)[:4]) & 0xFF


def parse_frame(frame: bytes) -> dict:
    """Parse one 5-byte YDS broadcast frame; raises ValueError if invalid."""
    frame = bytes(frame)
    if len(frame) != FRAME_LEN:
        raise ValueError(f'YDS frame must be {FRAME_LEN} bytes, got {len(frame)}')
    if frame_checksum(frame) != frame[4]:
        raise ValueError('sum checksum mismatch')
    rpm_raw, speed_raw, error_raw, coolant_raw = frame[0], frame[1], frame[2], frame[3]
    return {
        'rpm_candidate': rpm_raw * 50,
        'speed_kmh_candidate': speed_raw,
        'error_code_raw_candidate': error_raw,
        'coolant_c_candidate': coolant_raw - 30,
        'raw': frame.hex().upper(),
    }


def classify_startup(burst: bytes) -> str:
    """Classify an IMMO/startup burst: 'diag' if it ends 0xCD, else 'normal'."""
    burst = bytes(burst)
    if not burst or burst[0] != IMMO_START_BYTE:
        raise ValueError('startup burst must begin with 0x3E')
    if burst[-1] == DIAG_MENU_END_BYTE:
        return 'diag_menu'
    if burst[-1] == NORMAL_END_BYTE:
        return 'normal'
    return 'unknown_end_byte'


def decode_capture(frames) -> dict:
    """Passive summary of a YDS K-Line capture (iterable of raw byte strings)."""
    recognized = invalid = 0
    startup = None
    last_frame = None
    frames_out = []
    for frame in frames:
        frame = bytes(frame)
        if frame and frame[0] == IMMO_START_BYTE and len(frame) > FRAME_LEN:
            startup = classify_startup(frame)
            recognized += 1
            continue
        try:
            parsed = parse_frame(frame)
        except ValueError:
            invalid += 1
            continue
        recognized += 1
        last_frame = parsed
        if len(frames_out) < 50:
            frames_out.append(parsed)
    return {'profile': PROFILE, 'recognized': recognized, 'invalid': invalid,
            'startup_mode': startup, 'last_frame': last_frame, 'frames': frames_out}
