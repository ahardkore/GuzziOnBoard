"""Kawasaki W230 (2024-2026) KDS K-Line register candidates (source-reported).

From digitwolf/w230 (MIT-style LICENSE present), commit
c4e11d7dc54bf76470512da18361faab00e72dcf - see docs/CAPTURE_SEARCH_2026-11-03.md.
The firmware does ISO-14230 fast init (25 ms wake pulse = one 0x00 byte at
360 baud), then startCommunication and startDiagnosticSession, and polls two
registers read-only ~3-4 times per second:

* register 0x09 - engine RPM, quarter-rpm (raw * 0.25)
* register 0x0C - road speed, km/h (raw * 1)

This documents the source's register table only. It is not a validated
profile for any specific bike; the catalog's KDS entries keep their existing
confidence and gating.
"""
from __future__ import annotations

PROFILE = 'kawasaki_w230_kds'

#: register id -> (name, unit, scale)
REGISTERS = {
    0x09: ('rpm', 'rpm', 0.25),
    0x0C: ('speed', 'km/h', 1.0),
}

WAKE_PULSE_BYTE = 0x00   # one 0x00 at 360 baud = 25 ms wake pulse
WAKE_BAUD = 360
COMM_BAUD = 10400


def decode_register(register: int, raw: bytes) -> dict:
    """Decode one KDS register reply value; raises KeyError for unknown ids."""
    name, unit, scale = REGISTERS[register]
    value = int.from_bytes(bytes(raw), 'big') * scale
    return {'register': register, 'key': name, 'value': value, 'unit': unit,
            'raw': bytes(raw).hex().upper()}
