"""Evidence-backed map editing and reproducible tuning builds."""
from __future__ import annotations

import json
from functools import partial
from pathlib import Path

import pytest

from guzzionboard.firmware import FirmwareImage
from guzzionboard.maps import XdfError, XdfFile, inverse_math
from guzzionboard.tuning import (
    TUNING_ACKNOWLEDGEMENT,
    TuningError,
    build_tune,
    preview_tune,
)


XDF_TEXT = """<?xml version="1.0"?>
<XDFFORMAT version="1.60">
  <XDFHEADER>
    <deftitle>5AM evidence build fixture</deftitle>
    <fileversion>1.0</fileversion>
    <DEFAULTS signed="0" lsbfirst="0" />
    <REGION size="0x100" />
    <CATEGORY index="0" name="Fuel" />
  </XDFHEADER>
  <XDFTABLE uniqueid="fuel-main">
    <title>Main fuel</title><description>fixture table</description>
    <CATEGORYMEM category="0" />
    <XDFAXIS id="x"><indexcount>2</indexcount>
      <LABEL index="0" value="1000"/><LABEL index="1" value="2000"/>
      <MATH equation="X"><VAR id="X"/></MATH></XDFAXIS>
    <XDFAXIS id="y"><indexcount>2</indexcount>
      <LABEL index="0" value="low"/><LABEL index="1" value="high"/>
      <MATH equation="X"><VAR id="X"/></MATH></XDFAXIS>
    <XDFAXIS id="z"><EMBEDDEDDATA mmedaddress="0x20"
      mmedelementsizebits="8" mmedrowcount="2" mmedcolcount="2"/>
      <units>ms</units><decimalpl>1</decimalpl>
      <MATH equation="X/10"><VAR id="X"/></MATH></XDFAXIS>
  </XDFTABLE>
  <XDFCONSTANT uniqueid="rev-limit">
    <title>Rev limiter</title><EMBEDDEDDATA mmedaddress="0x30"
      mmedelementsizebits="16"/><units>RPM</units>
    <MATH equation="X*25"><VAR id="X"/></MATH>
  </XDFCONSTANT>
</XDFFORMAT>
"""


@pytest.fixture
def xdf(tmp_path) -> XdfFile:
    path = tmp_path / "5AM_fixture.xdf"
    path.write_text(XDF_TEXT)
    return XdfFile.from_file(path)


@pytest.fixture
def source(tmp_path) -> FirmwareImage:
    data = bytearray(0x100)
    data[0x20:0x24] = bytes([10, 20, 30, 40])
    data[0x30:0x32] = (340).to_bytes(2, "big")
    image = FirmwareImage(
        bytes(data), ecu_id="5am", region="flash", source="backup",
        identity={"Hardware": "IAW5AMHW610"},
    )
    image.save(tmp_path / "base.bin")
    return image


EVIDENCE = {
    "title": "Documented dyno recommendation",
    "url": "https://example.org/recommendations/griso-stage-one",
    "publisher": "Example workshop",
    "rationale": "Applies to this exact 5AM hardware and exhaust configuration.",
    "quote": "Set the named cell to 5.5 ms after measurement.",
}


def test_inverse_math_quantises_and_refuses_out_of_range():
    assert inverse_math("X*25", 9000, size_bits=16, signed=False) == (360, 9000)
    assert inverse_math("X/10", 5.54, size_bits=8, signed=False, decimalpl=1) == (55, 5.5)
    raw, value = inverse_math("15000000/X", 3000, size_bits=16, signed=False)
    assert raw == 5000 and value == 3000
    with pytest.raises(XdfError, match="cannot be represented"):
        inverse_math("X/10", 1000, size_bits=8, signed=False, decimalpl=1)


def test_apply_changes_writes_only_named_cells_and_keeps_source(xdf, source):
    original = bytes(source.data)
    rendered = xdf.render(source)
    fuel = rendered["tables"][0]
    limiter = rendered["constants"][0]
    tuned, changes = xdf.apply_changes(source, [
        {
            "kind": "table", "id": fuel["id"], "row": 1, "col": 1,
            "expected_raw": fuel["raw_values"][1][1], "value": 5.5,
            "x": fuel["x"][1], "y": fuel["y"][1],
        },
        {
            "kind": "constant", "id": limiter["id"],
            "expected_raw": limiter["raw"], "value": 9000,
        },
    ])
    assert source.data == original, "a build must never mutate its source"
    assert tuned[0x23] == 55
    assert int.from_bytes(tuned[0x30:0x32], "big") == 360
    changed_offsets = {i for i, (a, b) in enumerate(zip(original, tuned)) if a != b}
    assert changed_offsets == {0x23, 0x31}
    assert [change["title"] for change in changes] == ["Main fuel", "Rev limiter"]
    assert changes[0]["image_offset"] == "0x23"


def test_apply_changes_uses_expected_raw_as_an_optimistic_lock(xdf, source):
    with pytest.raises(XdfError, match="source changed"):
        xdf.apply_changes(source, [{
            "kind": "table", "id": "fuel-main", "row": 0, "col": 0,
            "expected_raw": 99, "value": 2.0,
        }])
    with pytest.raises(XdfError, match="more than once"):
        xdf.apply_changes(source, [
            {"kind": "table", "id": "fuel-main", "row": 0, "col": 0,
             "expected_raw": 10, "value": 2.0},
            {"kind": "table", "id": "fuel-main", "row": 0, "col": 0,
             "expected_raw": 10, "value": 2.1},
        ])


def test_build_requires_liability_evidence_and_non_base_opt_in(xdf, source, tmp_path):
    change = [{
        "kind": "table", "id": "fuel-main", "row": 0, "col": 0,
        "expected_raw": 10, "value": 2.0,
    }]
    with pytest.raises(TuningError, match="repeat exactly"):
        build_tune(
            source, xdf, change, recommendation=EVIDENCE,
            acknowledgement="yes", source_is_base_map=True, output_dir=tmp_path,
        )
    with pytest.raises(TuningError, match="inspectable"):
        build_tune(
            source, xdf, change,
            recommendation={**EVIDENCE, "url": "someone told me"},
            acknowledgement=TUNING_ACKNOWLEDGEMENT,
            source_is_base_map=True, output_dir=tmp_path,
        )
    with pytest.raises(TuningError, match="not the protected base map"):
        build_tune(
            source, xdf, change, recommendation=EVIDENCE,
            acknowledgement=TUNING_ACKNOWLEDGEMENT,
            source_is_base_map=False, output_dir=tmp_path,
        )


def test_preview_is_deterministic_and_writes_nothing(xdf, source, tmp_path):
    change = [{
        "kind": "table", "id": "fuel-main", "row": 0, "col": 1,
        "expected_raw": 20, "value": 2.54,
    }]
    before = set(tmp_path.rglob("*"))
    first = preview_tune(
        source, xdf, change, source_is_base_map=True
    )
    second = preview_tune(
        source, xdf, change, source_is_base_map=True
    )
    assert first == second
    assert first["changes"][0]["after"] == 2.5
    assert first["changes"][0]["quantized"] is True
    assert len(first["plan_sha256"]) == 64
    assert set(tmp_path.rglob("*")) == before


def test_build_refuses_when_reviewed_plan_changed(xdf, source, tmp_path):
    with pytest.raises(TuningError, match="reviewed tuning plan"):
        build_tune(
            source, xdf,
            [{"kind": "table", "id": "fuel-main", "row": 0, "col": 0,
              "expected_raw": 10, "value": 2.0}],
            recommendation=EVIDENCE,
            acknowledgement=TUNING_ACKNOWLEDGEMENT,
            source_is_base_map=True,
            expected_plan_sha256="0" * 64,
            output_dir=tmp_path / "outputs",
        )
    assert not (tmp_path / "outputs").exists()


def test_build_creates_a_new_provenance_carrying_image(xdf, source, tmp_path):
    original_path = Path(source.path)
    original_bytes = original_path.read_bytes()
    result = build_tune(
        source, xdf,
        [{"kind": "constant", "id": "rev-limit", "expected_raw": 340,
          "value": 9000}],
        recommendation=EVIDENCE,
        acknowledgement=TUNING_ACKNOWLEDGEMENT,
        source_is_base_map=True,
        output_dir=tmp_path / "outputs",
    )
    output = Path(result["path"])
    assert output.is_file() and output != original_path
    assert original_path.read_bytes() == original_bytes
    assert result["manifest"]["source"]["is_base_map"] is True
    assert result["manifest"]["recommendation"]["status"] == "traceable-not-endorsed"
    assert result["manifest"]["liability_acknowledged"] is True
    assert result["manifest"]["source"]["sha256"] == source.sha256
    sidecar = json.loads(Path(str(output) + ".json").read_text())
    assert sidecar["path"] == str(output)
    assert sidecar["meta"]["tuning_build"]["output_path"] == str(output)
    reopened = FirmwareImage.from_file(output)
    assert reopened.identity["Hardware"] == "IAW5AMHW610"
    assert reopened.meta["tuning_build"]["changes"][0]["after"] == 9000


class TestTuningApi:
    @pytest.fixture
    def api(self, tmp_path, monkeypatch, xdf):
        from guzzionboard import server
        from guzzionboard.workstation import Workstation

        monkeypatch.setattr(server, "available_xdfs", lambda directory=None: [xdf])
        monkeypatch.setattr(
            server, "build_tune",
            partial(build_tune, output_dir=tmp_path / "api-output"),
        )
        return server.Api(Workstation(session_dir=tmp_path / "sessions"))

    def test_map_catalog_advertises_the_advanced_gate(self, api):
        status, payload = api.get_maps({})
        assert status == 200
        assert payload["build"]["acknowledgement"] == TUNING_ACKNOWLEDGEMENT
        assert payload["build"]["requires_recommendation_evidence"] is True

    def test_build_endpoint_returns_named_diff(self, api, source):
        body = {
            "path": source.path,
            "accept_non_base_source": True,
            "xdf": "5AM_fixture.xdf",
            "changes": [{
                "kind": "table", "id": "fuel-main", "row": 0, "col": 1,
                "expected_raw": 20, "value": 2.5,
            }],
            "recommendation": EVIDENCE,
            "acknowledgement": TUNING_ACKNOWLEDGEMENT,
        }
        preview_status, preview = api.post_maps_preview(body)
        assert preview_status == 200
        assert preview["writes_file"] is False
        assert preview["diff"]["identical"] is False
        body["expected_plan_sha256"] = preview["plan_sha256"]
        status, payload = api.post_maps_build(body)
        assert status == 201
        assert Path(payload["path"]).is_file()
        assert payload["diff"]["identical"] is False
        assert payload["diff"]["tables"][0]["title"] == "Main fuel"
        assert payload["manifest"]["plan_sha256"] == preview["plan_sha256"]

    def test_build_endpoint_refuses_a_mismatched_xdf(self, api, source, monkeypatch):
        # The source sidecar says 5AM. Once a bench ECU is selected the server
        # enforces that fitment even though a mismatched XDF remains renderable.
        api.ws.select(ecu="7sm", transport="simulator")
        status, payload = api.post_maps_build({
            "path": source.path, "accept_non_base_source": True,
            "xdf": "5AM_fixture.xdf",
            "changes": [{"kind": "table", "id": "fuel-main", "row": 0,
                         "col": 0, "expected_raw": 10, "value": 2.0}],
            "recommendation": EVIDENCE,
            "acknowledgement": TUNING_ACKNOWLEDGEMENT,
        })
        assert status == 400
        assert "mismatched definitions" in payload["error"]
