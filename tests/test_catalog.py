"""Catalog integrity: the data is the product, so it gets validated."""
import pytest

from guzzionboard.catalog import (
    CONFIDENCE_LEVELS, CatalogError, confidence_rank, load_catalog, meets,
)


@pytest.fixture(scope="module")
def catalog():
    return load_catalog()


def test_catalog_loads_every_ecu_family(catalog):
    assert set(catalog.ecus) >= {
        "p8", "16m", "15m", "15rc", "5am", "7sm", "miug3", "miug4", "11mp"
    }


def test_coverage_spans_the_last_25_model_years(catalog):
    summary = catalog.summary()
    low, high = summary["year_range"]
    assert low <= 2000 and high >= 2025
    # Every model year in the window has at least one mapped motorcycle.
    for year in range(2000, 2026):
        assert any(v.covers(year) for v in catalog.vehicles), f"no coverage for {year}"


def test_every_vehicle_points_at_a_known_ecu(catalog):
    for vehicle in catalog.vehicles:
        assert vehicle.ecu in catalog.ecus


def test_confidence_levels_are_from_the_declared_vocabulary(catalog):
    for profile in catalog.ecus.values():
        assert profile.confidence in CONFIDENCE_LEVELS
        for param in profile.parameters:
            assert param.confidence in CONFIDENCE_LEVELS
        for actuator in profile.actuators:
            assert actuator.confidence in CONFIDENCE_LEVELS
        for routine in profile.routines:
            assert routine.confidence in CONFIDENCE_LEVELS
    for vehicle in catalog.vehicles:
        assert vehicle.confidence in CONFIDENCE_LEVELS


def test_confidence_ranking_orders_correctly():
    assert confidence_rank("verified-capture") < confidence_rank("documented")
    assert confidence_rank("documented") < confidence_rank("inferred")
    assert meets("verified-bench") and meets("documented")
    assert not meets("inferred") and not meets("unknown")


def test_low_confidence_families_cannot_offer_control_actions(catalog):
    for profile in catalog.ecus.values():
        if profile.confidence in ("inferred", "unknown"):
            assert not profile.supports("actuators")
            assert not profile.supports("dtc_clear")
            # ...but observation stays available, which is the whole point.
            if "identify" in profile.capabilities:
                assert profile.supports("identify")


def test_local_identifiers_are_unique_within_a_family(catalog):
    for profile in catalog.ecus.values():
        ids = [p.local_id for p in profile.parameters]
        assert len(ids) == len(set(ids)), f"{profile.id} has duplicate local ids"
        keys = [p.key for p in profile.parameters]
        assert len(keys) == len(set(keys))
        act = [a.local_id for a in profile.actuators]
        assert len(act) == len(set(act)), f"{profile.id} has duplicate actuator ids"


def test_dangerous_actuators_carry_a_warning(catalog):
    for profile in catalog.ecus.values():
        for actuator in profile.actuators:
            if actuator.group in ("fuelling", "ignition") or "pump" in actuator.key:
                assert actuator.warning, f"{profile.id}:{actuator.key} needs a warning"
            assert actuator.max_pulse_s <= 30


def test_every_family_declares_its_sources(catalog):
    for profile in catalog.ecus.values():
        assert profile.sources, f"{profile.id} has no provenance"
        assert profile.notes


def test_memory_writing_is_only_claimed_where_the_protocol_is_verified(catalog):
    """Writing is no longer blocked by policy - it is gated on evidence.

    A family may declare ``write_supported`` only once its programming block
    is marked ``verified-*``. Anything less and it must carry a reason saying
    what is missing, so the refusal is actionable rather than dogmatic.
    """
    for profile in catalog.ecus.values():
        memory = profile.memory or {}
        confidence = memory.get("programming", {}).get("confidence", "")
        if memory.get("write_supported"):
            assert confidence.startswith("verified"), (
                f"{profile.id} claims write support on a "
                f"{confidence or 'missing'} programming definition"
            )
            assert "memory_write" in profile.capabilities
        else:
            assert memory.get("write_blocked_reason"), (
                f"{profile.id} refuses writes without saying why"
            )
            assert "memory_write" not in profile.capabilities


def test_readable_families_declare_region_geometry_or_refuse(catalog):
    """A read path must either know its geometry or admit that it does not."""
    for profile in catalog.ecus.values():
        memory = profile.memory or {}
        if not memory.get("read_supported"):
            continue
        assert memory.get("programming", {}).get("protocol"), profile.id
        for name, region in memory.get("regions", {}).items():
            if not region.get("size"):
                assert region.get("note"), (
                    f"{profile.id}:{name} has no size and no explanation"
                )


def test_5am_scalings_match_the_verified_capture(catalog):
    p = catalog.ecu("5am")
    assert p.parameter("rpm").local_id == 0x30
    assert p.parameter("coolant_temp").bias == -40
    assert p.parameter("throttle").scale == 0.1
    assert p.parameter("injection_ms").scale == 0.001
    assert p.parameter("battery").scale == 0.1
    integrator = p.parameter("lambda_int_f")
    assert integrator.signed and integrator.length == 2
    assert p.actuator("fuel_pump").local_id == 5
    assert p.actuator("coil_rear").local_id == 3
    assert p.routine("tps_reset").service == 0x31
    assert p.routine("tps_reset").local_id == 0x21
    assert p.memory["image_size"] == 327680


def test_dead_identifiers_are_excluded_from_live_polling(catalog):
    p = catalog.ecu("5am")
    assert any(x.dead for x in p.parameters)
    assert all(not x.dead for x in p.live_parameters)


def test_shared_sae_dtc_table_is_merged_into_every_family(catalog):
    for profile in catalog.ecus.values():
        assert profile.dtc_descriptions.get("P0130")
        assert profile.dtc_descriptions.get("P0335")


def test_running_changes_resolve_to_the_narrower_window(catalog):
    # The V11 moved 15M -> 15RC during 2002.
    assert catalog.ambiguous("V11 Sport", 2002)
    _, profile = catalog.resolve("V11 Sport", 2001)
    assert profile.id == "15m"
    _, profile = catalog.resolve("V11 Sport", 2005)
    assert profile.id == "15rc"


def test_resolution_covers_a_representative_bike_from_each_era(catalog):
    expected = {
        ("California EV", 1999): "15m",
        ("V7 Classic", 2010): "15rc",
        ("Griso 1200 8V", 2012): "5am",
        ("Stelvio 1200", 2009): "5am",
        ("V7 II Stone", 2016): "miug3",
        ("California 1400 Touring", 2015): "7sm",
        ("V7 III Stone", 2018): "miug4",
        ("V100 Mandello", 2023): "11mp",
    }
    for (model, year), ecu_id in expected.items():
        _, profile = catalog.resolve(model, year)
        assert profile.id == ecu_id, f"{model} {year} -> {profile.id}, want {ecu_id}"


def test_unknown_vehicle_raises_rather_than_guessing(catalog):
    with pytest.raises(CatalogError):
        catalog.resolve("Ducati Monster", 2015)
    with pytest.raises(CatalogError):
        catalog.ecu("not-an-ecu")


# -- cross-brand coverage (Ducati, Aprilia) ---------------------------------


def test_cross_brand_makes_are_present(catalog):
    assert set(catalog.makes()) == {"Aprilia", "Ducati", "Moto Guzzi"}


def test_every_cross_brand_entry_is_read_only_until_confirmed(catalog):
    """Shared ECU hardware is not shared protocol knowledge.

    Ducati and Aprilia run the same Marelli ECUs, but this catalog's
    identifier tables were all captured in a Moto Guzzi context - so every
    cross-brand vehicle ships as 'inferred' and degrades to read-only via
    the effective-confidence rule in the workstation.
    """
    cross = [v for v in catalog.vehicles if v.make != "Moto Guzzi"]
    assert len(cross) >= 30
    for vehicle in cross:
        assert vehicle.confidence == "inferred", vehicle
        assert vehicle.ecu in catalog.ecus


def test_find_scopes_by_make(catalog):
    # the same model name may exist under different makes one day
    assert catalog.find("748", 2000, "Ducati")
    assert not catalog.find("748", 2000, "Moto Guzzi")
    # 916: P8 for the early cars, 16M for the later ones
    early = catalog.resolve("916", 1995, "Ducati")
    later = catalog.resolve("916", 1997, "Ducati")
    assert early[1].id == "p8" and later[1].id == "16m"


def test_the_59m_family_is_an_honest_placeholder(catalog):
    profile = catalog.ecu("59m")
    assert profile.confidence == "unknown"
    assert not profile.parameters and not profile.actuators
    assert not profile.memory.get("read_supported")
    # identification, DTCs and the read-only sweep only
    assert set(profile.capabilities) <= {"identify", "dtc_read", "discover"}
