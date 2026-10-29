"""ELM327 serial transport, restricted to HarleyDroid read-only J1850.

Protocol behavior adapted from HarleyDroid EVO, copyright (C) 2010–2012
Stelian Pop and (C) 2026 Quickosss, GPL-3.0-or-later. See
LICENSES/HarleyDroidEVO-GPL-3.0.txt and docs/HARLEY_TUNING.md. This
integration has synthetic tests only, not motorcycle validation.
"""
from __future__ import annotations

import os
import re
import time

from .base import Connection, InitResult, Transport, TransportError, TransportUnavailable

# Deliberately no arbitrary AT, raw-frame or ECU-command interface.
_ALLOWED = frozenset({"ATWS", "ATE1", "ATH1", "ATAL", "ATS0", "ATSP2", "ATMA",
                      "ATSH0C10F1", "ATSH6C10F1", "ATSH6C40F1", "ATSH6C60F1",
                      "3C01", "3C02", "3C03", "3C04", "3C0B", "3C0F", "3C10", "3C11", "1952FF00"})


class ElmJ1850Connection(Connection):
    def __init__(self, serial_port):
        self.serial = serial_port
        self._open = True

    @property
    def is_open(self):
        return self._open and bool(getattr(self.serial, "is_open", True))

    def write(self, data: bytes) -> None:
        raise PermissionError("ELM Harley session does not permit arbitrary frames")

    def read_frame(self, timeout: float) -> bytes:
        raise PermissionError("use the restricted Harley diagnostic operations")

    def _send(self, command: str) -> None:
        if command not in _ALLOWED or not self.is_open:
            raise PermissionError("ELM command is not allowed or port is closed")
        data = (command + "\r").encode("ascii")
        if self.serial.write(data) != len(data):
            raise TransportError("ELM command was not fully written")
        self.serial.flush()

    def _read_prompt(self, timeout: float, *, initial: bytes = b"") -> bytes:
        deadline = time.monotonic() + timeout
        result = bytearray(initial)
        while time.monotonic() < deadline:
            chunk = self.serial.read(1)
            if chunk == b">":
                return bytes(result)
            result.extend(chunk)
            if len(result) > 65536:
                raise TransportError("ELM response exceeds 64 KiB")
        raise TransportError("ELM prompt timed out; disconnect and reconnect")

    def command(self, command: str, timeout: float = 2.5) -> str:
        if command == "ATMA":
            raise PermissionError("monitor requires bounded monitor operation")
        try:
            self._send(command)
            raw = self._read_prompt(timeout)
            return raw.decode("ascii", "strict")
        except PermissionError:
            self.close()
            raise
        except (OSError, UnicodeError) as exc:
            self.close()
            raise TransportError(f"ELM serial command failed: {exc}") from exc
        except Exception:
            self.close()
            raise

    def monitor(self, timeout: float = 1.5) -> str:
        if not 0.1 <= timeout <= 3.0:
            raise ValueError("monitor timeout must be between 0.1 and 3 seconds")
        try:
            self._send("ATMA")
            deadline = time.monotonic() + timeout
            data = bytearray()
            while time.monotonic() < deadline:
                part = self.serial.read(1)
                if part == b">":
                    raise TransportError("ELM monitor stopped unexpectedly")
                data.extend(part)
                if len(data) > 65536:
                    raise TransportError("ELM monitor exceeds 64 KiB")
            # Source's monitor stop sequence: CR, then wait for the prompt.
            if self.serial.write(b"\r") != 1:
                raise TransportError("ELM monitor stop was not fully written")
            self.serial.flush()
            return self._read_prompt(2.5, initial=bytes(data)).decode("ascii", "strict")
        except (OSError, UnicodeError) as exc:
            self.close()
            raise TransportError(f"ELM serial monitor failed: {exc}") from exc
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        if self._open:
            self._open = False
            self.serial.close()


class ElmJ1850Transport(Transport):
    name = "elm_j1850"
    is_physical = True

    def __init__(self, device: str, baud: int = 38400):
        if not isinstance(device, str) or not device.strip() or any(ord(c) < 32 for c in device):
            raise TransportUnavailable("An explicit ELM327 serial device is required")
        self.device, self.baud = device.strip(), baud

    def open(self) -> Connection:
        try:
            import serial
        except ImportError as exc:
            raise TransportUnavailable("pyserial is required for ELM327 (install hardware extras)") from exc
        try:
            options = {"port": self.device, "baudrate": self.baud, "timeout": 0.05, "write_timeout": 1}
            if os.name == "posix":
                options["exclusive"] = True
            return ElmJ1850Connection(serial.Serial(**options))
        except (OSError, serial.SerialException) as exc:
            raise TransportUnavailable(f"ELM327 serial port could not be opened: {exc}") from exc

    def initialize(self, connection: Connection, **kwargs) -> InitResult:
        if kwargs.get("method") != "harley-j1850-harleydroid" or not isinstance(connection, ElmJ1850Connection):
            raise TransportUnavailable("Harley ELM requires the profile-default initialization")
        version = connection.command("ATWS", 5.0)
        if not re.search(r"ELM327", version, re.I):
            raise TransportError("ELM327 warm start did not identify an ELM327 adapter")
        for cmd in ("ATE1", "ATH1", "ATAL", "ATS0", "ATSP2"):
            response = connection.command(cmd)
            lines = [x.strip().upper() for x in re.split(r"[\r\n]+", response) if x.strip()]
            if "OK" not in lines:
                raise TransportError(f"ELM327 did not accept {cmd}")
        return InitResult(True, "harley-j1850-harleydroid", protocol="j1850-vpw",
                          handshake_complete=True, baud=self.baud,
                          detail="ELM configured for J1850 VPW; adapter setup does not confirm a bike response")
