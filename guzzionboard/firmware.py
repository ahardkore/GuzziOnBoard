"""ECU firmware images: containers, validation and comparison.

Nothing here touches a motorcycle. It exists so that an image is checked
*before* it is anywhere near an ECU, because the cheapest brick to avoid is
the one caused by writing a structurally wrong file.

Checks implemented:

* exact size against the catalog's declared region;
* interrupt/jump table sanity (the IAW images begin with an ``FA 00 xx xx``
  vector table - GuzziDiag's own writer uses this to refuse encrypted ``.ddg``
  files, and 5am_util tells you to eyeball the same bytes);
* hardware-family compatibility (flashing an HW1xx image into an HW3xx 7SM
  bricks it - this is the single most destructive mistake in the Guzzi world);
* blank/erased-image detection;
* content hashes for backup verification.
"""
from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass, field
from pathlib import Path


class FirmwareError(Exception):
    pass


class IncompatibleImage(FirmwareError):
    """The image does not belong in this ECU. Refuse loudly."""


# --------------------------------------------------------------------------
# Checksums
# --------------------------------------------------------------------------


def sum16(data: bytes) -> int:
    """16-bit arithmetic sum, the classic Marelli-style image checksum."""
    return sum(data) & 0xFFFF


def sum32(data: bytes) -> int:
    return sum(data) & 0xFFFFFFFF


def word_sum16(data: bytes, *, endian: str = "big") -> int:
    """Sum of 16-bit words, which some loaders use instead of a byte sum."""
    if len(data) % 2:
        data = data + b"\x00"
    order = "big" if endian == "big" else "little"
    total = 0
    for i in range(0, len(data), 2):
        total += int.from_bytes(data[i : i + 2], order)
    return total & 0xFFFF


def checksums(data: bytes) -> dict:
    """Every checksum worth recording for an image."""
    return {
        "length": len(data),
        "sum16": sum16(data),
        "sum32": sum32(data),
        "word_sum16_be": word_sum16(data, endian="big"),
        "word_sum16_le": word_sum16(data, endian="little"),
        "md5": hashlib.md5(data).hexdigest(),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


# --------------------------------------------------------------------------
# Structure checks
# --------------------------------------------------------------------------

#: IAW images start with an exception/interrupt vector table whose entries
#: begin with 0xFA. Observed directly at the start of a 5AM dump:
#:     FA 00 00 02  FA 00 04 40  FA 00 08 40  FA 00 0C 40 ...
VECTOR_MARKER = 0xFA
VECTOR_ENTRY_LEN = 4


def looks_like_vector_table(data: bytes, *, entries: int = 16) -> bool:
    """True when the image opens with a plausible IAW vector table."""
    if len(data) < entries * VECTOR_ENTRY_LEN:
        return False
    return all(
        data[i * VECTOR_ENTRY_LEN] == VECTOR_MARKER for i in range(entries)
    )


def is_blank(data: bytes) -> bool:
    """An erased or all-zero image: never a valid thing to flash."""
    if not data:
        return True
    first = data[0]
    return first in (0x00, 0xFF) and data.count(first) == len(data)


def entropy_estimate(data: bytes, *, sample: int = 65536) -> float:
    """Rough Shannon entropy in bits/byte over a sample.

    Encrypted or compressed containers (``.ddg``) sit close to 8.0; a plain
    firmware image is typically 3-6.
    """
    import math

    chunk = data[:sample]
    if not chunk:
        return 0.0
    counts = [0] * 256
    for byte in chunk:
        counts[byte] += 1
    total = len(chunk)
    return -sum(
        (c / total) * math.log2(c / total) for c in counts if c
    )


#: Hardware strings look like IAW5AMHW610, IAW7SMHW320, IAW15RCHW...
HW_PATTERN = re.compile(rb"IAW[0-9A-Z]{2,5}HW([0-9]{3})")


def extract_hardware_strings(data: bytes) -> list[str]:
    """Pull any embedded IAW hardware identifiers out of an image."""
    return sorted({m.group(0).decode("ascii") for m in HW_PATTERN.finditer(data)})


def hardware_family(hardware: str) -> str:
    """The family digit that must match: HW610 -> '6', HW320 -> '3'.

    The 7SM warning is explicit: do not flash an HW1xx image into an HW3xx ECU
    or the other way round.
    """
    match = re.search(r"HW(\d)", hardware or "")
    return match.group(1) if match else ""


# --------------------------------------------------------------------------
# Image
# --------------------------------------------------------------------------


@dataclass
class Finding:
    level: str          # "ok" | "warn" | "fatal"
    check: str
    detail: str

    def as_dict(self) -> dict:
        return {"level": self.level, "check": self.check, "detail": self.detail}


@dataclass
class FirmwareImage:
    """An ECU image plus everything known about where it came from."""

    data: bytes
    ecu_id: str = ""
    region: str = "flash"
    source: str = ""              # "read" | "file"
    path: str = ""
    read_at: float = field(default_factory=time.time)
    identity: dict = field(default_factory=dict)
    meta: dict = field(default_factory=dict)

    # -- construction -----------------------------------------------------
    @classmethod
    def from_file(cls, path: str | Path, **kw) -> "FirmwareImage":
        path = Path(path)
        return cls(data=path.read_bytes(), source="file", path=str(path), **kw)

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.data)
        sidecar = path.with_suffix(path.suffix + ".json")
        import json

        sidecar.write_text(
            json.dumps(self.describe(), indent=2, default=str), encoding="utf-8"
        )
        self.path = str(path)
        return path

    # -- description ------------------------------------------------------
    @property
    def size(self) -> int:
        return len(self.data)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()

    def describe(self) -> dict:
        return {
            "ecu_id": self.ecu_id,
            "region": self.region,
            "source": self.source,
            "path": self.path,
            "read_at": self.read_at,
            "read_at_text": time.strftime(
                "%Y-%m-%d %H:%M:%S", time.localtime(self.read_at)
            ),
            "identity": self.identity,
            "checksums": checksums(self.data),
            "hardware_strings": extract_hardware_strings(self.data),
            "vector_table": looks_like_vector_table(self.data),
            "entropy": round(entropy_estimate(self.data), 2),
            "blank": is_blank(self.data),
            "meta": self.meta,
        }

    def matches(self, other: "FirmwareImage") -> bool:
        return self.data == other.data

    # -- validation -------------------------------------------------------
    def validate_for(self, profile, *, region: str = "flash",
                     target_identity: dict | None = None) -> list[Finding]:
        """Check this image against an ECU profile before writing it.

        Returns findings; any ``fatal`` entry must block the write.
        """
        findings: list[Finding] = []
        spec = (profile.memory or {}).get("regions", {}).get(region, {})

        # -- size ---------------------------------------------------------
        expected = spec.get("size")
        if expected:
            if self.size == expected:
                findings.append(
                    Finding("ok", "size", f"{self.size} bytes, exactly as expected")
                )
            else:
                findings.append(
                    Finding(
                        "fatal", "size",
                        f"image is {self.size} bytes, the {region} region of "
                        f"{profile.family} is {expected} bytes",
                    )
                )
        else:
            findings.append(
                Finding(
                    "warn", "size",
                    f"no declared size for the {region} region of {profile.family}; "
                    "cannot confirm this image belongs here",
                )
            )

        # -- blank --------------------------------------------------------
        if is_blank(self.data):
            findings.append(
                Finding("fatal", "blank", "image is entirely 0x00 or 0xFF")
            )

        # -- structure ----------------------------------------------------
        if spec.get("expect_vector_table"):
            if looks_like_vector_table(self.data):
                findings.append(
                    Finding("ok", "vector-table", "IAW vector table present at offset 0")
                )
            else:
                head = self.data[:16].hex(" ")
                findings.append(
                    Finding(
                        "fatal", "vector-table",
                        f"no IAW vector table at offset 0 (starts {head}). "
                        "This is usually an encrypted .ddg container or an "
                        "image for a different ECU, not a flashable binary.",
                    )
                )

        # High entropy on its own is weak evidence; combined with a missing
        # vector table it is how GuzziDiag spots an encrypted .ddg container.
        entropy = entropy_estimate(self.data)
        if entropy > 7.8:
            if looks_like_vector_table(self.data):
                findings.append(
                    Finding(
                        "warn", "entropy",
                        f"entropy {entropy:.2f} bits/byte is unusually high for "
                        "firmware, but the vector table is intact",
                    )
                )
            else:
                findings.append(
                    Finding(
                        "fatal", "entropy",
                        f"entropy {entropy:.2f} bits/byte and no vector table - "
                        "this is an encrypted or compressed container, not a "
                        "flashable image",
                    )
                )

        # -- hardware compatibility ---------------------------------------
        target_hw = ""
        if target_identity:
            target_hw = str(target_identity.get("Hardware", "")).strip()
        image_hw = extract_hardware_strings(self.data)

        if target_hw and image_hw:
            target_family = hardware_family(target_hw)
            image_families = {hardware_family(h) for h in image_hw}
            if target_family and target_family in image_families:
                findings.append(
                    Finding("ok", "hardware", f"image matches {target_hw}")
                )
            else:
                findings.append(
                    Finding(
                        "fatal", "hardware",
                        f"ECU reports {target_hw} but the image carries "
                        f"{', '.join(image_hw)}. Flashing across hardware "
                        "families bricks the ECU.",
                    )
                )
        elif target_hw and not image_hw:
            findings.append(
                Finding(
                    "warn", "hardware",
                    f"ECU reports {target_hw} but the image embeds no hardware "
                    "string, so compatibility cannot be confirmed",
                )
            )
        else:
            findings.append(
                Finding(
                    "warn", "hardware",
                    "ECU identity unknown; identify the ECU before writing",
                )
            )

        return findings

    # -- comparison -------------------------------------------------------
    def diff(self, other: "FirmwareImage", *, max_runs: int = 200) -> dict:
        """Byte-level difference summary against another image."""
        a, b = self.data, other.data
        if len(a) != len(b):
            return {
                "identical": False,
                "size_mismatch": [len(a), len(b)],
                "runs": [],
                "changed_bytes": None,
            }
        runs: list[dict] = []
        changed = 0
        start = None
        for i in range(len(a)):
            if a[i] != b[i]:
                changed += 1
                if start is None:
                    start = i
            elif start is not None:
                if len(runs) < max_runs:
                    runs.append(
                        {"offset": start, "length": i - start,
                         "before": a[start:i][:32].hex(" "),
                         "after": b[start:i][:32].hex(" ")}
                    )
                start = None
        if start is not None and len(runs) < max_runs:
            runs.append(
                {"offset": start, "length": len(a) - start,
                 "before": a[start:][:32].hex(" "), "after": b[start:][:32].hex(" ")}
            )
        return {
            "identical": changed == 0,
            "changed_bytes": changed,
            "changed_pct": round(100 * changed / max(1, len(a)), 4),
            "run_count": len(runs),
            "runs": runs,
        }


def summarise_findings(findings: list[Finding]) -> dict:
    fatal = [f for f in findings if f.level == "fatal"]
    warn = [f for f in findings if f.level == "warn"]
    return {
        "ok": not fatal,
        "fatal": [f.as_dict() for f in fatal],
        "warnings": [f.as_dict() for f in warn],
        "findings": [f.as_dict() for f in findings],
    }
