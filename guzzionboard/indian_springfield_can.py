"""Indian Springfield 2017 J1939 broadcast candidates; not ECU diagnosis.

Adapted from firmware/src/main.cpp, Prinsessen/indian-thunderstroke-canbus,
commit 15799596e463 (Copyright (c) 2026 Nanna Agesen, MIT). See
LICENSES/Indian-Thunderstroke-CAN-MIT.txt. One source bike; integration tested
with synthetic frames only. Frames may vary between ECUs and motorcycles.
"""
from __future__ import annotations

from .canlog import CanFrame

# PGN and source address, without CAN priority. Extended J1939 only.
PGN_SOURCE = {(61444, 0), (65262, 0), (65265, 11), (65276, 0), (65215, 11)}
MASK = 0x03FFFFFF
FILTER_IDS = {(pgn << 8) | source for pgn, source in PGN_SOURCE}


def decode_capture(frames):
    events = []
    for frame in frames:
        if not frame.extended or frame.direction.lower().startswith('t') or len(frame.data) != 8:
            continue
        key = frame.id & MASK
        if key not in FILTER_IDS:
            continue
        pgn, source = key >> 8, key & 0xff
        d = frame.data
        if pgn == 61444:
            raw = d[3] | d[4] << 8
            values = {'rpm_candidate': None if raw == 0xffff else raw / 8,
                      'engine_demand_percent_candidate': None if d[7] == 0xff else d[7] - 125}
        elif pgn == 65262:
            # This source motorcycle is air-cooled; upstream calls this
            # cylinder-head temperature, not coolant or oil temperature.
            values = {'cylinder_head_c_candidate': None if d[0] == 0xff else d[0] - 40}
        elif pgn == 65276:
            values = {'fuel_percent_candidate': None if d[1] == 0xff else d[1] * 0.4}
        else:
            raw = (d[1] | d[2] << 8) if pgn == 65265 else (d[0] | d[1] << 8)
            field = 'rear_speed_kmh_candidate' if pgn == 65265 else 'front_speed_kmh_candidate'
            values = {field: None if raw == 0xffff else raw / 256}
        events.append({'timestamp': frame.timestamp, 'id': f'0x{frame.id:X}',
                       'direction': frame.direction or 'unknown', 'raw': d.hex().upper(),
                       'pgn': pgn, 'source_address': source, 'values': values})
    return events
