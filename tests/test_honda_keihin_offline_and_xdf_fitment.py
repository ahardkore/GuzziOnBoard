"""End-to-end synthetic tests for all 7 adapted Honda Keihin offline XDF families
and full Garage vehicle fitment across all 103 non-research bundled XDFs."""
from __future__ import annotations

import hashlib
import json
from functools import partial
from pathlib import Path

import pytest

from guzzionboard import honda_keihin_offline as hko
from guzzionboard import honda_mgz, honda_tuning, server
from guzzionboard.catalog import load_catalog
from guzzionboard.checksums import ChecksumUnavailable
from guzzionboard.firmware import FirmwareImage
from guzzionboard.maps import XdfFile, eval_math, fitment
from guzzionboard.tuning import TUNING_ACKNOWLEDGEMENT, build_tune
from guzzionboard.workstation import Workstation

HONDA_XDFS = Path("guzzionboard/xdfs/honda")
XDF_ROOT = Path("guzzionboard/xdfs")


@pytest.mark.parametrize("family", list(hko.SPECS))
def test_honda_keihin_offline_family_end_to_end_preview_and_build(tmp_path, monkeypatch, family):
    spec = hko.SPECS[family]
    xdf = XdfFile.from_file(HONDA_XDFS / spec.xdf_name)
    assert xdf.file_sha256 == spec.xdf_sha256
    assert xdf.unsupported == []
    assert xdf.checksums == [spec.checksum_name]
    assert not fitment(xdf.path)["research_only"]

    registered_ids = [p.provider_id for p in server.load_checksum_providers()[0]]
    assert spec.provider_id in registered_ids

    # Find a table cell safely away from the checksum byte
    target_table = next(
        t for t in xdf.tables
        if not (t.embedded.address <= spec.checksum_offset < t.embedded.address + t.embedded.count * 4)
    )
    cell_off = target_table.embedded.address
    cell_bytes = target_table.embedded.size_bits // 8
    le = (
        xdf.little_endian
        if target_table.embedded.little_endian is None
        else target_table.embedded.little_endian
    )

    data = bytearray(spec.image_size)
    data[cell_off:cell_off + cell_bytes] = (100).to_bytes(cell_bytes, "little" if le else "big")
    data[spec.checksum_offset] = (-(sum(data) - data[spec.checksum_offset])) & 0xFF
    assert sum(data) & 0xFF == 0

    synth_sha = hashlib.sha256(data).hexdigest()
    monkeypatch.setitem(spec.stock_sha256s, "SYNTHETIC-TEST", synth_sha)
    monkeypatch.setattr(server, "build_tune", partial(build_tune, output_dir=tmp_path / "out"))

    img_path = tmp_path / f"{family}.bin"
    img_path.write_bytes(data)

    rendered = xdf.render(FirmwareImage(data=bytes(data)), address_base=0)
    t_render = next(t for t in rendered["tables"] if t["id"] == target_table.uniqueid)
    before_raw = t_render["raw_values"][0][0]
    after_val = eval_math(target_table.math, before_raw + 1)

    api = server.Api(Workstation(session_dir=tmp_path / "sessions"))
    # Select primary calibration-qualified Garage model
    api.ws.select(make="Honda", model=spec.accepted_models[0], year=spec.years[0])

    body = {
        "path": str(img_path),
        "xdf": spec.xdf_name,
        "address_base": 0,
        "changes": [{
            "kind": "table",
            "id": target_table.uniqueid,
            "row": 0,
            "col": 0,
            "expected_raw": before_raw,
            "value": after_val,
        }],
        "checksum_provider": spec.provider_id,
    }
    status, preview = api.post_maps_preview(body)
    assert status == 200, preview
    assert preview["checksum_provider"]["byte_changes"][0]["offset"] == f"0x{spec.checksum_offset:X}"

    status, built_res = api.post_maps_build({
        **body,
        "accept_non_base_source": True,
        "expected_plan_sha256": preview["plan_sha256"],
        "acknowledgement": TUNING_ACKNOWLEDGEMENT,
        "recommendation": {
            "title": "Synthetic test",
            "url": "https://example.org/honda-test",
            "rationale": "Synthetic offline checksum test only.",
        },
    })
    assert status == 201, built_res
    built = FirmwareImage.from_file(built_res["path"])
    assert built.ecu_id == spec.ecu_id
    assert (sum(built.data) & 0xFF) == 0
    assert img_path.read_bytes() == bytes(data)

    # Standard honda_pgmfi_research Garage entry for the same bike/year also passes fitment
    for alt_model in spec.accepted_models[1:]:
        cat = load_catalog()
        if cat.find(alt_model, spec.years[0], "Honda"):
            api.ws.select(make="Honda", model=alt_model, year=spec.years[0])
            assert api.post_maps_preview(body)[0] == 200
            break

    # Mismatched bike is refused
    api.ws.select(make="Honda", model="CBR1000RR (US)", year=2012)
    assert api.post_maps_preview(body)[0] == 400

    # Direct checksum overlap is refused by the provider
    prov = next(p for p in hko.providers() if p.provider_id == spec.provider_id)
    with pytest.raises(ChecksumUnavailable, match="overlap"):
        prov.update_fn(
            bytes(data),
            {
                "address_base": 0,
                "xdf_sha256": spec.xdf_sha256,
                "source_sha256": synth_sha,
                "declared_checksums": [spec.checksum_name],
                "changes": [{
                    "image_offset": f"0x{spec.checksum_offset:X}",
                    "after_hex": "00",
                }],
            },
        )


def test_every_non_research_xdf_has_a_matching_garage_motorcycle(tmp_path, monkeypatch):
    load_catalog.cache_clear()
    cat = load_catalog()
    xdf_catalog = json.loads((XDF_ROOT / "catalog.json").read_text(encoding="utf-8"))
    api = server.Api(Workstation(session_dir=tmp_path / "sessions"))

    synth_256k = bytes(0x40000)
    synth_256k_sha = hashlib.sha256(synth_256k).hexdigest()
    monkeypatch.setattr(honda_tuning, "SOURCE_SHA256", synth_256k_sha)
    monkeypatch.setattr(honda_mgz, "SOURCE_SHA256", synth_256k_sha)
    for spec in hko.SPECS.values():
        s_img = bytes(spec.image_size)
        monkeypatch.setitem(spec.stock_sha256s, "SYNTH", hashlib.sha256(s_img).hexdigest())

    checked = 0
    for entry in xdf_catalog:
        if entry.get("research_only"):
            continue
        xdf = XdfFile.from_file(XDF_ROOT / entry["vendor_path"])
        fam = entry["family"]
        if fam == "CBR1000RR-2012-US":
            api.ws.select(make="Honda", model="CBR1000RR (US)", year=2012)
            api._check_build_fitment(xdf, FirmwareImage(data=synth_256k))
        elif fam == "CB500-MGZ-A03":
            api.ws.select(make="Honda", model="CBR500R", year=2014)
            api._check_build_fitment(xdf, FirmwareImage(data=synth_256k))
        elif fam in hko.SPECS:
            spec = hko.SPECS[fam]
            api.ws.select(make="Honda", model=spec.accepted_models[0], year=spec.years[0])
            api._check_build_fitment(xdf, FirmwareImage(data=bytes(spec.image_size)))
        else:
            tokens = api._family_tokens(fam)
            matching_vehicles = [
                v for v in cat.vehicles
                if api._family_tokens(cat.ecu(v.ecu).family) & tokens
            ]
            assert matching_vehicles, f"no Garage vehicle matches XDF {entry['vendor_path']} ({fam})"
            v = matching_vehicles[0]
            api.ws.select(make=v.make, model=v.model, year=v.year_to, ecu=v.ecu)
            api._check_build_fitment(xdf, FirmwareImage(data=bytes(0x10000)))
        checked += 1

    assert checked == 103
