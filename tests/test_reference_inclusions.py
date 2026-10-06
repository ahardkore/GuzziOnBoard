"""The four formerly-out-of-scope reference tools, now included:

- ManaTCU      -> catalog controller entry (identification + discovery)
- CDM/FTDI     -> driver bundle surfaced by the adapter pre-flight
- ZT2CSV->DIF  -> converter endpoint
- RPMSensorEmu -> bench signal endpoint

plus the GearSpeed model-ratio database, vendored for the gearing presets.
"""
from __future__ import annotations

import pytest

from guzzionboard import adapter as adapter_mod
from guzzionboard.catalog import load_catalog
from guzzionboard.server import Api
from guzzionboard.workstation import Workstation


@pytest.fixture(scope="module")
def catalog():
    load_catalog.cache_clear()
    return load_catalog()


# ------------------------------------------------------------- Mana TCU


def test_mana_tcu_is_cataloged_but_observation_only(catalog):
    profile = catalog.ecu("mana_tcu")
    assert profile.confidence == "unknown"
    # observed capabilities only: identify, dtc_read, discovery sweep —
    # nothing state-changing on a controller nobody has captured here
    assert set(profile.capabilities) <= {"identify", "dtc_read", "discover"}
    assert not profile.memory.get("read_supported")
    assert not profile.memory.get("write_supported")
    assert not profile.actuators
    # the evidence for its existence is the mirrored reference tool
    assert "ManaTCU" in profile.notes


def test_mana_850_vehicle_points_at_engine_and_tcu(catalog):
    entry, profile = catalog.resolve("Mana 850", 2010, "Aprilia")
    assert profile.id == "5am"                       # engine side: shared 5AM
    assert "mana_tcu" in (getattr(entry, "notes", "") or "")


# ----------------------------------------------------------- FTDI bundle


def test_the_vendored_driver_bundle_actually_exists():
    assert adapter_mod.DRIVER_BUNDLE_ZIP.exists(), (
        "vendor/guzzidiag mirror lost the CDM driver bundle "
        "(CDM-v2.12.36.20-WHQL-Certified.zip)"
    )


def test_driver_guidance_is_platform_specific(monkeypatch):
    monkeypatch.setattr(adapter_mod.platform, "system", lambda: "Windows")
    win = adapter_mod.driver_bundle_info()
    assert win["bundle_available"] and "CDM" in win["hint"] or "extract" in win["hint"]
    monkeypatch.setattr(adapter_mod.platform, "system", lambda: "Linux")
    assert "ftdi_sio" in adapter_mod.driver_bundle_info()["hint"]


def test_adapter_report_carries_the_driver_block():
    report = adapter_mod.AdapterReport(port="\test")
    assert "driver" in report.as_dict()
    assert report.as_dict()["driver"]["bundle_available"]


# ------------------------------------------------------------ tool APIs


@pytest.fixture
def api(tmp_path):
    return Api(Workstation(session_dir=tmp_path, record=False))


def test_z2dif_endpoint_converts(api):
    status, out = api.post_tools_z2dif(
        {"text": "AFR,RPM,TPS\n11.2,2400,12\n11.4,2450,13\n"}
    )
    assert status == 200
    assert out["dif"].startswith("Time (s)\t")
    assert out["rows"] == 2
    assert "factor" in out["note"] or "timeline" in out["note"]


def test_z2dif_endpoint_rejects(api):
    status, out = api.post_tools_z2dif({})
    assert status == 400
    status, out = api.post_tools_z2dif({"text": "not,a,zt2,csv\n1,2,3,4"})
    assert status == 400


def test_rpmsignal_endpoint_renders_a_preset(api):
    status, out = api.post_tools_rpmsignal(
        {"pattern": "motoguzzi", "rpm": 3000, "seconds": 0.5}
    )
    assert status == 200
    assert out["path"].endswith(".wav")
    assert out["teeth"] == 46


def test_rpmsignal_endpoint_renders_batch_events(api):
    status, out = api.post_tools_rpmsignal(
        {"pattern": "mvagusta", "events": [[300, 2000, 4000], [200, 4000]]}
    )
    assert status == 200
    assert out["wheel"] == "crankshaft"
    assert out["duration_s"] == pytest.approx(0.5)


def test_rpmsignal_endpoint_rejects_garbage(api):
    status, out = api.post_tools_rpmsignal({"pattern": "gsxr"})
    assert status == 400 and "presets" in out
    status, out = api.post_tools_rpmsignal({"pattern": "motoguzzi"})
    assert status == 400
    status, out = api.post_tools_rpmsignal({"teeth": 46, "wheel": "output shaft"})
    assert status == 400


# -------------------------------------------------- GearSpeed ratio table


def test_the_gearspeed_model_table_is_vendored():
    from guzzionboard import tools

    presets = tools.GEARING_PRESETS
    # the reference binary carries 63 entries but duplicates five of them
    # ("...again") with identical ratios; a dict legitimately collapses those
    assert len(presets) == 58
    for name, data in presets.items():
        assert data["gears"], name
        assert all(ratio > 0 for ratio in data["gears"]), (
            f"0.000-padding must be stripped: {name}"
        )
        assert 4 <= len(data["gears"]) <= 6, name
        assert data["max_rpm"] > 0, name


def test_the_preset_table_covers_the_fleet():
    from guzzionboard import tools

    names = " ".join(tools.GEARING_PRESETS)
    for family in ("V7", "V85TT", "Griso", "Breva", "Stelvio", "California",
                   "Norge", "V11", "Le Mans", "V9"):
        assert family in names, family


def test_gearing_endpoint_with_a_model_preset(api):
    status, out = api.get_gearing(
        {"preset": ["Moto Guzzi — V7"], "final_drive": ["4.0"], "rpm": ["1000,2000"]}
    )
    assert status == 200
    assert out["preset"] == "Moto Guzzi — V7"
    assert out["max_rpm"] == 7500
    assert list(out["gears"].keys()) == [f"gear{n}" for n in range(1, 6)]
    assert out["rpm"] == [1000, 2000]
    assert out["gear_ratios_used"] == pytest.approx([2.3636, 1.6429, 1.2778, 1.0556, 0.9])
    # every response carries the full preset table for the client dropdown
    assert len(out["presets"]) == 58


def test_gearing_endpoint_custom_ratios_override_the_preset(api):
    status, out = api.get_gearing(
        {"preset": ["Moto Guzzi — V7"], "gears": ["3.0, 2.0, 1.5, 0"], "rpm": ["1000"]}
    )
    assert status == 200
    # zeros trimmed (the reference table pads 5-speeds with 0.0000 rows)
    assert list(out["gears"].keys()) == ["gear1", "gear2", "gear3"]
    assert out["rpm"] == [1000]


def test_gearing_endpoint_unknown_preset_falls_back_without_a_preset_tag(api):
    status, out = api.get_gearing({"preset": ["Not a bike at all"]})
    assert status == 200
    assert "max_rpm" not in out
    assert "preset" not in out
    assert len(out["gears"]) == 6            # the default box
