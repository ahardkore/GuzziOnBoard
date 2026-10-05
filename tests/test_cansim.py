"""The virtual CAN bus: the ISO-TP framing path against the simulated ECU.

The CAN transport's segmentation, flow control and reassembly had only ever
been exercised by protocol unit tests - there was no ECU to talk to. These
tests run the full stack (workstation -> diagnostics -> KWP session ->
``CanConnection`` -> ISO-TP -> virtual bus -> bridge -> ``SimulatedEcu``)
so the code that will one day talk to a motorcycle is executed end to end,
flow-control handshakes included.

python-can is required; without it these skip rather than pretend.
"""
from __future__ import annotations

import pytest

pytest.importorskip("can", reason="python-can not installed")

from guzzionboard.catalog import load_catalog
from guzzionboard.safety import Mode, SafetyGate, VehicleState
from guzzionboard.transports.cansim import VirtualCanTransport
from guzzionboard.transports.simulator import EngineModel, SimulatedEcu


@pytest.fixture
def catalog():
    return load_catalog()


def build(catalog, ecu_id="miug4", **kw):
    from guzzionboard.diagnostics import DiagnosticsService

    profile = catalog.ecu(ecu_id)
    ecu = SimulatedEcu(profile, engine=EngineModel(running=True))
    transport = VirtualCanTransport(profile=profile, ecu=ecu, **kw)
    gate = SafetyGate(mode=Mode.SIMULATOR, state=VehicleState())
    service = DiagnosticsService(profile, transport, gate, catalog=catalog)
    return service, ecu


def test_identify_rides_the_isotp_round_trip(catalog):
    """A 55-byte identification forces first frame + flow control + consecutive
    frames in both directions - the path that had never run before."""
    service, _ecu = build(catalog, "miug4")
    service.connect()
    identity = service.identify()
    assert len(identity.raw) >= 40
    assert identity.fields
    service.disconnect()


def test_live_data_and_dtcs_over_the_virtual_bus(catalog):
    service, _ecu = build(catalog, "5am")
    service.connect()
    keys = [p.key for p in service.profile.default_parameters[:3]]
    samples = service.read_parameters(keys)
    assert len(samples) == 3
    assert all(s.raw for s in samples)          # provenance intact
    dtcs = service.read_dtcs()
    assert [d["code"] for d in dtcs] == ["P0130", "P0505"]
    service.disconnect()


def test_the_pair_being_rehearsed_is_the_pair_that_is_used(catalog):
    """Catalog defaults <- vehicle entry <- operator, same as real CAN: a
    29-bit pair set at selection time is what the virtual bus speaks."""
    from guzzionboard.workstation import Workstation

    ws = Workstation(record=False)
    ws.select(
        model="Griso 1200 8V", year=2012, transport="cansim",
        can_tx_id="0x18DA10F1", can_rx_id="0x18DAF110",
    )
    ws.connect()
    transport = ws.service.transport
    assert isinstance(transport, VirtualCanTransport)
    assert transport.tx_id == 0x18DA10F1 and transport.rx_id == 0x18DAF110
    identity = ws.require_service().identify()
    assert identity.raw
    ws.disconnect()


def test_workstation_lists_the_virtual_transport():
    from guzzionboard.workstation import Workstation

    transports = {t["id"]: t for t in Workstation.available_transports()}
    assert transports["cansim"]["available"] is True
    assert not transports["cansim"].get("ports")


def test_connection_close_stops_the_bridge_thread(catalog):
    service, _ecu = build(catalog, "miug4")
    service.connect()
    bridge = service.connection.bridge
    assert bridge._thread.is_alive()
    service.disconnect()
    assert not bridge._thread.is_alive()


def test_negative_responses_cross_the_bus(catalog):
    """An unmapped service must come back as a clean 0x7F, not a timeout."""
    from guzzionboard.protocol.kwp2000 import NegativeResponse

    service, _ecu = build(catalog, "miug4")
    service.connect()
    with pytest.raises(NegativeResponse, match="not supported"):
        service.session.request([0x71, 0x01])   # not mapped in this profile
    service.disconnect()
