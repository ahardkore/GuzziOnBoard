"""The console entry point: `guzzionboard` and `python -m guzzionboard`."""
import subprocess
import sys

from guzzionboard.__main__ import build_parser


def test_parser_knows_its_flags():
    args = build_parser().parse_args(["--host", "0.0.0.0", "--port", "9000",
                                      "--no-record"])
    assert args.host == "0.0.0.0" and args.port == 9000 and args.no_record


def test_parser_defaults_stay_local():
    args = build_parser().parse_args([])
    assert args.host == "127.0.0.1"      # a tool for one laptop, one bike
    assert args.port == 8000 and not args.no_record


def test_python_dash_m_help_works():
    out = subprocess.run(
        [sys.executable, "-m", "guzzionboard", "--help"],
        capture_output=True, text=True, timeout=30,
    )
    assert out.returncode == 0
    assert "simulator mode" in out.stdout.lower()
    assert "hardware" in out.stdout.lower()


def test_console_script_is_registered():
    src = open("pyproject.toml", encoding="utf-8").read()
    assert 'guzzionboard = "guzzionboard.__main__:main"' in src


# --------------------------------------------------------- the desktop build
#
# These are the parts of "it is an installed desktop application" that a test
# can check without a Windows machine: that the build recipe carries what the
# app reads at runtime, that the two entry points are wired to the right
# modules, and that the installer script describes a real installation.

import importlib
import pytest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "packaging" / "guzzionboard.spec"
INSTALLER = ROOT / "packaging" / "installer" / "guzzionboard.iss"
BUILD = ROOT / "packaging" / "build.py"
WORKFLOW = ROOT / ".github" / "workflows" / "desktop-build.yml"


def test_desktop_entry_point_is_registered():
    src = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'guzzionboard-desktop = "guzzionboard.desktop:main"' in src
    assert 'desktop = ["pywebview>=5.0"]' in src


def test_dash_desktop_hands_over_to_the_desktop_shell(monkeypatch):
    from guzzionboard.__main__ import main as console_main

    captured: dict = {}

    def fake_desktop_main(argv):
        captured["argv"] = argv
        return 0

    monkeypatch.setattr("guzzionboard.desktop.main", fake_desktop_main)
    assert console_main(["--desktop", "--port", "8123", "--host", "127.0.0.1"]) == 0
    assert "--port=8123" in captured["argv"] and "--desktop" not in captured["argv"]


def test_dash_selftest_hands_over_to_the_installation_check(monkeypatch):
    from guzzionboard.__main__ import main as console_main

    captured: dict = {}

    def fake_desktop_main(argv):
        captured["argv"] = argv
        return 0

    monkeypatch.setattr("guzzionboard.desktop.main", fake_desktop_main)
    assert console_main(["--selftest"]) == 0
    assert captured["argv"] == ["--selftest", "--host=127.0.0.1"]


def test_the_spec_ships_everything_the_runtime_reads():
    src = SPEC.read_text(encoding="utf-8")
    for relative in ('"web"', '"guzzionboard/catalog"', '"guzzionboard/xdfs"', '"vendor"'):
        assert relative in src, relative
    assert "packaging/icons" in src


def test_the_spec_builds_the_workstation_and_the_worker():
    src = SPEC.read_text(encoding="utf-8")
    assert 'name=f"{DIST_NAME}-worker"' in src
    assert "console=True" in src          # the worker needs stdout for its protocol
    assert "console=False" in src         # the application must not open a console
    assert "checksum_worker.py" in src    # built from source: stdlib-only, no data
    assert "BUNDLE(" in src               # macOS gets a real .app


def test_the_worker_entry_is_isolated_from_the_application():
    """A worker that dragged the workstation in would be a second app, not a filter."""
    import re

    source = SPEC.read_text(encoding="utf-8")
    match = re.search(r"worker_analysis = Analysis\(\n(.*?)\n\)", source, re.S)
    assert match, "the spec builds a worker analysis"
    analysis = match.group(1)
    assert "datas=[]" in analysis
    assert "entry_app" not in analysis
    assert "checksum_worker.py" in analysis


def test_installer_script_describes_a_real_installation():
    src = INSTALLER.read_text(encoding="utf-8")
    for required in (
        "AppId={{",                      # upgrades find the same installation
        "DefaultDirName={autopf}",
        "PrivilegesRequired=lowest",     # no administrator prompt for a garage tool
        "MinVersion=10.0.17763",
        "OutputBaseFilename=GuzziOnBoard-{#AppVersion}-setup",
        "UninstallDisplayIcon",
        "SetupIconFile",
        "AppDir}\\*",                    # the packaged folder is the payload
        "guzzionboard.ico",
    ):
        assert required in src, required
    assert "--selftest" in src           # a shortcut that checks the install
    assert "WebView2" in src             # the window engine is handled
    # The user's own data is evidence (backups, base maps, session logs), so
    # no install or uninstall directive may touch it - only the message the
    # uninstaller shows may mention where it lives.
    directives = "\n".join(
        line for line in src.splitlines() if not line.lstrip().startswith(";")
    )
    body, _, code = directives.partition("[Code]")
    assert ".guzzionboard" not in body          # nothing installs or deletes there
    assert "were kept" in code


def test_build_checks_the_artifact_it_produced(tmp_path, monkeypatch):
    build = _load_build_module()
    folder = tmp_path / "GuzziOnBoard"
    (folder / "web").mkdir(parents=True)
    (folder / "web" / "index.html").write_text("x")
    (folder / "web" / "desktop-bridge.js").write_text("x")
    (folder / "guzzionboard" / "catalog" / "ecus").mkdir(parents=True)
    (folder / "guzzionboard" / "catalog" / "ecus" / "5am.json").write_text("{}")
    (folder / "guzzionboard" / "xdfs").mkdir(parents=True)
    (folder / "guzzionboard" / "xdfs" / "catalog.json").write_text("{}")
    suffix = ".exe" if __import__("sys").platform == "win32" else ""
    (folder / f"GuzziOnBoard{suffix}").write_text("")
    (folder / f"GuzziOnBoard-worker{suffix}").write_text("")

    build.check_artifact(folder)                      # complete: accepted

    (folder / "guzzionboard" / "xdfs" / "catalog.json").unlink()
    try:
        build.check_artifact(folder)
    except SystemExit as exc:
        assert "xdfs" in str(exc)
    else:
        raise AssertionError("a build with no XDF library must be refused")

    with pytest.raises(SystemExit):
        build.check_artifact(tmp_path / "nothing-here")


def test_build_names_artifacts_by_platform_and_version(tmp_path):
    build = _load_build_module()
    assert build.platform_tag().count("-") == 1
    folder = tmp_path / "GuzziOnBoard"
    folder.mkdir()
    (folder / "app").write_text("payload")
    archive = build.portable_zip(folder, "9.9.9")
    assert archive.name == f"GuzziOnBoard-9.9.9-{build.platform_tag()}-portable.zip"
    with zipfile.ZipFile(archive) as opened:
        assert opened.namelist() == ["GuzziOnBoard/app"]

    sums = build.write_checksums(tmp_path, [archive])
    line = sums.read_text(encoding="utf-8").strip()
    assert line.endswith(archive.name)
    assert len(line.split()[0]) == 64


def test_build_reads_the_version_from_the_package():
    build = _load_build_module()
    import guzzionboard

    assert build.package_version() == guzzionboard.__version__


def test_the_release_workflow_builds_and_verifies_every_platform():
    src = WORKFLOW.read_text(encoding="utf-8")
    assert "windows-latest" in src and "ubuntu-latest" in src and "macos-latest" in src
    assert src.count("packaging/build.py") == 3          # one per platform
    assert "tags: ['v*']" in src                         # a tag is what releases
    assert "permissions:\n  contents: read" in src       # the release job asks for more
    assert "innosetup" in src
    assert "action-gh-release" in src


def _load_build_module():
    """Import packaging/build.py (it is a script, not part of the package)."""
    spec = importlib.util.spec_from_file_location("gob_build", BUILD)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
