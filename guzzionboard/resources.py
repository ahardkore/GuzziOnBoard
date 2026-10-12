"""Where the app's files live - in a source checkout and in an installed build.

Everything the runtime reads off disk (the UI, the catalog, the XDF library,
the vendored driver bundle) or writes for the user (logs, export files, the
single-instance record) is resolved here, so exactly one module knows the
difference between ``git clone`` and the folder an installer produced.

The frozen layout is deliberately the *same shape* as the source tree:

    <bundle>/web/...                       web/index.html, web/app.js
    <bundle>/guzzionboard/catalog/...      ECU + vehicle definitions
    <bundle>/guzzionboard/xdfs/...         the XDF library
    <bundle>/vendor/guzzidiag/...          mirrored tool manifest, CDM bundle

That is why the rest of the code can keep using ``Path(__file__).parent``:
PyInstaller points ``__file__`` inside the bundle, so those relative paths
land in the right place without a special case. The two things that do *not*
survive freezing - a second Python interpreter for the checksum worker and
``Path.home()`` for user data - are handled explicitly below and in
:mod:`guzzionboard.checksums` / :mod:`guzzionboard.desktop`.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

#: The directory the rest of the app already uses for user state
#: (``~/.guzzionboard/sessions``, ``.../basemaps``, ``.../xdfs``, ...).
DATA_DIR_NAME = ".guzzionboard"

#: Overrides, for packagers, portable installs and tests.
HOME_ENV = "GUZZIONBOARD_HOME"
WEB_ENV = "GUZZIONBOARD_WEB"
VENDOR_ENV = "GUZZIONBOARD_VENDOR"

#: The name the installer and the build give the application.
APP_NAME = "GuzziOnBoard"

#: Console-mode helper executable that runs checksum plugins in their own
#: process. Keep in step with ``packaging/guzzionboard.spec``.
WORKER_EXECUTABLE = "GuzziOnBoard-worker"

#: Header the desktop window's bridge sets on every API call, proving it was
#: handed this launch's token. Lives here because both the HTTP layer
#: (:mod:`guzzionboard.server`) and the shell (:mod:`guzzionboard.desktop`)
#: have to agree on it, and neither should import the other for one string.
TOKEN_HEADER = "X-GuzziOnBoard-Token"


class BundleIncomplete(RuntimeError):
    """A build is missing files it must ship (bad or partial install)."""


def frozen() -> bool:
    """True inside a PyInstaller build (one-folder or one-file)."""
    return bool(getattr(sys, "frozen", False))


def bundle_root() -> Path:
    """The directory read-only application files were unpacked into."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return Path(__file__).resolve().parent.parent


def _resolve(env_name: str, *candidates: Path) -> Path | None:
    override = os.environ.get(env_name)
    if override:
        path = Path(override).expanduser()
        if path.is_dir():
            return path
        raise BundleIncomplete(f"{env_name} points at {path}, which is not a directory")
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return None


def web_root() -> Path:
    """The directory holding ``index.html`` and the UI's assets."""
    root = _resolve(WEB_ENV, bundle_root() / "web", bundle_root() / "guzzionboard" / "web")
    if root is None:
        raise BundleIncomplete(
            "the workstation UI (web/) is missing from this installation. "
            "Run the build again (packaging/build.py) or reinstall GuzziOnBoard."
        )
    return root


def vendor_root() -> Path:
    """Mirrored reference tooling: manifest, and the FTDI CDM bundle."""
    root = _resolve(VENDOR_ENV, bundle_root() / "vendor")
    return root or (bundle_root() / "vendor")


def driver_bundle_path() -> Path:
    """Where the WHQL FTDI CDM bundle lives, whether or not it is there."""
    return vendor_root() / "guzzidiag" / "tools" / "CDM-v2.12.36.20-WHQL-Certified.zip"


def driver_bundle_zip() -> Path | None:
    """The WHQL FTDI CDM bundle, if this build ships it."""
    path = driver_bundle_path()
    return path if path.is_file() else None


def worker_executable() -> Path | None:
    """The bundled console helper that isolates checksum plugins, if built."""
    if not frozen():
        return None
    suffix = ".exe" if os.name == "nt" else ""
    candidate = Path(sys.executable).with_name(WORKER_EXECUTABLE + suffix)
    if candidate.is_file():
        return candidate
    # one-file builds put everything in one directory; look beside the bundle
    other = bundle_root() / (WORKER_EXECUTABLE + suffix)
    return other if other.is_file() else None


# --------------------------------------------------------------- user state

def user_home() -> Path:
    """The user's home directory, in one place.

    Tests and portable installs move this rather than patching
    ``pathlib.Path.home`` itself.
    """
    return Path.home()


def data_root() -> Path:
    """Per-user state: sessions, basemaps, plugins, XDF additions, logs."""
    override = os.environ.get(HOME_ENV)
    if override:
        return Path(override).expanduser()
    return user_home() / DATA_DIR_NAME


def sessions_dir() -> Path:
    return data_root() / "sessions"


def logs_dir() -> Path:
    return data_root() / "logs"


def exports_dir() -> Path:
    """Where the desktop app writes what a browser would have downloaded."""
    return data_root() / "exports"


def instance_file() -> Path:
    """Record of the running instance, used to refuse a second one politely."""
    return data_root() / "desktop-instance.json"


def default_export_dir() -> Path:
    """The user's Downloads folder when it exists, else our own exports dir."""
    downloads = user_home() / "Downloads"
    return downloads if downloads.is_dir() else exports_dir()


def storage_dir() -> Path:
    """Webview profile directory (local storage: the remembered garage)."""
    return data_root() / "webview"


# ------------------------------------------------------------ file writing

#: Characters Windows refuses in a file name, plus the POSIX separator.
_UNSAFE = set('<>:"/\\|?*')

#: Device names Windows still reserves, even with an extension.
_RESERVED = {
    "con", "prn", "aux", "nul",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}


def safe_filename(name: str, *, fallback: str = "guzzionboard-export") -> str:
    """A file name that cannot escape the directory it is written into.

    The name usually arrives from the UI (a report, a tune, a converted log),
    so it is treated as untrusted: directories are stripped rather than
    sandboxed, control characters removed, Windows' reserved names and
    trailing dots/spaces neutralised, and the length capped.
    """
    candidate = str(name or "").replace("\\", "/")
    candidate = candidate.rsplit("/", 1)[-1]              # no directory part
    candidate = "".join(ch for ch in candidate if ch >= " " and ch not in _UNSAFE)
    candidate = candidate.strip(" .")
    if not candidate or candidate in (".", ".."):
        return fallback
    stem, dot, suffix = candidate.rpartition(".")
    if not dot or not stem:
        stem, suffix = candidate, ""
    else:
        suffix = "." + suffix
    if stem.lower() in _RESERVED:
        stem = f"_{stem}"
    keep = max(1, 120 - len(suffix))
    return f"{stem[:keep]}{suffix}"


def unique_path(directory: Path, name: str, *, fallback: str = "guzzionboard-export") -> Path:
    """``directory/name``, or the first free ``name-1``, ``name-2``, ...

    Exporting twice must never silently destroy the first export: these files
    are evidence (session logs, backups, built images) and overwriting one is
    data loss, not a convenience.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    safe = safe_filename(name, fallback=fallback)
    candidate = directory / safe
    if not candidate.exists():
        return candidate
    stem, _, suffix = safe.rpartition(".")
    if not stem:
        stem, suffix = safe, ""
    else:
        suffix = "." + suffix
    for index in range(1, 1000):
        candidate = directory / f"{stem}-{index}{suffix}"
        if not candidate.exists():
            return candidate
    raise BundleIncomplete(f"cannot find a free name for {safe} in {directory}")


def describe() -> dict:
    """What a support question needs to know, without any ECU data."""
    return {
        "app": APP_NAME,
        "frozen": frozen(),
        "bundle_root": str(bundle_root()),
        "web_root": str(web_root()) if _resolve(
            WEB_ENV, bundle_root() / "web", bundle_root() / "guzzionboard" / "web"
        ) else None,
        "data_root": str(data_root()),
        "exports": str(default_export_dir()),
        "python": sys.version.split()[0],
        "platform": sys.platform,
    }
