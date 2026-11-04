"""Yamaha CAN_2015 (AiM logger protocol) broadcast decoder, R1/R1M 2015+, R6 2017+.

Signal layout reimplemented from the DBC at
billyjack2/CAN-DBC-Collection, path YAMAHA/CAN_2015/can1v3.dbc, commit
6e2f88fd6cd9c1f47d0db7bd022711b106f27027 (2026-07-28). The collection ships
no root license, which per the repo license policy is treated as open for
use/modification (modifiable or removable later if advised otherwise); the
facts are reimplemented here and cited. See
docs/CAPTURE_SEARCH_2026-11-03.md (Round 13).

DBC messages (11-bit IDs, all signals little-endian ``@1+``; start bit is
the DBC Intel LSB position):

* 0x205 (8 B): wheel speed F/R, bits 8|16 and 24|16, x0.01 km/h
* 0x209 (8 B): RPM bits 8|16 x0.4; TCS_MODE 25|4; GEAR 29|3 (0=N..6);
  GEAR_RAW 32|3; POW_MODE 38|2
* 0x215 (8 B): THROTTLE 8|10 x0.15 deg; TPS_HAND 24|10 x0.145 %;
  LIFT_SET 32|2, LAUNCH_SET 34|2, SCS_SET 40|2, QSS_SET 45|2;
  intervention flags byte 7: R_ABS 56, F_ABS 57, LAUNCH 58, LIFT 59,
  SCS 60, TCS 61 (1 bit each)
* 0x226 (8 B): MAP_SEL 53|3
* 0x23E (8 B): ECT byte 0, AAT byte 1, raw*0.66-36 degC
* 0x250 (8 B): ACCX 8|16, ACCY 24|16, raw*0.001-7 g
* 0x254 (8 B): GYRO 40|16 (bytes 5-6), raw*-0.01+300 deg/s (axis unspecified)
* 0x260 (declared 9 B - invalid for classic CAN; at least one field is off
  by one byte; load with strict=False): brake pressures F_REQ 8|16,
  R_REQ 24|16, F 40|16, R 56|16, x0.1 bar. This decoder accepts both 8- and
  9-byte frames and marks the values candidate-grade.

This is the *broadcast* bus, not a diagnostic session: it does not unlock
any physical profile. Synthetic tests only; ID match or decoding does not
identify a vehicle. The r1-forum thread puts wheel speeds on 0x264 instead
of 0x205; both may be right (ABS unit vs ECU rebroadcast) - noted, not merged.
"""
from __future__ import annotations

from collections.abc import Iterable
from .canlog import CanFrame

PROFILE = 'yamaha_can2015_aim_broadcast'

#: id -> accepted payload lengths (0x260's DBC declares 9 B, impossible on
#: classic CAN, so 8 B is also accepted and flagged).
FRAME_LENGTHS = {0x205: (8,), 0x209: (8,), 0x215: (8,), 0x226: (8,),
                 0x23E: (8,), 0x250: (8,), 0x254: (8,), 0x260: (8, 9)}
MAX_EVENTS = 200

GEAR_NAMES = {0: 'N', 1: '1', 2: '2', 3: '3', 4: '4', 5: '5', 6: '6', 7: '7', 8: '8', 9: '9', 10: '-'}


def _u(raw: bytes, bit_start: int, bits: int) -> int:
    """Little-endian (Intel) unsigned field, as DBC @1+ signals use."""
    value = 0
    for i in range(bits):
        pos = bit_start + i
        if raw[pos // 8] & (1 << (pos % 8)):
            value |= 1 << i
    return value


def decode_frame(frame: CanFrame) -> dict:
    data = frame.data
    fid = frame.id
    if fid == 0x205:
        values = {'wheel_speed_f_kmh_candidate': round(_u(data, 8, 16) * 0.01, 2),
                  'wheel_speed_r_kmh_candidate': round(_u(data, 24, 16) * 0.01, 2)}
    elif fid == 0x209:
        gear = _u(data, 29, 3)
        values = {'rpm_candidate': round(_u(data, 8, 16) * 0.4, 1),
                  'tcs_mode_raw_candidate': _u(data, 25, 4),
                  'gear_raw_candidate': gear, 'gear_candidate': GEAR_NAMES.get(gear),
                  'gear_raw2_candidate': _u(data, 32, 3),
                  'pow_mode_raw_candidate': _u(data, 38, 2)}
    elif fid == 0x215:
        values = {'throttle_valve_deg_candidate': round(_u(data, 8, 10) * 0.15, 2),
                  'grip_pct_candidate': round(_u(data, 24, 10) * 0.145, 2),
                  'lift_set_candidate': _u(data, 32, 2), 'launch_set_candidate': _u(data, 34, 2),
                  'scs_set_candidate': _u(data, 40, 2), 'qss_set_candidate': _u(data, 45, 2),
                  'r_abs_intervene': _u(data, 56, 1), 'f_abs_intervene': _u(data, 57, 1),
                  'launch_intervene': _u(data, 58, 1), 'lift_intervene': _u(data, 59, 1),
                  'scs_intervene': _u(data, 60, 1), 'tcs_intervene': _u(data, 61, 1)}
    elif fid == 0x226:
        values = {'map_select_candidate': _u(data, 53, 3)}
    elif fid == 0x23E:
        values = {'coolant_c_candidate': round(data[0] * 0.66 - 36, 2),
                  'air_temp_c_candidate': round(data[1] * 0.66 - 36, 2)}
    elif fid == 0x250:
        values = {'accel_x_g_candidate': round(_u(data, 8, 16) * 0.001 - 7, 3),
                  'accel_y_g_candidate': round(_u(data, 24, 16) * 0.001 - 7, 3)}
    elif fid == 0x254:
        values = {'gyro_degs_candidate': round(_u(data, 40, 16) * -0.01 + 300, 2),
                  'gyro_axis': 'unspecified in DBC'}
    elif fid == 0x260:
        # DBC declares 9 bytes; on classic CAN only 8 arrive, so the last
        # field (bits 56-71, reaching byte 8) may be truncated.
        values = {'brake_f_req_bar_candidate': round(_u(data, 8, 16) * 0.1, 1),
                  'brake_r_req_bar_candidate': round(_u(data, 24, 16) * 0.1, 1),
                  'brake_f_bar_candidate': round(_u(data, 40, 16) * 0.1, 1),
                  'brake_r_bar_candidate': round(_u(data, 56, 16) * 0.1, 1) if len(data) >= 9 else None,
                  'declared_9byte_caveat': True}
    else:  # pragma: no cover - guarded by FRAME_LENGTHS
        raise ValueError(f'unknown id 0x{fid:X}')
    return {'id': fid, 'message': f'YAMAHA_CAN_2015_{fid:03X}', 'values': values}


def decode_capture(frames: Iterable[CanFrame]) -> dict:
    events = []
    recognized = invalid = ignored_tx = 0
    for frame in frames:
        if frame.extended or frame.id not in FRAME_LENGTHS:
            continue
        if frame.direction.lower().startswith('t'):
            ignored_tx += 1
            continue
        if len(frame.data) not in FRAME_LENGTHS[frame.id]:
            invalid += 1
            continue
        recognized += 1
        if len(events) < MAX_EVENTS:
            events.append(decode_frame(frame))
    return {'profile': PROFILE, 'recognized_frames': recognized,
            'invalid_frames': invalid, 'ignored_tx_frames': ignored_tx,
            'events': events}
