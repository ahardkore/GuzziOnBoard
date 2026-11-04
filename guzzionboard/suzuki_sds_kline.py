"""Suzuki SDS K-Line session decode (03-05 SV650), from a real wire capture.

Source: synfinatic/sv650sds (archived 2026-08-25, master bacf803a9056241ef270acf0e7e31467961aeba5),
especially the captured SDT<->ECU transcript ``data/sds_tool_output.txt``
(~12 s of K-Line traffic) and the field table in ``sds_decode/sds_decode.ino``.
See docs/CAPTURE_SEARCH_2026-11-03.md (Round 8).

SDS is KWP-2000 / ISO 14230 on a single K-Line at 10400 baud 8N1. Observed
frame shape (KWP2000 header with separate length byte):

    fmt tgt src [len] data... csum      (fmt 0x80 -> separate length byte;
                                         fmt low 6 bits != 0 -> that many data
                                         bytes, no length byte, e.g. 0x81 = 1;
                                         tgt/src are the 0x12/0xF1 pair)
    csum = sum(all bytes except csum) & 0xFF

Captured session:

    tx  81 12 F1 81 05                         init (StartCommunication)
    rx  80 F1 12 03 C1 EA 8F C0                key bytes C1 EA 8F
    tx  80 12 F1 02 1A 91 30                   readDataByLocalId 0x91 (ECU model)
    rx  80 F1 12 12 5A 91 33 32 39 32 30 ...   "5A 91" + ASCII "32920-17G2"
    tx  80 12 F1 02 21 08 AE                   readDataByLocalId 0x08 (sensor block)
    rx  80 F1 12 34 61 08 <50 data bytes> 4A   52-byte payload, "61 08" prefix

The sensor-block field offsets below are the source's own table (1-based
positions into the full ECU frame) with its candidate formulas; several were
never verified by the author, so every derived value is marked candidate.
This documents a captured session shape; it grants no physical session and
no write/programming capability.
"""
from __future__ import annotations

PROFILE = 'suzuki_sv650_sds_kline'

BAUD = 10400
ECU_ADDR = 0x12
TESTER_ADDR = 0xF1

INIT_REQUEST = bytes.fromhex('81 12 F1 81 05')
INIT_RESPONSE = bytes.fromhex('80 F1 12 03 C1 EA 8F C0')
MODEL_REQUEST = bytes.fromhex('80 12 F1 02 1A 91 30')
MODEL_REQUEST_ALT = bytes.fromhex('80 12 F1 02 1A 9A 39')
SENSOR_REQUEST = bytes.fromhex('80 12 F1 02 21 08 AE')

#: Captured ECU-model reply from data/sds_tool_output.txt (ECU 32920-17G2).
EXAMPLE_MODEL_REPLY = bytes.fromhex(
    '80 F1 12 12 5A 91 33 32 39 32 30 2D 31 37 47 32 2A 00 00 00 00 00 B8')

#: Captured sensor-block reply from data/sds_tool_output.txt. Note: the
#: source log labels this line "57:" and its length byte says 0x34 (52 data
#: bytes => 57 total), but it actually lists 58 bytes; the checksum still
#: validates over all 58. SENSOR_REPLY_NORMALIZED below is the same bytes
#: with the length byte corrected to 0x35 and the checksum re-adjusted to
#: 0x4B, so strict parsing works; it is derived, not verbatim.
EXAMPLE_SENSOR_REPLY = bytes.fromhex(
    '80 F1 12 34 61 08 00 00 00 00 00 00 00 00 FF FF FF FF 00 FF 43 CC 41 3D '
    'FF A7 FF 00 FF FF FF FF 00 00 00 00 FF FF FF FF FF FF 47 47 FF FF FF '
    '7F FF FF FF FF 00 04 FF FF FF 4A')

SENSOR_REPLY_NORMALIZED = EXAMPLE_SENSOR_REPLY[:3] + bytes([0x35]) \
    + EXAMPLE_SENSOR_REPLY[4:-1] + bytes([0x4B])

#: Source field table (sds_decode.ino): 1-based byte position in the full
#: ECU frame, label, and the author's candidate formula name.
SENSOR_FIELDS = {
    'rpm':        (25, 26, 'rpm = a*100 + b'),
    'tps':        (27, -1, 'tps% = (a-55)*100/169 (alt a*125/255)'),
    'ect':        (29, -1, 'ect C = (a-48)*0.625 (alt a*160/255-30)'),
    'iat':        (30, -1, 'iat C = (a-48)*0.625 (alt a*160/255-30)'),
    'iap':        (31, -1, 'iap = (a-153)*133/4/255'),
    'batt':       (32, -1, 'battery (formula in source)'),
    'gear':       (34, -1, 'gear position, raw decimal'),
    'fuel1':      (40, -1, 'raw decimal'),
    'fuel2':      (42, -1, 'raw decimal'),
    'ign1':       (49, -1, 'raw decimal'),
    'ign2':       (50, -1, 'raw decimal'),
    'pair':       (51, -1, 'raw decimal'),
    'clutch_map': (52, -1, 'raw hex'),
    'neutral':    (53, -1, 'raw hex'),
    'stv':        (54, -1, 'stv% = a*100/255'),
}


def checksum(frame: bytes) -> int:
    """KWP2000 checksum: sum of all bytes except the trailing checksum."""
    return sum(frame[:-1]) & 0xFF


def parse_frame(frame: bytes) -> dict:
    """Parse one K-Line frame; raises ValueError on shape/checksum mismatch."""
    frame = bytes(frame)
    if len(frame) < 5:
        raise ValueError('SDS frame too short (<5 bytes)')
    fmt, second, third = frame[0], frame[1], frame[2]
    if fmt & 0xC0 != 0x80:
        raise ValueError(f'unexpected format byte 0x{fmt:02X}')
    if {second, third} != {ECU_ADDR, TESTER_ADDR}:
        raise ValueError('addresses are not the 0x12/0xF1 SDS pair')
    length = fmt & 0x3F
    if length == 0:
        # fmt 0x80: data length carried in a separate byte after the header
        if len(frame) < 6:
            raise ValueError('SDS frame too short for a length byte')
        length = frame[3]
        data_start = 4
        expected = length + 5
    else:
        # fmt low 6 bits carry the data length directly (e.g. 0x81 = 1 byte)
        data_start = 3
        expected = length + 4
    if len(frame) != expected:
        raise ValueError(f'length {length} does not match frame size {len(frame)}')
    if checksum(frame) != frame[-1]:
        raise ValueError('checksum mismatch')
    direction = 'to_ecu' if second == ECU_ADDR else 'from_ecu'
    payload = frame[data_start:-1]
    service = payload[0] if payload else None
    return {
        'direction': direction,
        'service': service,
        'payload': payload,
        'checksum_ok': True,
        'raw': frame.hex().upper(),
    }


def decode_model_reply(reply: bytes) -> dict:
    """Decode a 0x1A 9x ECU-model reply; model string is ASCII after 5A 9x."""
    parsed = parse_frame(reply)
    payload = parsed['payload']
    if parsed['direction'] != 'from_ecu' or payload[:2] not in (
            bytes.fromhex('5A 91'), bytes.fromhex('5A 9A')):
        raise ValueError('not an SDS ECU-model reply (expected 5A 9x prefix)')
    text = payload[2:].split(b'\x00')[0]
    return {
        'local_id': payload[1],
        'ecu_model': text.decode('ascii', errors='replace'),
        'raw': parsed['raw'],
    }


def decode_sensor_block(reply: bytes) -> dict:
    """Decode a 0x21 08 sensor-block reply into raw + candidate fields."""
    parsed = parse_frame(reply)
    payload = parsed['payload']
    if parsed['direction'] != 'from_ecu' or payload[:2] != bytes.fromhex('61 08'):
        raise ValueError('not an SDS sensor-block reply (expected 61 08 prefix)')
    frame = bytes(reply)
    out: dict = {'raw': parsed['raw'], 'data_len': len(payload) - 2, 'fields': {}}
    for name, (pos1, pos2, formula) in SENSOR_FIELDS.items():
        a = frame[pos1 - 1] if pos1 - 1 < len(frame) - 1 else None
        b = frame[pos2 - 1] if (pos2 > 0 and pos2 - 1 < len(frame) - 1) else None
        out['fields'][name] = {'a': a, 'b': b, 'formula': formula, 'verified': False}
    return out


def decode_capture(frames) -> dict:
    """Passive summary of an SDS K-Line capture (iterable of raw frames)."""
    recognized = invalid = 0
    services: dict[int, int] = {}
    last_model = None
    last_sensors = None
    for frame in frames:
        try:
            parsed = parse_frame(bytes(frame))
        except ValueError:
            invalid += 1
            continue
        recognized += 1
        if parsed['service'] is not None:
            services[parsed['service']] = services.get(parsed['service'], 0) + 1
        if parsed['direction'] == 'from_ecu' and parsed['payload'][:2] in (
                bytes.fromhex('5A 91'), bytes.fromhex('5A 9A')):
            last_model = decode_model_reply(frame)['ecu_model']
        if parsed['direction'] == 'from_ecu' and parsed['payload'][:2] == bytes.fromhex('61 08'):
            last_sensors = decode_sensor_block(frame)
    return {
        'profile': PROFILE,
        'recognized': recognized,
        'invalid': invalid,
        'services': {f'0x{k:02X}': v for k, v in sorted(services.items())},
        'ecu_model': last_model,
        'last_sensor_block': last_sensors,
    }
