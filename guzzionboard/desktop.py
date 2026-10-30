"""The desktop application: one window, one loopback server, one workstation.

``python -m guzzionboard`` hands a browser the workstation's page. This module
is the version that does not need a browser: it binds the same stdlib HTTP
server to loopback, opens a native window on it (pywebview, the platform's own
webview engine - WebView2 on Windows, WKWebView on macOS, WebKitGTK/Qt
elsewhere), and owns the process the way a desktop program should.

Three things a browser tab cannot do, and the only three this shell adds:

* **Files.** Downloads land where the app says (``--export-dir``, default your
  Downloads folder), through an explicit endpoint, instead of depending on a
  renderer honouring ``a.download`` on a blob URL.
* **Printing.** Webviews do not implement ``window.print()`` consistently, so
  "print this view" writes a self-contained snapshot next to your exports and
  opens it in your real browser - where Ctrl+P works.
* **Politeness.** A second launch raises the window that already exists rather
  than starting a second workstation that would fight over the adapter port,
  and closing a window while a flash read is in flight asks first.

Everything else - the catalog, the safety gate, the protocol stack, the UI -
is the same code the browser version runs. Nothing ECU-facing is implemented
here, and nothing here can bypass the safety gate: the window talks to the
same HTTP API on loopback, with the same guards, plus a per-launch token that
stops any other page on the machine from driving the bike through that port.

The window is optional at every level. No pywebview, or ``--browser``, or a
headless machine: the server still runs and the app opens the page in the
system browser (``--no-window`` skips even that). This is why the installed
build is useful even on a machine where the webview engine is missing.
"""
from __future__ import annotations

import argparse
import http.client
import json
import os
import secrets
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from dataclasses import asdict, dataclass, field
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from . import resources
from .storage import atomic_write

#: Renderer names pywebview accepts, for ``--gui``.
GUI_CHOICES = ("edgechromium", "cocoa", "gtk", "qt", "mshtml", "cef")

#: Addresses that keep the app to this machine. Anything else is an explicit
#: request to be reachable from the network.
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")

DEFAULT_WINDOW = (1360, 900)
MINIMUM_WINDOW = (1024, 700)

#: How long a launch waits for the window to say it is on screen before it
#: opens the workstation in the browser instead. pywebview starts the window
#: on a private GUI thread; if that thread dies or stalls, no Python code of
#: ours is running any more and nothing else would ever happen. The watchdog
#: that uses this is the operator's way out of exactly that.
WINDOW_SHOWN_TIMEOUT = 25.0

#: The oldest WebView2 runtime pywebview accepts for the Edge Chromium
#: renderer (``webview/platforms/winforms.py`` enforces the same floor).
#: Older than this and it silently falls back to the MSHTML/IE engine,
#: which cannot run the workstation's UI at all.
MINIMUM_WEBVIEW2 = "86.0.622.0"


def _webview2_build() -> str | None:
    """The installed WebView2 runtime's version string, or ``None``.

    The same registry value the installer and pywebview look at. Checked
    from the main thread, before any window exists, because a missing
    runtime found later kills the process from a thread whose exceptions
    cannot be caught.
    """
    if sys.platform != "win32":              # pragma: no cover - win32 only
        return None
    try:
        import winreg                        # noqa: PLC0415 - win32 only
    except ImportError:                      # pragma: no cover - defensive
        return None
    clients = (
        r"SOFTWARE\Microsoft\EdgeUpdate\Clients"
        r"\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    )
    for hive, view in (
        (winreg.HKEY_CURRENT_USER, 0),
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY),
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY),
    ):
        try:
            with winreg.OpenKey(hive, clients, 0, winreg.KEY_READ | view) as key:
                build, _ = winreg.QueryValueEx(key, "pv")
            if build:
                return str(build)
        except OSError:
            continue
    return None


def _version_tuple(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in str(text).split(".") if part.isdigit())


def _hook_dotnet_unhandled() -> None:
    """Log .NET exceptions that would otherwise kill the process silently.

    pywebview runs the window on a .NET thread; an exception there (0.4.0:
    a PNG handed to ``System.Drawing.Icon``) tears the process down with
    exit code 0xE0434352 and no Python traceback, because no Python frame is
    on that thread. ``AppDomain.UnhandledException`` runs before the
    teardown, so the exception at least reaches desktop.log - the difference
    between a bug report and a shrug.
    """
    if sys.platform != "win32":              # pragma: no cover - win32 only
        return
    try:
        import clr                           # noqa: F401,PLC0415 - present if the engine loaded
        import System

        def on_unhandled(sender, args) -> None:
            try:
                print(
                    f".NET unhandled exception on the window thread: "
                    f"{args.ExceptionObject}",
                    file=sys.stderr,
                )
            except Exception:                # pragma: no cover - last words only
                pass

        System.AppDomain.CurrentDomain.UnhandledException += on_unhandled
    except Exception:                        # pragma: no cover - diagnostic only
        pass


class DesktopError(RuntimeError):
    """The shell cannot start (bad options, port taken, broken install)."""


class AlreadyRunning(DesktopError):
    """Another GuzziOnBoard owns this user's port; it was told to come forward."""

    def __init__(self, instance: "Instance", focused: bool) -> None:
        super().__init__(
            "GuzziOnBoard is already running"
            + ("; its window was brought forward." if focused else
               f"; it is serving {instance.url}")
        )
        self.instance = instance
        self.focused = focused


# --------------------------------------------------------------- the window

class Backend:
    """How the UI is being shown: a native window, or the system browser."""

    def __init__(self, kind: str, renderer: str = "", detail: str = "") -> None:
        self.kind = kind              # "window" | "browser"
        self.renderer = renderer
        self.detail = detail

    @property
    def native(self) -> bool:
        return self.kind == "window"

    def as_dict(self) -> dict:
        return {"kind": self.kind, "renderer": self.renderer, "detail": self.detail}


def load_webview():
    """Import pywebview, or explain why the browser fallback is in use."""
    try:
        import webview  # noqa: PLC0415 - optional dependency, probed at runtime
    except Exception as exc:              # pragma: no cover - depends on install
        return None, f"{type(exc).__name__}: {exc}"
    return webview, ""


def choose_backend(*, prefer_browser: bool = False, gui: str | None = None) -> tuple[Backend, object | None]:
    """Pick a backend without starting anything."""
    if prefer_browser:
        return Backend("browser", "", "asked for the browser (--browser)"), None
    webview, error = load_webview()
    if webview is None:
        return (
            Backend("browser", "", f"no window backend available ({error})"),
            None,
        )
    return Backend("window", gui or getattr(webview, "renderer", "") or "", ""), webview


# --------------------------------------------------------- the running copy

@dataclass
class Instance:
    """What one running copy of the app records about itself."""

    pid: int
    port: int
    token: str
    backend: str
    url: str
    version: str
    started: float
    data_root: str = ""

    def as_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict) -> "Instance | None":
        try:
            return cls(
                pid=int(payload["pid"]),
                port=int(payload["port"]),
                token=str(payload["token"]),
                backend=str(payload.get("backend", "")),
                url=str(payload.get("url", "")),
                version=str(payload.get("version", "")),
                started=float(payload.get("started", 0)),
                data_root=str(payload.get("data_root", "")),
            )
        except (KeyError, TypeError, ValueError):
            return None


class InstanceDirectory:
    """The single-instance record, and the check that keeps it honest.

    A file is not proof of anything: the recorded process may be gone, or the
    port may belong to something else now. So the record is only believed
    after the port answers the app's own ping with the recorded token - and a
    record that fails that test is deleted, because a crashed app must never
    lock the operator out of the next launch.
    """

    def __init__(self, path: Path | None = None, *, timeout: float = 1.5) -> None:
        self.path = Path(path) if path else resources.instance_file()
        self.timeout = timeout

    # -- storage ---------------------------------------------------------
    def read(self) -> Instance | None:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return Instance.from_dict(payload) if isinstance(payload, dict) else None

    def write(self, instance: Instance) -> None:
        atomic_write(self.path, json.dumps(instance.as_dict(), indent=2).encode("utf-8"))
        try:
            os.chmod(self.path, 0o600)     # the token is in here
        except OSError:                    # pragma: no cover - Windows ignores modes
            pass

    def clear(self, *, token: str | None = None) -> None:
        """Remove the record, but never someone else's."""
        current = self.read()
        if token and current is not None and current.token != token:
            return
        try:
            self.path.unlink(missing_ok=True)
        except OSError:                     # pragma: no cover - unlikely
            pass

    # -- liveness --------------------------------------------------------
    def live(self) -> Instance | None:
        """The running copy, or ``None`` (clearing a stale record)."""
        instance = self.read()
        if instance is None:
            return None
        if self.probe(instance):
            return instance
        self.clear()
        return None

    def probe(self, instance: Instance) -> bool:
        connection = None
        try:
            connection = http.client.HTTPConnection(
                "127.0.0.1", instance.port, timeout=self.timeout
            )
            connection.request(
                "GET",
                "/api/desktop/ping",
                headers={
                    "Host": f"127.0.0.1:{instance.port}",
                    resources.TOKEN_HEADER: instance.token,
                },
            )
            response = connection.getresponse()
            body = response.read()
            if response.status != 200:
                return False
            payload = json.loads(body.decode("utf-8"))
            return bool(payload.get("ok")) and payload.get("app") == resources.APP_NAME
        except (OSError, ValueError, http.client.HTTPException):
            return False
        finally:
            if connection is not None:
                connection.close()

    def ask_to_raise(self, instance: Instance) -> dict:
        """Tell the running copy to come forward, and get back its URL."""
        connection = None
        try:
            connection = http.client.HTTPConnection(
                "127.0.0.1", instance.port, timeout=max(self.timeout, 3.0)
            )
            connection.request(
                "POST",
                "/api/desktop/raise",
                body=b"{}",
                headers={
                    "Host": f"127.0.0.1:{instance.port}",
                    "Content-Type": "application/json",
                    resources.TOKEN_HEADER: instance.token,
                },
            )
            response = connection.getresponse()
            payload = json.loads(response.read().decode("utf-8") or "{}")
            return payload if isinstance(payload, dict) else {}
        except (OSError, ValueError, http.client.HTTPException):
            return {}
        finally:
            if connection is not None:
                connection.close()


def _open_in_system(path: Path) -> bool:
    """Hand a file or folder to the operating system."""
    try:
        if os.name == "nt":
            os.startfile(str(path))          # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(
                ["open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        else:
            subprocess.Popen(
                ["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        return True
    except (OSError, AttributeError):
        return False


def open_url(url: str) -> bool:
    """Open an http/https URL in the user's browser."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return False
    try:
        return bool(webbrowser.open(url))
    except Exception:                        # pragma: no cover - browser layer
        return False


# -------------------------------------------------------------- the exports

class ExportDesk:
    """Where the files a browser would have downloaded end up."""

    def __init__(self, directory: Path | str | None = None) -> None:
        # Absolute, always: a window launched from a shortcut has a working
        # directory nobody chose, so a relative path would put the user's
        # reports somewhere unexpected.
        self.directory = (
            Path(directory).expanduser().absolute() if directory
            else resources.default_export_dir()
        )

    def write_text(self, name: str, text: str) -> dict:
        path = resources.unique_path(self.directory, name)
        atomic_write(path, text.encode("utf-8"))
        return {
            "name": path.name,
            "path": str(path),
            "dir": str(path.parent),
            "bytes": len(text.encode("utf-8")),
            "note": (
                "Written next to your other exports; an existing file is never "
                "overwritten - a second export gets a -1 suffix."
            ),
        }

    def write_binary(self, name: str, data: bytes) -> dict:
        """Save a bounded binary export without replacing an existing file."""
        if not isinstance(data, bytes) or len(data) > 1024 * 1024:
            raise ValueError("binary export must be bytes and no larger than 1 MiB")
        for _ in range(1000):
            path = resources.unique_path(self.directory, name)
            try:
                with path.open("xb") as output:
                    try:
                        output.write(data)
                        output.flush()
                        os.fsync(output.fileno())
                    except Exception:
                        path.unlink(missing_ok=True)
                        raise
                return {"name": path.name, "path": str(path), "dir": str(path.parent),
                        "bytes": len(data), "note": "Binary export saved without overwriting."}
            except FileExistsError:
                continue
        raise ValueError("could not find a free export name")

    def write_print_view(self, html: str) -> Path:
        """A standalone snapshot of the current view, ready to print."""
        name = f"guzzionboard-view-{time.strftime('%Y%m%d-%H%M%S')}.html"
        path = resources.unique_path(self.directory, name, fallback="guzzionboard-view.html")
        atomic_write(path, html.encode("utf-8"))
        return path


# --------------------------------------------------------------- the bridge

class DesktopBridge:
    """The host services behind ``/api/desktop/*`` and the page's bridge."""

    #: Folder names the UI may ask for. An allow-list, not a path from the page.
    FOLDERS = ("exports", "data", "logs", "sessions", "images", "basemaps",
               "xdfs", "checksums", "drivers")

    def __init__(self, app: "DesktopApp") -> None:
        self.app = app
        self.desk = app.desk

    # -- folders ---------------------------------------------------------
    def folder(self, which: str) -> Path:
        if which not in self.FOLDERS:
            raise ValueError(
                f"unknown folder {which!r}; known: {', '.join(self.FOLDERS)}"
            )
        if which == "data":
            return resources.data_root()
        if which == "exports":
            return self.desk.directory
        if which == "drivers":
            bundle = resources.driver_bundle_zip()
            return bundle.parent if bundle else resources.vendor_root() / "guzzidiag" / "tools"
        return resources.data_root() / which

    def info(self) -> dict:
        from . import __version__

        driver = resources.driver_bundle_zip()
        return {
            "available": True,
            "host": "desktop",
            "app": resources.APP_NAME,
            "version": __version__,
            "port": self.app.port,
            "url": self.app.url,
            "backend": self.app.backend.as_dict(),
            "launch_mode": self.app.mode,
            "frozen": resources.frozen(),
            "platform": sys.platform,
            "python": sys.version.split()[0],
            "data_root": str(resources.data_root()),
            "exports": str(self.desk.directory),
            "folders": {name: str(self.folder(name)) for name in self.FOLDERS},
            "driver_bundle": str(driver) if driver else None,
            "log": str(resources.logs_dir() / "desktop.log"),
            "job": self.app.busy(),
            "note": (
                "This window talks to the same local API a browser tab would; "
                "the difference is where saved files go and that no other page "
                "on this machine can reach the port."
            ),
        }

    # -- files -----------------------------------------------------------
    def save_text(self, name: str, content: str) -> dict:
        return self.desk.write_text(name, content)

    def save_binary(self, name: str, data: bytes) -> dict:
        return self.desk.write_binary(name, data)

    def print_view(self, html: str) -> dict:
        """Save the current view and print it from a real browser.

        None of the webview engines implement ``window.print()`` usefully, so
        pretending would be worse than saying so: the snapshot is written as a
        standalone file (styles inlined by the page) and opened, where the
        operating system's print dialog does the job properly.
        """
        path = self.desk.write_print_view(html)
        opened = _open_in_system(path)
        return {
            "path": str(path),
            "opened": opened,
            "note": (
                "A printable copy was saved and opened in your browser - press "
                "Ctrl+P (Cmd+P) there. The file stays in your exports folder."
                if opened else
                "A printable copy was saved to your exports folder; open it in "
                "a browser and print from there."
            ),
        }

    # -- links and folders ----------------------------------------------
    def open_external(self, url: str) -> dict:
        if not url:
            raise ValueError("'url' is required")
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https"):
            raise ValueError("only http(s) links can be opened")
        opened = open_url(url)
        return {"ok": opened, "url": url,
                "note": "" if opened else "this system has no browser to open it with"}

    def open_folder(self, which: str) -> dict:
        path = self.folder(which)
        path.mkdir(parents=True, exist_ok=True)
        opened = _open_in_system(path)
        return {"ok": opened, "path": str(path), "which": which,
                "note": "" if opened else "open the folder from your file manager"}

    # -- window and lifecycle -------------------------------------------
    def raise_window(self) -> dict:
        if self.app.backend.native and self.app.window is not None:
            focused = self.app.focus_window()
            return {"ok": True, "focused": focused, "url": self.app.url}
        return {
            "ok": True,
            "focused": False,
            "url": self.app.url,
            "reason": "this copy is running in a browser tab",
        }

    def quit(self) -> dict:
        self.app.request_quit("asked from the window")
        return {"ok": True, "note": "The workstation is shutting down."}

    # -- the page patch --------------------------------------------------
    def bridge_script(self) -> bytes:
        """``web/desktop-bridge.js`` with this launch's details in front.

        The token goes here rather than in the URL so it never reaches the
        address bar, the history, or a referrer header.
        """
        from . import __version__

        source = resources.web_root() / "desktop-bridge.js"
        try:
            script = source.read_text(encoding="utf-8")
        except OSError as exc:
            raise resources.BundleIncomplete(
                f"the desktop bridge script is missing from this install ({exc})"
            ) from exc
        preamble = {
            "token": self.app.token,
            "app": resources.APP_NAME,
            "version": __version__,
            "backend": self.app.backend.kind,
            "renderer": self.app.backend.renderer,
            "mode": self.app.mode,
            "port": self.app.port,
            "exports": str(self.desk.directory),
        }
        return (
            "window.__GOB_DESKTOP__ = " + json.dumps(preamble) + ";\n" + script
        ).encode("utf-8")


# ------------------------------------------------------------------ the app

class _Tee:
    """Write to a console and a log file, neither fatal."""

    def __init__(self, *streams) -> None:
        self.streams = [s for s in streams if s is not None]

    def write(self, text: str) -> int:
        for stream in self.streams:
            try:
                stream.write(text)
                stream.flush()
            except Exception:
                pass
        return len(text)

    def flush(self) -> None:
        for stream in self.streams:
            try:
                stream.flush()
            except Exception:
                pass


class DesktopApp:
    """Owns the process: the server, the window, and an orderly exit."""

    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 0,
        record: bool = True,
        prefer_browser: bool = False,
        no_window: bool = False,
        gui: str | None = None,
        debug: bool = False,
        window_size: tuple[int, int] = DEFAULT_WINDOW,
        export_dir: Path | str | None = None,
        allow_second_instance: bool = False,
    ) -> None:
        from . import __version__

        self.host = host
        self.port = port
        self.record = record
        self.debug = debug
        self.window_size = window_size
        self.allow_second_instance = allow_second_instance
        self.version = __version__

        self.token = secrets.token_urlsafe(32)
        self.instances = InstanceDirectory()
        self.desk = ExportDesk(export_dir)
        self.backend, self.webview = choose_backend(
            prefer_browser=prefer_browser, gui=gui
        )
        self.mode = "headless" if no_window else (
            "window" if self.backend.native else "browser"
        )
        self.gui = gui

        self.workstation = None
        self.handler = None
        self.httpd: ThreadingHTTPServer | None = None
        self.window = None
        self.bridge = DesktopBridge(self)
        self.exit_code = 0

        self._server_thread: threading.Thread | None = None
        self._protocol_updates = None
        self._stopping = threading.Event()
        self._stopped = False
        self._closing_anyway = False
        self._log_handle = None
        #: Set by the window watchdog when the window never appeared; a
        #: support question can be answered from the log alone.
        self.window_watchdog_fired = False
        #: Overridable so tests do not have to wait the real timeout.
        self.window_watchdog_timeout = WINDOW_SHOWN_TIMEOUT

    # -- properties ------------------------------------------------------
    @property
    def url(self) -> str:
        return f"http://{self.host if self.host not in ('0.0.0.0', '::') else '127.0.0.1'}:{self.port}/"

    # -- startup ---------------------------------------------------------
    def start(self) -> None:
        self._setup_logging()
        self._start_server()

    def _setup_logging(self) -> None:
        """A windowed build has no console, so keep a log the user can send."""
        try:
            resources.logs_dir().mkdir(parents=True, exist_ok=True)
            self._log_handle = open(
                resources.logs_dir() / "desktop.log", "a", encoding="utf-8", buffering=1
            )
        except OSError:
            return
        sys.stdout = _Tee(sys.stdout, self._log_handle)
        sys.stderr = _Tee(sys.stderr, self._log_handle)
        print(
            f"\n--- {resources.APP_NAME} {self.version} starting "
            f"({sys.platform}, {self.backend.kind}:{self.backend.renderer or 'n/a'}"
            f"{', frozen' if resources.frozen() else ''}) ---"
        )

    def _start_server(self) -> None:
        from .server import guard_for_bind, make_handler
        from .workstation import Workstation

        self.workstation = Workstation(record=self.record)
        # Loopback (the default, and the only sane one): strict Host list. An
        # explicit --host 0.0.0.0 asks for a LAN address, which the guard
        # honours the same way the console server does - other web origins are
        # still refused, but machines on the network are not.
        guard = guard_for_bind(self.host, token=self.token)
        self.handler = make_handler(self.workstation, guard=guard, desktop=self.bridge)
        try:
            self.httpd = ThreadingHTTPServer((self.host, self.port), self.handler)
        except OSError as exc:
            raise DesktopError(
                f"cannot listen on {self.host}:{self.port} ({exc}). Another program "
                "may be using that port; leave --port unset to let the app choose "
                "a free one."
            ) from exc
        self.httpd.daemon_threads = True
        self.port = int(self.httpd.server_address[1])
        if self.host not in LOOPBACK_HOSTS:
            print(
                f"  note: bound to {self.host}: anything that can reach this machine "
                "can open the workstation. Requests from other web origins are "
                "still refused."
            )
        self._server_thread = threading.Thread(
            target=self.httpd.serve_forever, name="guzzionboard-http", daemon=True
        )
        self._server_thread.start()
        from .auto_protocol_updates import AutoProtocolUpdates
        self._protocol_updates = AutoProtocolUpdates(self.workstation).start()
        self.handler.api.auto_protocol_updates = self._protocol_updates

    def _record_instance(self) -> None:
        self.instances.write(
            Instance(
                pid=os.getpid(),
                port=self.port,
                token=self.token,
                backend=self.backend.kind,
                url=self.url,
                version=self.version,
                started=time.time(),
                data_root=str(resources.data_root()),
            )
        )

    # -- the running copy -------------------------------------------------
    def _join_existing(self, instance: Instance) -> int:
        answer = self.instances.ask_to_raise(instance)
        focused = bool(answer.get("focused"))
        url = str(answer.get("url") or instance.url)
        if focused and self.backend.native:
            print("GuzziOnBoard is already running; its window was brought forward.")
            return 0
        if not focused and url:
            # A browser-hosted copy: give the operator the tab they want.
            if open_url(url):
                print(f"GuzziOnBoard is already running at {url}; opened a tab on it.")
                return 0
        print(f"GuzziOnBoard is already running at {url}.")
        return 0

    # -- modes -----------------------------------------------------------
    def run(self) -> int:
        if not self.allow_second_instance:
            existing = self.instances.live()
            if existing is not None:
                return self._join_existing(existing)
        try:
            self.start()
        except DesktopError as exc:
            self._fatal(str(exc))
            return 2
        self._record_instance()
        print(f"GuzziOnBoard {self.version}")
        print(f"  UI:        {self.url}")
        print(f"  mode:      {self.mode}"
              + (f" ({self.backend.renderer})" if self.backend.renderer else ""))
        print(f"  exports:   {self.desk.directory}")
        print(f"  data:      {resources.data_root()}")
        try:
            if self.mode == "window":
                self._run_window()
            elif self.mode == "browser":
                self._run_browser()
            else:
                self._run_headless()
        except Exception:
            traceback.print_exc()
            self.exit_code = 1
        finally:
            self.shutdown()
        return self.exit_code

    def _run_window(self) -> None:
        try:
            self._start_window()
        except Exception as exc:
            # No GPU, no WebView2 runtime, a broken GTK install: the window is
            # the only part that failed, so say so and use the browser instead
            # of leaving the operator with a process that does nothing.
            traceback.print_exc()
            print(
                f"the desktop window could not start ({type(exc).__name__}: {exc}); "
                "opening the workstation in your browser instead."
            )
            self.mode = "browser-fallback"
            self._run_browser()

    def _start_window(self) -> None:
        webview = self.webview
        self._preflight_window()
        icon = self._icon_path()
        self.window = webview.create_window(
            f"{resources.APP_NAME} — diagnostic workstation",
            url=self.url,
            width=self.window_size[0],
            height=self.window_size[1],
            min_size=MINIMUM_WINDOW,
            background_color="#0e1116",
            confirm_close=False,
        )
        self.window.events.closing += self._on_window_closing
        self.window.events.closed += self._on_window_closed
        _enable_downloads(webview)
        self._start_window_watchdog(self.window)
        webview.start(
            gui=self.gui,
            debug=self.debug,
            private_mode=False,          # keep localStorage: the garage is remembered there
            storage_path=str(resources.storage_dir()),
            icon=str(icon) if icon else None,
        )

    def _preflight_window(self) -> None:
        """Check everything the window needs *before* it starts.

        pywebview creates the window on a private GUI thread. A failure on
        that thread - a missing WebView2 runtime, a broken .NET install, an
        interop DLL that did not survive freezing - tears the whole process
        down with no Python exception, so the fallback in :meth:`_run_window`
        never runs and the operator sees nothing at all: no window, no
        message, no log line. Everything that can be checked from the main
        thread is checked here, where a failure is still an ordinary
        exception the fallback can catch, explain and recover from.

        This is why the first user launch of 0.4.0 "installed fine but never
        opened": the log ended at ``mode: window`` and the process was gone.
        """
        webview = self.webview
        version = getattr(webview, "__version__", "unknown")
        if sys.platform == "win32" and self.gui in (None, "edgechromium"):
            build = _webview2_build()
            if build is None or _version_tuple(build) < _version_tuple(MINIMUM_WEBVIEW2):
                found = (
                    f"version {build} is older than {MINIMUM_WEBVIEW2}"
                    if build
                    else "is not installed"
                )
                raise DesktopError(
                    f"the Microsoft WebView2 runtime {found}, and the window cannot "
                    "open without it. Install it from "
                    "https://developer.microsoft.com/microsoft-edge/webview2/ "
                    "and launch GuzziOnBoard again."
                )
        try:
            from webview.guilib import initialize
        except ImportError:                  # pragma: no cover - pywebview's own shape moved
            print("  window:    (pywebview internals not probeable; starting anyway)")
            return
        try:
            guilib = initialize(self.gui)
            renderer = getattr(guilib, "renderer", "") or ""
        except Exception as exc:
            raise DesktopError(
                f"the window engine could not be loaded ({type(exc).__name__}: {exc}). "
                "This installation may be damaged; reinstalling GuzziOnBoard is "
                "the usual fix."
            ) from exc
        print(f"  window:    pywebview {version}, {renderer or 'unknown'} renderer")
        _hook_dotnet_unhandled()

    def _start_window_watchdog(self, window) -> None:
        """If the window never appears, open the browser instead.

        The converse of the preflight: this covers what cannot be checked in
        advance - the GUI thread stalling or dying inside webview.start(),
        which blocks the main thread and would otherwise leave the operator
        with a process that does nothing. The workstation's server is on its
        own thread and still healthy, so the browser gets a fully working
        copy; this process stays up and keeps serving it.
        """
        def watch() -> None:
            shown = getattr(getattr(window, "events", None), "shown", None)
            if shown is None:               # pragma: no cover - defensive
                return
            if shown.wait(self.window_watchdog_timeout):
                return
            if self._stopping.is_set() or self.mode != "window":
                return
            self.window_watchdog_fired = True
            print(
                f"the desktop window did not appear within "
                f"{self.window_watchdog_timeout:.0f} seconds. The workstation is "
                "running; opening it in your browser instead. This is a bug "
                "worth reporting, with this log attached."
            )
            if not open_url(self.url):
                print(f"  open {self.url} in your browser")

        threading.Thread(
            target=watch, name="guzzionboard-window-watchdog", daemon=True
        ).start()

    def _run_browser(self) -> None:
        if self.backend.detail:
            print(f"  note:      {self.backend.detail}")
        if not open_url(self.url):
            print(f"  open {self.url} in your browser")
        self._run_headless()

    def _run_headless(self) -> None:
        print("  press Ctrl+C to stop")
        try:
            while not self._stopping.wait(0.5):
                pass
        except KeyboardInterrupt:
            print("\nshutting down")

    # -- window events ----------------------------------------------------
    def _on_window_closing(self):
        """Refuse to vanish in the middle of a flash read or write."""
        if self._closing_anyway:
            return True
        job = self.busy()
        if not job.get("running"):
            return True
        self._closing_anyway = True
        self._notify_ui(
            f"{job.get('name') or 'a memory operation'} is still running. Close the "
            "window again to shut GuzziOnBoard down anyway - the job stops with it."
        )
        return False

    def _on_window_closed(self) -> None:
        self._stopping.set()
        print("window closed")

    def _notify_ui(self, message: str) -> None:
        window = self.window
        if window is None:
            return
        script = (
            "window.dispatchEvent(new CustomEvent('gob-notice', "
            f"{{detail: {json.dumps(message)}}}));"
        )
        try:
            window.evaluate_js(script)
        except Exception:                     # pragma: no cover - GUI layer
            traceback.print_exc()

    def focus_window(self) -> bool:
        window = self.window
        if window is None:
            return False
        try:
            window.show()
            window.restore()
            # on_top is the only nudge pywebview offers for "come to the front";
            # it is set and immediately cleared so the window does not stay above
            # everything for the rest of the session.
            window.on_top = True
            window.on_top = False
            return True
        except Exception:                     # pragma: no cover - GUI layer
            traceback.print_exc()
            return False

    # -- shutdown ---------------------------------------------------------
    def busy(self) -> dict:
        api = getattr(self.handler, "api", None)
        if api is None:
            return {"running": False, "name": None, "state": "idle"}
        try:
            status = api.jobs.status()
        except Exception:                     # pragma: no cover - defensive
            return {"running": False, "name": None, "state": "unknown"}
        return {
            "running": bool(status.get("running")),
            "name": status.get("name"),
            "state": status.get("state"),
        }

    def request_quit(self, reason: str) -> None:
        """Stop from anywhere - the window, the UI's Quit button, a signal."""
        print(f"quit requested ({reason})")
        self._stopping.set()
        window = self.window
        if window is not None:
            # The GUI loop owns the window; destroy from a helper thread so a
            # request arriving on the HTTP thread cannot block on the loop.
            threading.Thread(target=self._destroy_window, daemon=True).start()

    def _destroy_window(self) -> None:
        window = self.window
        if window is None:
            return
        self._closing_anyway = True
        try:
            window.destroy()
        except Exception:                     # pragma: no cover - GUI layer
            traceback.print_exc()

    def shutdown(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        self._closing_anyway = True
        if self._protocol_updates is not None:
            self._protocol_updates.stop()
            self._protocol_updates = None
        if self.window is not None:
            try:
                self.window.destroy()
            except Exception:
                pass
            self.window = None
        if self.httpd is not None:
            try:
                self.httpd.shutdown()
                self.httpd.server_close()
            except Exception:                 # pragma: no cover - defensive
                traceback.print_exc()
            self.httpd = None
        if self.workstation is not None:
            try:
                self.workstation.disconnect()
            except Exception:                 # pragma: no cover - defensive
                traceback.print_exc()
            self.workstation = None
        self.instances.clear(token=self.token)
        if self._server_thread is not None:
            self._server_thread.join(timeout=5)
            self._server_thread = None
        print("GuzziOnBoard stopped.")

    # -- helpers ----------------------------------------------------------
    @staticmethod
    def _icon_path() -> Path | None:
        """The window icon, in the form the platform's loader survives.

        pywebview's Windows backend loads the icon with
        ``System.Drawing.Icon(path)`` - an API that accepts ``.ico`` files
        and throws an ArgumentException for anything else, on the GUI
        thread, where the exception kills the process with no Python error.
        That is exactly how 0.4.0 shipped: every Windows launch died
        silently (exit code 0xE0434352) because this method offered the
        ``.png`` first. macOS and GTK take the ``.png`` happily.
        """
        order = (
            ("guzzionboard.ico", "guzzionboard.png")
            if sys.platform == "win32"
            else ("guzzionboard.png", "guzzionboard.ico")
        )
        for name in order:
            candidate = resources.bundle_root() / "packaging" / "icons" / name
            if candidate.is_file():
                return candidate
        return None

    def _fatal(self, message: str) -> None:
        """Report a startup failure where the user will actually see it."""
        print(f"error: {message}", file=sys.stderr)
        if self._log_handle is not None and os.name == "nt":
            _windows_message_box(resources.APP_NAME, message)


def _enable_downloads(webview) -> None:
    """Let the renderer honour downloads the shell does not intercept."""
    try:
        webview.settings["ALLOW_DOWNLOADS"] = True
    except Exception:                         # pragma: no cover - not fatal
        pass


def _windows_message_box(title: str, message: str) -> None:  # pragma: no cover
    """A windowed build has nowhere to print a startup failure."""
    if os.name != "nt":
        return
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, title, 0x10)
    except Exception:
        pass


def _open_location(*, logs: bool, export_dir: str | None) -> int:
    """``--open-data`` / ``--open-logs``: show the user where things go."""
    if logs:
        path = resources.logs_dir()
    else:
        path = ExportDesk(export_dir).directory
    path.mkdir(parents=True, exist_ok=True)
    print(path)
    if not _open_in_system(path):
        print("(could not open a file manager here; the path above is yours)")
    return 0


def parse_window_size(value: str) -> tuple[int, int]:
    try:
        width, height = (int(part) for part in value.lower().split("x", 1))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("use WIDTHxHEIGHT, e.g. 1360x900") from exc
    if width < 640 or height < 480:
        raise argparse.ArgumentTypeError("the window must be at least 640x480")
    return width, height


# ------------------------------------------------------------------- the CLI

def build_parser() -> argparse.ArgumentParser:
    from . import __version__

    parser = argparse.ArgumentParser(
        prog="guzzionboard-desktop",
        description=(
            "GuzziOnBoard as a desktop application: a native window on the same "
            "loopback workstation the browser version serves."
        ),
        epilog=(
            "examples:\n"
            "  guzzionboard-desktop                  native window, files go to Downloads\n"
            "  guzzionboard-desktop --browser        use the system browser instead\n"
            "  guzzionboard-desktop --no-window      serve only (scripts, CI)\n"
            "  guzzionboard-desktop --selftest       verify this installation and exit\n"
            "  guzzionboard-desktop --export-dir D   save exports somewhere specific\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--host", default="127.0.0.1",
                        help="bind address (default 127.0.0.1 - keep it local)")
    parser.add_argument("--port", type=int, default=0,
                        help="port to listen on (default 0: the OS picks a free one)")
    parser.add_argument("--no-record", action="store_true",
                        help="do not write session logs to ~/.guzzionboard/sessions")
    parser.add_argument("--browser", action="store_true",
                        help="open the workstation in the system browser")
    parser.add_argument("--no-window", action="store_true",
                        help="run the server only; no window and no browser")
    parser.add_argument("--gui", choices=GUI_CHOICES, default=None,
                        help="force a pywebview renderer instead of the platform default")
    parser.add_argument("--window-size", type=parse_window_size, default=DEFAULT_WINDOW,
                        metavar="WIDTHxHEIGHT", help="initial window size (default 1360x900)")
    parser.add_argument("--export-dir", default=None,
                        help="where saved reports, logs and images land "
                             "(default: your Downloads folder)")
    parser.add_argument("--data-dir", default=None,
                        help="where session logs, backups and settings live "
                             "(default: ~/.guzzionboard)")
    parser.add_argument("--new-instance", action="store_true",
                        help="start even if another copy is already running")
    parser.add_argument("--debug", action="store_true",
                        help="webview developer tools and verbose output")
    parser.add_argument("--selftest", action="store_true",
                        help="check this installation (catalog, UI, API, worker) and exit")
    parser.add_argument("--open-data", action="store_true",
                        help="open the folder holding exports and recorded sessions, then exit")
    parser.add_argument("--open-logs", action="store_true",
                        help="open the log folder, then exit")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    # Redirect the per-user data root before the app modules are imported: the
    # paths they bind at import time are constants.
    if args.data_dir:
        os.environ[resources.HOME_ENV] = str(Path(args.data_dir).expanduser())
    if args.selftest:
        from . import selftest

        return selftest.run(
            export_dir=args.export_dir,
            host=args.host,
            verbose=True,
        )
    if args.open_data or args.open_logs:
        return _open_location(
            logs=args.open_logs,
            export_dir=args.export_dir,
        )
    app = DesktopApp(
        host=args.host,
        port=args.port,
        record=not args.no_record,
        prefer_browser=args.browser,
        no_window=args.no_window,
        gui=args.gui,
        debug=args.debug,
        window_size=tuple(args.window_size),
        export_dir=args.export_dir,
        allow_second_instance=args.new_instance,
    )
    try:
        return app.run()
    except KeyboardInterrupt:
        app.shutdown()
        return 0


if __name__ == "__main__":        # pragma: no cover - manual launch
    raise SystemExit(main())
