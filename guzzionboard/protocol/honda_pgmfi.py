"""Honda Keihin PGM-FI diagnostic table research (read-only).

Based on the diagnostic table request/response protocol and polling list of
HondaECU (WiseNoodle/honda-moto-ecu-suite, GPL-3.0, revision
85431bd831b2c50a640fac35dccf36c09df20c07). See
LICENSES/Honda-Moto-ECU-Suite-GPL-3.0.txt. The adaptation is not tested on
physical hardware; diagnostic-table fitment varies between ECUs.
"""
from __future__ import annotations

from .honda_cbr600rr import HondaCBR600RRSession, read_honda_frame
from .kwp2000 import ProtocolError


class HondaPgmfiSession(HondaCBR600RRSession):
    # HondaECU probes these twelve diagnostic tables, not ECU flash memory.
    LIVE_TABLES = frozenset((0x10, 0x11, 0x17, 0x20, 0x21, 0x60,
                             0x61, 0x67, 0x70, 0x71, 0xD0, 0xD1))

    def request(self, payload, *, timeout=None):
        payload = bytes(payload)
        if len(payload) != 2 or payload[0] != 0x71 or payload[1] not in (self.LIVE_TABLES | {0x00}):
            raise PermissionError('Honda PGM-FI research allows only fixed diagnostic table reads')
        table = payload[1]
        body = bytes([0x72, 0x05, 0x71, table])
        request = body + bytes([(-sum(body)) & 0xff])
        self._log('tx', request)
        self.connection.write(request)
        result = read_honda_frame(self.connection, 1.0 if timeout is None else timeout)
        self._log('rx', result)
        if result[0] != 0x02 or result[2:4] != bytes([0x71, table]):
            raise ProtocolError('Honda PGM-FI response header or table mismatch')
        if len(result) < (10 if table == 0x00 else 6):
            raise ProtocolError('Honda PGM-FI response has no complete table data')
        return result

    def read_table(self, table):
        if table not in self.LIVE_TABLES:
            raise PermissionError('Honda PGM-FI table is not allowlisted')
        return self.request(bytes([0x71, table]))[4:-1]

    def tester_present(self):
        return self.request(b'\x71\x00')
