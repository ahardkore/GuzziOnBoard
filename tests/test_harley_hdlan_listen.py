"""Synthetic receive-only HDLAN tests; not motorcycle validation."""
from types import SimpleNamespace

import pytest

from guzzionboard import harley_hdlan_listen as listen
from guzzionboard.server import Api
from guzzionboard.workstation import Workstation
from guzzionboard.transports.base import TransportError


class Bus:
    def __init__(self, frames=(), error=None):
        self.frames = list(frames)
        self.error = error
        self.shutdown_called = False
        self.send_called = False
    def recv(self, timeout):
        assert 0 < timeout <= 2.0
        if self.error: raise self.error
        return self.frames.pop(0) if self.frames else None
    def send(self, *_):
        self.send_called = True
        raise AssertionError('passive listener must never transmit')
    def shutdown(self): self.shutdown_called = True


def msg(ident, data, **kwargs):
    return SimpleNamespace(arbitration_id=ident, data=bytes(data), timestamp=123.0, **kwargs)


def setup_bus(monkeypatch, bus):
    calls = []
    def factory(**kwargs):
        calls.append(kwargs)
        return bus
    monkeypatch.setattr(listen, '_require_can', lambda: SimpleNamespace(interface=SimpleNamespace(Bus=factory)))
    return calls


def test_receive_only_latest_values_with_frame_filters(monkeypatch):
    bus = Bus([msg(0x521, [0, 20]), msg(0x521, [0, 40]), msg(0x541, [0] * 5 + [80]),
               msg(0x530, [0, 0, 0x81]), msg(0x550, [1]),
               msg(0x521, [1]), msg(0x521, [0, 99], is_rx=False),
               msg(0x521, [0, 99], is_extended_id=True), msg(0x521, [0, 99], is_fd=True),
               msg(0x521, [0, 99], is_remote_frame=True), msg(0x123, [0])])
    calls = setup_bus(monkeypatch, bus)
    result = listen.listen('can0')
    assert calls[0]['interface'] == 'socketcan' and calls[0]['channel'] == 'can0'
    assert {entry['can_id'] for entry in calls[0]['can_filters']} == set(listen.MIN_LENGTH)
    by_id = {event['id']: event for event in result['events']}
    assert by_id['0x521']['values']['speed_kmh_candidate'] == 40
    assert by_id['0x541']['values']['engine_temp_c_candidate'] == 80
    assert by_id['0x530']['values']['neutral_candidate'] is True
    assert by_id['0x550']['values']['clutch_candidate'] is True
    assert result['frames_received'] == 11 and result['invalid_length_frames'] == 1
    assert bus.shutdown_called and not bus.send_called


def test_each_window_is_fresh_and_interface_is_validated(monkeypatch):
    bus = Bus([]); calls = setup_bus(monkeypatch, bus)
    assert listen.listen('can0')['events'] == []
    for bad in ('', '../can0', 'can0;exit', 'x' * 16, None):
        with pytest.raises(ValueError): listen.listen(bad)
    assert len(calls) == 1 and bus.shutdown_called


def test_receive_errors_close_bus_and_do_not_return_stale_data(monkeypatch):
    bus = Bus(error=RuntimeError('failed')); setup_bus(monkeypatch, bus)
    with pytest.raises(TransportError, match='receive failed'): listen.listen('can0')
    assert bus.shutdown_called and not bus.send_called


def test_window_is_bounded_on_busy_bus(monkeypatch):
    bus = Bus([msg(0x521, [0, 1])] * 5); setup_bus(monkeypatch, bus)
    monkeypatch.setattr(listen, 'MAX_FRAMES', 3)
    result = listen.listen('can0')
    assert result['frames_received'] == 3 and result['frame_limit_reached']
    assert bus.shutdown_called and not bus.send_called


def test_api_confirmation_lock_and_release(monkeypatch):
    api = Api(Workstation(record=False)); called = []
    monkeypatch.setattr(listen, 'listen', lambda channel, profile: called.append((channel, profile)) or {'events': []})
    assert api.post_tools_harley_hdlan_listen({'channel': 'can0'})[0] == 400
    assert not called
    assert api.post_tools_harley_hdlan_listen({'channel': 'can0', 'confirm': True}) == (200, {'events': []})
    assert called == [('can0', 'community')]
    api._hdlan_lock.acquire()
    try: assert api.post_tools_harley_hdlan_listen({'channel': 'can0', 'confirm': True})[0] == 409
    finally: api._hdlan_lock.release()
    def fail(*_): raise TransportError('test')
    monkeypatch.setattr(listen, 'listen', fail)
    with pytest.raises(TransportError): api.post_tools_harley_hdlan_listen({'channel': 'can0', 'confirm': True})
    assert api._hdlan_lock.acquire(blocking=False)
    api._hdlan_lock.release()


def test_exact_2017_sportster_source_observations_preserve_unknowns(monkeypatch):
    bus = Bus([msg(0x550, [8, 0, 0, 0, 0, 0]), msg(0x542, [0x30] + [0]*7),
               msg(0x544, [0xc8] + [0]*7), msg(0x530, [0, 0, 0x81, 0, 0, 0xab, 0, 0]),
               msg(0x542, [0x10] + [0]*7), msg(0x544, [1])])
    calls = setup_bus(monkeypatch, bus)
    result = listen.listen('can0', 'sportster_2017')
    events = {event['id']: event for event in result['events']}
    assert events['0x550']['values']['high_beam_0x08_candidate'] is True
    assert events['0x542']['values'] == {'stand_byte0_raw': 0x10, 'jiffy_stand_candidate': None}
    assert events['0x544']['values']['throttle_frame_byte0_raw'] == 0xc8
    assert events['0x530']['values']['battery_frame_byte5_raw'] == 0xab
    assert events['0x530']['values']['neutral_0x81_candidate'] is True
    assert result['invalid_length_frames'] == 1
    assert {f['can_id'] for f in calls[0]['can_filters']} == set(listen.SPORTSTER_LENGTH)
    assert not bus.send_called and bus.shutdown_called
    with pytest.raises(ValueError): listen.listen('can0', 'arbitrary')


def test_ducati_mitsubishi_live_broadcasts_reuse_offline_decoder(monkeypatch):
    bus = Bus([msg(0x80, [0,0,0,0,80,0x12,0x34,0]),
               msg(0x18, [0,0,0,0,0x21,0x20]),
               msg(0x100, [0,0,0,120,125,70]),
               msg(0x80, [0,0]), msg(0x80, [0]*8, is_rx=False),
               msg(0x80, [0]*8, is_extended_id=True)])
    calls=setup_bus(monkeypatch,bus)
    result=listen.listen('can0','ducati_mitsubishi')
    assert {entry['can_id'] for entry in calls[0]['can_filters']} == {0x18,0x80,0x100}
    events={x['id']:x for x in result['events']}
    assert events['0x80']['values'] == {'throttle_percent':40, 'rpm':0x1234}
    assert events['0x18']['values'] == {'rear_wheel_speed_kmh':18, 'gear_raw':1}
    assert events['0x100']['values'] == {'coolant_c':80,'air_c':30,'battery_v':12.5}
    assert result['invalid_length_frames'] == 1 and bus.shutdown_called and not bus.send_called


def test_ducati_window_does_not_reuse_stale_frames(monkeypatch):
    bus=Bus([]); setup_bus(monkeypatch,bus)
    assert listen.listen('can0','ducati_mitsubishi')['events'] == []
