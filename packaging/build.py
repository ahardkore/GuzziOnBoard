#!/usr/bin/env python3
"""Build the installable GuzziOnBoard desktop application.

    python3 packaging/build.py                  # build for this machine
    python3 packaging/build.py --installer      # ... and the Windows installer
    python3 packaging/build.py --portable-zip   # ... and a portable archive
    python3 packaging/build.py --skip-selftest  # do not run the built app

What it does, in order:

1. runs PyInstaller over ``packaging/guzzionboard.spec`` (one folder, two
   executables: the windowed app and the isolated checksum worker),
2. wraps the result for the platform - a ``.app`` bundle on macOS,
   a ``.desktop`` entry + installer script on Linux,
3. runs the *built* application's ``--selftest`` and fails the build if the
   artifact is not actually usable (this is the check that catches a data file
   that never made it into the bundle),
4. writes ``SHA256SUMS`` next to the artifacts.

The installer (Windows) is built by Inno Setup from
``packaging/installer/guzzionboard.iss``; CI does exactly what you get here.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import platform
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DIST_NAME = "GuzziOnBoard"


def package_version() -> str:
    text = (ROOT / "guzzionboard" / "__init__.py").read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith("__version__"):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("cannot read the version from guzzionboard/__init__.py")


def platform_tag() -> str:
    system = {"Windows": "windows", "Darwin": "macos", "Linux": "linux"}.get(
        platform.system(), platform.system().lower()
    )
    machine = platform.machine().lower() or "unknown"
    machine = {"amd64": "x64", "x86_64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(
        machine, machine
    )
    return f"{system}-{machine}"


def run(command: list[str], *, env: dict | None = None, cwd: Path | None = None) -> int:
    print("+", " ".join(str(part) for part in command), flush=True)
    return subprocess.call(command, env=env, cwd=str(cwd) if cwd else None)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ------------------------------------------------------------------ building

def build_pyinstaller(dist: Path, work: Path, version: str, *, hardware: bool) -> Path:
    env = dict(os.environ)
    env["GOB_VERSION"] = version
    if hardware:
        env["GOB_WITH_HARDWARE"] = "1"
    command = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--log-level=WARN",
        "--distpath", str(dist), "--workpath", str(work),
        str(HERE / "guzzionboard.spec"),
    ]
    if run(command, env=env) != 0:
        raise SystemExit("PyInstaller failed")
    folder = dist / DIST_NAME
    if not folder.is_dir():
        raise SystemExit(f"PyInstaller produced no {folder}")
    return folder


def executable(folder: Path, name: str) -> Path:
    suffix = ".exe" if sys.platform == "win32" else ""
    return folder / f"{name}{suffix}"


def check_artifact(folder: Path, *, expect_worker: bool = True) -> None:
    """The files a build must contain, checked before anyone ships it."""
    app = executable(folder, DIST_NAME)
    if not app.is_file():
        raise SystemExit(f"missing application executable: {app}")
    if expect_worker and not executable(folder, f"{DIST_NAME}-worker").is_file():
        raise SystemExit("missing the isolated checksum worker executable")
    # PyInstaller's default contents directory; the frozen app resolves its
    # data from sys._MEIPASS, which is this directory inside such a build.
    root = folder / "_internal" if (folder / "_internal").is_dir() else folder
    for relative in ("web/index.html", "web/desktop-bridge.js",
                     "guzzionboard/catalog/ecus/5am.json",
                     "guzzionboard/xdfs/catalog.json"):
        if not (root / relative).exists():
            raise SystemExit(f"missing application data: {relative}")


def selftest(folder: Path, *, enabled: bool) -> Path | None:
    """Run the built app's own installation check; return its transcript."""
    if not enabled:
        return None
    app = executable(folder, DIST_NAME)
    # Beside the artifact, never inside it: the shipped folder is the app, and
    # a stale build log has no business being installed on someone's laptop.
    transcript = folder.parent / f"{platform_tag()}-selftest.log"
    env = dict(os.environ)
    env["GOB_SELFTEST_LOG"] = str(transcript)
    env["GUZZIONBOARD_HOME"] = str(Path(work_dir_for_run(folder)) / "selftest-data")
    print(f"+ {app} --selftest", flush=True)
    code = subprocess.call([str(app), "--selftest"], env=env)
    text = transcript.read_text(encoding="utf-8", errors="replace") if transcript.is_file() else ""
    # Print whatever the artifact said: a windowed build has no console, so
    # the transcript file is the only place its output can be read from.
    if text:
        print(text.rstrip())
    if code != 0:
        raise SystemExit(
            f"the built application failed its self-test (exit {code}); "
            "do not ship this artifact"
        )
    print("  built application self-test: passed")
    return transcript if transcript.is_file() else None


def work_dir_for_run(folder: Path) -> Path:
    return folder.parent


# ------------------------------------------------------------------ wrapping

def wrap_macos(folder: Path, version: str, *, selftest_bundle: bool = False) -> None:
    """PyInstaller's BUNDLE already made the .app; report it, and check it.

    The bundle is not the same folder as the one PyInstaller wrote: BUNDLE
    rearranges everything into ``Contents/`` and cross-links it back together,
    so a folder build that passes proves nothing about the .app. Running the
    bundle's own binary with ``--selftest`` is the only cheap way to know the
    .app can actually find its data.
    """
    app = folder.parent / f"{DIST_NAME}.app"
    if not app.exists():
        print("  note: no .app bundle was produced (was BUNDLE in the spec skipped?)")
        return
    print(f"  macOS application bundle: {app}")
    if not selftest_bundle:
        return
    binary = app / "Contents" / "MacOS" / DIST_NAME
    env = dict(os.environ)
    transcript = folder.parent / f"{platform_tag()}-app-selftest.log"
    env["GOB_SELFTEST_LOG"] = str(transcript)
    env["GUZZIONBOARD_HOME"] = str(Path(work_dir_for_run(folder)) / "selftest-data")
    print(f"+ {binary} --selftest", flush=True)
    code = subprocess.call([str(binary), "--selftest"], env=env)
    text = transcript.read_text(encoding="utf-8", errors="replace") if transcript.is_file() else ""
    if text:
        print(text.rstrip())
    if code != 0:
        raise SystemExit(
            f"the .app bundle failed its self-test (exit {code}); do not ship it"
        )
    print("  .app bundle self-test: passed")


def wrap_linux(folder: Path, version: str) -> Path:
    """A launcher and a .desktop entry the user can install without root."""
    install = folder / "install.sh"
    install.write_text(
        f"""#!/bin/sh
# Install GuzziOnBoard {version} for the current user (no root needed).
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
PREFIX="${{HOME}}/.local"
mkdir -p "$PREFIX/bin" "$PREFIX/share/applications" "$PREFIX/share/icons/hicolor/256x256/apps"
ln -sf "$HERE/{DIST_NAME}" "$PREFIX/bin/guzzionboard"
cp -f "$HERE/packaging/icons/guzzionboard.png" \\
      "$PREFIX/share/icons/hicolor/256x256/apps/guzzionboard.png"
sed "s|@APPDIR@|$HERE|g" "$HERE/guzzionboard.desktop.in" > \\
      "$PREFIX/share/applications/guzzionboard.desktop"
update-desktop-database "$PREFIX/share/applications" 2>/dev/null || true
echo "Installed. Start 'guzzionboard' from your menu or a terminal."
echo "Remove with: rm -f ~/.local/bin/guzzionboard \\\\"
echo "  ~/.local/share/applications/guzzionboard.desktop"
""",
        encoding="utf-8",
    )
    install.chmod(0o755)
    desktop = folder / "guzzionboard.desktop.in"
    desktop.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={DIST_NAME}\n"
        "Comment=Diagnostic workstation for Moto Guzzi motorcycles\n"
        "Exec=@APPDIR@/" + DIST_NAME + "\n"
        "Icon=guzzionboard\n"
        "Terminal=false\n"
        "Categories=Utility;Engineering;\n"
        "Keywords=ecu;diagnostics;motorcycle;moto guzzi;\n"
        "StartupWMClass=guzzionboard\n",
        encoding="utf-8",
    )
    print(f"  Linux launcher files: {install.name}, {desktop.name}")
    return install


def build_installer(dist: Path, version: str, *, iscc: str | None) -> Path | None:
    """Run Inno Setup over the packaged folder (Windows only)."""
    if platform.system() != "Windows":
        print("  note: the inno-setup installer is Windows-only; skipping")
        return None
    script = HERE / "installer" / "guzzionboard.iss"
    if not script.is_file():
        raise SystemExit(f"missing installer script: {script}")
    compiler = find_iscc(iscc)
    if compiler is None:
        print(
            "  note: Inno Setup was not found, so no installer was built.\n"
            "        Install it (winget install JRSoftware.InnoSetup) or pass --iscc PATH."
        )
        return None
    app_dir = dist / DIST_NAME
    out_dir = dist
    code = run([
        compiler,
        f"/DAppVersion={version}",
        f"/DAppDir={app_dir}",
        f"/DAppIcon={HERE / 'icons' / 'guzzionboard.ico'}",
        f"/DOutputDir={out_dir}",
        f"/DSourceRoot={ROOT}",
        str(script),
    ])
    if code != 0:
        raise SystemExit("Inno Setup failed")
    produced = sorted(dist.glob("*setup*.exe"))
    if not produced:
        raise SystemExit("Inno Setup reported success but produced no installer")
    installer = produced[-1]
    print(f"  installer: {installer}")
    return installer


def find_iscc(explicit: str | None) -> str | None:
    if explicit:
        return explicit
    found = shutil.which("iscc") or shutil.which("ISCC.exe")
    if found:
        return found
    for guess in (
        r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        r"C:\Program Files\Inno Setup 6\ISCC.exe",
    ):
        if Path(guess).is_file():
            return guess
    return None


def archive_app(app: Path, version: str) -> Path:
    """Zip a macOS .app bundle without flattening its framework links."""
    target = app.parent / f"{DIST_NAME}-{version}-{platform_tag()}.zip"
    print(f"  macOS bundle archive: {target}")
    command = (["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(app), str(target)]
               if shutil.which("ditto") else
               ["zip", "-q", "-r", "-y", str(target), app.name])
    if run(command) != 0:
        raise SystemExit("could not archive the macOS bundle")
    return target


def portable_zip(folder: Path, version: str) -> Path:
    """A zip of the folder build: the app without an installer.

    On macOS the archive is made with ``ditto`` when it is available, because a
    .app bundle contains symbolic links (Python.framework) that a plain zip
    would flatten into copies - or break entirely.
    """
    target = folder.parent / f"{DIST_NAME}-{version}-{platform_tag()}-portable.zip"
    print(f"  portable archive: {target}")
    if platform.system() == "Darwin" and shutil.which("ditto"):
        if run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent",
                str(folder), str(target)]) != 0:
            raise SystemExit("ditto failed to archive the application")
        return target
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(folder.rglob("*")):
            if path.is_file() and path.suffix != ".log":
                archive.write(path, Path(folder.name) / path.relative_to(folder))
    return target


def write_checksums(dist: Path, artifacts: list[Path]) -> Path:
    lines = []
    for artifact in artifacts:
        if artifact and artifact.is_file():
            lines.append(f"{sha256(artifact)}  {artifact.name}")
    path = dist / f"SHA256SUMS-{platform_tag()}.txt"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  checksums: {path}")
    for line in lines:
        print(f"    {line}")
    return path


# ----------------------------------------------------------------------- cli

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--version", default=None, help="version to stamp (default: the package's)")
    parser.add_argument("--dist", default=str(ROOT / "dist"), help="output directory")
    parser.add_argument("--work", default=str(ROOT / "build" / "pyinstaller"),
                        help="PyInstaller work directory")
    parser.add_argument("--hardware", action="store_true",
                        help="bundle pyserial and python-can (needs them installed)")
    parser.add_argument("--installer", action="store_true",
                        help="also build the Inno Setup installer (Windows)")
    parser.add_argument("--iscc", default=None, help="path to ISCC.exe")
    parser.add_argument("--portable-zip", action="store_true",
                        help="also write a portable .zip of the folder build")
    parser.add_argument("--skip-selftest", action="store_true",
                        help="do not run the built application's self-test")
    args = parser.parse_args(argv)

    if shutil.which("pyinstaller") is None and not _pyinstaller_importable():
        print("PyInstaller is required:  pip install pyinstaller", file=sys.stderr)
        return 2

    version = args.version or package_version()
    dist = Path(args.dist).resolve()
    work = Path(args.work).resolve()
    dist.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)

    print(f"GuzziOnBoard {version} — building for {platform_tag()}")
    folder = build_pyinstaller(dist, work, version, hardware=args.hardware)
    check_artifact(folder)
    print(f"  application folder: {folder}")

    if platform.system() == "Darwin":
        wrap_macos(folder, version, selftest_bundle=not args.skip_selftest)
    elif platform.system() == "Linux":
        wrap_linux(folder, version)

    artifacts: list[Path] = []
    selftest(folder, enabled=not args.skip_selftest)
    if args.portable_zip:
        if platform.system() == "Darwin" and (dist / f"{DIST_NAME}.app").is_dir():
            artifacts.append(archive_app(dist / f"{DIST_NAME}.app", version))
        artifacts.append(portable_zip(folder, version))
    if args.installer:
        installer = build_installer(dist, version, iscc=args.iscc)
        if installer:
            artifacts.append(installer)
    write_checksums(dist, artifacts)
    print("\ndone.")
    return 0


def _pyinstaller_importable() -> bool:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        return False
    return True


if __name__ == "__main__":
    raise SystemExit(main())
