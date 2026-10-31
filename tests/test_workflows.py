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
