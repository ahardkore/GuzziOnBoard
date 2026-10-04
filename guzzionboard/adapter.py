"""Adapter discovery and pre-flight checks.

The equivalent of GuzziDiag's AdapterTest, plus the one setting that quietly
ruins more ECU reads than anything else: the FTDI latency timer.

An FTDI chip defaults to a 16 ms read latency. KWP2000 block reads are a
request/response ping-pong, so 16 ms of dead time per block turns a 20 minute
flash read into something far longer, and pushes responses past the P2 timing
window on impatient ECUs. The GuzziDiag documentation is blunt about it:
"Have you set the delay of the driver to 1ms? That's essential!"

On Linux the timer is exposed in sysfs and this module can read and fix it.
On Windows and macOS it lives in the driver's properties and we can only tell
the user where to look.
"""
from __future__ import annotations

import os
import platform
import sys
from dataclasses import dataclass, field
from pathlib import Path

#: Recommended FTDI latency in milliseconds.
RECOMMENDED_LATENCY_MS = 1

#: sysfs location of the per-port latency timer on Linux.
SYSFS_USB_SERIAL = Path("/sys/bus/usb-serial/devices")


@dataclass
class Check:
    name: str
    status: str            # "ok" | "warn" | "fail" | "unknown"
    detail: str
    fix: str = ""

    def as_dict(self) -> dict:
        return {
            "name": self.name, "status": self.status,
            "detail": self.detail, "fix": self.fix,
        }


@dataclass
class AdapterReport:
    port: str = ""
    checks: list[Check] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(c.status == "fail" for c in self.checks)

    @property
    def warnings(self) -> list[Check]:
        return [c for c in self.checks if c.status == "warn"]

    def as_dict(self) -> dict:
        return {
            "port": self.port, "ok": self.ok,
            "checks": [c.as_dict() for c in self.checks],
        }

    def text(self) -> str:
        glyph = {"ok": "[ ok ]", "warn": "[warn]", "fail": "[FAIL]", "unknown": "[ ?? ]"}
        lines = [f"Adapter check: {self.port or 'no port selected'}", ""]
        for check in self.checks:
            lines.append(f"{glyph[check.status]} {check.name}")
            lines.append(f"        {check.detail}")
            if check.fix:
                lines.append(f"        fix: {check.fix}")
        return "\n".join(lines)


# --------------------------------------------------------------------------
# FTDI latency timer
# --------------------------------------------------------------------------


def _sysfs_latency_path(port: str) -> Path | None:
    """Map /dev/ttyUSB0 to its sysfs latency_timer attribute."""
    name = os.path.basename(port)
    if not name.startswith("ttyUSB"):
        return None
    path = SYSFS_USB_SERIAL / name / "latency_timer"
    return path if path.exists() else None


def read_latency_timer(port: str) -> int | None:
    """Current FTDI latency in ms, or None if it cannot be determined."""
    path = _sysfs_latency_path(port)
    if path is None:
        return None
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None


def set_latency_timer(port: str, value: int = RECOMMENDED_LATENCY_MS) -> bool:
    """Try to set the FTDI latency timer. Usually needs root or a udev rule."""
    path = _sysfs_latency_path(port)
    if path is None:
        return False
    try:
        path.write_text(str(value))
        return read_latency_timer(port) == value
    except OSError:
        return False


UDEV_RULE = (
    'ACTION=="add", SUBSYSTEM=="usb-serial", DRIVER=="ftdi_sio", '
    'ATTR{latency_timer}="1"'
)


def latency_fix_instructions(port: str) -> str:
    system = platform.system()
    if system == "Linux":
        return (
            f"sudo sh -c 'echo 1 > /sys/bus/usb-serial/devices/"
            f"{os.path.basename(port)}/latency_timer'\n"
            "To make it permanent, put this in "
            "/etc/udev/rules.d/99-ftdi-latency.rules:\n"
            f"  {UDEV_RULE}"
        )
    if system == "Windows":
        return (
            "Device Manager -> Ports (COM & LPT) -> your adapter -> Properties "
            "-> Port Settings -> Advanced -> Latency Timer (msec) -> 1"
        )
    return (
        "macOS: the FTDI VCP driver defaults to 1 ms with the D2XX "
        "configuration tool; the Apple-supplied driver does not expose it."
    )


# --------------------------------------------------------------------------
# Port discovery
# --------------------------------------------------------------------------


def list_ports() -> list[dict]:
    """Serial ports, with the ones that look like diagnostic adapters first."""
    try:
        from serial.tools import list_ports as pyserial_ports
    except ImportError:
        return []

    out = []
    for info in pyserial_ports.comports():
        description = (info.description or "").lower()
        manufacturer = (getattr(info, "manufacturer", "") or "").lower()
        likely = any(
            tag in description or tag in manufacturer
            for tag in ("ftdi", "ft232", "usb serial", "kkl", "obd", "prolific", "ch340")
        )
        out.append(
            {
                "device": info.device,
                "description": info.description or "",
                "manufacturer": getattr(info, "manufacturer", "") or "",
                "vid": info.vid,
                "pid": info.pid,
                "serial_number": getattr(info, "serial_number", "") or "",
                "likely_adapter": likely,
                "latency_ms": read_latency_timer(info.device),
            }
        )
    out.sort(key=lambda p: (not p["likely_adapter"], p["device"]))
    return out


# --------------------------------------------------------------------------
# The check itself
# --------------------------------------------------------------------------


def check_adapter(port: str = "", *, loopback: bool = False) -> AdapterReport:
    """Run every pre-flight check we can without touching an ECU."""
    report = AdapterReport(port=port)
    add = report.checks.append
    system = platform.system()

    # -- pyserial present -------------------------------------------------
    try:
        import serial  # noqa: F401

        add(Check("pyserial", "ok", "pyserial is installed"))
    except ImportError:
        add(
            Check(
                "pyserial", "fail", "pyserial is not installed",
                fix="pip install 'guzzionboard[hardware]'",
            )
        )
        return report

    # -- the port exists --------------------------------------------------
    if not port:
        ports = list_ports()
        likely = [p for p in ports if p["likely_adapter"]]
        if likely:
            add(
                Check(
                    "port", "warn",
                    "no port selected; candidates: "
                    + ", ".join(p["device"] for p in likely),
                    fix=f"select {likely[0]['device']}",
                )
            )
        else:
            add(
                Check(
                    "port", "fail", "no serial adapter found",
                    fix=(
                        "plug the adapter in. Linux: /dev/ttyUSB*, "
                        "macOS: /dev/tty.usbserial*, Windows: COMx"
                    ),
                )
            )
        return report

    if not Path(port).exists() and system != "Windows":
        add(Check("port", "fail", f"{port} does not exist",
                  fix="check the cable and `dmesg | tail`"))
        return report
    add(Check("port", "ok", f"{port} is present"))

    # -- permissions ------------------------------------------------------
    if system == "Linux":
        if os.access(port, os.R_OK | os.W_OK):
            add(Check("permissions", "ok", f"{port} is readable and writable"))
        else:
            add(
                Check(
                    "permissions", "fail", f"no read/write access to {port}",
                    fix="sudo usermod -aG dialout $USER, then log out and back in",
                )
            )

    # -- FTDI latency timer ----------------------------------------------
    latency = read_latency_timer(port)
    if latency is None:
        add(
            Check(
                "latency-timer", "unknown",
                "cannot read the FTDI latency timer on this platform. A 16 ms "
                "default makes long memory reads crawl and can break ECU timing.",
                fix=latency_fix_instructions(port),
            )
        )
    elif latency <= RECOMMENDED_LATENCY_MS:
        add(Check("latency-timer", "ok", f"{latency} ms"))
    else:
        add(
            Check(
                "latency-timer", "warn",
                f"{latency} ms. GuzziDiag calls 1 ms essential: at {latency} ms "
                "every block read wastes that long waiting for the USB chip, "
                "which is the usual cause of a 30 minute read taking hours.",
                fix=latency_fix_instructions(port),
            )
        )

    # -- the port actually opens -----------------------------------------
    try:
        import serial

        with serial.Serial(port, 10400, timeout=0.2) as handle:
            add(Check("open", "ok", f"opened {port} at 10400 8N1"))
            if loopback:
                handle.reset_input_buffer()
                handle.write(b"\x55")
                echo = handle.read(1)
                if echo == b"\x55":
                    add(
                        Check(
                            "loopback", "ok",
                            "byte came back - K and L are bridged, which is "
                            "normal for a K-Line adapter reading its own echo",
                        )
                    )
                else:
                    add(
                        Check(
                            "loopback", "warn",
                            "no echo. On a K-Line adapter the tester normally "
                            "hears itself; without an ECU attached this is "
                            "inconclusive.",
                        )
                    )
    except Exception as exc:
        add(Check("open", "fail", f"cannot open {port}: {exc}",
                  fix="close any other program using the port"))

    # -- environment ------------------------------------------------------
    if sys.platform == "win32":
        add(
            Check(
                "environment", "warn",
                "disable the screensaver, standby and the virus scanner before "
                "a long read or any write",
            )
        )
    if _in_virtual_machine():
        add(
            Check(
                "environment", "fail",
                "this looks like a virtual machine. USB serial timing through a "
                "VM is unreliable and has bricked ECUs mid-write.",
                fix="run the write from the host operating system",
            )
        )

    return report


def _in_virtual_machine() -> bool:
    for path in ("/sys/class/dmi/id/product_name", "/sys/class/dmi/id/sys_vendor"):
        try:
            value = Path(path).read_text().strip().lower()
        except OSError:
            continue
        if any(tag in value for tag in ("virtualbox", "vmware", "kvm", "qemu", "xen")):
            return True
    return False
