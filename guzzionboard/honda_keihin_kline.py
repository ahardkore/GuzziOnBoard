"""Honda Keihin PGM-FI K-Line protocol decode (K25 capture), research only.

Source: AutotronicCommunity/Honda_Keihin_KLine_Protocol (main,
`REQUEST - RESPONSE ECU HONDA K25 901.txt` is a real captured SDT<->ECU
transcript) plus the field offsets in AutotronicCommunity/ScantoolHonda
(`ScantoolHonda.ino`) and AutotronicCommunity/READ-ECM-CODE-DAN-ECM-PART-
DENGAN-ESP32. Same 0x72/0x71 message family as RyanHope/HondaECU
(see guzzionboard/honda_cbr1000rr_kline.py). See
docs/CAPTURE_SEARCH_2026-11-03.md (Round 9).

License note: the AutotronicCommunity sources carry no license; per the
project policy they are treated as open for use/modification and can be
modified or removed later if an author advises otherwise. Protocol facts and
captured frames are cited; this decoder is an independent reimplementation.

Wire procedure (10400 baud 8N1): Tx low 70 ms, high 120 ms, then
wake `FE 04 72 8C` -> ECU `0E 04 72 7C`; init `72 05 00 F0 99` -> `02 04 00 FA`.

Request shape: `72 NN QQ ZZ CS` — 0x72 header, NN byte count incl. checksum,
QQ query (0x71 data tables, 0x73 past DTCs, 0x74 current DTCs), ZZ table,
CS = (0x100 - (sum of the four preceding bytes & 0xFF)) & 0xFF.

Captured K25 session highlights (verbatim in the source txt):
    72 05 71 00 18 -> 02 0F 71 00 01 01 34 0F 01 01 00 00 00 00 37   (ECM ID)
    72 05 71 17 01 -> 02 18 71 17 00 00 04 00 FF 0A FF FF FF FF 7C 00 00 80 A6 00 00 00 00 B3
    72 05 74 01 14 -> 02 0C 74 01 00 07 02 0C 01 00 00 67            (current DTC 1)

Table-17 live-data offsets (from the response's first byte 0x02) are the
ScantoolHonda sketch's own, marked candidate where the author was unsure.
This documents a captured session shape; it grants no physical session,
no memory read and no write/flash capability.
"""
from __future__ import annotations

PROFILE = 'honda_keihin_k25_kline'

BAUD = 10400
WAKEUP = bytes.fromhex('FE 04 72 8C')
WAKEUP_RESPONSE = bytes.fromhex('0E 04 72 7C')
INIT_REQUEST = bytes.fromhex('72 05 00 F0 99')
INIT_RESPONSE = bytes.fromhex('02 04 00 FA')
ECM_ID_REQUEST = bytes.fromhex('72 05 71 00 18')
TABLE17_REQUEST = bytes.fromhex('72 05 71 17 01')

#: Captured table-17 reply from the K25 transcript.
EXAMPLE_TABLE17_REPLY = bytes.fromhex(
    '02 18 71 17 00 00 04 00 FF 0A FF FF FF FF 7C 00 00 80 A6 00 00 00 00 B3')

#: Captured ECM-ID reply from the K25 transcript.
EXAMPLE_ECM_ID_REPLY = bytes.fromhex(
    '02 0F 71 00 01 01 34 0F 01 01 00 00 00 00 37')

#: Captured current-DTC reply (table 0x74 sub 0x01) from the K25 transcript.
EXAMPLE_DTC_REPLY = bytes.fromhex(
    '02 0C 74 01 00 07 02 0C 01 00 00 67')

#: ECM part-number decode example from READ-ECM-CODE-...-ESP32:
#: reply data bytes [4:9] hex "0102E30F01" -> part 30400-K81H-N52.
KNOWN_ECM_PARTS = {'0102E30F01': '30400-K81H-N52'}


def checksum(msg: bytes) -> int:
    """Honda K-Line checksum: two's complement of the sum of all given bytes.

    Pass a complete frame minus its trailing checksum byte, or a bare
    request head when building one with make_request().
    """
    return (0x100 - (sum(bytes(msg)) & 0xFF)) & 0xFF


def make_request(query: int, table: int) -> bytes:
    """Build a `72 05 QQ ZZ CS` request (read-only data/DTC table query)."""
    head = bytes([0x72, 0x05, query, table])
    return head + bytes([checksum(head)])


def verify_response(resp: bytes) -> bool:
    resp = bytes(resp)
    return len(resp) >= 3 and resp[0] == 0x02 and checksum(resp[:-1]) == resp[-1]


def decode_table17(reply: bytes) -> dict:
    """Decode a table-17 live-data reply using the ScantoolHonda offsets."""
    reply = bytes(reply)
    if len(reply) < 24 or reply[:4] != bytes.fromhex('02 18 71 17'):
        raise ValueError('not a Honda table-17 reply (expected 02 18 71 17 header)')
    if not verify_response(reply):
        raise ValueError('checksum mismatch')
    b = reply
    iat1 = iat2 = 0 if b[15] == 0xFF else (b[15] * 19.6, b[16] - 40)
    map1 = map2 = 0 if b[17] == 0xFF else (b[17] * 19.6, b[18])
    return {
        'rpm': (b[9] << 8) | b[10],
        'tps1_mv_candidate': round(b[11] * 19.6, 1),
        'tps2_pct_candidate': round(b[12] * 1.57, 2),
        'ect1_mv_candidate': round(b[13] * 19.6, 1),
        'ect2_c_candidate': b[14] - 40,
        'iat1_mv_candidate': round(iat1[0], 1) if iat1 else 0.0,
        'iat2_c_candidate': iat2[1] if iat2 else 0,
        'map1_mv_candidate': round(map1[0], 1) if map1 else 0.0,
        'map2_kpa_candidate': map2[1] if map2 else 0,
        'battery_v_candidate': round(b[19] / 10.0, 2),
        'injector_us_candidate': round(((b[20] << 8) | b[21]) * 3.92, 2),
        'ignition_deg_candidate': round(-64 + b[22] * 0.5, 2),
        'speed_kmh_candidate': b[24] if len(reply) > 24 else None,
        'raw': reply.hex().upper(),
    }


def decode_ecm_id_reply(reply: bytes) -> dict:
    """Decode a `71 00` ECM-ID reply; data bytes [4:9] carry the part code."""
    reply = bytes(reply)
    if len(reply) < 14 or reply[0] != 0x02 or reply[2:4] != bytes.fromhex('71 00'):
        raise ValueError('not a Honda ECM-ID reply (expected 02 .. 71 00 header)')
    if not verify_response(reply):
        raise ValueError('checksum mismatch')
    part_hex = reply[4:9].hex().upper()
    return {
        'part_code_hex': part_hex,
        'part_number': KNOWN_ECM_PARTS.get(part_hex),
        'raw': reply.hex().upper(),
    }


def decode_capture(frames) -> dict:
    """Passive summary of a Honda Keihin K-Line capture (raw frames)."""
    recognized = invalid = 0
    queries: dict[str, int] = {}
    last_table17 = None
    last_ecm_id = None
    for frame in frames:
        frame = bytes(frame)
        try:
            if not verify_response(frame) and frame[:1] != bytes([0x72]):
                raise ValueError('unrecognized')
        except ValueError:
            invalid += 1
            continue
        recognized += 1
        if frame[0] == 0x72 and len(frame) == 5:
            queries[f'0x{frame[2]:02X}/0x{frame[3]:02X}'] = queries.get(f'0x{frame[2]:02X}/0x{frame[3]:02X}', 0) + 1
        if frame[:4] == bytes.fromhex('02 18 71 17'):
            last_table17 = decode_table17(frame)
        if len(frame) > 4 and frame[0] == 0x02 and frame[2:4] == bytes.fromhex('71 00'):
            last_ecm_id = decode_ecm_id_reply(frame)
    return {
        'profile': PROFILE,
        'recognized': recognized,
        'invalid': invalid,
        'requests': queries,
        'ecm_id': last_ecm_id,
        'last_table17': last_table17,
    }


#: Per-table live-data parameter map from the "PROTOKOL LIVE DATA PGM-FI
#: HONDA BIKE" poster (AutotronicCommunity/Protokol-Live-Data-PGM-FI-Honda-
#: Bike). D# is the reply byte index (reply[0] == 0x02). Formulas are the
#: poster's own; all values are candidate-grade.
TABLES = {
    0x10: {'alias': 0x60, 'params': [
        ('rpm', 9, 'D9*256+D10', 'rpm'), ('tps_v', 11, 'D11*5/256', 'V'),
        ('tps_pct', 12, 'D12*0.5', '%'), ('ect_v', 13, 'D13*5/256', 'V'),
        ('ect_c', 14, 'D14-40', 'C'), ('iat_v', 15, 'D15*5/256', 'V'),
        ('iat_c', 16, 'D16-40', 'C'), ('map_v', 17, 'D17*5/256', 'V'),
        ('map_kpa', 18, 'D18', 'kPa'), ('bat_v', 21, 'D21*0.1', 'V'),
        ('mode', 22, 'D22', '-'), ('inj_ms', 23, '(D23*256+D24)/200', 'ms'),
        ('igt_deg', 25, '-64+D25*0.5', 'BTDC'), ('speed_kmh', 26, 'D26', 'km/h')]},
    0x11: {'alias': 0x61, 'params': [
        ('rpm', 9, 'D9*256+D10', 'rpm'), ('tps_v', 11, 'D11*5/256', 'V'),
        ('tps_pct', 12, 'D12*0.5', '%'), ('ect_v', 13, 'D13*5/256', 'V'),
        ('ect_c', 14, 'D14-40', 'C'), ('iat_v', 15, 'D15*5/256', 'V'),
        ('iat_c', 16, 'D16-40', 'C'), ('map_v', 17, 'D17*5/256', 'V'),
        ('map_kpa', 18, 'D18', 'kPa'), ('bat_v', 21, 'D21*0.1', 'V'),
        ('mode', 22, 'D22', '-'), ('inj_ms', 23, '(D23*256+D24)/200', 'ms'),
        ('igt_deg', 25, '-64+D25*0.5', 'BTDC'), ('speed_kmh', 26, 'D26', 'km/h')]},
    0x13: {'alias': 0x63, 'params': [
        ('rpm', 9, 'D9*256+D10', 'rpm'), ('tps_v', 11, 'D11*5/256', 'V'),
        ('tps_pct', 12, 'D12*0.5', '%'), ('ect_v', 13, 'D13*5/256', 'V'),
        ('ect_c', 14, 'D14-40', 'C'), ('iat_v', 15, 'D15*5/256', 'V'),
        ('iat_c', 16, 'D16-40', 'C'), ('map_v', 17, 'D17*5/256', 'V'),
        ('map_kpa', 18, 'D18', 'kPa'), ('bat_v', 21, 'D21*0.1', 'V'),
        ('mode', 22, 'D22', '-'), ('inj_ms', 20, '(D20*256+D21)/200', 'ms'),
        ('igt_deg', 25, '-64+D25*0.5', 'BTDC'), ('speed_kmh', 25, 'D25', 'km/h'),
        ('eot_c', 18, 'D18-40', 'C')]},
    0x17: {'alias': 0x67, 'params': [
        ('rpm', 9, 'D9*256+D10', 'rpm'), ('tps_v', 11, 'D11*5/256', 'V'),
        ('tps_pct', 12, 'D12*0.5', '%'), ('ect_v', 13, 'D13*5/256', 'V'),
        ('ect_c', 14, 'D14-40', 'C'), ('iat_v', 15, 'D15*5/256', 'V'),
        ('iat_c', 16, 'D16-40', 'C'), ('map_v', 17, 'D17*5/256', 'V'),
        ('map_kpa', 18, 'D18', 'kPa'), ('bat_v', 19, 'D19*0.1', 'V'),
        ('inj_ms', 20, '(D20*256+D21)/200', 'ms'), ('igt_deg', 22, '-64+D22*0.5', 'BTDC'),
        ('mode', 23, 'D23', '-'), ('fast_idle', 23, 'D23:(128|80)=ON', '-'),
        ('speed_kmh', 24, 'D24', 'km/h'), ('eot_c', 18, 'D18-40', 'C')]},
    0x20: {'alias': 0x70, 'params': [
        ('o2_v', 9, 'D9*5/256', 'V'), ('stft_pct', 10, 'D10/128', '%'),
        ('o2_heater_v', 11, 'D11*5/256', 'V')]},
    0x21: {'alias': 0x71, 'params': [
        ('o2_v', 9, 'D9*5/256', 'V'), ('stft_pct', 10, 'D10/128', '%'),
        ('o2_heater_v', 11, 'D11*5/256', 'V')]},
    0xD1: {'alias': None, 'params': [
        ('bank_angle', 9, 'D9: 00=on gear, 01=neutral', '-'),
        ('starter_switch', 11, 'D11: 02=SSS ON', '-'),
        ('fuel_pump', 13, 'D13: 00/01 or 05=ON', '-'),
        ('cooling_fan', 14, 'D14: 00=OFF, 01=ON', '-')]},
}

#: Query 0x60 is the poster's CLEAR-DTC command. It is a write operation and
#: is deliberately NOT implemented anywhere in this module.
CLEAR_DTC_QUERY = 0x60


def decode_table(reply: bytes, table: int) -> dict:
    """Decode any known live-data table reply via the poster's TABLES map."""
    reply = bytes(reply)
    spec = TABLES.get(table)
    if spec is None:  # allow the poster's alias tables (0x67 -> 0x17 etc.)
        spec = next((v for v in TABLES.values() if v['alias'] == table), None)
    if spec is None:
        raise ValueError(f'unknown Honda live-data table 0x{table:02X}')
    alias = spec['alias']
    primary = next(k for k, v in TABLES.items() if v is spec)
    if len(reply) < 5 or reply[0] != 0x02 or reply[2] != 0x71 \
            or reply[3] not in (table, alias, primary):
        raise ValueError(f'not a Honda 0x71/0x{table:02X} reply')
    if not verify_response(reply):
        raise ValueError('checksum mismatch')
    out = {'table': f'0x{table:02X}', 'raw': reply.hex().upper(), 'params': {}}
    for name, off, formula, unit in spec['params']:
        out['params'][name] = {
            'raw': reply[off] if off < len(reply) else None,
            'formula': formula, 'unit': unit, 'verified': False}
    return out
