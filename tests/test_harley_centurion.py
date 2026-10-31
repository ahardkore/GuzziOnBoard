"""Synthetic local header checks; no customer files or ECU communications."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_centurion_header_parser_synthetic():
    if not shutil.which('node'):
        pytest.skip('Node.js required')
    result = subprocess.run(['node', str(ROOT / 'tests/harley-centurion-harness.cjs')],
                            text=True, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert 'synthetic Centurion headers passed' in result.stdout


def test_centurion_containers_never_render_or_diff_as_raw(tmp_path):
    from guzzionboard.server import Api
    from guzzionboard.workstation import Workstation
    api = Api(Workstation(record=False))
    xdf = tmp_path / 'test.xdf'
    xdf.write_text('<XDFFORMAT><XDFHEADER><deftitle>Test</deftitle></XDFHEADER></XDFFORMAT>')
    raw = tmp_path / 'normal.bin'
    raw.write_bytes(bytes(256))
    for name, content in [('opaque.ori', bytes(256)), ('renamed.bin', b'Delphi\x00' + bytes(249))]:
        path = tmp_path / name
        path.write_bytes(content)
        status, body = api.post_maps_render({'path': str(path), 'xdf': str(xdf)})
        assert status == 400 and 'not raw ECU images' in body['error']
        status, body = api.post_maps_diff({'path_a': str(raw), 'path_b': str(path), 'xdf': str(xdf)})
        assert status == 400 and 'not raw ECU images' in body['error']
