"""Read-only KDS conversation for the 2006 ER-6n.

Adapted from Gabriele Randazzo's MIT-licensed iKawa Kline.cpp/Kline.h,
revision 79eb9049d13037be6fd91b8a1d1acd164ca70104. See LICENSES/iKawa-MIT.txt.
This implementation has not been tested on hardware by GuzziOnBoard.
"""
from __future__ import annotations

import time
from .kwp2000 import KWP2000Session, ProtocolError, NegativeResponse, checksum, decode_frame


class KawasakiER6nSession(KWP2000Session):
    """A deliberately closed request set, including the session startup."""

    # The source specifies the exact payload length for each read.
    LENGTHS = {0x02: 1, 0x04: 2, 0x44: 4, 0x05: 2, 0x06: 1, 0x07: 1, 0x08: 1,
               0x09: 2, 0x0A: 1, 0x0B: 1, 0x0C: 2}

    def request(self, payload, *, timeout=None):
        payload = bytes(payload)
        allowed = payload == b"\x10\x80" or (
            len(payload) == 2 and payload[0] == 0x21 and payload[1] in self.LENGTHS
        )
        if not allowed:
            raise PermissionError("ER-6n read-only session refuses this request")
        # iKawa uses an explicit length field for all two-byte requests.
        body = bytes([0x80, 0x11, 0xF1, len(payload)]) + payload
        raw = body + bytes([checksum(body)])
        # Source uses 55ms between requests and 5ms between individual bytes.
        time.sleep(0.055)
        self._log("tx", raw)
        self.connection.write(raw)
        reply = self.connection.read_frame(2.0 if timeout is None else timeout)
        if not reply:
            raise ProtocolError("ER-6n response timed out")
        self._log("rx", reply)
        frame = decode_frame(reply)
        if frame.target != 0xF1 or frame.source != 0x11:
            raise ProtocolError("ER-6n response address mismatch")
        if frame.is_negative:
            if frame.payload[1] != payload[0]:
                raise ProtocolError("ER-6n negative response does not match request")
            raise NegativeResponse(frame.payload[1], frame.nrc or 0)
        if payload == b"\x10\x80":
            if frame.payload != b"\x50\x80":
                raise ProtocolError("ER-6n session start response mismatch")
        else:
            if (len(frame.payload) != 2 + self.LENGTHS[payload[1]]
                    or frame.payload[:2] != bytes([0x61, payload[1]])):
                raise ProtocolError("ER-6n data response identifier or length mismatch")
        return frame

    def tester_present(self):
        # iKawa continuously polls; do not invent a TesterPresent service.
        return self.request([0x21, 0x09])


def decode_kawasaki_value(local_id: int, raw: bytes) -> float:
    """Source-reported ER-6n formulas; validate lengths before arithmetic."""
    expected = KawasakiER6nSession.LENGTHS.get(local_id)
    if expected is None or len(raw) != expected:
        raise ProtocolError("unexpected ER-6n data length")
    a = raw[0]
    if local_id == 0x02:
        return int(a != 0)  # upstream presents this switch as boolean
    if local_id == 0x04:
        # C++ integer division truncates toward zero, including below closed TPS.
        numerator = (int.from_bytes(raw, 'big') - 226) * 100
        return (numerator // 635 if numerator >= 0 else -((-numerator) // 635)) + 2
    if local_id == 0x44:
        # Upstream displays hours plus whole minutes; semantics unconfirmed.
        return (int.from_bytes(raw, 'big') // 60) / 60
    if local_id in (0x05, 0x09, 0x0C):
        value = a * 100 + raw[1]  # upstream uses decimal weighting, not 16-bit BE
        return value / 2 if local_id != 0x09 else value
    if local_id in (0x06, 0x07):
        return (a - 48) / 1.6
    if local_id == 0x08:
        return a // 2
    if local_id == 0x0A:
        return round(a / 12.75, 2)
    return a
