"""Synthetic Worker-to-desktop compatibility; no Cloudflare or ECU contacted."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from guzzionboard import protocol_updates, read_sharing, signing
from guzzionboard.catalog import load_catalog
from test_read_sharing import shared  # noqa: F401 - shared test fixture

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
