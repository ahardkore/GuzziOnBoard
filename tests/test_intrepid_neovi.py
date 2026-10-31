"""Synthetic neoVI adapter tests; no physical Intrepid interface or bike used."""
import sys
from types import SimpleNamespace

import pytest

from guzzionboard.workstation import Workstation
from guzzionboard.transports.base import TransportUnavailable, TransportError
from guzzionboard.transports.can import CanTransport


def kwargs(**extra):
    return dict(interface='neovi', channel=extra.get('channel', 'HSCAN'),
                serial=extra.get('serial', '123456'), bitrate=500000,
                tx_id=0x7e0, rx_id=0x7e8, padding=0)


@pytest.mark.parametrize('channel,serial', [('', '123'), ('HSCAN,MSCAN', '123'), ('../../abc', '123'),
                                             ('65536', '123'), ('15', '123'), ('ISO14230', '123'), ('JVPW', '123'), ('HSCAN', ''), ('HSCAN', 'a b')])
def test_fail_closed_before_device_open(channel, serial):
    with pytest.raises(TransportUnavailable, match='Intrepid'):
        CanTransport(**kwargs(channel=channel, serial=serial)).open()


def test_missing_python_ics_produces_actionable_error(monkeypatch):
    monkeypatch.setitem(sys.modules, 'ics', None)
    with pytest.raises(TransportUnavailable, match='python_ics.*packaged builds'):
        CanTransport(**kwargs()).open()


def test_workstation_requires_valid_explicit_neo_parameters():
    ws = Workstation(record=False)
    for opts in (dict(device='',can_serial='123'), dict(device='HSCAN',can_serial=''),
                 dict(device='HSCAN,MSCAN',can_serial='123')):
        with pytest.raises(ValueError, match='explicit serial'):
            ws.select(ecu='harley_delphi_can_uds',transport='can',can_interface='neovi',**opts)
    with pytest.raises(ValueError, match='physical CAN'):
        ws.select(ecu='harley_delphi_can_uds',transport='cansim',device='HSCAN',can_serial='123',can_interface='neovi')
    with pytest.raises(ValueError, match='only used'):
        ws.select(ecu='harley_delphi_can_uds',transport='can',device='can0',can_serial='123')
    selected = ws.select(ecu='harley_delphi_can_uds',transport='can',device='HSCAN',can_serial='a1b2',can_interface='neovi')
    assert selected['can_interface'] == 'neovi'
    t = ws._build_transport()
    assert (t.interface,t.channel,t.serial,t.bitrate,t.tx_id,t.rx_id,t.padding) == ('neovi','HSCAN','a1b2',500000,0x7e0,0x7e8,0)
    with pytest.raises(TransportUnavailable): ws.connect(mode='service')


def test_mocked_actual_python_can_neovi_backend(monkeypatch):
    """Exercise python-can backend device selection, ISO-TP send, reply and close."""
    pytest.importorskip('can')
    import can.interfaces.ics_neovi.neovi_bus as neovi
    devices = [SimpleNamespace(Name='other', SerialNumber=111), SimpleNamespace(Name='selected', SerialNumber=222)]
    events = []
    fake = SimpleNamespace(NETID_HSCAN=1, RuntimeError=RuntimeError, SPY_STATUS_TX_MSG=1,
                           SPY_STATUS_GLOBAL_ERR=2, SPY_STATUS_XTD_FRAME=4, SPY_STATUS_REMOTE_FRAME=8,
                           SPY_STATUS2_ERROR_FRAME=1, SPY_PROTOCOL_CANFD=30,
                           SPY_STATUS3_CANFD_BRS=1, SPY_STATUS3_CANFD_ESI=2,
                           find_devices=lambda: devices, open_device=lambda d: events.append(('open',d.SerialNumber)),
                           set_bit_rate=lambda d,b,c: events.append(('bitrate',d.SerialNumber,b,c)),
                           validate_hobject=lambda d: True, SpyMessage=SimpleNamespace,
                           transmit_messages=lambda d,m: events.append(('tx',d.SerialNumber,m.NetworkID,m.ArbIDOrHeader,bytes(m.Data))),
                           close_device=lambda d: events.append(('close',d.SerialNumber)),
                           get_timestamp_for_msg=lambda *_: 1.0)
    msg = SimpleNamespace(NetworkID=1,NetworkID2=0,StatusBitField=0,StatusBitField2=0,
                          Protocol=0,ArbIDOrHeader=0x7e8,NumberBytesData=8,
                          Data=(2,0x7e,0,0,0,0,0,0))
    fake.get_messages=lambda *_: ([msg],0)
    monkeypatch.setitem(sys.modules,'ics',fake)
    monkeypatch.setattr(neovi,'ics',fake)
    transport=CanTransport(**kwargs(serial='222'))
    conn=transport.open()
    conn.write(b'\x3e\x00')
    assert conn.read_frame(0.5) == b'\x7e\x00'
    conn.close()
    assert events == [('open',222), ('bitrate',222,500000,1),
                      ('tx',222,1,0x7e0,bytes.fromhex('02 3e 00 00 00 00 00 00')),('close',222)]


def test_backend_failure_never_falls_back_to_first_device(monkeypatch):
    pytest.importorskip('can')
    import can.interfaces.ics_neovi.neovi_bus as neovi
    opened=[]
    fake=SimpleNamespace(NETID_HSCAN=1,find_devices=lambda: [SimpleNamespace(SerialNumber=111)],
                         open_device=lambda d: opened.append(d))
    monkeypatch.setitem(sys.modules,'ics',fake)
    monkeypatch.setattr(neovi,'ics',fake)
    with pytest.raises(TransportError,match='No device.*222'):
        CanTransport(**kwargs(serial='222')).open()
    assert not opened
