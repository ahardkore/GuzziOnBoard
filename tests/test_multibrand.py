"""Multi-make identities do not weaken vehicle or transport boundaries."""
import pytest

from guzzionboard.catalog import Catalog, CatalogError, VehicleEntry, load_catalog
from guzzionboard.transports.base import TransportUnavailable
from guzzionboard.workstation import Workstation


def duplicate_catalog():
    original = load_catalog(overlays=False)
    return Catalog(original.ecus, [
        VehicleEntry(make="Aprilia", model="Shared", year_from=2000, year_to=2002, ecu="16m", confidence="inferred"),
        VehicleEntry(make="Moto Guzzi", model="Shared", year_from=2000, year_to=2004, ecu="5am", confidence="documented"),
    ])


def test_make_required_for_cross_make_collision_and_ambiguity_is_scoped():
    catalog = duplicate_catalog()
    with pytest.raises(CatalogError, match="multiple makes"):
        catalog.resolve("Shared", 2001)
    assert catalog.resolve("Shared", 2001, "aprilia")[0].make == "Aprilia"
    assert catalog.ambiguous("Shared", 2001)
    assert catalog.summary()["model_count"] == 2  # make-qualified identities
    assert not catalog.ambiguous("Shared", 2001, "Aprilia")
    with pytest.raises(TypeError):
        VehicleEntry(model="Unknown", year_from=2000, year_to=2001, ecu="5am")


def test_override_retains_vehicle_confidence_and_rejects_other_make():
    ws = Workstation(record=False)
    ws.catalog = duplicate_catalog()
    with pytest.raises(ValueError, match="multiple makes"):
        ws.select(model="Shared", year=2001, ecu="5am")
    with pytest.raises(ValueError, match="not cataloged"):
        ws.select(make="Aprilia", model="Shared", year=2001, ecu="5am")
    selected = ws.select(make="Aprilia", model="Shared", year=2001, ecu="16m")
    assert selected["ecu"]["confidence"] == "inferred"
    assert selected["entry"]["make"] == "Aprilia"
    assert not any("spans more than one" in notice["text"] for notice in selected["notices"])
    with pytest.raises(ValueError, match="partial vehicle identity"):
        ws.select(make="Honda", ecu="5am")
    assert ws.select(ecu="5am")["entry"] is None  # explicit ECU-only bench path


def test_honda_placeholder_blocks_hardware_and_simulator_before_open():
    ws = Workstation(record=False)
    selected = ws.select(make="Honda", model="CBR600RR", year=2005, transport="kline")
    assert selected["ecu"]["capabilities"] == []
    assert selected["ecu"]["session"]["physical_supported"] is False
    with pytest.raises(TransportUnavailable, match="no transport was constructed"):
        ws.connect(mode="read_only")
    assert ws.log is None and ws.service is None
    for kind in ("simulator", "cansim"):
        ws.select(make="Honda", model="CBR600RR", year=2005, transport=kind)
        with pytest.raises(TransportUnavailable, match="no matching simulator"):
            ws.connect()
        with pytest.raises(TransportUnavailable, match="no matching simulator"):
            ws._build_transport()
    with pytest.raises(ValueError, match="not cataloged"):
        ws.select(make="Honda", model="CBR600RR", year=2005, ecu="5am")


def test_connected_session_cannot_be_relabelled_with_another_vehicle():
    ws = Workstation(record=False)
    ws.select(make="Moto Guzzi", model="Griso 1200 8V", year=2012)
    ws.connect()
    with pytest.raises(ValueError, match="disconnect the current session"):
        ws.select(make="Honda", model="CBR600RR", year=2005, transport="kline")
    assert ws.status()["selection"]["make"] == "Moto Guzzi"
    assert ws.status()["connected"] is True
    ws.disconnect()
    assert ws.select(make="Honda", model="CBR600RR", year=2005)["make"] == "Honda"


@pytest.mark.parametrize("make,model,year", [
    ("Suzuki", "SV650AK7", 2007),
])
def test_research_profiles_have_no_hardware_or_simulator(make, model, year):
    ws = Workstation(record=False)
    for transport in ("kline", "can", "simulator", "cansim"):
        selection = ws.select(make=make, model=model, year=year, transport=transport)
        assert selection["ecu"]["capabilities"] == []
        assert selection["ecu"]["session"]["physical_supported"] is False
        assert selection["ecu"]["session"]["simulator_supported"] is False
        with pytest.raises(TransportUnavailable):
            ws.connect(mode="simulator" if transport in ("simulator", "cansim") else "read_only")
        assert ws.service is None and ws.log is None
    with pytest.raises(ValueError, match="not cataloged"):
        ws.select(make=make, model=model, year=year, ecu="5am")
