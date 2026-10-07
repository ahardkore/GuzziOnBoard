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


@pytest.mark.parametrize("verified", [False, True])
def test_failed_replacement_preserves_original(vault, tmp_path, verified):
    vault.store(ecu_id="5am", source_path=image(tmp_path), verified=True)
    before = vault.index_path.read_bytes()
    with pytest.raises(BaseMapError):
        vault.replace_base_map(ecu_id="5am", source_path=tmp_path / "missing.bin",
                               verified=verified)
    assert vault.index_path.read_bytes() == before
    assert vault.status("5am")["intact"]


def test_corrupt_index_is_not_silently_replaced(vault, tmp_path):
    vault.directory.mkdir()
    vault.index_path.write_text("{broken")
    with pytest.raises(BaseMapError, match="index"):
        vault.store(ecu_id="5am", source_path=image(tmp_path), verified=True)
    assert vault.index_path.read_text() == "{broken"


def test_repeated_saves_have_distinct_artifacts(vault, tmp_path):
    source = image(tmp_path)
    paths = [vault.store(ecu_id="5am", source_path=source, verified=True)["stored"]["path"]
             for _ in range(3)]
    assert len(set(paths)) == 3


def test_failed_index_publication_preserves_original(vault, tmp_path, monkeypatch):
    vault.store(ecu_id="5am", source_path=image(tmp_path), verified=True)
    before = vault.index_path.read_bytes()
    def fail(*args):
        raise OSError("disk full")
    monkeypatch.setattr("guzzionboard.storage.os.replace", fail)
    with pytest.raises(OSError, match="disk full"):
        vault.replace_base_map(ecu_id="5am", source_path=image(tmp_path, "new.bin", b"new"),
                               verified=True)
    assert vault.index_path.read_bytes() == before
    assert vault.status("5am")["intact"]
    assert not list(vault.directory.glob(".index.json.*"))


def test_concurrent_vault_instances_keep_every_entry(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    source = image(tmp_path)
    def store(i):
        BaseMapVault(tmp_path / "vault").store(
            ecu_id=str(i), source_path=source, verified=True)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(store, range(16)))
    assert len(BaseMapVault(tmp_path / "vault").all_entries()) == 16
