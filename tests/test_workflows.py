"""Guard against accidentally concatenating separate GitHub workflows."""
from pathlib import Path


WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"


def test_workflows_have_one_top_level_mapping_each():
    for path in WORKFLOWS.glob("*.yml"):
        content = path.read_text(encoding="utf-8")
        for key in ("name:", "on:", "jobs:"):
            assert sum(line.startswith(key) for line in content.splitlines()) == 1, (path, key)


def test_ci_uses_node_22_for_worker_and_browser_tests():
    content = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
    assert "node-version: '22'" in content
    assert "pytest -q" in content
    assert "npx playwright test" in content


def test_python_test_jobs_install_virtual_can_dependency():
    for name in ("ci.yml", "desktop-build.yml"):
        assert "pip install -e '.[dev,hardware]'" in (WORKFLOWS / name).read_text(encoding="utf-8")


def test_desktop_release_jobs_bundle_hardware_dependencies():
    workflow = (WORKFLOWS / 'desktop-build.yml').read_text(encoding='utf-8')
    for name in ('windows', 'linux'):
        # Job ordering can evolve; isolate each top-level job by indentation.
        import re
        match = re.search(rf'^  {name}:\n(?:(?!^  [a-zA-Z0-9_-]+:).)*', workflow, re.M | re.S)
        assert match, name
        job = match.group()
        assert 'pyserial python-can' in job
        assert 'packaging/build.py --hardware ' in job
    mac = workflow.split('\n  macos:', 1)[1]
    assert 'pyserial python-can' in mac
    assert 'packaging/build.py --hardware ' in mac
