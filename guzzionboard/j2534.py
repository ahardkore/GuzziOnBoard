"""Read-only Windows J2534 driver inventory.

Registry entries are claims made by installed drivers, not evidence that an
adapter is present, usable, or compatible with a motorcycle. No DLL is loaded.
"""
from __future__ import annotations

import platform
import struct


def inventory(*, registry=None, system=None) -> dict:
    system = system or platform.system()
    result = {
        "platform": system,
        "process_bits": struct.calcsize("P") * 8,
        "devices": [], "errors": [],
        "note": ("Registry inventory only: drivers are not loaded, devices are not "
                 "opened, and protocol flags are unverified driver claims. J2534 "
                 "transport and real-bike use are not enabled."),
    }
    if system != "Windows":
        result["note"] += " Windows registry discovery is unavailable on this platform."
        return result
    if registry is None:
        try:
            import winreg as registry
        except ImportError:
            result["errors"].append("Windows registry module is unavailable")
            return result
    protocols = ("CAN", "ISO15765", "ISO9141", "ISO14230", "J1850PWM", "J1850VPW")
    for version in ("04.04", "05.00"):
        path = rf"SOFTWARE\PassThruSupport.{version}"
        for bits, flag in ((32, registry.KEY_WOW64_32KEY), (64, registry.KEY_WOW64_64KEY)):
            try:
                root = registry.OpenKey(registry.HKEY_LOCAL_MACHINE, path, 0, registry.KEY_READ | flag)
            except FileNotFoundError:
                continue
            except OSError as exc:
                result["errors"].append(f"{version} {bits}-bit registry: {exc}")
                continue
            with root:
                index = 0
                while True:
                    try:
                        name = registry.EnumKey(root, index)
                    except OSError as exc:
                        # Windows ERROR_NO_MORE_ITEMS. Other errors must not look like
                        # a complete scan. Mock registries may use the same code.
                        if getattr(exc, "winerror", None) != 259:
                            result["errors"].append(f"{version} {bits}-bit enumeration: {exc}")
                        break
                    index += 1
                    try:
                        with registry.OpenKey(root, name, 0, registry.KEY_READ | flag) as key:
                            def value(field):
                                try:
                                    return registry.QueryValueEx(key, field)[0]
                                except FileNotFoundError:
                                    return None
                            library = value("FunctionLibrary")
                            if library is not None and not isinstance(library, str):
                                library = None
                            claims = {}
                            for protocol in protocols:
                                raw = value(protocol)
                                if raw is not None:
                                    claims[protocol] = raw if isinstance(raw, (int, str)) else str(raw)
                            result["devices"].append({
                                "name": name, "version": version, "registry_view_bits": bits,
                                "library": library or "", "protocol_claims": claims,
                                "process_matches_registry_view": bits == result["process_bits"],
                            })
                    except OSError as exc:
                        result["errors"].append(f"{version} {bits}-bit {name}: {exc}")
    return result
