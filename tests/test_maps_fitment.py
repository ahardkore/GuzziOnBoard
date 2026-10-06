"""Which bike a map definition belongs to, and how the chooser groups them.

An XDF title is whatever its author typed; the thing that decides whether a
definition describes the ECU in front of you is its family and the bikes the
archive publishes it for. These tests pin that down, because picking the
wrong definition is how someone ends up tuning a Ducati map into a V7.
"""
from pathlib import Path

from guzzionboard.maps import (
    available_xdfs,
    brand_label,
    family_from_filename,
    fitment,
    group_xdfs,
    load_bundled_xdfs,
)
from guzzionboard.server import Api
from guzzionboard.workstation import Workstation


def test_every_bundled_definition_knows_its_bike_and_family():
    for xdf in load_bundled_xdfs():
        fit = fitment(xdf.path)
        name = Path(xdf.path).name
        assert fit["catalogued"], f"{name} is not in catalog.json"
        assert fit["family"], f"{name} has no ECU family"
        assert fit["fits"], f"{name} lists no motorcycles"
        assert fit["label"], f"{name} has no model label"


def test_fitment_lists_every_brand_a_shared_definition_is_published_for():
    fit = fitment("guzzionboard/xdfs/aprilia/15P_1P0Z_V1.02.xdf")
    assert fit["family"] == "15P"
    assert "Aprilia" in fit["fits_brands"] and "Piaggio" in fit["fits_brands"]
    assert any("Beverly" in f["label"] for f in fit["fits"])


def test_an_unknown_file_falls_back_to_what_the_filename_says():
    fit = fitment("/tmp/xdfs/5AM_Something_Custom_V1.0.xdf")
    assert fit["catalogued"] is False
    assert fit["family"] == "5AM"
    assert fit["brand_label"] == "Uncatalogued"
    assert fit["label"] == "5AM Something Custom V1.0"


def test_family_detection_only_accepts_a_real_prefix():
    assert family_from_filename("MIUG3_MotoGuzzi_V7III_V1.15.xdf") == "MIUG3"
    assert family_from_filename("notafamily_V1.xdf") == ""


def test_brand_labels_are_human_readable():
    assert brand_label("moto_guzzi") == "Moto Guzzi"
    assert brand_label("") == "Unknown"


def test_grouping_separates_the_library_by_bike_then_family():
    groups = group_xdfs([x.describe() for x in available_xdfs()])
    by_label = {g["brand_label"]: g for g in groups}
    assert "Moto Guzzi" in by_label and "Ducati" in by_label

    guzzi = by_label["Moto Guzzi"]
    families = {f["family"] for f in guzzi["families"]}
    assert {"5AM", "15M", "MIUG3"} <= families

    # a Ducati-only definition must not turn up under Moto Guzzi
    guzzi_files = {f for fam in guzzi["families"] for f in fam["files"]}
    assert not any("Ducati" in name for name in guzzi_files)


def test_the_maps_endpoint_tells_the_chooser_what_is_on_the_bench(tmp_path):
    api = Api(Workstation(session_dir=tmp_path, record=False))
    status, body = api.get_maps({})
    assert status == 200
    assert body["groups"], "the chooser needs the by-bike grouping"
    assert "ecu_family" in body["vehicle"]
    first = body["xdfs"][0]
    assert first["filename"] and first["family"] and first["fits"]


def test_an_ambiguous_title_is_refused_rather_than_guessed(tmp_path):
    api = Api(Workstation(session_dir=tmp_path, record=False))
    titles: dict[str, int] = {}
    for xdf in available_xdfs():
        if xdf.title:
            titles[xdf.title] = titles.get(xdf.title, 0) + 1
    shared = next(t for t, n in titles.items() if n > 1)

    import pytest

    from guzzionboard.maps import XdfError

    with pytest.raises(XdfError, match="different definitions"):
        api._load_xdf(shared)


def test_a_filename_always_resolves_to_exactly_that_file(tmp_path):
    api = Api(Workstation(session_dir=tmp_path, record=False))
    name = "MIUG3_MotoGuzzi_V7III_V1.15.xdf"
    xdf = api._load_xdf(name)
    assert Path(xdf.path).name == name
