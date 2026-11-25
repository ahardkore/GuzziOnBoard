"""Synthetic tests for all 9 ECU image checksum families, research preview/export, and /api/tools/ecu-checksum."""
from __future__ import annotations

import hashlib
import zlib

from guzzionboard import ecu_image_checksums as cs
from guzzionboard import resources, server
from guzzionboard.workstation import Workstation


def _make_italjet_suzuki_image(*, valid: bool = True) -> bytes:
    img = bytearray(0x80000)
    img[0x20000:0x20010] = b"CALIBRATION_BODY"
    pos = 0x7FF00
    img[pos:pos + 4] = b"\xAA\x55\xCC\x33"
    img[pos + 4:pos + 16] = b"33950-03K000"  # 12 printable ASCII chars
    loc = pos + 16
    # Put placeholder complement pair first so _find_italjet_suzuki_loc matches
    img[loc:loc + 2] = b"\x00\x00"
    img[loc + 2:loc + 4] = b"\xFF\xFF"
    repaired = bytearray(cs.repair_italjet_suzuki(bytes(img)))
    if not valid:
        repaired[0x20020] ^= 0x37  # mutate payload byte while leaving stored/complement pair intact
    return bytes(repaired)


def _make_continental_m3c_image(*, valid: bool = True) -> bytes:
    # 256 KiB MC9S12X image (16 pages of 0x4000 bytes: PPAGE 0xF0..0xFF)
    img = bytearray(b"\xFF" * 0x40000)
    # Place non-FF payload in page 0xFE (offset (0xFE % 16)*0x4000 = 0x38000)
    # and page 0xFF (offset (0xFF % 16)*0x4000 = 0x3C000)
    for i in range(0x38000, 0x38400):
        img[i] = (i * 7 + 3) & 0xFF
    for i in range(0x3C200, 0x3C600):
        img[i] = (i * 11 + 5) & 0xFF

    # Descriptor 1 at 0x0104 (preceded by FF FF FF FF): covers 0xFE:8000..0xFE:83FF
    d1 = 0x0104
    img[d1:d1 + 2] = b"\x00\x00"
    img[d1 + 2:d1 + 4] = (1).to_bytes(2, "big")
    img[d1 + 4:d1 + 8] = (0x00FE8000).to_bytes(4, "big")
    img[d1 + 8:d1 + 12] = (0x00FE83FF).to_bytes(4, "big")

    # Descriptor 2 at 0x3C104 (inside page 0xFF, preceded by FF FF FF FF):
    # covers two ranges on page 0xFF including 0xFF:8200..0xFF:85FF
    d2 = 0x3C104
    img[d2:d2 + 2] = b"\x00\x00"
    img[d2 + 2:d2 + 4] = (1).to_bytes(2, "big")
    img[d2 + 4:d2 + 8] = (0x00FF8200).to_bytes(4, "big")
    img[d2 + 8:d2 + 12] = (0x00FF85FF).to_bytes(4, "big")

    repaired = bytearray(cs.repair_continental_m3c(bytes(img)))
    if not valid:
        repaired[0x38010] ^= 0x5A
    return bytes(repaired)


def test_italjet_suzuki_verify_and_repair_roundtrip():
    valid = _make_italjet_suzuki_image(valid=True)
    res = cs.verify_italjet_suzuki(valid)
    assert res is not None and res["ok"] is True
    assert res["stored"] == res["computed"] == res["byte_sum_tail"]

    broken = _make_italjet_suzuki_image(valid=False)
    bad = cs.verify_italjet_suzuki(broken)
    assert bad is not None and bad["ok"] is False
    fixed = cs.repair_italjet_suzuki(broken)
    after = cs.verify_italjet_suzuki(fixed)
    assert after is not None and after["ok"] is True


def test_continental_m3c_verify_and_repair_roundtrip():
    valid = _make_continental_m3c_image(valid=True)
    recs = cs.verify_continental_m3c(valid)
    assert len(recs) == 2 and all(r["ok"] for r in recs)

    broken = _make_continental_m3c_image(valid=False)
    bad_recs = cs.verify_continental_m3c(broken)
    assert len(bad_recs) == 2 and not bad_recs[0]["ok"] and bad_recs[1]["ok"]
    fixed = cs.repair_continental_m3c(broken)
    assert all(r["ok"] for r in cs.verify_continental_m3c(fixed))

    # Non-power-of-two size or single descriptor is rejected
    assert cs.verify_continental_m3c(b"\xFF" * 0x30000) == []


def test_proposals_require_valid_original_and_avoid_false_positives():
    # Unrelated 256 KiB image filled with 0xFF must NOT propose bosch_mse8
    blank = bytearray(b"\xFF" * 0x40000)
    edited_blank = bytearray(blank)
    edited_blank[0x100] = 0x42
    assert cs.proposals(bytes(blank), bytes(edited_blank)) == []

    # Valid Bosch MSE8 256 KiB block proposes exact 4-byte CRC repair
    mse8 = bytearray(0x40000)
    mse8[0x3FFE0:0x3FFE8] = b"MSE8SIG!"
    crc = (zlib.crc32(mse8[:0x3FFF8]) ^ 0xA18AFC77) & 0xFFFFFFFF
    mse8[0x3FFF8:0x3FFFC] = crc.to_bytes(4, "big")
    edited_mse8 = bytearray(mse8)
    edited_mse8[0x1200] = 0x99
    props = cs.proposals(bytes(mse8), bytes(edited_mse8))
    assert len(props) == 1 and props[0]["family"] == "bosch_mse8"
    assert props[0]["byte_changes"][0]["offset"] == "0x3FFF8"

    # Direct edit to checksum bytes themselves refuses proposal
    touched_cs = bytearray(mse8)
    touched_cs[0x3FFF9] ^= 0x01
    assert cs.proposals(bytes(mse8), bytes(touched_cs)) == []


def test_research_preview_and_export_with_ecu_checksum_candidate(tmp_path, monkeypatch):
    monkeypatch.setattr(resources, "data_root", lambda: tmp_path / "data")
    orig = bytearray(_make_continental_m3c_image(valid=True))
    orig[0x38020:0x38022] = (1000).to_bytes(2, "big")
    orig_valid = cs.repair_continental_m3c(bytes(orig))
    bin_path = tmp_path / "te300i.bin"
    bin_path.write_bytes(orig_valid)

    xdf_xml = """<XDFFORMAT><XDFHEADER><deftitle>M3C Research</deftitle>
      <DEFAULTS signed="0" lsbfirst="0" float="0"/>
      <REGION size="0x40000"/></XDFHEADER>
      <XDFCONSTANT uniqueid="0x10"><title>FuelTrim</title>
        <EMBEDDEDDATA mmedaddress="0x38020" mmedelementsizebits="16"/>
        <MATH equation="X"/></XDFCONSTANT></XDFFORMAT>"""
    xdf_path = tmp_path / "m3c_user.xdf"
    xdf_path.write_text(xdf_xml, encoding="latin-1")

    api = server.Api(Workstation(session_dir=tmp_path / "sessions"))
    base_body = {
        "path": str(bin_path),
        "xdf": str(xdf_path),
        "address_base": 0,
        "expected_source_sha256": hashlib.sha256(orig_valid).hexdigest(),
        "expected_xdf_sha256": hashlib.sha256(xdf_path.read_bytes()).hexdigest(),
        "changes": [{"kind": "constant", "id": "0x10", "expected_raw": 1000, "value": 1050}],
    }
    status, preview = api.post_maps_research_preview(base_body)
    assert status == 200, preview
    cands = preview["ecu_checksum_candidates"]
    assert len(cands) == 1 and cands[0]["family"] == "continental_m3c"
    cand = cands[0]

    # Missing confirm_ecu_checksum is refused
    status, err = api.post_maps_research_export({
        **base_body,
        "region_start": 0,
        "region_end": len(orig_valid),
        "expected_candidate_sha256": preview["candidate_sha256"],
        "accept_research_only": True,
        "ecu_checksum_family": "continental_m3c",
        "expected_checksum_output_sha256": cand["output_sha256"],
    })
    assert status == 400 and "confirmation" in err["error"]

    # Confirmed export writes verified copy + manifest without mutating source
    status, exported = api.post_maps_research_export({
        **base_body,
        "region_start": 0,
        "region_end": len(orig_valid),
        "expected_candidate_sha256": preview["candidate_sha256"],
        "accept_research_only": True,
        "ecu_checksum_family": "continental_m3c",
        "confirm_ecu_checksum": True,
        "expected_checksum_output_sha256": cand["output_sha256"],
    })
    assert status == 201, exported
    saved_bytes = (tmp_path / exported["path"]).read_bytes()
    assert hashlib.sha256(saved_bytes).hexdigest() == cand["output_sha256"]
    assert all(r["ok"] for r in cs.verify_continental_m3c(saved_bytes))
    assert bin_path.read_bytes() == orig_valid


def test_post_tools_ecu_checksum_inspect_and_opt_in_repair(tmp_path, monkeypatch):
    monkeypatch.setattr(resources, "data_root", lambda: tmp_path / "data")
    broken = _make_italjet_suzuki_image(valid=False)
    bin_path = tmp_path / "dragster.bin"
    bin_path.write_bytes(broken)

    api = server.Api(Workstation(session_dir=tmp_path / "sessions"))
    status, inspected = api.post_tools_ecu_checksum({"path": str(bin_path)})
    assert status == 200, inspected
    assert inspected["writes_file"] is False
    assert "continental_m3c" in inspected["families"]
    match = next(m for m in inspected["matches"] if m["family"] == "italjet_suzuki")
    assert match["ok"] is False and match["repaired_ok"] is True

    # Repair without confirmation phrase is refused
    assert api.post_tools_ecu_checksum({
        "path": str(bin_path),
        "family": "italjet_suzuki",
        "repair": True,
        "expected_source_sha256": inspected["source"]["sha256"],
        "expected_output_sha256": match["output_sha256"],
    })[0] == 400

    # Repair with explicit confirmation phrase creates verified copy
    status, repaired = api.post_tools_ecu_checksum({
        "path": str(bin_path),
        "family": "italjet_suzuki",
        "repair": True,
        "confirm": "APPLY RESEARCH ECU CHECKSUM",
        "expected_source_sha256": inspected["source"]["sha256"],
        "expected_output_sha256": match["output_sha256"],
    })
    assert status == 201, repaired
    out_bytes = (tmp_path / repaired["path"]).read_bytes()
    assert cs.verify_italjet_suzuki(out_bytes)["ok"] is True
    assert bin_path.read_bytes() == broken
