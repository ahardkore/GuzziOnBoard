"""Synthetic Worker-to-desktop compatibility; no Cloudflare or ECU contacted."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from guzzionboard import protocol_updates, read_sharing, signing

ROOT = Path(__file__).resolve().parent.parent


def test_worker_signs_read_report_for_desktop(shared, monkeypatch):
    if not shutil.which('node'):
        pytest.skip('Node 22 or newer is required for the Worker test')
    tmp_path, diag, image = shared
    assert read_sharing.queue_read(diag, image, 'flash')
    report = json.loads(next(read_sharing.OUTBOX.glob('*.json')).read_text())
    result = subprocess.run(['node', str(ROOT / 'tests/cloudflare-worker-harness.mjs')],
                            input=json.dumps({'report': report, 'public_key': signing.public_key('11' * 32)}),
                            text=True, capture_output=True, check=True, timeout=30)
    output = json.loads(result.stdout)
    envelope = output['envelope']
    assert protocol_updates.verify_envelope(envelope, {'release': signing.public_key('11' * 32)})['signature_verified']
    assert envelope['payload']['quorum'] == 1
    assert all(effect['target'] == 'source' for promotion in envelope['payload']['promotions']
               for effect in promotion['effects'])
    assert 'flash' in envelope['payload']['promotions'][0]['effects'][0]['value']
    assert len(output['row']) == 1 and 'capture' not in output['row'][0]
    consumer = tmp_path / 'consumer'
    protocol_updates.pin_key('release', signing.public_key('11' * 32), directory=consumer)
    preview = protocol_updates.check_envelope(envelope, directory=consumer)
    protocol_updates.apply_pack(envelope, expected_sha256=preview['sha256'], directory=consumer)
    overlay, status = protocol_updates.load_applied_overlay(directory=consumer)
    assert status['state'] == 'applied'
    entry = overlay['promotions']['5am']
    assert not entry['memory_read_supported'] and not entry['capability_confidence']
    assert "region 'flash'" in entry['sources_add'][0]
    diag.log.close()


def test_worker_catalog_matches_app():
    subprocess.run([os.sys.executable, str(ROOT / 'scripts/build_cloudflare_catalog.py'), '--check'],
                   cwd=ROOT, check=True, timeout=30)


def test_workers_build_configuration_deploys_relay_not_website():
    import tomllib
    from uuid import UUID
    config = tomllib.loads((ROOT / 'cloudflare/wrangler.build.toml').read_text())
    assert config['name'] == 'guzzionboard-validation'
    assert config['main'] == 'worker.mjs'
    assert config['keep_vars'] is True
    assert config['preview_urls'] is False
    assert config['observability'] == {'enabled': False}
    assert 'assets' not in config
    assert config['d1_databases'] == [{
        'binding': 'DB', 'database_name': 'guzzionboard',
        'database_id': '66e69f17-cf5b-4728-b07b-6eb365be587f',
    }]
    assert str(UUID(config['d1_databases'][0]['database_id'])) == config['d1_databases'][0]['database_id']
    assert not (set(config.get('vars', {})) & {'GOB_SIGNING_SEED', 'GOB_VALIDATION_TOKEN'})


# ------------------------------------------------- relay parity contract
#
# There are two relay implementations and both are wanted: the Cloudflare
# Worker is what actually runs at the edge, and validation_service.py is what
# an operator can run on their own network. They must not quietly disagree
# about what is accepted, so the constants and the accept/refuse decisions are
# pinned here rather than assumed.

def _worker_source() -> str:
    return (ROOT / 'cloudflare' / 'worker.mjs').read_text(encoding='utf-8')


def test_the_two_relays_agree_on_their_size_limits():
    from guzzionboard import validation_service
    source = _worker_source()
    assert 'MAX_REQUEST = 65536' in source
    assert 'MAX_CAPTURE = 32768' in source
    assert validation_service.MAX_REQUEST == 65536
    assert 'len(text.encode()) > 32768' in (ROOT / 'guzzionboard' / 'validation_service.py').read_text(
        encoding='utf-8')


def test_the_worker_and_the_relay_accept_the_same_claim_shape():
    """Only a completed memory-read is promotable, in both implementations."""
    relay = (ROOT / 'guzzionboard' / 'validation_service.py').read_text(encoding='utf-8')
    worker = _worker_source()
    assert "set(bundle[\"claims\"]) != {\"memory_read\"}" in relay
    assert "hasKeys(b.claims, ['memory_read'])" in worker
    assert 'b.verdict === \'ok\'' in worker and 'bundle.get("verdict") != "ok"' in relay


def test_neither_relay_signs_an_unvalidated_report():
    """A report must be verified against its capture before anything is signed."""
    worker = _worker_source()
    assert 'capture_sha256' in worker
    relay = (ROOT / 'guzzionboard' / 'validation_service.py').read_text(encoding='utf-8')
    assert 'confirmations.verify_confirmation(bundle, capture)' in relay


def test_both_relays_refuse_personal_data_fields():
    worker = _worker_source()
    for field in ('vin', 'serial', 'plate', 'owner', 'email', 'address'):
        assert field in worker, field
