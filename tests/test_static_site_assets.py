"""The static site Worker publishes exactly what wrangler.jsonc says it does.

Cloudflare's build log used to show automatic project configuration running on
every deploy: it detected a static project, answered its own prompts with
fallback values, wrote a throwaway `wrangler.jsonc`, appended to `.gitignore`,
created its own `.assetsignore`, and read 3,497 files from the build container.
Nothing in the repository decided which of those became public URLs.

`wrangler.jsonc` now pins the asset directory to the repository root and turns
preview URLs off, and `.assetsignore` lists what must never be uploaded. These
tests pin both halves, because the failure mode is silent: a new cache directory
or a 25 MiB build artifact in an unignored directory either leaks into the
public site or fails the deploy outright with "Asset too large".
"""

from __future__ import annotations

import fnmatch
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'wrangler.jsonc'
ASSETS_IGNORE = ROOT / '.assetsignore'
DOCS = ROOT / 'docs/CLOUDFLARE_DEPLOYMENT.md'


def _load_config() -> dict:
    """Parse wrangler.jsonc, which is JSON with comments and trailing commas."""
    text = CONFIG.read_text(encoding='utf-8')
    text = re.sub(r'^\s*//.*$', '', text, flags=re.MULTILINE)
    text = re.sub(r',(\s*[}\]])', r'\1', text)
    return json.loads(text)


def _ignore_patterns() -> list[str]:
    lines = ASSETS_IGNORE.read_text(encoding='utf-8').splitlines()
    return [line.strip() for line in lines
            if line.strip() and not line.lstrip().startswith('#')]


def _ignored(path: str, patterns: list[str] | None = None) -> bool:
    """True when any pattern would exclude `path` from the upload."""
    patterns = _ignore_patterns() if patterns is None else patterns
    candidates = [path, path.rstrip('/')]
    candidates += [part + '/' for part in path.split('/')]
    for pattern in patterns:
        negate = pattern.startswith('!')
        body = pattern[1:] if negate else pattern
        for candidate in candidates:
            if fnmatch.fnmatch(candidate, body) or fnmatch.fnmatch(candidate.rstrip('/'), body):
                return not negate
    return False


def test_website_config_publishes_from_the_repository_root():
    config = _load_config()
    assert config['name'] == 'guzzionboard'
    assert config['assets']['directory'] == '.'
    assert config['preview_urls'] is False
    assert config['workers_dev'] is True


def test_website_config_cannot_become_the_relay():
    """The relay is a separate Worker with a D1 binding and its own config."""
    config = _load_config()
    assert 'd1_databases' not in config
    assert config['name'] != 'guzzionboard-validation'
    relay = (ROOT / 'cloudflare/wrangler.build.toml').read_text(encoding='utf-8')
    assert 'name = "guzzionboard-validation"' in relay


def test_build_artifacts_and_tooling_are_never_published():
    for path in ['node_modules/wrangler/package.json', '.git/config', 'build/lib/x.py',
                 'guzzionboard.egg-info/PKG-INFO', '__pycache__/m.pyc',
                 '.venv/bin/python', 'dist/app.tar.gz', '.wrangler/tmp/x']:
        assert _ignored(path), path


def test_research_binaries_are_kept_off_the_cdn():
    """OEM calibration archives are third-party material, not site content."""
    for path in ['7SM_MotoGuzzi_1400_EURO4_V1.04.zip',
                 'Hayabusa gen 3 stock.bin',
                 'docs/STOCK ECU OPEN.bin',
                 'docs/14CUX_CHECKSUM.ZIP'.lower(),
                 'Suzuki-GSXR1300-32910-10LX0.zip']:
        assert _ignored(path), path


def test_the_site_itself_is_still_published():
    """Excluding everything would make the deploy succeed and serve nothing."""
    for path in ['index.html', 'web/index.html', 'web/app.js',
                 'web/xdf-library.json', 'docs/CLOUDFLARE_DEPLOYMENT.md',
                 'docs/BENCH_CALCULATORS.md', 'LICENSE']:
        assert not _ignored(path), path


def test_every_ignored_artifact_directory_in_gitignore_is_covered():
    """A path git already refuses to track must not become public via assets."""
    patterns = _ignore_patterns()
    required = ['__pycache__', '*.egg-info', 'build', 'dist', '.venv',
                'node_modules', '.pytest_cache', '.wrangler', '.dev.vars']
    gitignore = (ROOT / '.gitignore').read_text(encoding='utf-8')
    for entry in required:
        assert entry in gitignore, f'{entry} is no longer git-ignored; update both files'
        probe = entry.replace('*', 'x').rstrip('/')
        assert _ignored(f'{probe}/anything.txt', patterns), entry


def test_deployment_docs_describe_the_static_site_worker():
    docs = DOCS.read_text(encoding='utf-8')
    assert 'wrangler.jsonc' in docs
    assert '.assetsignore' in docs
    assert 'guzzionboard.aaron-hard11.workers.dev' in docs
