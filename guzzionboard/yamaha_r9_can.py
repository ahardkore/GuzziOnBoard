"""2026 Yamaha R9 CAN observation candidates, not ECU diagnostics.

Adapted from motocan bluecan/firmware/bluecan/src/canbus/r9.hpp and
analysis/r9.dbc, commit acdb1464e327363a7be52a53134f34d0ca2d4e62.
Copyright (c) 2026 DeziderMesko, MIT; see LICENSES/MotoCAN-MIT.txt.
Synthetic integration tests only. Source measurements describe one R9, not
all Yamaha motorcycles. Neither ID match nor decoding identifies a vehicle.
"""
from __future__ import annotations

from collections.abc import Iterable
from .canlog import CanFrame

PROFILE = 'yamaha_r9_2026'
FRAME_LENGTHS = {0x27C: 7, 0x512: 4}
MAX_EVENTS = 200


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
        if frame.id == 0x27C:
            values = {'rpm_candidate': ((data[0] * 256 + data[1]) * 100) // 256,
                      'gear_raw_candidate': data[4] & 7,
                      'tcs_setting_candidate': (data[3] >> 1) & 15,
                      'pwr_setting_candidate': (data[4] >> 6) + 1}
        else:
            values = {'coolant_c_candidate': ((data[0] * 25) // 4 - 300) / 10,
                      'air_c_candidate': ((data[1] * 25) // 4 - 300) / 10}
        recognized += 1
        if len(events) < MAX_EVENTS:
            events.append({'timestamp': frame.timestamp, 'id': f'0x{frame.id:X}',
                           'direction': frame.direction or 'unknown', 'raw': data.hex().upper(),
                           'values': values})
    return {'profile': PROFILE, 'events': events, 'recognized_frames': recognized,
            'invalid_length_frames': invalid, 'ignored_tx_frames': ignored_tx,
            'omitted_events': max(0, recognized - len(events))}
