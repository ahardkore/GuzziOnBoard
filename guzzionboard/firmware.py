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
# IAW 5AM upload encoding
# --------------------------------------------------------------------------
#
# The IAW 5AM does not accept a plain dump on TransferData. The uploaded blob
# opens with eight fixed bytes, and every payload byte is then transformed by
# an add/rotate/invert pattern with an 8-byte period. Both the magic and the
# per-byte transforms are transcribed from ``encrypt_blob()`` in 5am_util's
# ``main.c`` and byte-verified against a compiled copy of the original C (see
# ``docs/PRIOR_ART.md`` 1.3 and the known-answer tests in test_firmware.py).

#: The eight bytes every upload blob begins with.
IAW5AM_UPLOAD_MAGIC = bytes((0xC2, 0x07, 0x16, 0x33, 0x6F, 0xEB, 0xB0, 0x1D))

#: Flash region 0x4000..0x50000, the part a dump contains.
IAW5AM_FLASH_SIZE = 0x4C000
#: The whole device, including the bootloader below 0x4000 that K-Line
#: cannot reach. A full-device file is 0x50000 bytes.
IAW5AM_DEVICE_SIZE = 0x50000
#: The program routine's checksum covers the region minus its last two bytes,
#: exactly as 5am_util computes it.
IAW5AM_CHECKSUM_LEN = 0x4BFFE


def _ror8(value: int, n: int) -> int:
    return ((value >> n) | (value << (8 - n))) & 0xFF


def _rol8(value: int, n: int) -> int:
    return ((value << n) | (value >> (8 - n))) & 0xFF


def iaw5am_encode_byte(value: int, position: int) -> int:
    """One byte of the upload transform. ``position`` is the blob offset."""
    step = position & 7
    if step == 0:
        return _ror8((value + 0x88) & 0xFF, 1) ^ 0xFF
    if step == 1:
        return _ror8((value + 0xC7) & 0xFF, 1)
    if step == 2:
        return _ror8((value + 0x26) & 0xFF, 3) ^ 0xFF
    if step == 3:
        return _ror8((value + 0xA5) & 0xFF, 5) ^ 0xFF
    if step == 4:
        return _ror8((value + 0x6C) & 0xFF, 2)
    if step == 5:
        return _ror8((value + 0xEB) & 0xFF, 6)
    if step == 6:
        return _ror8((value + 0x0A) & 0xFF, 6) ^ 0xFF
    return _ror8((0x66 - value) & 0xFF, 4)


def iaw5am_decode_byte(value: int, position: int) -> int:
    """The exact inverse of :func:`iaw5am_encode_byte`."""
    step = position & 7
    if step == 0:
        return (_rol8(value ^ 0xFF, 1) - 0x88) & 0xFF
    if step == 1:
        return (_rol8(value, 1) - 0xC7) & 0xFF
    if step == 2:
        return (_rol8(value ^ 0xFF, 3) - 0x26) & 0xFF
    if step == 3:
        return (_rol8(value ^ 0xFF, 5) - 0xA5) & 0xFF
    if step == 4:
        return (_rol8(value, 2) - 0x6C) & 0xFF
    if step == 5:
        return (_rol8(value, 6) - 0xEB) & 0xFF
    if step == 6:
        return (_rol8(value ^ 0xFF, 6) - 0x0A) & 0xFF
    return (0x66 - _rol8(value, 4)) & 0xFF


def iaw5am_encode(data: bytes) -> bytes:
    """Apply the upload transform to a whole buffer (magic included)."""
    return bytes(iaw5am_encode_byte(b, i) for i, b in enumerate(data))


def iaw5am_decode(data: bytes) -> bytes:
    """Undo :func:`iaw5am_encode` on a whole buffer."""
    return bytes(iaw5am_decode_byte(b, i) for i, b in enumerate(data))


def iaw5am_flash_payload(image: bytes) -> bytes:
    """Extract the 0x4C000 flash payload from a dump.

    Accepts either a region image (what :meth:`ProgrammingService.read_region`
    produces) or a full-device file (what IAW5xReader writes), and refuses
    anything else rather than guess what it is looking at.
    """
    if len(image) == IAW5AM_FLASH_SIZE:
        return image
    if len(image) == IAW5AM_DEVICE_SIZE:
        return image[0x4000:]
    raise FirmwareError(
        f"expected a {IAW5AM_FLASH_SIZE}-byte flash image or a "
        f"{IAW5AM_DEVICE_SIZE}-byte full-device dump, got {len(image)} bytes"
    )


def iaw5am_upload_blob(image: bytes) -> bytes:
    """Encode a flash image into the blob the 5AM write path expects.

    The result is 0x4C008 bytes: the magic, then the transformed payload.
    This is what RequestDownload hands over and TransferData streams, and it
    is *not* what the ECU ends up holding - the ECU decodes it into flash.
    """
    return iaw5am_encode(IAW5AM_UPLOAD_MAGIC + iaw5am_flash_payload(image))


def iaw5am_upload_checksum(image: bytes) -> int:
    """The 16-bit byte sum the program routine validates.

    Computed over the *plain* payload (0x4BFFE bytes of it), not the encoded
    blob - the ECU decodes before it checks.
    """
    return sum16(iaw5am_flash_payload(image)[:IAW5AM_CHECKSUM_LEN])


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
