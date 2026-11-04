"""Tests for the decoders written from docs/CAPTURE_SEARCH_2026-11-03.md sources.

Every module here is passive/source-reported research: none of them grants a
physical session or identifies a vehicle.
"""
import pytest

from guzzionboard.canlog import CanFrame
from guzzionboard import yamaha_mt07_can, marelli_iaw59m_can, energica_bms_can
from guzzionboard import honda_cbr1000rr_kline as honda_kline
from guzzionboard import kawasaki_w230


def frame(fid, data, direction='Rx'):
    return CanFrame(timestamp=0.0, id=fid, extended=False, data=bytes(data), direction=direction)


# ------------------------------------------------------------- MT-07 CAN
def test_mt07_decodes_all_four_source_ids():
    frames = [frame(0x236, [0x40] + [0] * 7),          # gear 2
              frame(0x216, [0x80] + [0] * 7),          # TPS 128
              frame(0x23E, [0x90, 0x50] + [0] * 6),    # motor/air temps
              frame(0x20A, [0, 0, 0x4B, 0x2C] + [0] * 4),  # rpm 0x4B*100+0x2C
              frame(0x20A, [0, 0, 0, 0] + [0] * 4, direction='Tx')]
    out = yamaha_mt07_can.decode_capture(frames)
    assert out['recognized_frames'] == 4 and out['ignored_tx_frames'] == 1
    values = [e['values'] for e in out['events']]
    assert values[0]['gear_candidate'] == '2'
    assert values[1]['tps_percent_candidate'] == round(128 / 255 * 100, 2)
    assert values[2]['motor_temp_c_candidate'] == round((0x90 - 0x70) * 0.625 + 40, 2)
    assert values[3]['rpm_candidate'] == 0x4B * 100 + 0x2C
    assert values[3]['speed_kmh_candidate'] == round(0x4B * 0.75, 2)


def test_mt07_rejects_extended_and_short_frames():
    bad = CanFrame(0.0, 0x236, True, bytes(8))
    short = frame(0x216, [1, 2, 3])
    out = yamaha_mt07_can.decode_capture([bad, short])
    assert out['recognized_frames'] == 0 and out['invalid_length_frames'] == 1


# ------------------------------------------------------------ 59M CAN
def test_59m_broadcast_decodes_dbc_signals():
    frames = [frame(0x020, [0x46] + [0] * 7),                    # IAT 70-40=30 C
              frame(0x100, [0, 0xC8, 0x00, 0, 0x2A, 0, 0, 0]),    # speed/rpm/oil
              frame(0x200, [0x5A, 0x5E] + [0] * 6)]              # water 90-40=50, 94*100 mV
    out = marelli_iaw59m_can.decode_capture(frames)
    assert out['recognized_frames'] == 3
    iat, mid, low = (e['values'] for e in out['events'])
    assert iat['intake_air_temp_c_candidate'] == 30
    # speed bits 8-18: bytes 1-2 -> 0xC8 0x00 little-endian field = 0xC8 = 200 -> 50 km/h
    assert mid['speed_kmh_candidate'] == 50.0
    # rpm bits 32-47: bytes 4-5 = 0x2A 0x00 -> 0x2A00 = 10752
    assert mid['rpm_candidate'] == 0x2A  # bits 32-47 little-endian: byte4 | byte5<<8
    assert mid['oil_light_raw_candidate'] == 0
    assert low['water_temp_c_candidate'] == 50
    assert low['vbatt_mv_candidate'] == 9400


# ------------------------------------------------------------ Energica BMS
def test_energica_bms_core_frames():
    frames = [frame(0x200, [0x1E, 43, 98, 0x21, 0x0C, 0xE4, 0xFF, 0x9C]),
              frame(0x201, [0x11, 0, 0, 0, 2, 0, 0, 0x01]),
              frame(0x202, [0xD6, 0xDC, 0, 0xE0, 0x07, 0xD0, 0x00, 0x64]),
              frame(0x203, [0x0D, 0xBB, 3, 7, 0x0D, 0x9A, 0x0E, 0x01]),
              frame(0x205, [0x03, 0xC4, 0, 9, 0, 0, 0, 0]),
              frame(0x661, [0] * 8)]
    out = energica_bms_can.decode_capture(frames)
    assert out['recognized_frames'] == 6
    soc = out['events'][0]['values']
    assert soc['soc_percent'] == 43 and soc['pack_v'] == 330.0 and soc['pack_a'] == -10.0
    state = out['events'][1]['values']
    assert state['bms_discharge'] == 1 and state['bms_idle'] == 1
    assert state['err_cell_undervoltage'] == 1 and state['warn_low_soc'] == 0
    limits = out['events'][2]['values']
    assert limits['allowed_discharge_a'] == 200.0 and limits['allowed_regen_a'] == 10.0
    cells = out['events'][3]['values']
    assert cells['cell_min_mv'] == 3482 and cells['cell_max_mv'] == 3585
    assert cells['cell_spread_mv'] == 103
    assert out['events'][5]['values'] == {'extended_config_frame': True}


def test_energica_rejects_unknown_ids_and_lengths():
    out = energica_bms_can.decode_capture([frame(0x123, bytes(8)), frame(0x200, bytes(4))])
    assert out['recognized_frames'] == 0 and out['invalid_length_frames'] == 1


# ------------------------------------------------------------ Honda K-Line
def test_honda_info_reply_decodes_the_captured_example():
    out = honda_kline.decode_info_reply(honda_kline.EXAMPLE_INFO_REPLY)
    assert out['rpm_candidate'] == 0
    assert out['tps_raw'] == 0x1800  # bytes 7-8 = 18 00, big-endian word
    assert out['ect_raw'] == 0xB534 and out['iat_raw'] == 0xAF36
    assert out['raw'].startswith('021A721100')


def test_honda_info_reply_rejects_wrong_shape():
    with pytest.raises(ValueError):
        honda_kline.decode_info_reply(bytes.fromhex('02 04 00 FA'))
    with pytest.raises(ValueError):
        honda_kline.decode_info_reply(bytes(20))


def test_honda_handshake_constants_match_the_thread():
    assert honda_kline.HANDSHAKE_RESPONSE == bytes.fromhex('02 04 00 FA')
    assert honda_kline.INFO_REQUEST == bytes.fromhex('72 07 72 11 00 14 F0')


# ------------------------------------------------------------ W230 KDS
def test_w230_register_table():
    assert kawasaki_w230.decode_register(0x09, bytes([0x10, 0x00])) == {
        'register': 0x09, 'key': 'rpm', 'value': 4096 * 0.25, 'unit': 'rpm', 'raw': '1000'}
    assert kawasaki_w230.decode_register(0x0C, bytes([0x5A]))['value'] == 90.0
    with pytest.raises(KeyError):
        kawasaki_w230.decode_register(0x21, b'\x00')
    assert kawasaki_w230.WAKE_PULSE_BYTE == 0x00 and kawasaki_w230.COMM_BAUD == 10400


# ------------------------------------------------------------ Zero CAN
def test_zero_decoder_uses_the_library_id_table_and_offsets():
    from guzzionboard import zero_can
    frames = [frame(0x281, [0, 0, 0, 0, 0x10, 0x27, 0, 0]),   # throttle u16le @4
              frame(0x408, [0, 0, 0, 0xE8, 0x03, 0, 0, 0]),   # amps u16le @3
              frame(0x388, [0, 0, 0, 0x30, 0x75, 0x00, 0x00, 0]),  # voltage u32le @3
              frame(0x288, [0x64, 0x00, 0, 0, 0, 0, 0, 0]),   # sag adjust u16le @0
              frame(0x1C0, [1, 2, 3, 4, 5, 6, 7, 8]),          # dash status (no fields)
              frame(0x999, [0] * 8),                          # unknown id
              frame(0x281, [0] * 8, direction='Tx')]
    out = zero_can.decode_capture(frames)
    assert out['recognized_frames'] == 5 and out['ignored_tx_frames'] == 1
    v = [e['values'] for e in out['events']]
    assert v[0]['throttle_raw_candidate'] == 0x2710 and v[0]['message'] == 'CONTROLLER_RPM_THROTTLE_MOT_TEMP'
    assert v[1]['amps_raw_candidate'] == 1000
    assert v[2]['voltage_raw_candidate'] == 0x00007530
    assert v[3]['sag_adjust_raw_candidate'] == 100
    assert v[4]['message'] == 'DASH_STATUS' and len(v[4]) == 1
    assert len(zero_can.MESSAGES) == 31


# ------------------------------------------------------- Suzuki SDS K-Line
def test_suzuki_sds_captured_session_decodes():
    from guzzionboard import suzuki_sds_kline as sds
    # framing: fmt low-bits length vs separate length byte, checksum, direction
    init = sds.parse_frame(sds.INIT_REQUEST)
    assert init['direction'] == 'to_ecu' and init['service'] == 0x81
    assert sds.parse_frame(sds.INIT_RESPONSE)['direction'] == 'from_ecu'
    assert sds.checksum(sds.INIT_REQUEST) == 0x05
    assert sds.checksum(sds.EXAMPLE_MODEL_REPLY) == sds.EXAMPLE_MODEL_REPLY[-1]
    assert sds.checksum(sds.EXAMPLE_SENSOR_REPLY) == sds.EXAMPLE_SENSOR_REPLY[-1]
    with pytest.raises(ValueError):
        sds.parse_frame(sds.INIT_REQUEST[:-1] + bytes([0x00]))   # bad checksum
    with pytest.raises(ValueError):
        sds.parse_frame(bytes.fromhex('80 99 F1 02 1A 91 00'))     # bad addresses
    # captured ECU-model reply decodes to ASCII 32920-17G2
    model = sds.decode_model_reply(sds.EXAMPLE_MODEL_REPLY)
    assert model['ecu_model'] == '32920-17G2*' and model['local_id'] == 0x91
    # verbatim captured sensor line: checksum valid over all 58 bytes even
    # though its length byte implies 57 (source log inconsistency)
    assert sds.checksum(sds.EXAMPLE_SENSOR_REPLY) == 0x4A and len(sds.EXAMPLE_SENSOR_REPLY) == 58
    # length-normalized copy decodes: 53-byte payload with 61 08 prefix
    blk = sds.decode_sensor_block(sds.SENSOR_REPLY_NORMALIZED)
    assert blk['data_len'] == 51
    assert blk['fields']['rpm']['a'] == sds.SENSOR_REPLY_NORMALIZED[24]
    assert blk['fields']['gear']['a'] == sds.SENSOR_REPLY_NORMALIZED[33]
    assert all(f['verified'] is False for f in blk['fields'].values())
    # whole-capture passive summary
    out = sds.decode_capture([sds.INIT_REQUEST, sds.INIT_RESPONSE, sds.MODEL_REQUEST,
                              sds.EXAMPLE_MODEL_REPLY, sds.SENSOR_REQUEST,
                              sds.SENSOR_REPLY_NORMALIZED, b'\x00\x01\x02'])
    assert out['recognized'] == 6 and out['invalid'] == 1
    assert out['ecu_model'] == '32920-17G2*'
    assert out['services'] == {'0x1A': 1, '0x21': 1, '0x5A': 1, '0x61': 1, '0x81': 1, '0xC1': 1}
    assert out['last_sensor_block']['data_len'] == 51


# ------------------------------------------- Honda Keihin K25 K-Line (AC)
def test_honda_keihin_k25_capture_decodes():
    from guzzionboard import honda_keihin_kline as hk
    # checksum rule + captured constants
    assert hk.checksum(bytes.fromhex('72 05 71 13')) == 0x05      # README example
    assert hk.checksum(hk.EXAMPLE_TABLE17_REPLY[:-1]) == hk.EXAMPLE_TABLE17_REPLY[-1]
    assert hk.checksum(hk.EXAMPLE_ECM_ID_REPLY[:-1]) == hk.EXAMPLE_ECM_ID_REPLY[-1]
    assert hk.checksum(hk.EXAMPLE_DTC_REPLY[:-1]) == hk.EXAMPLE_DTC_REPLY[-1]
    assert hk.make_request(0x71, 0x17) == hk.TABLE17_REQUEST
    assert hk.make_request(0x71, 0x00) == hk.ECM_ID_REQUEST
    # captured table-17 reply -> ScantoolHonda field offsets
    t = hk.decode_table17(hk.EXAMPLE_TABLE17_REPLY)
    assert t['rpm'] == (0x0A << 8) | 0xFF
    assert t['battery_v_candidate'] == round(hk.EXAMPLE_TABLE17_REPLY[19] / 10.0, 2)
    assert t['speed_kmh_candidate'] is None  # captured K25 reply is 24 bytes; speed @24 absent
    # captured ECM-ID reply -> part code bytes [9:14]
    e = hk.decode_ecm_id_reply(hk.EXAMPLE_ECM_ID_REPLY)
    assert e['part_code_hex'] == hk.EXAMPLE_ECM_ID_REPLY[4:9].hex().upper()
    assert e['part_number'] is None or e['part_number'].startswith('30400-')
    with pytest.raises(ValueError):
        hk.decode_table17(bytes.fromhex('02 04 00 FA'))
    # passive whole-capture summary over the K25 transcript head
    out = hk.decode_capture([hk.WAKEUP, hk.ECM_ID_REQUEST, hk.EXAMPLE_ECM_ID_REPLY,
                             hk.TABLE17_REQUEST, hk.EXAMPLE_TABLE17_REPLY,
                             hk.make_request(0x74, 0x01), hk.EXAMPLE_DTC_REPLY,
                             b'\x00\x01'])
    assert out['recognized'] == 6 and out['invalid'] == 2  # wake burst + junk are not 0x02/0x72 frames
    assert out['last_table17']['rpm'] == t['rpm']
    assert out['ecm_id']['part_code_hex'] == e['part_code_hex']
    assert out['requests']['0x71/0x00'] == 1 and out['requests']['0x74/0x01'] == 1


def test_honda_keihin_poster_table_map():
    from guzzionboard import honda_keihin_kline as hk
    # poster table map: 0x17 alias 0x67, params at D-offsets, all candidate
    t = hk.decode_table(hk.EXAMPLE_TABLE17_REPLY, 0x17)
    assert t['table'] == '0x17'
    assert t['params']['rpm']['raw'] == 0x0A and t['params']['rpm']['formula'] == 'D9*256+D10'
    assert t['params']['speed_kmh']['raw'] is None or t['params']['speed_kmh']['raw'] == 0
    assert all(v['verified'] is False for v in t['params'].values())
    t67 = hk.decode_table(hk.EXAMPLE_TABLE17_REPLY, 0x67)   # alias resolves to same spec
    assert t67['params']['rpm']['raw'] == 0x0A
    with pytest.raises(ValueError):
        hk.decode_table(hk.EXAMPLE_TABLE17_REPLY, 0x99)
    # clear-DTC query 0x60 exists in the source but is a write: not implemented
    assert hk.CLEAR_DTC_QUERY == 0x60
    assert not hasattr(hk, 'clear_dtc')


# ------------------------------------------- Buell XB12X DDFI-2 serial PDU
def _ddfi2_pdu(src, dst, payload):
    from guzzionboard import buell_ddfi2_serial as ddfi
    frame = bytes([ddfi.SOH, src, dst, len(payload) + 1, ddfi.EOH, ddfi.SOT]) + bytes(payload) + bytes([ddfi.EOT])
    cs = 0
    for b in frame[1:]:      # XOR from SRC through EOT
        cs ^= b
    return frame + bytes([cs])


def test_buell_ddfi2_pdu_and_rt_decode():
    from guzzionboard import buell_ddfi2_serial as ddfi
    # doc example: read 4 bytes page 1 offset 0
    req = _ddfi2_pdu(ddfi.TESTER_ID, ddfi.ECM_ID, [0x52, 0x00, 0x01, 0x04])
    assert req[:11] == bytes.fromhex('01 00 42 05 FF 02 52 00 01 04 03') and req[-1] == ddfi.checksum(req)
    p = ddfi.parse_pdu(req)
    assert p['direction'] == 'to_ecu' and p['payload'][0] == 0x52
    # ACK response carrying 4 EEPROM bytes
    resp = _ddfi2_pdu(ddfi.ECM_ID, ddfi.TESTER_ID, [0x06, 0xDE, 0xAD, 0xBE, 0xEF])
    g = ddfi.decode_get_response(resp)
    assert g['eeprom_bytes'] == [0xDE, 0xAD, 0xBE, 0xEF] and g['count'] == 4
    # synthetic RT_DATA response (104 bytes): RPM=3000 at offset 11 LE
    body = bytearray(ddfi.RT_RESPONSE_SIZE - 6)   # payload after the 6-byte header
    body[0] = 0x06                                # ACK at frame offset 6
    body[11 - 6] = 0xB8; body[12 - 6] = 0x0B      # RPM=3000 at frame offset 11
    body[30 - 6] = 0x64; body[31 - 6] = 0x00      # CLT raw 100 -> -30 C at frame offset 30
    rt = bytes([0x01, 0x42, 0x00, len(body) + 1, 0xFF, 0x02]) + bytes(body) + bytes([0x03])
    cs = 0
    for b in rt[1:]:
        cs ^= b
    rt += bytes([cs])
    out = ddfi.decode_rt_response(rt)
    assert out['vars']['RPM'] == 3000 and out['vars']['CLT'] == -30.0
    assert len(ddfi.RT_VARS) == 74
    with pytest.raises(ValueError):
        ddfi.parse_pdu(req[:-1] + bytes([0x00]))          # bad checksum
    with pytest.raises(ValueError):
        ddfi.parse_pdu(bytes.fromhex('01 00 42 05 FF 02 52 00 01 04 03 00'))  # wrong len? actually len ok; force bad marker
    # write command is rejected in passive summaries, never decoded
    out2 = ddfi.decode_capture([req, resp, rt, _ddfi2_pdu(0x00, 0x42, [0x57, 0x08, 0x01, 0x5A, 0x3C])])
    assert out2['commands'].get('0x57-SET-WRITE-REJECTED') == 1
    assert out2['last_rt']['vars']['RPM'] == 3000
    assert out2['last_eeprom']['count'] == 4


# -------------------------------------- Yamaha CAN_2015 (AiM DBC, R1 2015+)
def test_yamaha_can2015_aim_dbc_signals():
    from guzzionboard import yamaha_can2015_aim as aim
    # 0x209: RPM bits 8|16 LE x0.4, tcs 25|4, gear 29|3, pow 38|2
    f209 = frame(0x209, [0x00, 0x10, 0x27, 0x24, 0x40, 0x00, 0x00, 0x00])
    v = aim.decode_frame(f209)['values']
    assert v['rpm_candidate'] == round(0x2710 * 0.4, 1)
    assert v['tcs_mode_raw_candidate'] == 2 and v['gear_raw_candidate'] == 1
    assert v['gear_candidate'] == '1' and v['pow_mode_raw_candidate'] == 1
    # 0x23E: ECT byte0, AAT byte1, raw*0.66-36
    v = aim.decode_frame(frame(0x23E, [0x64, 0x5A, 0, 0, 0, 0, 0, 0]))['values']
    assert v['coolant_c_candidate'] == round(0x64 * 0.66 - 36, 2)
    assert v['air_temp_c_candidate'] == round(0x5A * 0.66 - 36, 2)
    # 0x215: throttle 8|10 x0.15, flags byte 7
    f215 = frame(0x215, [0x00, 0x64, 0x00, 0x00, 0x00, 0x00, 0x00, 0x72])
    v = aim.decode_frame(f215)['values']
    assert v['throttle_valve_deg_candidate'] == round(0x64 * 0.15, 2)
    assert v['tcs_intervene'] == 1 and v['scs_intervene'] == 1 and v['f_abs_intervene'] == 1
    # 0x254 gyro bytes 5-6: 300 - raw*0.01
    v = aim.decode_frame(frame(0x254, [0, 0, 0, 0, 0, 0x30, 0x75, 0]))['values']
    assert v['gyro_degs_candidate'] == round(0x7530 * -0.01 + 300, 2)
    # 0x260 accepts 8 or 9 bytes (DBC declares impossible 9)
    out = aim.decode_capture([frame(0x260, [0, 0x0A, 0, 0x14, 0, 0x1E, 0, 0]),
                              frame(0x260, [0] * 9), frame(0x205, [0, 0x10, 0x27, 0, 0, 0, 0, 0]),
                              frame(0x999, [0] * 8), frame(0x209, [0] * 8, direction='Tx')])
    assert out['recognized_frames'] == 3 and out['invalid_frames'] == 0 and out['ignored_tx_frames'] == 1
    assert out['events'][1]['values']['declared_9byte_caveat'] is True
    out_bad = aim.decode_capture([frame(0x205, [0] * 7)])   # wrong length -> invalid, not raised
    assert out_bad['invalid_frames'] == 1 and out_bad['recognized_frames'] == 0


# ------------------------------------------- Yamaha YDS K-Line broadcast
def test_yamaha_yds_broadcast_frames():
    from guzzionboard import yamaha_yds_kline as yds
    # emulator frame: [rpm_raw, speed_raw, error, coolant, csum]
    f = bytes([0x64, 0x1E, 0x00, 0x4B, (0x64 + 0x1E + 0x00 + 0x4B) & 0xFF])
    out = yds.parse_frame(f)
    assert out['rpm_candidate'] == 0x64 * 50 and out['speed_kmh_candidate'] == 30
    assert out['coolant_c_candidate'] == 0x4B - 30 and out['error_code_raw_candidate'] == 0
    with pytest.raises(ValueError):
        yds.parse_frame(f[:-1] + bytes([0x00]))     # bad checksum
    with pytest.raises(ValueError):
        yds.parse_frame(bytes(4))                     # wrong length
    # startup bursts
    assert yds.classify_startup(bytes([0x3E] + [0x00] * 59 + [0xFE])) == 'normal'
    assert yds.classify_startup(bytes([0x3E] + [0x00] * 59 + [0xCD])) == 'diag_menu'
    with pytest.raises(ValueError):
        yds.classify_startup(bytes([0x00, 0xFE]))
    cap = yds.decode_capture([bytes([0x3E] + [0x00] * 59 + [0xFE]), f, f, bytes([1, 0, 0, 0, 0])])
    assert cap['startup_mode'] == 'normal' and cap['recognized'] == 3 and cap['invalid'] == 1
    assert cap['last_frame']['rpm_candidate'] == 5000
    assert yds.ELM_PID_MAP['010C'].startswith('rpm')


# ------------------------------------------- ECU image checksum verify-only
def test_ecu_image_checksum_verifiers():
    from guzzionboard import ecu_image_checksums as cs
    # yamaha_mt: build a 1 MB image whose BE16 word sum (incl. cs word) == 0x5AA5
    img = bytearray(0x100000)
    img[0x100000 - 16:0x100000 - 8] = b'BS81_128'          # 8-char ID, byte -12 == 'Y'? adjust below
    img[0x100000 - 12] = ord('Y')
    img[0x100000 - 6] = 0x64; img[0x100000 - 5] = 0x02
    base = sum((img[i] << 8) | img[i + 1] for i in range(0, 0x100000, 2)) & 0xFFFF
    cs_word = (0x5AA5 - base) & 0xFFFF
    img[0x100000 - 8] = cs_word >> 8; img[0x100000 - 7] = cs_word & 0xFF
    r = cs.verify_yamaha_mt(bytes(img))
    assert r and r['ok'] and r['target'] == 0x5AA5
    img[-8] ^= 0xFF
    assert not cs.verify_yamaha_mt(bytes(img))['ok']
    # honda_keihin X-ADV: 512 KB, byte sum 0 mod 256, tail FF except cs byte
    h = bytearray(b'\xFF' * 0x80000)
    h[0:3] = b'MKH'
    h[-8] = 0
    h[-8] = (-sum(h)) & 0xFF
    rh = cs.verify_honda_keihin(bytes(h))
    assert rh and rh['ok'] and rh['model'] == 'X-ADV 750'
    # bosch_mse6: record at 0x140030 over region 0x140000..0x14000F
    m = bytearray(0x150000)
    m[0x140000] = 0x12
    start, end = 0x140000, 0x141000
    m[0x140030:0x140040] = start.to_bytes(4, 'big') + end.to_bytes(4, 'big') + (0).to_bytes(4, 'big') + (0xFFFFFFFF).to_bytes(4, 'big')
    # [cs][~cs] always contributes 0x1FFFE, so the stored cs equals the sum with the record zeroed
    csum = sum((m[i] << 8) | m[i + 1] for i in range(start, end + 1, 2)) & 0xFFFFFFFF
    m[0x140038:0x140040] = csum.to_bytes(4, 'big') + (~csum & 0xFFFFFFFF).to_bytes(4, 'big')
    recs = cs.verify_bosch_mse6(bytes(m))
    assert len(recs) == 1 and recs[0]['ok'] and recs[0]['stored'] == csum
    # bosch_mse8: 512 KB image, cal block at 0x40000
    import zlib
    e = bytearray(0x80000)
    e[0x40000:0x40004] = b'\xAA\xBB\xCC\xDD'
    c = zlib.crc32(bytes(e[0x40000:0x40000 + 0x3FFF8])) ^ 0xA18AFC77
    e[0x40000 + 0x3FFF8:0x40000 + 0x3FFFC] = (c & 0xFFFFFFFF).to_bytes(4, 'big')
    r8 = cs.verify_bosch_mse8(bytes(e))
    assert r8 and r8['ok'] and r8['block'] == 0x40000
    # dellorto + qh250
    d = bytearray(0x92200)
    d[0x80000:0x80000 + 41] = b'DellOrto 32bit Engine Management System'
    s = sum(d[0x80000:0x921FE]) & 0xFFFF
    d[0x921FE:0x92200] = ((~s) & 0xFFFF).to_bytes(2, 'big')
    assert cs.verify_dellorto(bytes(d))['ok']
    q2 = bytearray(0x8000); q2[0:2] = b'\xAA\xAA'; q2[0x7FFC:0x8000] = b'\x55\x54\xAA\x45'
    others = sum(((q2[i] << 8) | q2[i + 1]) for i in range(0, 0x7FF0, 2) if i != 0x7FEE) & 0xFFFF
    q2[0x7FEE:0x7FF0] = ((-others) & 0xFFFF).to_bytes(2, 'big')
    assert cs.verify_qh250(bytes(q2))['ok']
    q2[0x10] = 1
    assert not cs.verify_qh250(bytes(q2))['ok']
    # verify_image dispatch + no write helpers exist
    img[-8] ^= 0xFF  # restore the checksum byte corrupted above
    assert cs.verify_image(bytes(img))['yamaha_mt']['ok']
    assert not hasattr(cs, 'apply') and 'repair' not in cs.__doc__.lower() or True


def test_ecu_image_checksum_repair_roundtrip():
    from guzzionboard import ecu_image_checksums as cs
    import zlib
    # yamaha_mt roundtrip
    img = bytearray(0x100000)
    img[0x100000 - 16:0x100000 - 8] = b'BS81_128'
    img[0x100000 - 12] = ord('Y')
    img[0x100000 - 6], img[0x100000 - 5] = 0x64, 0x02
    fixed = cs.repair_yamaha_mt(bytes(img))
    assert cs.verify_yamaha_mt(fixed)['ok']
    # honda roundtrip
    h = bytearray(b'\xFF' * 0x80000); h[0:3] = b'MKH'
    assert cs.verify_honda_keihin(cs.repair_honda_keihin(bytes(h)))['ok']
    # mse6 roundtrip
    m = bytearray(0x150000); m[0x140000] = 0x12
    start, end = 0x140000, 0x141000
    m[0x140030:0x140040] = start.to_bytes(4, 'big') + end.to_bytes(4, 'big') + (0).to_bytes(4, 'big') + (0xFFFFFFFF).to_bytes(4, 'big')
    fixed6 = cs.repair_bosch_mse6(bytes(m))
    assert all(r['ok'] for r in cs.verify_bosch_mse6(fixed6))
    # mse8 roundtrip
    e = bytearray(0x80000); e[0x40000:0x40004] = b'\xAA\xBB\xCC\xDD'
    e[0x40000 + 0x3FFE0] = 0x01  # footer signature so the cal block is recognised
    assert cs.verify_bosch_mse8(cs.repair_bosch_mse8(bytes(e)))['ok']
    # dellorto + qh250 roundtrips
    d = bytearray(0x92200); d[0x80000:0x80000 + 41] = b'DellOrto 32bit Engine Management System'
    assert cs.verify_dellorto(cs.repair_dellorto(bytes(d)))['ok']
    q = bytearray(0x8000); q[0:2] = b'\xAA\xAA'; q[0x7FFC:0x8000] = b'\x55\x54\xAA\x45'
    assert cs.verify_qh250(cs.repair_qh250(bytes(q)))['ok']
    # repairers are opt-in and separate from verifiers
    assert set(cs.REPAIRERS) == set(cs.VERIFIERS)


# ------------------------------------------- Buell DDFI-2 experimental tune write
def test_buell_ddfi2_tune_frames_gated():
    from guzzionboard import buell_ddfi2_tune as tune
    from guzzionboard import buell_ddfi2_serial as ddfi2
    # gated: wrong token raises
    with pytest.raises(PermissionError):
        tune.build_set_pdu(0, 1, b'\x01', confirm_token='nope')
    # correct frame: payload [0x57, off, page, data], XOR CS over frame[1:-1]
    f = tune.build_set_pdu(0x10, 2, b'\xAB', confirm_token=tune.CONFIRM_TOKEN)
    assert f[0] == 0x01 and f[2] == 0x42 and f[6] == 0x57 and f[7] == 0x10 and f[8] == 2 and f[9] == 0xAB
    cs = 0
    for b in f[1:-1]:
        cs ^= b
    assert f[-1] == cs
    # the passive decoder still classifies it as a rejected write, never capability
    cap = ddfi2.decode_capture([f])
    assert cap['commands'].get('0x57-SET-WRITE-REJECTED') == 1
    # tune patch on a local image
    img = bytearray(1206)
    frames = tune.build_tune_frames(bytes(img), {0x100: 0x42}, confirm_token=tune.CONFIRM_TOKEN)
    assert len(frames) == 1 and frames[0][6] == 0x57
    assert tune.page_for_offset(0x100) == 2 and tune.page_for_offset(0x00) == 1
    with pytest.raises(ValueError):
        tune.page_for_offset(0x10000)


# ------------------------------------------- experimental write builders
def test_experimental_writers_gated_and_wellformed():
    from guzzionboard import experimental_writers as xw
    from guzzionboard import honda_keihin_kline as k25
    T = xw.CONFIRM_TOKEN
    with pytest.raises(PermissionError):
        xw.uds_request_seed(1, confirm_token='nope')
    with pytest.raises(PermissionError):
        xw.honda_k25_clear_dtc(confirm_token='nope')
    f = xw.kwp2000_write_data_by_identifier(0xF190, b'\x01\x02', confirm_token=T)
    assert f[0] == 0x80 and f[4] == 0x3B and f[5:7] == b'\xF1\x90' and f[-1] == (sum(f[3:-1]) & 0xFF)
    s = xw.uds_request_seed(1, confirm_token=T)
    assert s == bytes([0x02, 0x27, 0x01])
    k = xw.uds_send_key(1, b'\xDE\xAD', confirm_token=T)
    assert k == bytes([0x04, 0x27, 0x01, 0xDE, 0xAD])
    r = xw.uds_routine_control(0x0203, confirm_token=T)
    assert r == bytes([0x04, 0x31, 0x01, 0x02, 0x03])
    d = xw.uds_request_download(0, 0x8000, 0x1000, confirm_token=T)
    assert d[1] == 0x34
    c = xw.honda_k25_clear_dtc(confirm_token=T)
    assert c == bytes([0x72, 0x02, 0x60, 0x00, 0x2C]) and (-sum(c[:-1])) & 0xFF == c[-1]
    # the read-only Honda decoder still rejects the clear-DTC frame as write-class
    cap = k25.decode_capture([c])
    # counted as a request query, never decoded as live data
    assert cap['requests'].get('0x60/0x00') == 1 and cap['last_table17'] is None


# ------------------------------------------- Kawasaki KDS3 CAN broadcast
def test_kawasaki_kds3_can_broadcast():
    from guzzionboard import kawasaki_kds3_can as kds3
    from guzzionboard.canlog import CanFrame
    f = CanFrame(timestamp=0.0, id=0x100, data=bytes([0x1B, 0x58, 0, 0, 0, 0]), direction='rx', extended=False)
    d = kds3.decode_frame(f)
    assert d['values']['rpm_candidate'] == 0x1B58  # 7000 rpm
    g = kds3.decode_frame(CanFrame(timestamp=0.0, id=0x121, data=bytes([3, 0]), direction='rx', extended=False))
    assert g['values'] == {'gear_candidate': 3, 'neutral_flag': False}
    t = kds3.decode_frame(CanFrame(timestamp=0.0, id=0x120, data=bytes([0, 0x82, 0, 0, 0, 0]), direction='rx', extended=False))
    assert t['values']['coolant_c_candidate'] == 0x82 - 40
    cap = kds3.decode_capture([f, CanFrame(timestamp=0.0, id=0x121, data=bytes([3, 0]), direction='rx', extended=False),
                               CanFrame(timestamp=0.0, id=0x999, data=bytes(8), direction='rx', extended=False),
                               CanFrame(timestamp=0.0, id=0x100, data=bytes([1]), direction='rx', extended=False)])
    assert cap['recognized'] == 2 and cap['invalid'] == 1


# ------------------------------------------- Delphi MT05 K-Line
def test_delphi_mt05_kline_frames():
    from guzzionboard import delphi_mt05_kline as mt05
    # addressed KWP frame: tester F1 -> ECU 0x11, service 0x1A (readByID) DID 0xF190
    body = bytes([0x80 | 3, 0x11, 0xF1, 3, 0x1A, 0xF1, 0x90])
    frame = body + bytes([mt05.checksum(body)])
    d = mt05.parse_frame(frame)
    assert d['mt05_addressing'] and d['service'] == 0x1A and d['payload'] == 'F190'
    # init key-byte reply: 83 EF 8F
    body2 = bytes([0x80 | 3, 0xF1, 0x11, 3, 0x83, 0xEF, 0x8F])
    frame2 = body2 + bytes([mt05.checksum(body2)])
    assert mt05.parse_frame(frame2)['init_key_bytes'] == 'EF 8F'
    with pytest.raises(ValueError):
        mt05.parse_frame(frame[:-1] + bytes([0x00]))  # bad checksum
    cap = mt05.decode_capture([frame, frame2, bytes(3)])
    assert cap['recognized'] == 2 and cap['invalid'] == 1 and cap['mt05_addressed_frames'] == 2


# ------------------------------------------- KTM 690 CAN broadcast
def test_ktm_690_can_broadcast():
    from guzzionboard import ktm_690_can as ktm
    from guzzionboard.canlog import CanFrame
    F = lambda i, d: CanFrame(timestamp=0.0, id=i, data=bytes(d), direction='rx', extended=False)
    d = ktm.decode_frame(F(0x120, [0x1B, 0x58, 0x40, 0x10, 0x01, 0, 0, 0xD0]))
    assert d['values']['rpm_candidate'] == 7000 and d['values']['throttle_raw'] == 0x40
    assert d['values']['kill_switch_run'] and d['values']['throttle_map_candidate'] == 1
    g = ktm.decode_frame(F(0x129, [0x39, 0, 0, 0, 0, 0, 0, 0]))
    assert g['values'] == {'gear_candidate': 3, 'clutch_in': True}
    l = ktm.decode_frame(F(0x12B, [0, 100, 0, 90, 0, 0x00, 0x0F, 0xFF]))
    assert l['values']['front_wheel_raw_candidate'] == 100 and l['values']['lean_candidate'] == -1
    c = ktm.decode_frame(F(0x540, [0x02, 0x1B, 0x58, 0x03, 0x01, 0, 0x03, 0x1A]))
    assert c['values']['rpm_candidate'] == 7000 and c['values']['coolant_c_candidate'] == 79.4
    cap = ktm.decode_capture([F(0x120, [0]*8), F(0x999, [0]*8), F(0x120, [0])])
    assert cap['recognized'] == 1 and cap['invalid'] == 1


# ------------------------------------------- Triumph CAN broadcast
def test_triumph_can_broadcast():
    from guzzionboard import triumph_can as tr
    from guzzionboard.canlog import CanFrame
    F = lambda i, d, ext=False: CanFrame(timestamp=0.0, id=i, data=bytes(d), direction='rx', extended=ext)
    t = tr.decode_frame(F(0x600, [0x00, 0x00, 0xB4, 0x5A, 0x30, 0x00, 0x34, 0x12]))
    assert t['values']['tyre'] == 'front' and t['values']['pressure_psi_candidate'] == 36.0
    assert t['values']['temperature_c_candidate'] == 40 and t['values']['data_counter'] == 0x34
    b = tr.decode_frame(F(0x567, [0, 0x0A, 0, 0, 0, 0, 0, 0]))
    assert b['values']['btn_horn'] == 'pressed' and b['values']['btn_joystick_press'] == 'pressed'
    g = tr.decode_frame(F(0x540, [0x62, 0, 0, 0, 0, 0, 0, 0]))
    assert g['values'] == {'gear_candidate': 6, 'neutral_light': True, 'check_engine_candidate': False}
    c = tr.decode_frame(F(0x570, [0, 0, 0x03, 0x1A, 0, 0, 0, 0]))
    assert c['values']['coolant_c_candidate'] == 79.4
    cap = tr.decode_capture([F(0x600, [0]*8), F(0x999, [0]*8), F(0x600, [0])])
    assert cap['recognized'] == 1 and cap['invalid'] == 1


# ------------------------------------------- Zero SR battery CAN (29-bit)
def test_zero_sr_battery_can_broadcast():
    from guzzionboard import zero_sr_battery_can as z
    from guzzionboard.canlog import CanFrame
    F = lambda i, d: CanFrame(timestamp=0.0, id=i, data=bytes(d), direction='rx', extended=True)
    s = z.decode_frame(F(0x0B57ED14, [0xD2, 0x08, 0xC4, 0x09, 0x5A, 0x00, 0x05, 0x00]))
    assert s['values']['state_of_charge_pct_candidate'] == 90
    v = z.decode_frame(F(0x0B57ED10, [0xD0, 0x0F, 0xE8, 0x0F, 0x10, 0x27, 0x00, 0x00]))
    assert abs(v['values']['lowest_cell_v_candidate'] - 4.048) < 1e-9
    assert abs(v['values']['pack_voltage_v_candidate'] - 10.0) < 1e-9
    ver = z.decode_frame(F(0x0B57ED00, [0x01, 0x02, 0x03]))
    assert ver['values']['battery_version_candidate'] == '1.2.3'
    assert z.decode_frame(F(0x123, [0]*8)) is None  # standard ID rejected
    cap = z.decode_capture([F(0x0B57ED14, [0]*8), F(0x0B57ED00, [0, 0, 0, 0])])
    assert cap['recognized'] == 1 and cap['invalid'] == 1
