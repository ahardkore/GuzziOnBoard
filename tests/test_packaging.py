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


def test_the_frozen_folder_keeps_the_data_beside_the_executable():
    """The app finds its data relative to itself, so _internal/ would break it."""
    src = SPEC.read_text(encoding="utf-8")
    # One EXE per executable in the folder, and both must opt out of the
    # default hidden contents directory.
    assert src.count("contents_directory=\".\"") == 2
    assert "_internal" not in src


def test_a_misplaced_data_folder_is_reported_plainly(tmp_path):
    build = _load_build_module()
    folder = tmp_path / "GuzziOnBoard"
    (folder / "_internal" / "web").mkdir(parents=True)
    (folder / "_internal" / "web" / "index.html").write_text("x")
    suffix = ".exe" if __import__("sys").platform == "win32" else ""
    (folder / f"GuzziOnBoard{suffix}").write_text("")
    (folder / f"GuzziOnBoard-worker{suffix}").write_text("")
    with pytest.raises(SystemExit) as caught:
        build.check_artifact(folder)
    assert "contents_directory" in str(caught.value)


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


#: The [Files] flags Inno Setup 6 knows. An invented flag is a compile error
#: on the runner ("Parameter \"Flags\" includes an unknown flag"), which is a
#: slow way to find out - so the script is checked here first. Order is not
#: meaningful; this is the documented set, not every flag Inno 7 added.
INNO_FILE_FLAGS = {
    "32bit", "64bit", "allowunsafefiles", "comparetimestamp",
    "comparetimestampalways", "confirmoverwrite", "createallsubdirs",
    "deleteafterinstall", "dontcopy", "dontverifychecksum", "external",
    "fontisnttruetype", "ignoreversion", "nocliptargetpath", "nocompression",
    "noencryption", "onlyifdestfileexists", "onlyifdoesntexist",
    "overwritereadonly", "promptifolder", "readonly", "recursesubdirs",
    "replacesameversion", "restartreplace", "setntfscompression", "sharedfile",
    "skipifsourcedoesntexist", "solidbreak", "sortfilesbydate",
    "sortfilesbyname", "touch", "uninsalwaysuninstall", "uninsneveruninstall",
    "uninsremovereadonly",
}


def test_the_installer_only_uses_flags_the_compiler_has():
    """`skipifsilent` is a [Run] flag; in [Files] it aborted a real build."""
    import re

    body = INSTALLER.read_text(encoding="utf-8").partition("[Files]")[2]
    body = body.partition("\n[")[0]                       # the section only
    used = set()
    for line in body.splitlines():
        if line.lstrip().startswith(";"):
            continue
        for flags in re.findall(r"Flags:\s*([^;]+)", line):
            used.update(flags.split())
    assert used, "the [Files] section should declare flags"
    assert used <= INNO_FILE_FLAGS, f"unknown Inno Setup flags: {sorted(used - INNO_FILE_FLAGS)}"


def test_the_optional_bootstrapper_is_optional():
    src = INSTALLER.read_text(encoding="utf-8")
    assert "Flags: deleteafterinstall skipifsourcedoesntexist" in src
    # [Code] runs it from {tmp}; nothing may try to extract a dontcopy entry.
    assert "ExtractTemporaryFile" not in src
    # skipifsilent is a [Run] flag and belongs on the two [Run] lines, nowhere
    # near [Files]: that mistake is what aborted the first Windows build.
    files = src.partition("[Files]")[2].partition("\n[")[0]
    assert "skipifsilent" not in files
    assert src.count("skipifsilent") == 2


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


def test_a_macos_bundle_must_pass_its_own_self_test(tmp_path, monkeypatch, capsys):
    """The .app rearranges the folder, so only running it proves it works."""
    build = _load_build_module()
    app = tmp_path / "GuzziOnBoard.app"
    binary = app / "Contents" / "MacOS" / build.DIST_NAME
    binary.parent.mkdir(parents=True)
    binary.write_text("")
    folder = tmp_path / build.DIST_NAME
    folder.mkdir()
    ran = []

    def fake_call(command, env=None, **_):
        ran.append(command)
        transcript = Path(env["GOB_SELFTEST_LOG"])
        transcript.write_text("30 checks\n")
        return 0

    monkeypatch.setattr(build.subprocess, "call", fake_call)
    build.wrap_macos(folder, "9.9.9", selftest_bundle=True)
    assert ran == [[str(binary), "--selftest"]]
    assert "self-test: passed" in capsys.readouterr().out

    monkeypatch.setattr(build.subprocess, "call", lambda *a, **k: 1)
    with pytest.raises(SystemExit) as caught:
        build.wrap_macos(folder, "9.9.9", selftest_bundle=True)
    assert "do not ship it" in str(caught.value)


def test_the_workflow_keeps_the_self_test_transcripts():
    src = WORKFLOW.read_text(encoding="utf-8")
    # A macOS runner is the only place the .app can be run at all, so whatever
    # it says has to survive the job: the upload glob covers both the folder's
    # transcript and the bundle's (`macos-<arch>-app-selftest.log`).
    assert "dist/macos-*-selftest.log" in src
    assert "if-no-files-found: error" in src


def _load_build_module():
    """Import packaging/build.py (it is a script, not part of the package)."""
    spec = importlib.util.spec_from_file_location("gob_build", BUILD)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
