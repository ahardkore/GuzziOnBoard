"""Zero SR/SR-F battery & ESC CAN broadcast decoder (offline, read-only).

Source: rscullin/beambreak "CAN Bus/SR_Battery.dbc" + "SR Battery CAN Bus.md"
(repo license field empty — treated as open per standing policy; facts
reimplemented and cited, not vendored, Round 28). 250 kbit/s, 29-bit extended
IDs (DBC encodes the extended flag bit 0x80000000). Passive decode only —
the upstream battery/ESC *emulator* (TX) is deliberately NOT implemented.

Known IDs (base 0x0B57ED00 | 0x0B57EDC0 | 0x0B57EDxx):
  0x0B57ED00 DLC3 battery version major/minor/point (D0-2)
  0x0B57ED01 battery serial (D0-3 LE)
  0x0B57ED0F ESC version + serial
  0x0B57ED10 lowest cell V (D0-1 LE x0.001), highest cell V (D2-3), pack V (D4-5)
  0x0B57ED14 state of charge % (D4)
  0x0B57ED1F ESC power control (D0: 0=run, 2=power off, 7=idle power off)
  0x0B57EDC0 button press count (D0 lo-nibble), BLE pair control (D1 lo-nibble)
  0x0B57ED02/03/11/12/13/15/C2 and 0x1034xxxx ESC frames: observed, undecoded.
"""
from __future__ import annotations

from collections.abc import Iterable
from .canlog import CanFrame

PROFILE = 'zero_sr_battery_can_broadcast'

# 29-bit extended IDs; DLC per DBC/docs
FRAME_LENGTHS = {
    0x0B57ED00: 3, 0x0B57ED01: 8, 0x0B57ED02: 8, 0x0B57ED03: 8,
    0x0B57ED0F: 8, 0x0B57ED10: 8, 0x0B57ED11: 8, 0x0B57ED12: 8,
    0x0B57ED13: 8, 0x0B57ED14: 8, 0x0B57ED15: 8, 0x0B57ED1F: 8,
    0x0B57EDC0: 8, 0x0B57EDC1: 8, 0x0B57EDC2: 8,
}
MAX_EVENTS = 200


def decode_frame(frame: CanFrame) -> dict | None:
    if not frame.extended or frame.id not in FRAME_LENGTHS:
        return None
    data = bytes(frame.data)
    if len(data) != FRAME_LENGTHS[frame.id]:
        return None
    fid = frame.id
    if fid == 0x0B57ED00:
        values = {'battery_version_candidate': f'{data[0]}.{data[1]}.{data[2]}'}
    elif fid == 0x0B57ED01:
        values = {'battery_serial_candidate': f'{data[0]:02X}{data[1]:02X}{data[2]:02X}{data[3]:02X}'}
    elif fid == 0x0B57ED0F:
        values = {'esc_version_candidate': f'{data[0]}.{data[1]}.{data[2]}',
                  'esc_serial_candidate': f'{data[4]:02X}{data[5]:02X}{data[6]:02X}{data[7]:02X}'}
    elif fid == 0x0B57ED10:
        values = {'lowest_cell_v_candidate': ((data[0] | (data[1] << 8)) * 0.001),
                  'highest_cell_v_candidate': ((data[2] | (data[3] << 8)) * 0.001),
                  'pack_voltage_v_candidate': ((data[4] | (data[5] << 8)) * 0.001)}
    elif fid == 0x0B57ED14:
        values = {'state_of_charge_pct_candidate': data[4]}
    elif fid == 0x0B57ED1F:
        values = {'esc_power_control_candidate': {0: 'run', 2: 'power_off', 7: 'idle_power_off'}.get(data[0], f'raw_{data[0]}')}
    elif fid == 0x0B57EDC0:
        values = {'button_press_count_candidate': data[0] & 0xF, 'ble_pair_candidate': data[1] & 0xF}
    else:
        values = {'observed_undecoded': True}
    return {'id': fid, 'values': values}


def decode_capture(frames: Iterable[CanFrame]) -> dict:
    events = []
    recognized = invalid = ignored_tx = 0
    for frame in frames:
        if not frame.extended or frame.id not in FRAME_LENGTHS:
            continue
        if frame.direction.lower().startswith('t'):
            ignored_tx += 1
            continue
        decoded = decode_frame(frame)
        if decoded is None:
            invalid += 1
            continue
        recognized += 1
        if len(events) < MAX_EVENTS:
            events.append(decoded)
    return {'profile': PROFILE, 'recognized': recognized, 'invalid': invalid,
            'ignored_tx': ignored_tx, 'events': events}
