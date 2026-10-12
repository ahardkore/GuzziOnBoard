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


def test_the_frozen_folder_keeps_pyinstallers_contents_directory():
    """The default keeps the executable and the data directory from colliding."""
    src = SPEC.read_text(encoding="utf-8")
    # `GuzziOnBoard` (the executable) and `guzzionboard` (the data) cannot both
    # sit in the root of the same folder on a case-insensitive filesystem, and
    # macOS is one. The app reads from sys._MEIPASS, so it does not care.
    assert "contents_directory=" not in src
    assert "_internal (see guzzionboard/resources.py)" in src or "_internal/" in src


def test_the_artifact_check_follows_the_data_wherever_it_lands(tmp_path):
    """`_internal/` is the default and the flat layout is legal: both pass."""
    import sys as _sys

    build = _load_build_module()
    suffix = ".exe" if _sys.platform == "win32" else ""
    needed = {
        "web/index.html": "x",
        "web/desktop-bridge.js": "x",
        "guzzionboard/catalog/ecus/5am.json": "{}",
        "guzzionboard/xdfs/catalog.json": "{}",
    }
    for root_name in ("_internal", ""):
        folder = tmp_path / f"GuzziOnBoard{root_name or '-flat'}"
        root = folder / root_name if root_name else folder
        for relative, body in needed.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body)
        (folder / f"GuzziOnBoard{suffix}").write_text("")
        (folder / f"GuzziOnBoard-worker{suffix}").write_text("")
        build.check_artifact(folder)

    empty = tmp_path / "GuzziOnBoard-empty"
    empty.mkdir()
    (empty / f"GuzziOnBoard{suffix}").write_text("")
    (empty / f"GuzziOnBoard-worker{suffix}").write_text("")
    with pytest.raises(SystemExit) as caught:
        build.check_artifact(empty)
    assert "missing application data" in str(caught.value)


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
        # Shortcut icons come from the executable, which carries the icon and
        # is always at the root of the install; a path into the payload would
        # point at _internal/ and quietly give the shortcuts a blank icon.
        'IconFilename: "{app}\\{#AppExe}"',
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
    assert "innosetup" in src
    assert "action-gh-release" in src
    # Read-only everywhere, and the three publishing jobs ask for the one
    # permission publishing needs. Without it the build succeeds, the artifact
    # is uploaded, and the release step dies on "Resource not accessible by
    # integration" - a tag that builds three platforms and publishes no release.
    assert "permissions:\n  contents: read" in src
    assert src.count("permissions:\n      contents: write") == 3   # windows, linux, macos


def test_a_release_that_failed_to_publish_can_be_published_without_moving_the_tag():
    """Publishing is not only the tag push: a run that built and self-tested
    everything but could not write the release is repaired by dispatching this
    workflow at a branch carrying the fix and naming the tag. The tag stays
    where it is, and the build is the tag's own tree."""
    src = WORKFLOW.read_text(encoding="utf-8")
    assert "gh workflow run desktop-build.yml" in src              # documented where it is read
    assert "tag:" in src.split("workflow_dispatch:")[1]            # the input that names it
    assert src.count("ref: ${{ inputs.tag || github.ref }}") == 6   # every job builds that tag
    assert src.count("tag_name: ${{ inputs.tag || github.ref_name }}") == 3
    # A branch ref has no tag, so `release` alone must not be enough to publish:
    # softprops/action-gh-release would look for a release of the branch.
    assert src.count("inputs.release && inputs.tag != ''") == 3


def test_the_release_page_carries_the_checksums_and_the_transcripts():
    """What the workflow proves has to be readable next to the download: the
    installers and archives alone leave a user no way to check what they got."""
    src = WORKFLOW.read_text(encoding="utf-8")
    # three artifacts uploaded, three attached to the release
    assert src.count("dist/SHA256SUMS-*.txt") == 6
    assert src.count("dist/windows-*-selftest.log") == 2   # kept, and published
    assert src.count("dist/macos-*-selftest.log") == 2
    # Linux keeps its two transcripts by name (the build's, the install check's)
    # and publishes both through the glob.
    assert src.count("dist/linux-install-selftest.log") == 1
    assert src.count("dist/linux-*-selftest.log") == 1
    # Whichever publishing job creates the release first, the notes are on it.
    assert src.count("body: |") == 3


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


def test_a_real_install_is_checked_somewhere():
    """CI installs the setup, runs the installed app, and uninstalls it.

    The installer is the deliverable for Windows, so it cannot be the one
    thing nobody ever executes. The steps live in a script next to the .iss
    rather than in the workflow, which is why this test reads both.
    """
    script = ROOT / "packaging" / "installer" / "windows-install-check.ps1"
    assert script.is_file()
    body = script.read_text(encoding="utf-8")
    # Each of these is a claim the job makes; if one disappears, the job is
    # testing less than it says it is.
    for required in (
        "/VERYSILENT",                       # install without a wizard
        "Find-UninstallEntry",               # ask Windows where it went
        "--selftest",                        # run the *installed* application
        "--no-window",                       # ... and start it for real
        "/api/desktop/ping",                 # talking to its own API
        "GuzziOnBoard-worker.exe",           # the second executable shipped
        "All \\d+ checks passed",            # and read what it said
        "Stop-Process",                      # stop it again, cleanly
        "unins*.exe",                        # then uninstall it
        ".guzzionboard",                     # and check the data survived
        "::error title=",                    # failures are readable from the PR
    ):
        assert required in body, required
    # The uninstaller must not be assumed to finish when its process does.
    assert "UninstallTimeoutSeconds" in body

    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "windows-install-check.ps1" in workflow
    assert "needs: windows" in workflow       # it tests the built installer


@pytest.mark.skipif(not sys.platform.startswith("linux"),
                    reason="install.sh is the Linux launcher, and the check uses readlink -f")
def test_the_linux_install_script_installs_something_that_runs(tmp_path):
    """The Linux installer is install.sh, so it gets executed here.

    A stand-in executable does what the frozen application does when it is
    started: records itself in the user's data folder, serves the UI, and
    answers its own token-checked ping. Everything else - the generated
    script, the .desktop entry, the icon path, the launcher symlink, and the
    checks themselves - is the real thing.
    """
    import os

    build = _load_build_module()
    folder = tmp_path / "dist" / "GuzziOnBoard"
    icons = folder / "_internal" / "packaging" / "icons"
    icons.mkdir(parents=True)
    icons.joinpath("guzzionboard.png").write_bytes(
        (ROOT / "packaging" / "icons" / "guzzionboard.png").read_bytes()
    )

    stand_in = """#!/bin/sh
if [ "$1" = "--selftest" ]; then
  echo 'All 30 checks passed. This copy is usable.' > "$GOB_SELFTEST_LOG"
  exit 0
fi
if [ "$1" = "--no-window" ]; then
  exec python3 - <<'PYTHON'
import json, os
from http.server import BaseHTTPRequestHandler, HTTPServer

TOKEN = "test-token"
home = os.path.join(os.environ["HOME"], ".guzzionboard")
os.makedirs(os.path.join(home, "logs"), exist_ok=True)
with open(os.path.join(home, "logs", "desktop.log"), "w") as handle:
    print("the stand-in application started", file=handle)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/api/desktop/ping"):
            if self.headers.get("X-GuzziOnBoard-Token") != TOKEN:
                self.send_response(403)
                self.end_headers()
                return
            body = b'{"ok": true, "app": "GuzziOnBoard", "version": "9.9.9", "desktop": true}'
        else:
            body = b"<html><head><title>GuzziOnBoard</title></head><body></body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


server = HTTPServer(("127.0.0.1", 0), Handler)
port = server.server_address[1]
with open(os.path.join(home, "desktop-instance.json"), "w") as handle:
    json.dump({"pid": os.getpid(), "port": port, "token": TOKEN, "backend": "stand-in",
               "url": "http://127.0.0.1:%d/" % port, "version": "9.9.9",
               "started": 0.0, "data_root": home}, handle, indent=2)
server.serve_forever()
PYTHON
fi
echo "would open a window"
"""
    app = folder / "GuzziOnBoard"
    app.write_text(stand_in, encoding="utf-8")
    app.chmod(0o755)
    build.wrap_linux(folder, "9.9.9")

    check = ROOT / "packaging" / "installer" / "linux-install-check.sh"
    assert check.is_file()
    home = tmp_path / "home"
    home.mkdir()
    result = subprocess.run(
        ["sh", str(check), str(folder)],
        capture_output=True, text=True, timeout=300,
        env={**os.environ, "HOME": str(home)},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    launcher = home / ".local" / "bin" / "guzzionboard"
    assert launcher.is_symlink() and os.path.realpath(launcher) == str(app)
    menu = home / ".local" / "share" / "applications" / "guzzionboard.desktop"
    assert f"Exec={app}\n" in menu.read_text(encoding="utf-8")
    assert (home / ".local" / "share" / "icons" / "hicolor" / "256x256" /
            "apps" / "guzzionboard.png").is_file()
    # It ran, wrote where it should, and the check stopped it again.
    assert (home / ".guzzionboard" / "logs" / "desktop.log").is_file()
    assert "answered its own ping" in result.stdout


def test_the_documented_window_engine_matches_the_build():
    """Windows and macOS bundle pywebview. Linux does not, and the docs say so.

    Freezing a Linux window needs PyGObject and the WebKitGTK typelibs
    collected - PyInstaller has a Gtk hook but no WebKit2 typelib hook - so a
    one-line `pip install pywebview` would produce an app whose window fails
    when it is created. If somebody does that work, this test and
    docs/DESKTOP.md should change together.
    """
    workflow = WORKFLOW.read_text(encoding="utf-8")
    linux_job = workflow.partition("\n  linux:")[2].partition("\n  macos:")[0]
    assert linux_job, "the linux job should be in the workflow"
    assert "pywebview" not in linux_job
    assert "pip install pyinstaller pywebview" in workflow     # windows and macOS
    docs = (ROOT / "docs" / "DESKTOP.md").read_text(encoding="utf-8")
    assert "carries no window engine" in docs


def test_the_workflow_runs_the_install_checks():
    src = WORKFLOW.read_text(encoding="utf-8")
    assert "linux-install-check.sh" in src
    assert "windows-install-check.ps1" in src, "the Windows job installs the setup"


def _load_build_module():
    """Import packaging/build.py (it is a script, not part of the package)."""
    spec = importlib.util.spec_from_file_location("gob_build", BUILD)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
