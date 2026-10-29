"""Read-only HarleyDroid J1850 session for an ELM327 serial connection.

Adapted from HarleyDroid EVO (J1850.kt / HarleyDroidDiagnostics.kt),
Copyright (C) 2010–2012 Stelian Pop and (C) 2026 Quickosss,
GPL-3.0-or-later. See LICENSES/HarleyDroidEVO-GPL-3.0.txt.
No ECU write, memory, security, actuator, or fault-clear operation.
This integration is tested with synthetic fixtures only.
"""
from __future__ import annotations

import re

from .kwp2000 import ProtocolError


def _crc(payload: bytes) -> int:
    value = 0xff
    for byte in payload:
        value ^= byte
        for _ in range(8):
            value = ((value << 1) ^ (0x1d if value & 0x80 else 0)) & 0xff
    return value ^ 0xff


def _lines(response: str) -> list[bytes]:
    """Parse candidate full J1850 frames; callers must validate their CRCs."""
    frames = []
    for line in re.split(r"[\r\n]+", response):
        line = line.strip()
        if not line:
            continue
        if line.upper() in ("?", "BUS ERROR", "CAN ERROR", "UNABLE TO CONNECT", "BUFFER FULL"):
            raise ProtocolError(f"ELM reported {line}")
        if not re.fullmatch(r"[0-9A-Fa-f ]+", line):
            continue
        compact = line.replace(" ", "")
        if len(compact) % 2 or len(compact) < 8 or len(compact) > 24:
            continue
        raw = bytes.fromhex(compact)
        frames.append(raw)
    return frames


def _verified(raw: bytes) -> bool:
    return len(raw) >= 4 and _crc(raw[:-1]) == raw[-1]


class HarleyJ1850Session:
    def __init__(self, connection, *, on_frame=None):
        self.connection = connection
        self.on_frame = on_frame or (lambda _direction, _raw: None)

    def _command(self, command: str, timeout=2.5) -> str:
        return self.connection.command(command, timeout)

    def _header(self, header: str) -> None:
        lines = [line.strip().upper() for line in re.split(r"[\r\n]+", self._command(header))]
        if "OK" not in lines:
            raise ProtocolError(f"ELM did not accept {header}")

    def _matching(self, response: str, prefix: bytes, length: int) -> list[bytes]:
        out = []
        for frame in _lines(response):
            if not frame.startswith(prefix):
                continue
            if len(frame) != length or not _verified(frame):
                raise ProtocolError("Harley J1850 matching response has invalid length or CRC")
            self.on_frame("rx", frame)
            out.append(frame)
        return out

    def read_identity(self) -> tuple[dict, bytes]:
        self._header("ATSH0C10F1")
        fragments, raw = {}, []
        lengths = {1: 6, 2: 6, 3: 6, 4: 6, 11: 1, 15: 6, 16: 6, 17: 5}
        for block, length in lengths.items():
            response = self._command(f"3C{block:02X}", 2.5)
            frames = self._matching(response, bytes([0x0c, 0xf1, 0x10, 0x7c, block]), 6 + length)
            if len(frames) > 1:
                raise ProtocolError("Ambiguous repeated Harley identity block")
            if not frames:
                continue
            part = frames[0][5:-1]
            raw.append(frames[0])
            if block != 11 and any(byte < 32 or byte > 126 for byte in part):
                raise ProtocolError("Harley identity contains non-printable data")
            fragments[block] = part
        fields = {}
        for title, blocks in (("ECM part number", (1, 2)), ("ECM calibration ID", (3, 4)), ("VIN", (15, 16, 17))):
            if all(block in fragments for block in blocks):
                fields[title] = b"".join(fragments[block] for block in blocks).decode("ascii").strip()
        if 11 in fragments:
            fields["ECM software level"] = str(fragments[11][0])
        if not fields:
            raise ProtocolError("No complete Harley identity fields returned; ELM setup alone is not ECU identification")
        return fields, b"".join(raw)

    def read_snapshot(self) -> dict[int, bytes]:
        data = self.connection.monitor(1.5)
        prefixes = {b"\x28\x1b\x10\x02": (1, 7),
                    b"\x48\x29\x10\x02": (2, 7),
                    b"\xa8\x49\x10\x10": (3, 6)}
        result = {}
        for frame in _lines(data):
            entry = prefixes.get(frame[:4])
            if entry and len(frame) == entry[1] and _verified(frame):
                self.on_frame("rx", frame)
                result[entry[0]] = frame[4:-1]
        return result

    def read_dtcs(self) -> dict:
        dtcs, modules = [], {}
        for address, name in ((0x10, "ECM"), (0x40, "ABS"), (0x60, "TSM")):
            self._header(f"ATSH6C{address:02X}F1")
            response = self._command("1952FF00", 3.0)
            frames = self._matching(response, bytes([0x6c, 0xf1, address, 0x59]), 7)
            modules[name] = {"responded": bool(frames)}
            for frame in frames:
                a, b = frame[4:6]
                if not (a or b):
                    continue
                code = f"{'PCBU'[a >> 6]}{(a >> 4) & 3}{a & 15:X}{b:02X}"
                dtcs.append({"code": code, "description": "", "status_byte": None,
                             "kind": f"{name} response", "status": "unknown", "warning_indicator": False})
        return {"dtcs": dtcs, "format": "harley-j1850", "modules": modules, "context": {},
                "note": "Only responding ECM/ABS/TSM modules are represented. Current/historic status and warning-lamp state were not determined; missing responses do not mean no faults."}

    def close(self):
        pass  # monitor is stopped before returning; no guessed ECU stop command
