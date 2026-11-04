"""Buell XB12X IDS DDFI-2 serial PDU decoder (offline, read-only research).

Source: pacdavid1/buell-xb12x-logger, MIT license (LICENSES/
Buell-XB12X-Logger-MIT.txt), commit pinned in docs/CAPTURE_SEARCH_2026-11-03.md
(Round 12). Protocol reference: docs/10_DDFI2_PROTOCOL.md; RT field table:
ecu_defs/rtdata.xml (DDFI-2 rtoffsets) as normalized by ecu/rt_defs.py.

PDU envelope (9600 8N1 serial, both directions):

    SOH 0x01  SRC  DST  LEN=N+1  EOH 0xFF  SOT 0x02  PAYLOAD(N)  EOT 0x03  XOR-CS
    checksum = XOR of all bytes from SRC through EOT (i.e. frame[1:-1])

Tester->ECU uses SRC 0x00 (DROID) / DST 0x42 (ECM); ECU replies swap them.
Commands: GET 0x52 read EEPROM chunk, VERSION 0x56, RT_DATA 0x43 real-time
block, ACK 0x06. CMD_SET 0x57 (EEPROM write) exists in the source but is a
write operation and is deliberately NOT implemented here.

This module only parses/decodes already-captured frames. It grants no
physical session and no write capability.
"""
from __future__ import annotations

PROFILE = 'buell_xb12x_ddfi2_serial'

SOH, EOH, SOT, EOT, ACK = 0x01, 0xFF, 0x02, 0x03, 0x06
TESTER_ID, ECM_ID = 0x00, 0x42
CMD_GET, CMD_SET, CMD_VERSION, CMD_RT_DATA = 0x52, 0x57, 0x56, 0x43

#: DDFI-2 real-time frame fields from ecu_defs/rtdata.xml (name -> offset,
#: nbytes, scale, translate); 2-byte fields are little-endian. Names follow
#: the source's ecu/rt_defs.py normalization/overrides.
RT_VARS: dict[str, tuple[int, int, float, float]] = {
    'SysConfig': (7, 1, 1.0, 0.0), 'MilliSec': (8, 1, 0.01, 0.0),
    'Seconds': (9, 2, 1.0, 0.0), 'RPM': (11, 2, 1.0, 0.0),
    'spark1': (13, 2, 0.0025, 0.0), 'spark2': (15, 2, 0.0025, 0.0),
    'veCurr1_RAW': (17, 2, 1.0, 0.0), 'veCurr1': (17, 2, 0.026666, 0.0),
    'veCurr2_RAW': (19, 2, 1.0, 0.0), 'veCurr2': (19, 2, 0.026666, 0.0),
    'pw1': (21, 2, 0.00133, 0.0), 'pw2': (23, 2, 0.00133, 0.0),
    'TPD': (25, 2, 0.1, 0.0), 'Load': (27, 1, 1.0, 0.0),
    'Batt_V': (28, 2, 0.01, 0.0), 'CLT': (30, 2, 0.1, -40.0),
    'CLT_F': (30, 2, 0.18, -40.0), 'MAT': (32, 2, 0.1, -40.0),
    'MAT_F': (32, 2, 0.18, -40.0), 'O2_ADC': (34, 2, 1.0, 0.0),
    'O2': (34, 2, 0.004887585, 0.0), 'Batt_Corr': (36, 2, 0.00133, 0.0),
    'WUE': (38, 2, 0.1, 0.0), 'IAT_Corr': (40, 2, 0.1, 0.0),
    'Accel_Corr': (42, 2, 0.1, 0.0), 'Decel_Corr': (44, 2, 0.1, 0.0),
    'WOT_Corr': (46, 2, 0.1, 0.0), 'Idle_Corr': (48, 2, 0.1, 0.0),
    'OL_Corr': (50, 2, 0.1, 0.0), 'AFV': (52, 2, 0.1, 0.0),
    'EGO_Corr': (54, 2, 0.1, 0.0), 'Flags0': (56, 1, 1.0, 0.0),
    'Flags1': (57, 1, 1.0, 0.0), 'Flags2': (58, 1, 1.0, 0.0),
    'Flags3': (59, 1, 1.0, 0.0), 'Flags4': (60, 1, 1.0, 0.0),
    'Flags5': (61, 1, 1.0, 0.0), 'Flags6': (62, 1, 1.0, 0.0),
    'Unk63': (63, 1, 1.0, 0.0), 'BAS_ADC': (65, 2, 1.0, 0.0),
    'BAS_V': (65, 2, 0.004887585, 0.0), 'CDiag0': (67, 1, 1.0, 0.0),
    'CDiag1': (68, 1, 1.0, 0.0), 'CDiag2': (69, 1, 1.0, 0.0),
    'CDiag3': (70, 1, 1.0, 0.0), 'HDiag0': (75, 1, 1.0, 0.0),
    'HDiag1': (76, 1, 1.0, 0.0), 'HDiag2': (77, 1, 1.0, 0.0),
    'HDiag3': (78, 1, 1.0, 0.0), 'Unk79': (79, 1, 1.0, 0.0),
    'Unk80': (80, 1, 1.0, 0.0), 'Unk81': (81, 1, 1.0, 0.0),
    'Unk82': (82, 1, 1.0, 0.0), 'Rides': (83, 1, 1.0, 0.0),
    'DOut': (84, 1, 1.0, 0.0), 'DIn': (85, 1, 1.0, 0.0),
    'Coil1_ADC': (86, 1, 1.0, 0.0), 'Coil2_ADC': (87, 1, 1.0, 0.0),
    'Inj1_ADC': (88, 1, 1.0, 0.0), 'Inj2_ADC': (89, 1, 1.0, 0.0),
    'TPS_10Bit': (90, 2, 1.0, 0.0), 'TPS_V': (90, 2, 0.004887585, 0.0),
    'Batt_ADC': (92, 2, 1.0, 0.0), 'ETS_ADC': (94, 1, 1.0, 0.0),
    'ETS_V': (94, 1, 0.019607843, 0.0), 'IAT_ADC': (95, 1, 1.0, 0.0),
    'IAT_V': (95, 1, 0.019607843, 0.0), 'FPp_ADC': (96, 1, 1.0, 0.0),
    'Fan_ADC': (97, 1, 1.0, 0.0), 'Fan_Duty_Pct': (98, 1, 1.0, 0.0),
    'VSS_Count': (99, 1, 1.0, 0.0), 'VSS_RPM_Ratio': (100, 1, 1.0, 0.0),
    'CDiag4': (101, 1, 1.0, 0.0), 'HDiag4': (103, 1, 1.0, 0.0),
}

#: Real-time response size in bytes (max offset+size from rtdata.xml).
RT_RESPONSE_SIZE = 104

#: BUEIB EEPROM page map (docs/10_DDFI2_PROTOCOL.md section 5).
BUEIB_PAGES = [(1, 0, 256), (2, 256, 256), (3, 512, 158),
               (4, 670, 256), (5, 926, 256), (6, 1182, 24)]


def checksum(frame: bytes) -> int:
    """XOR of every byte after SOH through EOT (frame[1:-1])."""
    cs = 0
    for b in bytes(frame)[1:-1]:
        cs ^= b
    return cs & 0xFF


def parse_pdu(frame: bytes) -> dict:
    """Parse one DDFI-2 PDU; raises ValueError on shape/checksum mismatch."""
    frame = bytes(frame)
    if len(frame) < 9:
        raise ValueError('DDFI-2 PDU too short (<9 bytes)')
    if frame[0] != SOH or frame[4] != EOH or frame[5] != SOT or frame[-2] != EOT:
        raise ValueError('bad DDFI-2 envelope markers')
    if {frame[1], frame[2]} != {TESTER_ID, ECM_ID}:
        raise ValueError('addresses are not the 0x00/0x42 DDFI-2 pair')
    if len(frame) != frame[3] + 7:   # LEN = payload bytes + 1; total = 6 hdr + N + EOT + CS
        raise ValueError(f'length byte {frame[3]} does not match frame size {len(frame)}')
    if checksum(frame) != frame[-1]:
        raise ValueError('XOR checksum mismatch')
    direction = 'to_ecu' if frame[2] == ECM_ID else 'from_ecu'
    return {'direction': direction, 'payload': frame[6:-2],
            'raw': frame.hex().upper()}


def decode_rt_response(frame: bytes) -> dict:
    """Decode an RT_DATA (0x43) ACK response into scaled candidate values."""
    parsed = parse_pdu(frame)
    if parsed['direction'] != 'from_ecu':
        raise ValueError('not an ECU response')
    payload = parsed['payload']
    if not payload or payload[0] != ACK:
        raise ValueError('RT response must start with ACK 0x06')
    if len(frame) < RT_RESPONSE_SIZE:
        raise ValueError(f'RT response too short (<{RT_RESPONSE_SIZE} bytes)')
    out: dict = {'raw': parsed['raw'], 'vars': {}}
    for name, (off, nbytes, scale, translate) in RT_VARS.items():
        if off + nbytes > len(frame):
            out['vars'][name] = None
            continue
        raw = (frame[off] | (frame[off + 1] << 8)) if nbytes == 2 else frame[off]
        out['vars'][name] = round(raw * scale + translate, 4)
    return out


def decode_get_response(frame: bytes) -> dict:
    """Decode a CMD_GET (0x52) ACK response carrying EEPROM bytes."""
    parsed = parse_pdu(frame)
    if parsed['direction'] != 'from_ecu':
        raise ValueError('not an ECU response')
    payload = parsed['payload']
    if not payload or payload[0] != ACK:
        raise ValueError('GET response must start with ACK 0x06')
    data = payload[1:]
    return {'eeprom_bytes': list(data), 'count': len(data),
            'hex': data.hex().upper(), 'raw': parsed['raw']}


def decode_capture(frames) -> dict:
    """Passive summary of a DDFI-2 capture (iterable of raw PDUs)."""
    recognized = invalid = 0
    commands: dict[str, int] = {}
    last_rt = None
    last_eeprom = None
    for frame in frames:
        frame = bytes(frame)
        if len(frame) > 6 and frame[0] == SOH and frame[1] == TESTER_ID and frame[2] == ECM_ID and frame[6] == CMD_SET:
            invalid += 1
            commands['0x57-SET-WRITE-REJECTED'] = commands.get('0x57-SET-WRITE-REJECTED', 0) + 1
            continue
        try:
            parsed = parse_pdu(frame)
        except ValueError:
            invalid += 1
            continue
        recognized += 1
        cmd = parsed['payload'][0] if parsed['payload'] else None
        if cmd is not None:
            key = f'0x{cmd:02X}'
            commands[key] = commands.get(key, 0) + 1
        if parsed['direction'] == 'from_ecu' and parsed['payload'][:1] == bytes([ACK]):
            if len(frame) >= RT_RESPONSE_SIZE:
                try:
                    last_rt = decode_rt_response(frame)
                except ValueError:
                    pass
            elif len(parsed['payload']) > 1:
                last_eeprom = decode_get_response(frame)
    return {'profile': PROFILE, 'recognized': recognized, 'invalid': invalid,
            'commands': commands, 'last_rt': last_rt, 'last_eeprom': last_eeprom}
