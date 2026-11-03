"""Cloudflare Workers Builds entry point: which command runs on which branch.

`scripts/deploy_worker.sh` exists because Workers Builds runs one configured
command for every branch it builds. A production `wrangler deploy` in that slot
fails every non-production build, which is what the failing Workers Builds checks
on a pull request look like. These tests pin the branch rule without contacting
Cloudflare: a stub stands in for wrangler and records the arguments it was given.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "deploy_worker.sh"


@pytest.fixture()
def stub(tmp_path: Path) -> Path:
    path = tmp_path / "wrangler-stub"
    path.write_text("#!/bin/sh\necho \"ARGS: $*\"\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def run(stub: Path, **env: str) -> subprocess.CompletedProcess:
    environment = {key: value for key, value in os.environ.items()
                   if key not in {"WORKERS_CI_BRANCH", "GITHUB_REF_NAME"}}
    environment.update({"WRANGLER": str(stub), **env})
    return subprocess.run(["sh", str(SCRIPT)], cwd=ROOT, env=environment,
                          capture_output=True, text=True, timeout=60)


def test_production_branch_deploys_the_relay(stub: Path):
    result = run(stub, WORKERS_CI_BRANCH="main")
    assert result.returncode == 0, result.stderr
    assert "ARGS: deploy --config cloudflare/wrangler.build.toml" in result.stdout
    # The printed command is what a build log shows; the stub stands in for wrangler.
    assert "deploy_worker: command: " in result.stdout
    assert " deploy --config cloudflare/wrangler.build.toml" in result.stdout


def test_a_feature_branch_uploads_a_version_and_deploys_nothing(stub: Path):
    result = run(stub, WORKERS_CI_BRANCH="arena/3d3ca97f-guzzionboard")
    assert result.returncode == 0, result.stderr
    # A version upload stores a version; it does not touch the live Worker.
    assert "ARGS: versions upload --config cloudflare/wrangler.build.toml" in result.stdout
    # The printed command is what a build log shows, so it must name the upload.
    assert "deploy_worker: command: " in result.stdout and " versions upload " in result.stdout
    assert " deploy --config" not in result.stdout
    assert "nothing is deployed to production" in result.stderr


def test_github_ref_name_is_used_when_workers_ci_branch_is_absent(stub: Path):
    result = run(stub, GITHUB_REF_NAME="some-branch")
    assert result.returncode == 0, result.stderr
    assert "versions upload" in result.stdout


def test_the_production_branch_can_be_overridden(stub: Path):
    result = run(stub, WORKERS_CI_BRANCH="release", WORKERS_CI_PRODUCTION_BRANCH="release")
    assert result.returncode == 0, result.stderr
    assert "ARGS: deploy --config" in result.stdout


def test_an_unknown_branch_refuses_to_guess(stub: Path):
    result = run(stub)
    # Guessing "production" would deploy from a branch nobody identified.
    assert result.returncode == 2
    assert "no branch" in result.stderr
    assert "ARGS:" not in result.stdout


def test_dry_run_is_forwarded(stub: Path):
    result = run(stub, WORKERS_CI_BRANCH="main", WRANGLER_DRY_RUN="1")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("--dry-run")


def test_the_script_names_the_same_config_the_tests_and_docs_expect():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "cloudflare/wrangler.build.toml" in text
    # The relay config keeps previews off; the script must not imply otherwise.
    import tomllib
    config = tomllib.loads((ROOT / "cloudflare" / "wrangler.build.toml").read_text())
    assert config["preview_urls"] is False
    assert "--preview-alias" not in text
    docs = (ROOT / "docs" / "CLOUDFLARE_DEPLOYMENT.md").read_text(encoding="utf-8")
    assert "scripts/deploy_worker.sh" in docs


def test_ci_exercises_the_script_on_every_push():
    workflow = (ROOT / ".github" / "workflows" / "worker-build.yml").read_text(encoding="utf-8")
    assert "scripts/deploy_worker.sh" in workflow
    assert "WRANGLER_DRY_RUN" in workflow
