"""Keihin KMSK16 K-Line capture decoder (offline, read-only, candidate-grade).

Source: gobftald/CCM450-diag @ 43104d2c (CCM 450 Adventure Keihin KMSK16;
same ECU family on Husqvarna 449/511 per the Husqvarna community, cited in
docs/CHECKSUM_AND_DECODER_EVIDENCE.md §4.1; EDIABAS job table
docs/KMSK16_jobs.txt transcribed from the repo). Repo license: see upstream
LICENSE; facts reimplemented and cited, nothing vendored.

Transport: K-Line 10,400 baud, KWP2000 framing (FMT 0x80|len, TGT, SRC, SID,
params, 8-bit sum checksum) — same framing as guzzionboard/klinelog.py.

Decoded (positive responses only; passive):
  0x62 + DID -> named value per the job table (raw u16 BE unless noted):
    0x1001/0x0100 rpm, 0x1002 MAP mbar, 0x1004 coolant, 0x1005 IAT,
    0x1006 throttle angle, 0x1007/0x0102 STFT, 0x1009 HEGO, 0x1012 2nd TPS,
    0x1013 battery V, 0x1020/0x0110 injector on-time us, 0x1030/0x0120 ignition
    timing, 0x0130 dwell, 0x0107 CLV (=(PM1M/10103mbar)*100), 0x0140 THREF,
    0x0142/0x0143/0x0149 lambda adaptions, 0x0170-0x0174 2nd throttle
    (0x0170 angle=(STHAD-STHADL)/(STHADH-STHADL)*100%), 0x0185 purge duty,
    0x0500 RaceMAP switch, 0x0510 high-rev counter, 0x0006/0x0000/0x0018 raw V
  0x58 -> DTC list (status byte + codes)
Write-class services (0x14 clear DTC, 0x31/0x32 routines, 0x2E/0x3B/0x3D
writes, 0x27 security access) are classified as write_class and never emitted
as decodable events. The brute-forced supplier access code is NOT shipped.
"""
from __future__ import annotations

from .klinelog import Frame, parse as parse_klinelog

PROFILE = 'kmsk16_kline_research'

WRITE_CLASS_SIDS = {0x11, 0x14, 0x27, 0x2E, 0x31, 0x32, 0x3B, 0x3D}

# DID -> (name, kind) ; kind: u16 raw, u8 raw, text
_DIDS = {
    0x1001: ('engine_rpm', 'u16'), 0x0100: ('engine_rpm_alt', 'u16'),
    0x1002: ('intake_manifold_pressure_mbar', 'u16'),
    0x1004: ('engine_coolant_temp_raw', 'u16'), 0x1005: ('intake_air_temp_raw', 'u16'),
    0x1006: ('throttle_angle_raw', 'u16'), 0x1007: ('short_term_fuel_trim', 'u16'),
    0x0102: ('short_term_fuel_trim_alt', 'u16'), 0x1009: ('heated_ego', 'u16'),
    0x1012: ('second_throttle_position_raw', 'u16'), 0x1013: ('battery_voltage_raw', 'u16'),
    0x1020: ('injector_on_time_us', 'u16'), 0x0110: ('injector_on_time_us_alt', 'u16'),
    0x1030: ('ignition_timing_raw', 'u16'), 0x0120: ('ignition_timing_raw_alt', 'u16'),
    0x0130: ('ignition_dwell_raw', 'u16'), 0x0107: ('calculated_load_raw', 'u16'),
    0x0140: ('throttle_angle_reference_raw', 'u16'),
    0x0142: ('lambda_adaption_part_load', 'u16'), 0x0143: ('lambda_adaption_idle', 'u16'),
    0x0149: ('lambda_adaption_show', 'u16'),
    0x0170: ('second_throttle_angle_raw', 'u16'), 0x0171: ('second_throttle_target_raw', 'u16'),
    0x0172: ('second_throttle_adll_raw', 'u16'), 0x0173: ('second_throttle_adhh_raw', 'u16'),
    0x0174: ('second_throttle_steps_raw', 'u16'), 0x0185: ('purge_duty_raw', 'u16'),
    0x0500: ('racemap_switch', 'u16'), 0x0510: ('high_rev_counter', 'u16'),
    0x0006: ('battery_voltage_adc_raw', 'u16'), 0x0000: ('tps_voltage_raw', 'u16'),
    0x0018: ('second_throttle_actuator_voltage_raw', 'u16'),
}

MAX_EVENTS = 200


def decode_frame(frame: Frame) -> dict | None:
    """Decode one K-Line frame; None if not a KMSK16-relevant rx frame."""
    if frame.direction != 'rx' or not frame.payload:
        return None
    sid = frame.payload[0]
    if sid in WRITE_CLASS_SIDS or (sid - 0x40) in WRITE_CLASS_SIDS:
        return {'kind': 'write_class', 'sid': sid}
    if sid == 0x62 and len(frame.payload) >= 3:
        did = (frame.payload[1] << 8) | frame.payload[2]
        data = frame.payload[3:]
        spec = _DIDS.get(did)
        values = {'did': f'0x{did:04X}', 'raw': data.hex(' ').upper()}
        if spec:
            name, kind = spec
            if kind == 'u16' and len(data) >= 2:
                values[name + '_candidate'] = (data[0] << 8) | data[1]
            elif kind == 'u8' and data:
                values[name + '_candidate'] = data[0]
        return {'kind': 'data', 'values': values}
    if sid == 0x58 and len(frame.payload) >= 2:
        return {'kind': 'dtc', 'values': {'status': frame.payload[1],
                'raw': frame.payload[2:].hex(' ').upper()}}
    if sid == 0x7F:
        return {'kind': 'negative', 'values': {'requested': frame.payload[1] if len(frame.payload) > 1 else None,
                'nrc': frame.payload[2] if len(frame.payload) > 2 else None}}
    return {'kind': 'other', 'sid': sid}


def decode_capture(source) -> dict:
    """source: klinelog text or an iterable of klinelog Frame objects."""
    frames = parse_klinelog(source) if isinstance(source, str) else list(source)
    events, write_class, invalid = [], 0, 0
    for fr in frames:
        d = decode_frame(fr)
        if d is None:
            continue
        if d['kind'] == 'write_class':
            write_class += 1
            continue
        if d['kind'] == 'other' and d['sid'] is None:
            invalid += 1
            continue
        if len(events) < MAX_EVENTS:
            d['t'] = fr.t
            events.append(d)
    return {'profile': PROFILE, 'events': events, 'write_class_frames': write_class,
            'parsed_frames': len(frames)}
