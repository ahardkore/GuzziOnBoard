"""Shared fixtures for the test suite.

A fixture that two suites need lives here rather than in one of them: a test
module that imports another test module for a fixture breaks collection order,
and a name collision then looks like a bug in the code under test.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from guzzionboard import confirmations, read_sharing
from guzzionboard.catalog import load_catalog
from guzzionboard.firmware import FirmwareImage
from guzzionboard.safety import Mode
from guzzionboard.sessionlog import SessionLog

#: Bearer credential used by the synthetic relay tests.
TOKEN = "t" * 40


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
