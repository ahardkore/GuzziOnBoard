"""Energica Eva Ribelle (2021) BMS broadcast CAN candidates.

Layouts reimplemented from danieltroger/cool-eva (src/can/decode-bms.ts and
CAN_MAP.md), whose author read them out of the bike's own decrypted BMS
configuration cross-referenced with the LiBAL application manual - see
docs/CAPTURE_SEARCH_2026-11-03.md for the pinned source. All frames big-endian
unless noted. Passive broadcast only; cool-eva also transmits standard OBD-II
*read* requests, but nothing here is a diagnostic session and nothing here
identifies a vehicle. Synthetic tests only.

Frames (8-byte, 11-bit):

* 0x200 (20 Hz): b0/b3 pack temp lo/hi as seen by VCU (signed), b1 SOC %,
  b2 SOH %, b4-5 pack volts /10, b6-7 pack amps signed /10
* 0x201 (10 Hz): b0 system state bitfield (bit0 discharge, bit4 idle),
  b1-4 error flags BE32, b5-7 warning flags BE24
* 0x202 (10 Hz): b4-5 allowed discharge A /10, b6-7 allowed regen A /10
  (b0-3 are config constants, not live data)
* 0x203 (20 Hz): b0-1 avg cell mV, b2 lowest-cell index, b3 highest-cell
  index, b4-5 min cell mV, b6-7 max cell mV
* 0x205 (1 Hz): b0-1 remaining energy raw, b2-3 cell deviation mV
* 0x660-0x665: extended-config frames (pack temps, energy Wh, cell
  voltages/temps multiplexed at 0x662-0x664, cell limits at 0x665) - present
  only with the extended BMS config flashed; layout kept as raw candidates.
"""
from __future__ import annotations

from collections.abc import Iterable
from .canlog import CanFrame

PROFILE = 'energica_eva_bms'

KNOWN_IDS = {0x200, 0x201, 0x202, 0x203, 0x205, 0x660, 0x661, 0x662, 0x663, 0x664, 0x665}
EXTENDED_IDS = {0x660, 0x661, 0x662, 0x663, 0x664, 0x665}
MAX_EVENTS = 200


def _u16be(data: bytes, off: int) -> int:
    return (data[off] << 8) | data[off + 1]


def _i16be(data: bytes, off: int) -> int:
    v = _u16be(data, off)
    return v - 0x10000 if v >= 0x8000 else v


def _s8(v: int) -> int:
    return v - 0x100 if v >= 0x80 else v


def decode_frame(frame_id: int, data: bytes) -> dict | None:
    """Decode one BMS frame; None if the ID/length is not a known layout."""
    if len(data) != 8 or frame_id not in KNOWN_IDS:
        return None
    if frame_id == 0x200:
        return {'batt_temp_lo_vcu_c': _s8(data[0]), 'soc_percent': data[1],
                'soh_percent': data[2], 'batt_temp_hi_vcu_c': _s8(data[3]),
                'pack_v': _u16be(data, 4) / 10, 'pack_a': _i16be(data, 6) / 10}
    if frame_id == 0x201:
        err = int.from_bytes(data[1:5], 'big')
        warn = int.from_bytes(data[5:8], 'big')
        return {'charge_state_raw': data[0],
                'bms_discharge': 1 if data[0] & 0x01 else 0,
                'bms_idle': 1 if data[0] & 0x10 else 0,
                'bms_error_flags_raw': err, 'bms_warning_flags_raw': warn,
                'err_cell_overvoltage': 1 if err & 0x1 else 0,
                'err_cell_undervoltage': 1 if err & 0x2 else 0,
                'err_leak_detected': 1 if err & 0x10000 else 0,
                'err_leak_detect_failed': 1 if err & 0x20000 else 0,
                'warn_low_soc': 1 if warn & 0x10000 else 0,
                'warn_balancing_required': 1 if warn & 0x20000 else 0}
    if frame_id == 0x202:
        return {'allowed_discharge_a': _u16be(data, 4) / 10,
                'allowed_regen_a': _u16be(data, 6) / 10}
    if frame_id == 0x203:
        return {'cell_avg_mv': _u16be(data, 0), 'cell_lowest_v_idx': data[2],
                'cell_highest_v_idx': data[3], 'cell_min_mv': _u16be(data, 4),
                'cell_max_mv': _u16be(data, 6), 'cell_spread_mv': _u16be(data, 6) - _u16be(data, 4)}
    if frame_id == 0x205:
        return {'bms_remaining_energy_raw': _u16be(data, 0),
                'cell_deviation_mv': _u16be(data, 2)}
    # 0x660-0x665: extended-config frames; only raw candidates are committed.
    return {'extended_config_frame': True}


def decode_capture(frames: Iterable[CanFrame]) -> dict:
    events = []
    recognized = invalid = ignored_tx = 0
    for frame in frames:
        if frame.extended or frame.id not in KNOWN_IDS:
            continue
        if frame.direction.lower().startswith('t'):
            ignored_tx += 1
            continue
        values = decode_frame(frame.id, frame.data)
        if values is None:
            invalid += 1
            continue
        recognized += 1
        if len(events) < MAX_EVENTS:
            events.append({'timestamp': frame.timestamp, 'id': f'0x{frame.id:X}',
                           'direction': frame.direction or 'unknown', 'raw': frame.data.hex().upper(),
                           'values': values})
    return {'profile': PROFILE, 'events': events, 'recognized_frames': recognized,
            'invalid_length_frames': invalid, 'ignored_tx_frames': ignored_tx,
            'omitted_events': max(0, recognized - len(events))}
