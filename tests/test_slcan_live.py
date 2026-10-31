"""Synthetic SLCAN serial emulation; no adapter or motorcycle was tested."""
import pytest
from guzzionboard.transports.base import TransportUnavailable
from guzzionboard.transports.can import CanTransport, validate_slcan_selection
from guzzionboard.workstation import Workstation


@pytest.mark.parametrize('port', ['COM5', 'com10@115200', '/dev/ttyACM0', '/dev/serial/by-id/usb-ABC@230400'])
def test_local_ports_are_accepted(port):
    assert validate_slcan_selection(port) == port


@pytest.mark.parametrize('port', ['', 'can0', 'socket://host:1234', '/dev/../etc/passwd',
                                  '/dev//ttyACM0', 'COM0', 'COM3@1', 'COM1@9999999',
                                  'COM1@115200@3', 'COM1;evil', None])
def test_nonlocal_or_malformed_ports_are_rejected(port):
    with pytest.raises(ValueError): validate_slcan_selection(port)
    with pytest.raises(TransportUnavailable):
        CanTransport(interface='slcan', channel=port, bitrate=500000,tx_id=0x7e0,rx_id=0x7e8).open()


def test_workstation_slcan_scope_and_existing_safety_gate():
    ws = Workstation(record=False)
    with pytest.raises(ValueError,match='physical CAN'):
        ws.select(ecu='harley_delphi_can_uds',transport='cansim',can_interface='slcan',device='COM5')
    with pytest.raises(ValueError, match='local COM'):
        ws.select(ecu='harley_delphi_can_uds',transport='can',can_interface='slcan',device='')
    selection=ws.select(ecu='harley_delphi_can_uds',transport='can',can_interface='slcan',device='COM5')
    assert selection['can_interface'] == 'slcan'
    t=ws._build_transport()
    assert (t.channel,t.interface,t.bitrate,t.tx_id,t.rx_id,t.padding)==('COM5','slcan',500000,0x7e0,0x7e8,0)
    with pytest.raises(TransportUnavailable): ws.connect(mode='service')


def test_actual_python_can_slcan_backend_with_mock_serial(monkeypatch):
    pytest.importorskip('can'); pytest.importorskip('serial')
    import can.interfaces.slcan as slcan
    class Serial:
        def __init__(self): self.writes=[]; self.input=bytearray(); self.write_timeout=None; self.closed=False
        def write(self, data): self.writes.append(bytes(data)); return len(data)
        def flush(self): pass
        @property
        def in_waiting(self): return len(self.input)
        def read(self, size):
            result=self.input[:size]; del self.input[:size]; return bytes(result)
        def close(self): self.closed=True
    serial=Serial(); calls=[]
    def factory(*args,**kwargs): calls.append((args,kwargs)); return serial
    monkeypatch.setattr(slcan.serial,'serial_for_url',factory)
    monkeypatch.setattr(slcan.time,'sleep',lambda _: None)
    t=CanTransport(interface='slcan',channel='COM5@230400',bitrate=500000,tx_id=0x7e0,rx_id=0x7e8,padding=0)
    conn=t.open()
    assert calls[0][0] == ('COM5',) and calls[0][1]['baudrate'] == 230400
    assert b'S6\r' in serial.writes and b'O\r' in serial.writes
    conn.write(bytes.fromhex('3e 00'))
    assert serial.writes[-1] == b't7E08023E000000000000\r'
    serial.input.extend(b't7E88027E000000000000\r')
    assert conn.read_frame(0.1) == bytes.fromhex('7e 00')
    conn.close()
    assert serial.closed and serial.writes[-1] == b'C\r'
