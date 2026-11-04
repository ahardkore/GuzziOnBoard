"""Yamaha MT-07 (2014) broadcast CAN observation candidates, not ECU diagnostics.

Adapted from JackHat1/MT07_CAN_Project (ESP32 + MCP2515, 500 kbps),
commit fec86c3da7a05b099e9259b1142980f339b3fa92, MIT License
(Copyright (c) 2024 Andreas Panagiotakis) - see LICENSES note in
docs/CAPTURE_SEARCH_2026-11-03.md. The source ships decode code only, no raw
capture; every value below is a per-frame candidate, exactly as the source's
getter functions compute them. Synthetic integration tests only. Source
measurements describe one MT-07, not all Yamaha motorcycles. Neither ID match
nor decoding identifies a vehicle, and nothing here is a diagnostic session.
"""
from __future__ import annotations

from collections.abc import Iterable
from .canlog import CanFrame

PROFILE = 'yamaha_mt07_2014'

#: CAN IDs from MT07_CAN_Library.h (fec86c3).
GEAR_POSITION_ID = 0x236
TPS_ID = 0x216
TEMP_ID = 0x23E
RPM_SPEED_ID = 0x20A
FRAME_LENGTHS = {GEAR_POSITION_ID: 8, TPS_ID: 8, TEMP_ID: 8, RPM_SPEED_ID: 8}

GEAR_MAP = {0x00: 'N', 0x20: '1', 0x40: '2', 0x60: '3', 0x80: '4', 0xA0: '5', 0xC0: '6'}

MAX_EVENTS = 200


def _gear(data: bytes) -> str:
    return GEAR_MAP.get(data[0], 'unknown')


def decode_capture(frames: Iterable[CanFrame]) -> dict:
    events = []
    recognized = invalid = ignored_tx = 0
    for frame in frames:
        if frame.extended or frame.id not in FRAME_LENGTHS:
            continue
        if frame.direction.lower().startswith('t'):
            ignored_tx += 1
            continue
        data = frame.data
        if len(data) != FRAME_LENGTHS[frame.id]:
            invalid += 1
            continue
        if frame.id == GEAR_POSITION_ID:
            values = {'gear_candidate': _gear(data)}
        elif frame.id == TPS_ID:
            values = {'tps_percent_candidate': round(data[0] / 255.0 * 100.0, 2)}
        elif frame.id == TEMP_ID:
            motor_raw, air_raw = data[0], data[1]
            motor = 'LO' if motor_raw < 0x70 else 'HI' if motor_raw > 0xEA else round((motor_raw - 0x70) * 0.625 + 40, 2)
            air = 'LO' if air_raw < 0x21 else 'HI' if air_raw > 0xCF else round((air_raw - 0x30) * 0.625, 2)
            values = {'motor_temp_c_candidate': motor, 'air_temp_c_candidate': air}
        else:  # RPM_SPEED_ID
            values = {'rpm_candidate': data[2] * 100 + data[3],
                      'speed_kmh_candidate': round(data[2] * 0.75, 2)}
        recognized += 1
        if len(events) < MAX_EVENTS:
            events.append({'timestamp': frame.timestamp, 'id': f'0x{frame.id:X}',
                           'direction': frame.direction or 'unknown', 'raw': data.hex().upper(),
                           'values': values})
    return {'profile': PROFILE, 'events': events, 'recognized_frames': recognized,
            'invalid_length_frames': invalid, 'ignored_tx_frames': ignored_tx,
            'omitted_events': max(0, recognized - len(events))}
