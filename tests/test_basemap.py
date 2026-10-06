"""The base map vault: the guaranteed way back to what the bike arrived with."""
from pathlib import Path

import pytest

from guzzionboard.basemap import BaseMapError, BaseMapVault, ecu_key


def image(tmp_path: Path, name: str = "dump.bin", body: bytes = b"\x01\x02" * 64) -> Path:
    path = tmp_path / name
    path.write_bytes(body)
    path.with_suffix(path.suffix + ".json").write_text('{"ecu_id": "5am"}')
    return path


@pytest.fixture
def vault(tmp_path):
    return BaseMapVault(tmp_path / "vault")


def test_an_ecu_with_no_base_map_says_so(vault):
    status = vault.status("5am", "IAW5AMHW610")
    assert status["present"] is False and status["intact"] is False
    assert "save one" in status["reason"]


def test_an_unverified_read_is_not_a_base_map(vault, tmp_path):
    with pytest.raises(BaseMapError, match="verified"):
        vault.store(ecu_id="5am", source_path=image(tmp_path), verified=False)


def test_a_verified_backup_becomes_the_base_map(vault, tmp_path):
    result = vault.store(
        ecu_id="5am", hardware="IAW5AMHW610", source_path=image(tmp_path),
        verified=True,
    )
    assert result["is_base_map"] is True
    status = vault.status("5am", "IAW5AMHW610")
    assert status["present"] and status["intact"]
    # the copy is in the vault, not just a pointer at the working file
    assert Path(status["path"]).parent.parent == vault.directory
    assert Path(status["path"] + ".json").is_file()


def test_the_first_base_map_is_never_silently_replaced(vault, tmp_path):
    vault.store(ecu_id="5am", source_path=image(tmp_path, "first.bin", b"\x11" * 128),
                verified=True)
    first = vault.status("5am")["path"]
    vault.store(ecu_id="5am", source_path=image(tmp_path, "later.bin", b"\x22" * 128),
                verified=True)
    status = vault.status("5am")
    assert status["path"] == first, "the original calibration must stay the base map"
    assert len(status["restore_points"]) == 1


def test_replacing_the_base_map_is_explicit_and_keeps_the_old_one(vault, tmp_path):
    vault.store(ecu_id="5am", source_path=image(tmp_path, "first.bin", b"\x11" * 128),
                verified=True)
    first = vault.status("5am")["path"]
    vault.replace_base_map(
        ecu_id="5am", source_path=image(tmp_path, "new.bin", b"\x33" * 128),
        verified=True,
    )
    status = vault.status("5am")
    assert status["path"] != first
    assert any("superseded" in p.get("note", "") for p in status["restore_points"])
    assert Path(first).is_file(), "nothing in the vault is ever deleted"


def test_a_tampered_base_map_is_not_a_restore_map(vault, tmp_path):
    vault.store(ecu_id="5am", source_path=image(tmp_path), verified=True)
    path = Path(vault.status("5am")["path"])
    path.write_bytes(b"\x00" * 16)
    status = vault.status("5am")
    assert status["present"] and not status["intact"]
    assert "SHA-256" in status["reason"]


def test_a_deleted_base_map_is_reported_missing(vault, tmp_path):
    vault.store(ecu_id="5am", source_path=image(tmp_path), verified=True)
    Path(vault.status("5am")["path"]).unlink()
    status = vault.status("5am")
    assert not status["present"] and not status["intact"]


def test_the_key_separates_hardware_variants_and_regions():
    assert ecu_key("5am", "IAW5AMHW610") != ecu_key("5am", "IAW5AMHW103")
    assert ecu_key("5am", "", "flash") != ecu_key("5am", "", "eeprom")
    assert ecu_key("5AM", "iaw5amhw610 ") == ecu_key("5am", "IAW5AMHW610")


def test_a_base_map_for_another_hardware_variant_does_not_count(vault, tmp_path):
    vault.store(ecu_id="5am", hardware="IAW5AMHW103",
                source_path=image(tmp_path), verified=True)
    assert not vault.status("5am", "IAW5AMHW610")["intact"]
