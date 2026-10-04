"""Image validation: the cheap checks that stop an expensive mistake."""
from __future__ import annotations

import pytest

from guzzionboard.catalog import load_catalog
from guzzionboard.firmware import (
    FirmwareImage,
    checksums,
    entropy_estimate,
    extract_hardware_strings,
    hardware_family,
    is_blank,
    looks_like_vector_table,
    summarise_findings,
)


def vector_table(entries: int = 16) -> bytes:
    return b"".join(
        bytes([0xFA, 0x00, (i * 4) & 0xFF, 0x40]) for i in range(entries)
    )


def plausible_image(size: int) -> bytes:
    """A vector table followed by low-entropy, code-like filler."""
    head = vector_table(64)
    body = bytes((i // 7) % 23 for i in range(size - len(head)))
    return head + body


@pytest.fixture
def catalog():
    return load_catalog()


@pytest.fixture
def profile(catalog):
    return catalog.ecu("5am")


@pytest.fixture
def region_size(profile):
    return profile.memory["regions"]["flash"]["size"]


# -- primitives ------------------------------------------------------------


def test_vector_table_detection():
    assert looks_like_vector_table(vector_table())
    assert not looks_like_vector_table(b"\x00" * 64)
    assert not looks_like_vector_table(vector_table(4))  # too short


def test_blank_images_are_recognised():
    assert is_blank(b"\xff" * 100)
    assert is_blank(b"\x00" * 100)
    assert is_blank(b"")
    assert not is_blank(b"\x00" * 99 + b"\x01")


def test_entropy_separates_code_from_ciphertext():
    import os

    assert entropy_estimate(b"\x00" * 4096) < 0.1
    assert entropy_estimate(os.urandom(65536)) > 7.9


def test_hardware_strings_and_families():
    data = b"junk" + b"IAW5AMHW610" + b"more" + b"IAW7SMHW320"
    assert extract_hardware_strings(data) == ["IAW5AMHW610", "IAW7SMHW320"]
    assert hardware_family("IAW7SMHW320") == "3"
    assert hardware_family("IAW7SMHW120") == "1"
    assert hardware_family("nonsense") == ""


def test_checksums_cover_the_formats_loaders_use():
    sums = checksums(b"\x01\x02\x03\x04")
    assert sums["length"] == 4
    assert sums["sum16"] == 10
    assert sums["word_sum16_be"] == 0x0102 + 0x0304
    assert sums["word_sum16_le"] == 0x0201 + 0x0403
    assert len(sums["sha256"]) == 64


# -- validation ------------------------------------------------------------


def test_a_correct_image_passes(profile, region_size):
    image = FirmwareImage(data=plausible_image(region_size))
    result = summarise_findings(
        image.validate_for(
            profile, target_identity={"Hardware": "IAW5AMHW610"}
        )
    )
    assert result["ok"], result["fatal"]


def test_wrong_size_is_fatal(profile, region_size):
    image = FirmwareImage(data=plausible_image(region_size - 16))
    result = summarise_findings(image.validate_for(profile))
    assert not result["ok"]
    assert any(f["check"] == "size" for f in result["fatal"])


def test_an_encrypted_container_is_rejected(profile, region_size):
    """GuzziDiag refuses encrypted .ddg files via a jump-table test."""
    import os

    image = FirmwareImage(data=os.urandom(region_size))
    result = summarise_findings(image.validate_for(profile))
    assert not result["ok"]
    checks = {f["check"] for f in result["fatal"]}
    assert "vector-table" in checks
    assert "entropy" in checks


def test_high_entropy_alone_is_only_a_warning(profile, region_size):
    """A packed image with an intact vector table is suspicious, not fatal."""
    import os

    data = vector_table(64) + os.urandom(region_size - 256)
    image = FirmwareImage(data=data + b"\x00" * (region_size - len(data)))
    result = summarise_findings(
        image.validate_for(profile, target_identity={"Hardware": "IAW5AMHW610"})
    )
    assert result["ok"]
    assert any(w["check"] == "entropy" for w in result["warnings"])


def test_blank_image_is_fatal(profile, region_size):
    image = FirmwareImage(data=b"\xff" * region_size)
    result = summarise_findings(image.validate_for(profile))
    assert any(f["check"] == "blank" for f in result["fatal"])


def test_cross_family_flash_is_refused(profile, region_size):
    """The mistake that bricks 7SM ECUs, caught before a byte is sent."""
    data = bytearray(plausible_image(region_size))
    data[1024 : 1024 + 11] = b"IAW7SMHW320"
    image = FirmwareImage(data=bytes(data))
    result = summarise_findings(
        image.validate_for(profile, target_identity={"Hardware": "IAW5AMHW610"})
    )
    assert not result["ok"]
    fatal = next(f for f in result["fatal"] if f["check"] == "hardware")
    assert "IAW7SMHW320" in fatal["detail"]


def test_matching_hardware_family_is_accepted(profile, region_size):
    data = bytearray(plausible_image(region_size))
    data[1024 : 1024 + 11] = b"IAW5AMHW610"
    result = summarise_findings(
        FirmwareImage(data=bytes(data)).validate_for(
            profile, target_identity={"Hardware": "IAW5AMHW610"}
        )
    )
    assert result["ok"], result["fatal"]


def test_unknown_ecu_identity_warns_rather_than_passes_silently(profile, region_size):
    result = summarise_findings(
        FirmwareImage(data=plausible_image(region_size)).validate_for(profile)
    )
    assert any(w["check"] == "hardware" for w in result["warnings"])


# -- diff and persistence --------------------------------------------------


def test_diff_locates_changed_runs():
    a = FirmwareImage(data=bytes(100))
    changed = bytearray(100)
    changed[10:14] = b"\x01\x02\x03\x04"
    changed[50] = 0xFF
    result = a.diff(FirmwareImage(data=bytes(changed)))
    assert not result["identical"]
    assert result["changed_bytes"] == 5
    assert result["run_count"] == 2
    assert result["runs"][0]["offset"] == 10
    assert result["runs"][0]["length"] == 4


def test_identical_images_diff_clean():
    a = FirmwareImage(data=b"abc" * 10)
    assert a.diff(FirmwareImage(data=b"abc" * 10))["identical"]
    assert a.matches(FirmwareImage(data=b"abc" * 10))


def test_saving_writes_a_sidecar_with_provenance(tmp_path):
    image = FirmwareImage(
        data=plausible_image(4096), ecu_id="5am", identity={"Hardware": "IAW5AMHW610"}
    )
    path = image.save(tmp_path / "dump.bin")
    assert path.read_bytes() == image.data

    import json

    sidecar = json.loads(path.with_suffix(".bin.json").read_text())
    assert sidecar["ecu_id"] == "5am"
    assert sidecar["checksums"]["sha256"] == image.sha256
    assert sidecar["identity"]["Hardware"] == "IAW5AMHW610"
