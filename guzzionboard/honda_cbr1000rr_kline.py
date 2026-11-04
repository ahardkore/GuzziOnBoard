"""Honda CBR1000RR K-Line session trace decode (source-reported, research only).

From the 1000rr.net thread 247922 ("K-Line ECU logging", 2018) with code at
RyanHope/HondaECU - see docs/CAPTURE_SEARCH_2026-11-03.md. The tester exchange
on the wire (10400 baud):

    tx  FE 04 FF FF          wake/address burst
    tx  72 05 00 F0 99       -> rx 02 04 00 FA
    tx  72 07 72 11 00 14 F0 info request
    rx  02 1A 72 11 00 00 00 18 00 B5 34 AF 36 8F 61 FF FF 78 00 00 00 80 57 1D F7 2A

Field offsets in the info reply payload (after the leading ``02 1A 72 11``):
RPM signed-16 at [5:7], TPS raw-16 at [7:9], ECT raw-16 at [9:11], IAT raw-16
at [11:13], with the thread's voltage conversion ``volts = raw * 20 / 255``
as a candidate scaling. The exact °C formulas were not pinned by the source,
so temperatures stay raw. This documents a captured session shape; it is NOT
a verified profile for any specific bike and grants no physical session (the
`honda_cbr1000rr_2012_us` catalog entry stays blocked).
"""
from __future__ import annotations

PROFILE = 'honda_cbr1000rr_kline_trace'

WAKE_BURST = bytes.fromhex('FE 04 FF FF')
HANDSHAKE_REQUEST = bytes.fromhex('72 05 00 F0 99')
HANDSHAKE_RESPONSE = bytes.fromhex('02 04 00 FA')
INFO_REQUEST = bytes.fromhex('72 07 72 11 00 14 F0')

#: Example info reply captured in the source thread.
EXAMPLE_INFO_REPLY = bytes.fromhex(
    '02 1A 72 11 00 00 00 18 00 B5 34 AF 36 8F 61 FF FF 78 00 00 00 80 57 1D F7 2A')


def _u16be(data: bytes, off: int) -> int:
    return (data[off] << 8) | data[off + 1]


def _i16be(data: bytes, off: int) -> int:
    v = _u16be(data, off)
    return v - 0x10000 if v >= 0x8000 else v


def decode_info_reply(reply: bytes) -> dict:
    """Decode one info reply; raises ValueError on shape mismatch."""
    reply = bytes(reply)
    if len(reply) < 15 or reply[:4] != bytes.fromhex('02 1A 72 11'):
        raise ValueError('not a Honda K-Line info reply (expected 02 1A 72 11 header)')
    rpm = _i16be(reply, 5)
    tps_raw = _u16be(reply, 7)
    ect_raw = _u16be(reply, 9)
    iat_raw = _u16be(reply, 11)
    return {
        'rpm_candidate': rpm,
        'tps_raw': tps_raw,
        'tps_volt_candidate': round(tps_raw * 20 / 255 / 255, 4),
        'ect_raw': ect_raw,
        'ect_volt_candidate': round(ect_raw * 20 / 255 / 255, 4),
        'iat_raw': iat_raw,
        'iat_volt_candidate': round(iat_raw * 20 / 255 / 255, 4),
        'raw': reply.hex().upper(),
    }
