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


def test_honda_live_profile_remains_scoped_and_no_simulator():
    ws = Workstation(record=False)
    selected = ws.select(make="Honda", model="CBR600RR", year=2005, transport="kline")
    assert selected["ecu"]["capabilities"] == ["identify", "live"]
    assert selected["ecu"]["session"]["physical_supported"] is True
    assert not selected["ecu"]["memory"]["read_supported"]
    with pytest.raises(TransportUnavailable, match="read-only mode"):
        ws.connect(mode="service")
    for kind in ("simulator", "cansim"):
        ws.select(make="Honda", model="CBR600RR", year=2005, transport=kind)
        with pytest.raises(TransportUnavailable):
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


def test_sv650_source_scoped_session_is_read_only_and_no_simulator():
    ws = Workstation(record=False)
    selection = ws.select(make="Suzuki", model="SV650AK7", year=2007, transport="kline")
    assert selection["ecu"]["capabilities"] == ["live"]
    assert selection["ecu"]["session"]["physical_supported"] is True
    assert selection["ecu"]["session"]["simulator_supported"] is False
    assert not selection["ecu"]["memory"]["read_supported"]
    with pytest.raises(TransportUnavailable): ws.connect(mode="service")
    for transport in ("can", "simulator", "cansim"):
        ws.select(make="Suzuki", model="SV650AK7", year=2007, transport=transport)
        with pytest.raises(TransportUnavailable): ws.connect(mode="simulator" if transport in ("simulator", "cansim") else "read_only")
    with pytest.raises(ValueError, match="not cataloged"):
        ws.select(make="Suzuki", model="SV650AK7", year=2007, ecu="5am")


@pytest.mark.parametrize('selection', [
    {'make':'Honda','model':'Wave 110','year':2012},
    {'make':'Suzuki','model':'SV650AK7','year':2007},
    {'make':'Suzuki','model':'SV650','year':2004},
    {'ecu':'harley_delphi_can_uds'},
    {'ecu':'harley_j1850_harleydroid'},
])
def test_synthetic_validation_evidence_is_in_selection_notice(selection):
    ws=Workstation(record=False)
    result=ws.select(**selection)
    evidence=result['ecu']['session']['physical_evidence_note']
    assert 'synthetic' in evidence.lower()
    assert any(n['text']==f'Validation: {evidence}' for n in result['notices'])
