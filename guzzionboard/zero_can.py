"""Zero motorcycle broadcast CAN observation candidates, not ECU diagnostics.

Message ID table and field offsets reimplemented from
RIAEvangelist/zero-motorcycle-canbus (libraries/ZERO_MOTORCYCLE/Network.h and
ZERO.cpp), MIT License, commits 2704ac4864b366736d6ea56657457e8dbc648b29 /
2d9cac6d87b9c9a3a7028e46b2a0dc28d6cd70c8 - see
docs/CAPTURE_SEARCH_2026-11-03.md. The source ships discovery code only, no
raw capture; field offsets below are the library's own getters, and every
value is a candidate. 8-byte frames, 11-bit IDs, 500 kbps class bus.
Passive broadcast only; ID match or decoding does not identify a vehicle.

Nodes/IDs (from Network.h):

* controller: 0x181 speed/torque, 0x281 RPM/throttle/motor temp,
  0x381 temps/digital in, 0x481 volt/mod/inductance/temp est,
  0x501 target vel/max IQ/cont volt, 0x205 drive control (RPD)
* dash: 0x1C0 status, 0x2C0 odo, 0x3C0 odo-to-dash, 0x440 status2,
  0x540 status3 (trip/range/temp, wh/km)
* BMS0: 0x188 pack status, 0x288 pack config (sag adjust b0-1),
  0x308 pack stats, 0x388 cell voltage, 0x408 pack active data (amps b3-4),
  0x488 pack temp data, 0x508 pack time, 0x506 control (RPD)
* BMS1 (Power Tank): same +1 (0x189...0x509)
* charger (Calex): 0x192 charge status, 0x292 max charge V/I (T),
  0x206 charge control (RPD), 0x306 max charge V/I (R), 0x406 taper current

Library getter offsets used here: throttle = u16le at b4-5 of 0x281;
ulier amps = u16le at b3-4 of 0x408/0x409; cell/pack voltage = u32le at b3-6
of 0x388/0x389; sag adjust = u16le at b0-1 of 0x288/0x289.
"""
from __future__ import annotations

from collections.abc import Iterable
from .canlog import CanFrame

PROFILE = 'zero_broadcast'

MESSAGES = {
    0x181: 'CONTROLLER_SPEED_TORQUE', 0x281: 'CONTROLLER_RPM_THROTTLE_MOT_TEMP',
    0x381: 'CONTROLLER_TEMP_DIGITAL_IN_18', 0x481: 'CONTROLLER_VOLT_MOD_INDUCTANCE_TEMP_EST',
    0x501: 'CONTROLLER_TARGET_VEL_MAX_IQ_CONT_VOLT', 0x205: 'CONTROLLER_DRIVE_CONTROL',
    0x1C0: 'DASH_STATUS', 0x2C0: 'DASH_ODO_FROM_DASH', 0x3C0: 'DASH_ODO_TO_DASH',
    0x440: 'DASH_STATUS2', 0x540: 'DASH_STATUS3',
    0x188: 'BMS_PACK_STATUS', 0x288: 'BMS_PACK_CONFIG', 0x308: 'BMS_PACK_STATS',
    0x388: 'BMS_CELL_VOLTAGE', 0x408: 'BMS_PACK_ACTIVE_DATA', 0x488: 'BMS_PACK_TEMP_DATA',
    0x508: 'BMS_PACK_TIME', 0x506: 'BMS_CONTROL',
    0x189: 'BMS1_PACK_STATUS', 0x289: 'BMS1_PACK_CONFIG', 0x309: 'BMS1_PACK_STATS',
    0x389: 'BMS1_CELL_VOLTAGE', 0x409: 'BMS1_PACK_ACTIVE_DATA', 0x489: 'BMS1_PACK_TEMP_DATA',
    0x509: 'BMS1_PACK_TIME',
    0x192: 'CALEX_CHARGE_STATUS', 0x292: 'T_CALEX_MAX_CHARGE_VOLTAGE_CURRENT',
    0x206: 'CALEX_CHARGE_CONTROL', 0x306: 'R_CALEX_MAX_CHARGE_VOLTAGE_CURRENT',
    0x406: 'CALEX_TAPER_CUTOFF_CURRENT',
}

MAX_EVENTS = 200


def _u16le(data: bytes, off: int) -> int:
    return data[off] | (data[off + 1] << 8)


def _u32le(data: bytes, off: int) -> int:
    return int.from_bytes(data[off:off + 4], 'little')


def decode_frame(frame_id: int, data: bytes) -> dict | None:
    """Decode one Zero frame; known IDs get their library field candidates."""
    if len(data) != 8 or frame_id not in MESSAGES:
        return None
    values: dict = {'message': MESSAGES[frame_id]}
    if frame_id == 0x281:
        values['throttle_raw_candidate'] = _u16le(data, 4)
    elif frame_id in (0x408, 0x409):
        values['amps_raw_candidate'] = _u16le(data, 3)
    elif frame_id in (0x388, 0x389):
        values['voltage_raw_candidate'] = _u32le(data, 3)
    elif frame_id in (0x288, 0x289):
        values['sag_adjust_raw_candidate'] = _u16le(data, 0)
    return values


def decode_capture(frames: Iterable[CanFrame]) -> dict:
    events = []
    recognized = invalid = ignored_tx = 0
    for frame in frames:
        if frame.extended or frame.id not in MESSAGES:
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
