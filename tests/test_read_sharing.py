"""Synthetic relay tests. No actual ECU or hosted service is used."""
import json
from types import SimpleNamespace

import pytest

from guzzionboard import confirmations, protocol_updates, read_sharing, signing
from guzzionboard.catalog import load_catalog
from guzzionboard.firmware import FirmwareImage
from guzzionboard.safety import Mode
from guzzionboard.sessionlog import SessionLog
from guzzionboard.validation_service import RelayError, ValidationRelay

SEED = '11' * 32
TOKEN = 't' * 40


@pytest.fixture
def shared(tmp_path, monkeypatch):
    monkeypatch.setenv('GOB_SHARE_READ_VALIDATIONS', '1')
    monkeypatch.setenv('GOB_VALIDATION_URL', 'https://validation.example')
    monkeypatch.setenv('GOB_VALIDATION_TOKEN', TOKEN)
    monkeypatch.setattr(read_sharing, 'OUTBOX', tmp_path / 'outbox')
    monkeypatch.setattr(confirmations, 'INSTALL_FILE', tmp_path / 'install.json')
    monkeypatch.setattr(read_sharing, 'flush_outbox', lambda: None)
    profile = load_catalog(overlays=False).ecu('5am')
    log = SessionLog(directory=tmp_path / 'sessions', meta={'ecu':'5am', 'transport':'kline', 'mode':'read_only'})
    log.frame('tx', b'\x81\x10\xf1\x81\x05')
    log.frame('rx', b'\x80\xf1\x10\xc1\xea\x8f')
    log.action('connect', {'ok':True, 'init':'fast', 'protocol':'iso14230'})
    log.action('identify', {'fields':{'VIN':'PRIVATE VIN'}})
    log.frame('rx', b'private firmware data')
    image = FirmwareImage(data=bytearray(311296), ecu_id='5am', region='flash', source='read')
    log.action('memory_read_complete', {'region':'flash','size':image.size,'sha256':image.sha256})
    diag = SimpleNamespace(transport=SimpleNamespace(name='kline', is_physical=True),
                           log=log, profile=profile, gate=SimpleNamespace(mode=Mode.READ_ONLY))
    return tmp_path, diag, image


def test_report_is_minimal_and_is_published_with_one_read(shared):
    tmp_path, diag, image = shared
    assert read_sharing.queue_read(diag,image,'flash')
    path = next((tmp_path/'outbox').glob('conf-*.json'))
    raw = path.read_text(); report=json.loads(raw)
    assert 'PRIVATE VIN' not in raw and 'private firmware data' not in raw
    assert set(report['bundle']['claims']) == {'memory_read'}
    assert report['bundle']['session']['identity'] == {}
    assert confirmations.verify_confirmation(report['bundle'],report['capture'].encode())['ok']
    relay = ValidationRelay(tmp_path/'relay.sqlite',token=TOKEN,seed=SEED,key_id='release')
    result=relay.submit(report)
    assert result['accepted'] and result['sequence']==1
    assert relay.submit(report)['duplicate']
    envelope=relay.latest()
    assert protocol_updates.verify_envelope(envelope,{'release':signing.public_key(SEED)})['signature_verified']
    assert envelope['payload']['quorum']==1
    assert all(effect['target'] == 'source'
               for p in envelope['payload']['promotions'] for effect in p['effects'])
    assert "'flash'" in envelope['payload']['promotions'][0]['effects'][0]['value']
    diag.log.close()


def test_simulator_or_missing_consent_never_queues(shared, monkeypatch):
    _, diag, image=shared
    diag.transport.is_physical=False
    assert not read_sharing.queue_read(diag,image,'flash')
    diag.transport.is_physical=True
    monkeypatch.delenv('GOB_SHARE_READ_VALIDATIONS')
    assert not read_sharing.queue_read(diag,image,'flash')
    diag.log.close()


def test_relay_rejects_changed_capture_and_extra_sensitive_events(shared):
    tmp_path, diag, image=shared
    assert read_sharing.queue_read(diag,image,'flash')
    report=json.loads(next((tmp_path/'outbox').glob('conf-*.json')).read_text())
    relay=ValidationRelay(tmp_path/'relay.sqlite',token=TOKEN,seed=SEED,key_id='release')
    report['capture'] += '{"kind":"frame","hex":"dead"}\n'
    with pytest.raises(RelayError): relay.submit(report)
    assert relay.latest() is None
    diag.log.close()


def test_http_submission_retry_and_automatic_application(shared, monkeypatch):
    """Synthetic capture traverses a real local HTTP relay; HTTPS is mocked only at the proxy boundary."""
    import http.client
    import threading
    import urllib.request
    from http.server import ThreadingHTTPServer
    from guzzionboard.auto_protocol_updates import AutoProtocolUpdates
    from guzzionboard.validation_service import handler_for, MAX_REQUEST
    from guzzionboard.workstation import Workstation

    tmp_path, diag, image = shared
    relay = ValidationRelay(tmp_path / 'http.sqlite', token=TOKEN, seed=SEED, key_id='release')
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler_for(relay))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        conn = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
        conn.request('POST', '/v1/confirmations', body='{}')
        response = conn.getresponse(); assert response.status == 401; response.read()
        conn.request('POST', '/v1/confirmations', headers={'Authorization': 'Bearer ' + TOKEN,
                                                           'Content-Length': str(MAX_REQUEST + 1)})
        response = conn.getresponse(); assert response.status == 413; response.read(); conn.close()

        assert read_sharing.queue_read(diag, image, 'flash')
        assert read_sharing.queue_read(diag, image, 'flash')
        assert len(list(read_sharing.OUTBOX.glob('*.json'))) == 1

        # A network failure retains the report. A later successful retry removes it.
        actual_opener = urllib.request.build_opener()
        class Offline:
            def open(self, *args, **kwargs): raise OSError('offline')
        monkeypatch.setattr(urllib.request, 'build_opener', lambda *args: Offline())
        _real_flush_outbox()
        assert len(list(read_sharing.OUTBOX.glob('*.json'))) == 1
        class Proxy:
            def open(self, request, timeout):
                local = urllib.request.Request(f'http://127.0.0.1:{port}/v1/confirmations',
                                               data=request.data, headers=dict(request.header_items()),
                                               method='POST')
                return actual_opener.open(local, timeout=timeout)
        monkeypatch.setattr(urllib.request, 'build_opener', lambda *args: Proxy())
        _real_flush_outbox()
        assert list(read_sharing.OUTBOX.glob('*.json')) == []

        conn = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
        conn.request('GET', '/protocol-update.json')
        response = conn.getresponse(); assert response.status == 200
        envelope = json.loads(response.read()); conn.close()
        assert protocol_updates.verify_envelope(envelope, {'release': signing.public_key(SEED)})['signature_verified']

        monkeypatch.setattr(protocol_updates, 'DEFAULT_DIR', tmp_path / 'consumer')
        protocol_updates.pin_key('release', signing.public_key(SEED))
        monkeypatch.setattr(protocol_updates, 'fetch_pack', lambda *args: envelope)
        monkeypatch.setattr(read_sharing, 'flush_outbox', lambda: None)
        workstation = Workstation(session_dir=tmp_path / 'consumer-sessions')
        before_confidence = dict(workstation.catalog.ecu('5am').capability_confidence)
        updater = AutoProtocolUpdates(workstation)
        updater.check_once()
        assert updater.status()['state'] == 'applied'
        assert workstation.catalog.ecu('5am').field_confirmation
        assert workstation.catalog.ecu('5am').capability_confidence == before_confidence
        assert any("region 'flash'" in str(source) for source in workstation.catalog.ecu('5am').sources)
        updater.check_once()
        assert updater.status()['state'] == 'current'
    finally:
        diag.log.close()
        server.shutdown(); server.server_close(); thread.join()
        load_catalog.cache_clear()


# Preserve the implementation when the fixture disables background sends.
_real_flush_outbox = read_sharing.flush_outbox
