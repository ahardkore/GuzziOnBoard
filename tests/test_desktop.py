"""The desktop application: the shell, its host routes, and a frozen layout.

The workstation API is the same one the browser version serves; what these
tests cover is everything that is only true once GuzziOnBoard is an installed
program rather than a page:

* files the app reads when it is a bundle rather than a checkout
  (:mod:`guzzionboard.resources`), including a bundle that only exists in the
  test,
* the request policy that stops another page on the machine from driving a
  connected motorcycle (token, origin, host),
* the host routes the page uses to save a file, print a view and quit,
* the single-instance record: proven live before it is obeyed, and cleared
  when it is stale,
* the self-test, which is what CI runs against the built artifact.
"""
from __future__ import annotations

import base64
import http.client
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import types
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

import guzzionboard.desktop
from guzzionboard import resources
from guzzionboard.checksums import load_providers
from guzzionboard.desktop import (
    DesktopApp,
    DesktopError,
    ExportDesk,
    Instance,
    InstanceDirectory,
    _hook_dotnet_unhandled,
    _open_location,
    build_parser,
    choose_backend,
    parse_window_size,
)
from guzzionboard.server import (
    RequestGuard,
    guard_for_bind,
    make_handler,
    mark_desktop,
    mark_live_backend,
)
from guzzionboard.workstation import Workstation

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Every test gets its own per-user data root."""
    directory = tmp_path / "home"
    monkeypatch.setenv(resources.HOME_ENV, str(directory))
    return directory


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    """A fake frozen bundle with the repository's files copied into it."""
    root = tmp_path / "bundle"
    (root / "guzzionboard").mkdir(parents=True)
    for name in ("catalog", "xdfs"):
        shutil.copytree(ROOT / "guzzionboard" / name, root / "guzzionboard" / name)
    shutil.copytree(ROOT / "web", root / "web")
    (root / "vendor" / "guzzidiag" / "tools").mkdir(parents=True)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(root), raising=False)
    return root


class FakeBridge:
    """Stands in for :class:`guzzionboard.desktop.DesktopBridge`."""

    def __init__(self, exports: Path) -> None:
        self.exports = Path(exports)
        self.calls: list[tuple[str, dict]] = []

    def info(self) -> dict:
        return {"available": True, "host": "test", "exports": str(self.exports)}

    def save_text(self, name: str, content: str) -> dict:
        self.calls.append(("save", {"name": name, "content": content}))
        path = resources.unique_path(self.exports, name)
        path.write_text(content, encoding="utf-8")
        return {"name": path.name, "path": str(path), "dir": str(path.parent),
                "bytes": len(content)}

    def print_view(self, html: str) -> dict:
        self.calls.append(("print", {"html": html}))
        return {"path": str(self.exports / "view.html"), "opened": True, "note": "printed"}

    def open_external(self, url: str) -> dict:
        self.calls.append(("external", {"url": url}))
        return {"ok": True, "url": url, "note": ""}

    def open_folder(self, which: str) -> dict:
        self.calls.append(("folder", {"which": which}))
        return {"ok": True, "path": str(self.exports), "which": which, "note": ""}

    def raise_window(self) -> dict:
        self.calls.append(("raise", {}))
        return {"ok": True, "focused": False, "url": "http://127.0.0.1/1/", "reason": "no window"}

    def quit(self) -> dict:
        self.calls.append(("quit", {}))
        return {"ok": True, "note": "closing"}

    def bridge_script(self) -> bytes:
        return b'window.__GOB_DESKTOP__ = {"token": "test-token"};\n'


@pytest.fixture
def api_server(home, tmp_path):
    """A real HTTP server behind the guard and a fake desktop host."""
    workstation = Workstation(record=False)
    bridge = FakeBridge(tmp_path / "exports")
    token = "unit-test-token"
    handler = make_handler(
        workstation, guard=RequestGuard(token=token), desktop=bridge
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server, bridge, token
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)
    workstation.disconnect()


def call(server, method, path, *, token=None, payload=None, headers=None, host=None):
    connection = http.client.HTTPConnection(*server.server_address, timeout=10)
    try:
        sent = {"Host": host or f"127.0.0.1:{server.server_address[1]}"}
        if token:
            sent[resources.TOKEN_HEADER] = token
        sent.update(headers or {})
        body = json.dumps(payload).encode() if payload is not None else None
        if body is not None:
            sent["Content-Type"] = "application/json"
        connection.request(method, path, body=body, headers=sent)
        response = connection.getresponse()
        raw = response.read()
        try:
            return response.status, json.loads(raw or b"{}")
        except ValueError:
            return response.status, raw
    finally:
        connection.close()


# ------------------------------------------------------------- resources

def test_source_checkout_paths_point_at_the_repository():
    assert resources.frozen() is False
    assert resources.web_root() == ROOT / "web"
    assert (resources.web_root() / "index.html").is_file()
    assert resources.vendor_root() == ROOT / "vendor"


def test_data_root_defaults_to_the_home_directory(monkeypatch):
    monkeypatch.delenv(resources.HOME_ENV, raising=False)
    assert resources.data_root() == Path.home() / ".guzzionboard"


def test_data_root_and_children_follow_the_override(home):
    assert resources.data_root() == home
    for path in (resources.sessions_dir(), resources.logs_dir(), resources.exports_dir(),
                 resources.storage_dir()):
        assert home in path.parents
    assert resources.instance_file().parent == home


def test_frozen_bundle_resolves_inside_the_bundle(bundle, monkeypatch):
    monkeypatch.delenv(resources.WEB_ENV, raising=False)
    assert resources.frozen() is True
    assert resources.bundle_root() == bundle
    assert resources.web_root() == bundle / "web"
    assert (resources.web_root() / "desktop-bridge.js").is_file()
    assert resources.vendor_root() == bundle / "vendor"


def test_frozen_bundle_also_finds_a_packaged_web_directory(bundle, monkeypatch):
    """A layout that puts web/ under guzzionboard/ still works."""
    monkeypatch.delenv(resources.WEB_ENV, raising=False)
    (bundle / "guzzionboard" / "web").parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(bundle / "web"), str(bundle / "guzzionboard" / "web"))
    assert resources.web_root() == bundle / "guzzionboard" / "web"


def test_missing_ui_in_a_bundle_is_an_explicit_failure(bundle, monkeypatch):
    monkeypatch.delenv(resources.WEB_ENV, raising=False)
    shutil.rmtree(bundle / "web")
    with pytest.raises(resources.BundleIncomplete):
        resources.web_root()
    # The server falls back to a path rather than dying at import time; the
    # 404 the user gets is a better answer than a traceback on startup.
    assert isinstance(resources.bundle_root() / "web", Path)


def test_environment_override_wins(bundle, tmp_path, monkeypatch):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.setenv(resources.WEB_ENV, str(elsewhere))
    assert resources.web_root() == elsewhere
    monkeypatch.setenv(resources.WEB_ENV, str(tmp_path / "nope"))
    with pytest.raises(resources.BundleIncomplete):
        resources.web_root()


def test_worker_executable_is_only_looked_for_in_a_frozen_build(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert resources.worker_executable() is None
    name = resources.WORKER_EXECUTABLE + (".exe" if os.name == "nt" else "")
    stub = Path(sys.executable).with_name(name)
    stub.write_text("stub")
    try:
        assert resources.worker_executable() == stub
    finally:
        stub.unlink()


@pytest.mark.parametrize("name,expected", [
    ("report.txt", "report.txt"),
    ("../../etc/passwd", "passwd"),
    (r"..\..\windows\system32\evil.dll", "evil.dll"),
    ("con", "_con"),
    ("nul.txt", "_nul.txt"),
    ("trailing...", "trailing"),
    ("", "guzzionboard-export"),
    ("..", "guzzionboard-export"),
    ("a" * 400 + ".txt", None),            # capped, checked below
    ("bad:name?.txt", "badname.txt"),
])
def test_safe_filename_neutralises_escapes(name, expected):
    result = resources.safe_filename(name)
    assert "/" not in result and "\\" not in result
    assert result and result not in (".", "..")
    if expected is not None:
        assert result == expected
    else:
        assert len(result) <= 120 and result.endswith(".txt")


def test_unique_path_never_overwrites(tmp_path):
    first = resources.unique_path(tmp_path, "session.jsonl")
    first.write_text("evidence")
    second = resources.unique_path(tmp_path, "session.jsonl")
    assert second != first and not second.exists()
    second.write_text("more evidence")
    third = resources.unique_path(tmp_path, "session.jsonl")
    assert third.name == "session-2.jsonl"
    assert first.read_text() == "evidence"      # the first export survives


def test_describe_reports_a_usable_installation(home):
    described = resources.describe()
    assert described["app"] == resources.APP_NAME
    assert described["web_root"] and Path(described["web_root"]).is_dir()
    assert described["data_root"] == str(home)


# ----------------------------------------------------------- the policy

@pytest.mark.parametrize("host", ["127.0.0.1:8000", "localhost:8000", "[::1]:8000"])
def test_guard_allows_loopback_names(host):
    guard = RequestGuard(token=None)
    assert guard.check(command="GET", path="/api/status", host=host, origin=None) is None


@pytest.mark.parametrize("host", ["evil.example", "attacker.example:8000", "10.0.0.5:8000", None, ""])
def test_guard_refuses_any_other_host(host):
    guard = RequestGuard(token=None)
    decision = guard.check(command="GET", path="/api/status", host=host, origin=None)
    assert decision is not None and decision[0] == 403


def test_guard_refuses_another_page_on_the_same_machine():
    """The check that matters: a web page cannot reach this API."""
    guard = RequestGuard(token=None)
    decision = guard.check(
        command="POST", path="/api/actuators/pulse", host="127.0.0.1:8000",
        origin="https://evil.example",
    )
    assert decision is not None and "origin" in decision[1]


def test_guard_accepts_its_own_origin_and_localhost_alias():
    guard = RequestGuard(token=None)
    for origin in ("http://127.0.0.1:8000", "http://localhost:8000"):
        assert guard.check(command="GET", path="/api/status", host="127.0.0.1:8000",
                           origin=origin) is None
    # a different port is a different origin
    assert guard.check(command="GET", path="/api/status", host="127.0.0.1:8000",
                       origin="http://127.0.0.1:9999") is not None
    assert guard.check(command="GET", path="/api/status", host="127.0.0.1:8000",
                       origin="null") is not None


def test_token_is_required_for_api_paths_only():
    guard = RequestGuard(token="secret")
    assert guard.check(command="GET", path="/", host="127.0.0.1:1", origin=None) is None
    assert guard.check(command="GET", path="/api/status", host="127.0.0.1:1",
                       origin=None) is not None
    assert guard.check(command="GET", path="/api/status", host="127.0.0.1:1",
                       origin=None, header_token="secret") is None
    assert guard.check(command="GET", path="/api/status", host="127.0.0.1:1",
                       origin=None, query_token="secret") is None
    assert guard.check(command="GET", path="/api/status", host="127.0.0.1:1",
                       origin=None, header_token="wrong") is not None


def test_an_explicit_lan_bind_relaxes_the_host_check_but_not_the_origin():
    wide = guard_for_bind("0.0.0.0")
    assert wide.check(command="GET", path="/api/status", host="workshop-laptop:8000",
                      origin=None) is None
    assert wide.check(command="GET", path="/api/status", host="workshop-laptop:8000",
                      origin="https://evil.example") is not None
    loopback = guard_for_bind("127.0.0.1")
    assert loopback.check(command="GET", path="/api/status", host="workshop-laptop:8000",
                          origin=None) is not None


# ------------------------------------------------------ the host routes

def test_desktop_info_route(api_server):
    server, bridge, token = api_server
    status, payload = call(server, "GET", "/api/desktop", token=token)
    assert status == 200 and payload["available"] is True and payload["host"] == "test"


def test_api_answers_only_with_the_launch_token(api_server):
    server, _bridge, token = api_server
    assert call(server, "GET", "/api/status")[0] == 403
    assert call(server, "GET", "/api/status", token="nope")[0] == 403
    assert call(server, "GET", "/api/status", token=token)[0] == 200
    encoded = base64.b64encode(b"nope").decode()      # a long wrong token
    assert call(server, "GET", "/api/status", token=encoded)[0] == 403


def test_the_page_is_marked_and_the_bridge_is_injected(api_server):
    server, _bridge, token = api_server
    status, body = call(server, "GET", "/", token=token)
    page = body.decode("utf-8")
    assert status == 200
    assert 'data-desktop="1"' in page
    assert 'data-backend="live"' in page
    assert "/desktop-bridge.js" in page
    # ... before app.js, because the token has to be installed before the UI
    # makes its first request.
    assert page.index("desktop-bridge.js") < page.index("app.js")
    status, script = call(server, "GET", "/desktop-bridge.js", token=token)
    assert status == 200 and b"__GOB_DESKTOP__" in script


def test_browser_sessions_get_the_plain_page(home, tmp_path):
    """With no desktop host there is no bridge tag and no token: one marker."""
    workstation = Workstation(record=False)
    handler = make_handler(workstation)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, body = call(server, "GET", "/")
        page = body.decode("utf-8")
        assert status == 200 and 'data-backend="live"' in page
        assert "desktop-bridge.js" not in page
        assert call(server, "GET", "/api/desktop")[1]["available"] is False
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        workstation.disconnect()


def test_saving_a_file_goes_to_the_host(api_server, tmp_path):
    server, bridge, token = api_server
    status, payload = call(server, "POST", "/api/desktop/save",
                           token=token, payload={"name": "report.txt", "content": "text"})
    assert status == 200 and Path(payload["path"]).read_text() == "text"
    assert bridge.calls[-1][0] == "save"
    # the host, not the page, decides where a name may point
    status, payload = call(server, "POST", "/api/desktop/save",
                           token=token, payload={"name": "../../escape.txt", "content": "x"})
    written = Path(payload["path"])
    assert status == 200 and written.parent == bridge.exports


def test_saving_requires_a_name_and_text(api_server):
    server, _bridge, token = api_server
    assert call(server, "POST", "/api/desktop/save", token=token,
                payload={"content": "x"})[0] == 400
    assert call(server, "POST", "/api/desktop/save", token=token,
                payload={"name": "x.txt", "content": 5})[0] == 400


def test_print_view_and_folder_routes(api_server):
    server, bridge, token = api_server
    status, payload = call(server, "POST", "/api/desktop/print", token=token,
                           payload={"html": "<html>view</html>"})
    assert status == 200 and payload["opened"] is True
    assert call(server, "POST", "/api/desktop/print", token=token, payload={})[0] == 400
    status, payload = call(server, "POST", "/api/desktop/open-folder", token=token,
                           payload={"which": "exports"})
    assert status == 200 and payload["which"] == "exports"
    status, payload = call(server, "POST", "/api/desktop/open-external", token=token,
                           payload={"url": "https://github.com/ahardkore/GuzziOnBoard"})
    assert status == 200 and payload["ok"] is True
    status, _ = call(server, "POST", "/api/desktop/quit", token=token, payload={})
    assert status == 200 and bridge.calls[-1][0] == "quit"


def test_host_routes_say_so_when_there_is_no_host(home):
    workstation = Workstation(record=False)
    handler = make_handler(workstation)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, payload = call(server, "POST", "/api/desktop/save",
                               payload={"name": "x.txt", "content": "y"})
        assert status == 400 and "desktop app" in payload["error"]
        status, payload = call(server, "POST", "/api/desktop/raise", payload={})
        assert status == 200 and payload["ok"] is False
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        workstation.disconnect()


def test_bridge_script_is_not_served_without_a_host(home):
    workstation = Workstation(record=False)
    handler = make_handler(workstation)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        assert call(server, "GET", "/desktop-bridge.js")[0] == 404
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        workstation.disconnect()


def test_markers_are_idempotent_and_ordered():
    page = b"<html><head></head><body><script src=\"app.js\"></script></body></html>"
    desktop = mark_desktop(page)
    assert b'data-desktop="1"' in desktop
    assert desktop.count(b"desktop-bridge.js") == 1
    assert mark_desktop(desktop) == desktop
    assert mark_live_backend(b"<body>") == b'<body data-backend="live">'


def test_static_serving_stays_inside_the_web_root(api_server):
    server, _bridge, token = api_server
    assert call(server, "GET", "/../pyproject.toml", token=token)[0] in (403, 404)
    assert call(server, "GET", "/%2e%2e/pyproject.toml", token=token)[0] in (403, 404)


# ------------------------------------------------------ single instance

def test_instance_record_round_trip(home):
    directory = InstanceDirectory()
    instance = Instance(pid=os.getpid(), port=1234, token="t", backend="window",
                        url="http://127.0.0.1:1234/", version="0.0.0", started=1.0,
                        data_root=str(home))
    directory.write(instance)
    assert directory.read() == instance
    assert home in directory.path.parents
    if os.name != "nt":
        assert (directory.path.stat().st_mode & 0o777) == 0o600      # the token is in it
    directory.clear(token="t")
    assert directory.read() is None


def test_clear_never_removes_someone_elses_record(home):
    directory = InstanceDirectory()
    directory.write(Instance(pid=1, port=1, token="mine", backend="window", url="u",
                             version="0.0.0", started=0.0))
    directory.clear(token="theirs")
    assert directory.read() is not None
    directory.clear(token="mine")
    assert directory.read() is None


def test_a_stale_record_is_not_believed(home):
    directory = InstanceDirectory(timeout=0.4)
    directory.write(Instance(pid=999999, port=9, token="old", backend="window",
                             url="http://127.0.0.1:9/", version="0.0.0", started=0.0))
    assert directory.live() is None
    assert directory.read() is None          # and the dead record is gone


def test_unreadable_or_wrong_records_are_ignored(home):
    directory = InstanceDirectory()
    directory.path.parent.mkdir(parents=True, exist_ok=True)
    directory.path.write_text("{not json")
    assert directory.read() is None and directory.live() is None
    directory.path.write_text(json.dumps({"pid": "x"}))
    assert directory.read() is None


def test_a_live_instance_is_found_and_asked_to_come_forward(api_server, home):
    server, bridge, _token = api_server
    directory = InstanceDirectory()
    directory.write(Instance(
        pid=os.getpid(), port=server.server_address[1], token="unit-test-token",
        backend="window", url="http://127.0.0.1:%d/" % server.server_address[1],
        version="0.0.0", started=time.time(), data_root=str(home),
    ))
    live = directory.live()
    assert live is not None and live.port == server.server_address[1]
    answer = directory.ask_to_raise(live)
    assert answer["ok"] is True and bridge.calls[-1][0] == "raise"


# --------------------------------------------------------- the export desk

def test_export_desk_writes_and_never_overwrites(tmp_path):
    desk = ExportDesk(tmp_path / "exports")
    first = desk.write_text("report.txt", "one")
    second = desk.write_text("report.txt", "two")
    assert first["name"] == "report.txt" and second["name"] == "report-1.txt"
    assert Path(first["path"]).read_text() == "one"
    assert Path(second["path"]).read_text() == "two"
    assert "overwritten" in second["note"]


def test_export_desk_keeps_a_directory_out_of_the_name(tmp_path):
    desk = ExportDesk(tmp_path / "exports")
    saved = desk.write_text("../../important/report.txt", "x")
    assert Path(saved["path"]).parent == tmp_path / "exports"


def test_print_view_is_a_standalone_file(tmp_path):
    desk = ExportDesk(tmp_path / "exports")
    path = desk.write_print_view("<!doctype html><html>view</html>")
    assert path.is_file() and "view" in path.read_text()
    assert path.name.startswith("guzzionboard-view-")


def test_export_desk_defaults_to_downloads_when_it_exists(home, monkeypatch):
    monkeypatch.delenv(resources.HOME_ENV, raising=False)
    monkeypatch.setattr(resources, "user_home", lambda: home)
    downloads = home / "Downloads"
    downloads.mkdir(parents=True)
    assert resources.default_export_dir() == downloads
    assert resources.data_root() == home / ".guzzionboard"
    shutil.rmtree(downloads)
    assert resources.default_export_dir() == resources.exports_dir()


def test_open_location_reports_the_folder(home, monkeypatch, capsys):
    opened: list[Path] = []
    monkeypatch.setattr("guzzionboard.desktop._open_in_system",
                        lambda path: opened.append(path) or True)
    assert _open_location(logs=False, export_dir=None) == 0
    assert opened[0] == resources.default_export_dir()
    assert _open_location(logs=True, export_dir=None) == 0
    assert opened[1] == resources.logs_dir()
    assert str(opened[1]) in capsys.readouterr().out


def test_open_location_says_so_when_it_cannot_open_a_file_manager(home, monkeypatch, capsys):
    monkeypatch.setattr("guzzionboard.desktop._open_in_system", lambda path: False)
    assert _open_location(logs=False, export_dir=None) == 0
    assert "could not open" in capsys.readouterr().out


# ------------------------------------------------------------- the shell

def test_cli_defaults_stay_on_this_machine():
    args = build_parser().parse_args([])
    assert args.host == "127.0.0.1"
    assert args.port == 0                     # a free port: never fight over one
    assert args.window_size == (1360, 900)
    assert not args.browser and not args.no_window


def test_cli_parses_the_desktop_options():
    args = build_parser().parse_args([
        "--port", "8000", "--browser", "--window-size", "1024x768",
        "--export-dir", "/tmp/out", "--data-dir", "/tmp/data", "--new-instance", "--debug",
    ])
    assert args.port == 8000 and args.browser and args.window_size == (1024, 768)
    assert args.export_dir == "/tmp/out" and args.data_dir == "/tmp/data"
    assert args.new_instance and args.debug


@pytest.mark.parametrize("value", ["wide", "1360x", "100x100", "0x0"])
def test_window_size_rejects_nonsense(value):
    import argparse

    with pytest.raises(argparse.ArgumentTypeError):
        parse_window_size(value)


def test_browser_mode_is_available_when_asked_for():
    backend, webview = choose_backend(prefer_browser=True)
    assert backend.kind == "browser" and webview is None
    assert "browser" in backend.detail


def test_backend_selection_explains_a_missing_window_engine(monkeypatch):
    monkeypatch.setattr("guzzionboard.desktop.load_webview", lambda: (None, "no engine here"))
    backend, webview = choose_backend()
    assert backend.kind == "browser" and webview is None
    assert "no engine here" in backend.detail


def test_backend_selection_uses_the_window_engine_when_present(monkeypatch):
    class FakeWebview:
        renderer = "fake"

    monkeypatch.setattr("guzzionboard.desktop.load_webview", lambda: (FakeWebview, ""))
    backend, webview = choose_backend()
    assert backend.native and backend.renderer == "fake" and webview is FakeWebview


def test_a_wildcard_bind_says_so_and_relaxes_only_the_host_check(home, monkeypatch, capsys):
    app = DesktopApp(host="0.0.0.0", no_window=True, record=False)
    try:
        app.start()
        captured = capsys.readouterr().out
        assert "anything that can reach this machine" in captured
        assert call(app.httpd, "GET", "/api/desktop/ping")[0] == 403   # still needs the token
        assert call(app.httpd, "GET", "/api/desktop/ping", token=app.token)[0] == 200
        assert app.url.startswith("http://127.0.0.1:")   # ... but the URL we hand out is loopback
    finally:
        app.shutdown()


def test_app_starts_a_loopback_server_and_records_itself(home):
    app = DesktopApp(no_window=True, record=False)
    try:
        app.start()
        assert app.port > 0
        assert app.url == f"http://127.0.0.1:{app.port}/"
        app._record_instance()
        record = InstanceDirectory().read()
        assert record is not None and record.port == app.port and record.token == app.token
        status, payload = call(app.httpd, "GET", "/api/desktop/ping", token=app.token)
        assert status == 200 and payload["ok"] is True and payload["desktop"] is True
        script = app.bridge.bridge_script().decode()
        assert "GuzziOnBoard" in script and app.token in script
        assert "desktop-bridge.js" not in script        # that is the file, not the payload
    finally:
        app.shutdown()
    assert InstanceDirectory().read() is None            # cleaned up on the way out


def test_a_request_without_the_token_is_refused_by_a_running_app(home):
    app = DesktopApp(no_window=True, record=False)
    try:
        app.start()
        assert call(app.httpd, "GET", "/api/status")[0] == 403
        assert call(app.httpd, "GET", "/api/status", token=app.token)[0] == 200
    finally:
        app.shutdown()


def test_app_reports_the_export_folder_and_data_folder(home, tmp_path):
    app = DesktopApp(no_window=True, record=False, export_dir=tmp_path / "exports")
    assert app.desk.directory == tmp_path / "exports"
    info = app.bridge.info()
    assert info["exports"] == str(tmp_path / "exports")
    assert info["data_root"] == str(home)
    assert info["folders"]["sessions"] == str(home / "sessions")
    assert info["folders"]["exports"] == str(tmp_path / "exports")
    assert info["log"].endswith("desktop.log")


def test_bridge_folder_lookup_is_an_allow_list(home):
    app = DesktopApp(no_window=True, record=False)
    with pytest.raises(ValueError):
        app.bridge.folder("../..")
    with pytest.raises(ValueError):
        app.bridge.folder("C:\\Windows")


def test_a_window_does_not_close_in_the_middle_of_a_flash_read(home):
    app = DesktopApp(no_window=True, record=False)
    try:
        app.start()
        assert app._on_window_closing() is True            # nothing running: fine
        api = app.handler.api
        api.jobs.start("read:flash", lambda report: time.sleep(0.6))
        assert app.busy()["running"] is True
        assert app._on_window_closing() is False           # refused, with a notice
        assert app._on_window_closing() is True            # second attempt: allowed
        time.sleep(0.8)
        assert app.busy()["running"] is False
    finally:
        app.shutdown()


def test_a_second_launch_joins_the_running_copy(home, capsys):
    first = DesktopApp(no_window=True, record=False)
    try:
        first.start()
        first._record_instance()
        second = DesktopApp(no_window=True, record=False)
        assert second.run() == 0
        assert second.httpd is None                 # it never bound a port
        assert "already running" in capsys.readouterr().out
        assert first.httpd is not None              # the first copy is untouched
    finally:
        first.shutdown()


def test_new_instance_flag_ignores_the_running_copy(home):
    first = DesktopApp(no_window=True, record=False)
    try:
        first.start()
        first._record_instance()
        second = DesktopApp(no_window=True, record=False, allow_second_instance=True)
        try:
            second.start()
            assert second.port != first.port or second.port > 0
        finally:
            second.shutdown()
    finally:
        first.shutdown()


def test_a_taken_port_is_a_clear_error(home):
    from guzzionboard.desktop import DesktopError

    first = DesktopApp(no_window=True, record=False)
    try:
        first.start()
        second = DesktopApp(port=first.port, no_window=True, record=False)
        with pytest.raises(DesktopError):
            second.start()
        assert second.run() == 2                    # ... and it exits non-zero
    finally:
        first.shutdown()


def test_the_only_icon_a_build_carries_is_found():
    icon = ROOT / "packaging" / "icons" / "guzzionboard.ico"
    assert icon.is_file(), "the Windows icon is part of what gets installed"
    assert (ROOT / "packaging" / "icons" / "guzzionboard.png").is_file()
    assert (ROOT / "packaging" / "icons" / "guzzionboard.icns").is_file()


# ------------------------------------------------------- the self-test

def test_selftest_passes_on_this_checkout(home, tmp_path, capsys):
    from guzzionboard import selftest

    code = selftest.run(export_dir=str(tmp_path / "exports"))
    output = capsys.readouterr().out
    assert code == 0, output
    assert "checks passed" in output
    assert not (home / "sessions").exists()      # the run keeps to itself


def test_selftest_writes_a_transcript_for_a_windowed_build(home, tmp_path, monkeypatch):
    from guzzionboard import selftest

    target = tmp_path / "logs" / "selftest.log"
    monkeypatch.setenv(selftest.LOG_ENV, str(target))
    assert selftest.run(export_dir=str(tmp_path / "exports")) == 0
    assert "checks passed" in target.read_text(encoding="utf-8")


def test_selftest_reports_a_failure_rather_than_crashing(home, tmp_path, monkeypatch, capsys):
    from guzzionboard import selftest

    monkeypatch.setattr(selftest, "_run_checks",
                        lambda *_: (_ for _ in ()).throw(RuntimeError("broken install")))
    assert selftest.run(export_dir=str(tmp_path / "exports")) == 1
    assert "broken install" in capsys.readouterr().out


def test_frozen_selftest_requires_the_worker_executable(home, bundle, monkeypatch, capsys):
    """A frozen build with no worker helper must say so, not fail obscurely."""
    from guzzionboard import selftest

    monkeypatch.delenv(resources.WEB_ENV, raising=False)
    assert selftest.run(export_dir=str(home / "exports")) == 1
    output = capsys.readouterr().out
    assert "isolated checksum worker executable" in output
    assert "[FAIL]" in output


# ------------------------------------------- the frozen worker, end to end

PLUGIN = '''
PROVIDER_ID = "frozen.test"
NAME = "Frozen Test"
VERSION = "1"
SUPPORTED_CHECKSUMS = ["Some XDF Title"]
VERIFIED = True


def update(image, context):
    return bytes(image)


def verify(image, context):
    return True
'''


def test_frozen_worker_is_discovered_and_runs_plugins(tmp_path, monkeypatch):
    """The whole frozen path, with a stub standing in for the built helper.

    In a real install ``GuzziOnBoard-worker`` is a PyInstaller executable; here
    it is a script that runs the same worker module, which is what proves the
    lookup, the command line and the isolated round trip all line up.
    """
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    name = resources.WORKER_EXECUTABLE + (".exe" if os.name == "nt" else "")
    stub = Path(sys.executable).with_name(name)
    stub.write_text(
        "#!/bin/sh\n"
        f'exec "{sys.executable}" -I -S -B "{ROOT / "guzzionboard" / "checksum_worker.py"}"\n'
    )
    stub.chmod(0o755)
    plugins = tmp_path / "checksums"
    plugins.mkdir()
    (plugins / "frozen_plugin.py").write_text(PLUGIN, encoding="utf-8")
    try:
        assert resources.worker_executable() == stub
        providers, errors = load_providers(plugins)
        assert not errors and len(providers) == 1
        provider = providers[0]
        assert provider.provider_id == "frozen.test"
        assert provider.supports(["Some XDF Title"])
        updated, verified = provider._isolated_apply(b"12345678", {"region": "flash"})
        assert updated == b"12345678" and verified == b"12345678"
    finally:
        stub.unlink()


def test_unfrozen_builds_run_plugins_with_this_interpreter(tmp_path):
    from guzzionboard.checksums import worker_command

    command = worker_command()
    assert command is not None and command[0] == sys.executable
    assert str(ROOT / "guzzionboard" / "checksum_worker.py") in command
    plugins = tmp_path / "checksums"
    plugins.mkdir()
    (plugins / "plugin.py").write_text(PLUGIN, encoding="utf-8")
    providers, errors = load_providers(plugins)
    assert not errors and providers[0].provider_id == "frozen.test"


# ------------------------------------------------- the page script itself

@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_bridge_script_is_valid_javascript():
    script = ROOT / "web" / "desktop-bridge.js"
    result = subprocess.run(["node", "--check", str(script)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_app_js_is_still_valid_javascript():
    result = subprocess.run(
        ["node", "--check", str(ROOT / "web" / "app.js")], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_bridge_installs_the_token_and_reroutes_saves():
    """Run the bridge in a tiny fake DOM and watch what it does."""
    harness = """
    const fs = require('fs');
    const SCRIPT = process.env.GOB_BRIDGE;
    const calls = [];

    // Node has no DOM. These stand in for the four globals the bridge uses,
    // installed on globalThis so the script and this harness agree on them.
    const fakeWindow = {
      __GOB_DESKTOP__: { token: 'tok', version: '1', backend: 'window',
                         renderer: 'x', exports: '/tmp/exports', port: 1 },
      location: { href: 'http://127.0.0.1:1/', origin: 'http://127.0.0.1:1' },
      addEventListener: () => {},
    };
    const fakeNavigator = { sendBeacon: (url) => { calls.push(['beacon', url]); return true; } };
    const fakeDocument = {
      documentElement: {}, querySelectorAll: () => [],
      addEventListener: () => {}, body: { setAttribute: () => {} },
    };
    // Records what the bridge actually attached to *this* call, not what a
    // previous call left lying around.
    class FakeHeaders {
      constructor(init) { this.map = new Map(init && init.map ? init.map : []); }
      set(k, v) { this.map.set(k, v); }
      get(k) { return this.map.get(k); }
    }
    const realFetch = (input, init) => {
      const sent = init && init.headers;
      calls.push(['fetch', input,
                  sent && sent.get ? sent.get('X-GuzziOnBoard-Token') : undefined]);
      return Promise.resolve({ ok: true, json: async () => ({}) });
    };
    fakeWindow.fetch = realFetch;
    fakeWindow.window = fakeWindow;
    // Node defines some of these itself, so they are redefined rather than
    // assigned (its `navigator` has no sendBeacon, for one).
    for (const [name, value] of Object.entries({
      window: fakeWindow, navigator: fakeNavigator, document: fakeDocument,
      fetch: realFetch, Headers: FakeHeaders,
    })) {
      Object.defineProperty(globalThis, name, { value, configurable: true, writable: true });
    }

    const source = fs.readFileSync(SCRIPT, 'utf8');
    new Function('window', 'document', 'navigator', 'fetch', 'Headers', 'URL', 'console',
                 source)(fakeWindow, fakeDocument, fakeNavigator, realFetch, FakeHeaders, URL, console);

    // a same-origin call must carry the token; a foreign one must be untouched
    fakeWindow.fetch('/api/status');
    fakeWindow.fetch('https://example.com/x');
    fakeNavigator.sendBeacon('/api/disconnect', '{}');
    console.log(JSON.stringify({ calls, api: Object.keys(fakeWindow.gobDesktop) }));
    """
    result = subprocess.run(
        ["node", "-e", harness],
        capture_output=True, text=True,
        env={**os.environ, "GOB_BRIDGE": str(ROOT / "web" / "desktop-bridge.js")},
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    token_header = "X-GuzziOnBoard-Token"
    same_origin = [c for c in payload["calls"] if c[0] == "fetch" and c[1] == "/api/status"]
    foreign = [c for c in payload["calls"] if c[0] == "fetch" and c[1].startswith("https://")]
    assert same_origin and same_origin[0][2] == "tok"
    assert foreign and foreign[0][2] is None
    beacon = [c for c in payload["calls"] if c[0] == "beacon"]
    assert beacon and "token=tok" in beacon[0][1]
    assert {"saveText", "printView", "openFolder", "quit", "openExternal"} <= set(payload["api"])


# ------------------------------------------- the window preflight and watchdog
#
# pywebview starts the window on a private GUI thread, and a failure there
# kills the process with no Python exception - which is how 0.4.0 shipped:
# the first real launch installed fine, printed "mode: window", and then
# nothing. These tests pin the two pieces that make that failure impossible
# to miss instead: everything checkable is checked on the main thread first
# (and turns into an explained browser fallback), and a watchdog opens the
# browser if the window never appears.


class FakeGuiLib:
    """Stands in for ``webview.guilib`` so no window stack is needed."""

    def __init__(self, renderer: str = "edgechromium") -> None:
        self.renderer = renderer

    def initialize(self, gui):
        return FakeGuiLib(self.renderer)


@pytest.fixture
def window_app(home):
    """A DesktopApp with a fake pywebview, as if the window stack imports."""
    app = DesktopApp()
    app.webview = types.SimpleNamespace(__version__="6.2.1")
    app.mode = "window"
    return app


def test_preflight_refuses_a_missing_webview2(window_app, monkeypatch, capsys):
    monkeypatch.setattr(guzzionboard.desktop.sys, "platform", "win32")
    monkeypatch.setattr(guzzionboard.desktop, "_webview2_build", lambda: None)
    with pytest.raises(DesktopError, match="WebView2 runtime is not installed"):
        window_app._preflight_window()
    assert "did not open a window" not in capsys.readouterr().out


def test_preflight_refuses_an_ancient_webview2(window_app, monkeypatch):
    monkeypatch.setattr(guzzionboard.desktop.sys, "platform", "win32")
    monkeypatch.setattr(guzzionboard.desktop, "_webview2_build", lambda: "79.0.309.0")
    with pytest.raises(DesktopError, match=r"older than 86\.0\.622\.0"):
        window_app._preflight_window()


def test_preflight_accepts_a_current_webview2_and_names_the_renderer(
    window_app, monkeypatch, capsys
):
    monkeypatch.setattr(guzzionboard.desktop.sys, "platform", "win32")
    monkeypatch.setattr(guzzionboard.desktop, "_webview2_build", lambda: "120.0.2210.61")
    monkeypatch.setitem(
        sys.modules, "webview.guilib", FakeGuiLib(renderer="edgechromium")
    )
    window_app._preflight_window()
    out = capsys.readouterr().out
    assert "pywebview 6.2.1" in out and "edgechromium renderer" in out


def test_preflight_refuses_a_broken_window_engine(window_app, monkeypatch):
    monkeypatch.setattr(guzzionboard.desktop.sys, "platform", "win32")
    monkeypatch.setattr(guzzionboard.desktop, "_webview2_build", lambda: "120.0.2210.61")

    class Broken:
        def initialize(self, gui):
            raise RuntimeError("cannot load pythonnet")

    monkeypatch.setitem(sys.modules, "webview.guilib", Broken())
    with pytest.raises(DesktopError, match="window engine could not be loaded"):
        window_app._preflight_window()


def test_preflight_skips_the_webview2_check_when_mshtml_is_forced(
    window_app, monkeypatch
):
    monkeypatch.setattr(guzzionboard.desktop.sys, "platform", "win32")
    window_app.gui = "mshtml"
    monkeypatch.setattr(guzzionboard.desktop, "_webview2_build", lambda: None)
    monkeypatch.setitem(sys.modules, "webview.guilib", FakeGuiLib(renderer="mshtml"))
    window_app._preflight_window()          # must not raise: mshtml needs no WebView2


def test_the_watchdog_opens_the_browser_when_the_window_never_shows(
    window_app, monkeypatch, capsys
):
    opened = []
    monkeypatch.setattr(guzzionboard.desktop, "open_url", lambda url: opened.append(url) or True)
    window_app.window_watchdog_timeout = 0.05
    window = types.SimpleNamespace(
        events=types.SimpleNamespace(shown=threading.Event())
    )
    window_app._start_window_watchdog(window)
    time.sleep(0.3)
    assert window_app.window_watchdog_fired is True
    assert opened == [window_app.url]
    out = capsys.readouterr().out
    assert "did not appear" in out and "browser" in out


def test_the_watchdog_stays_quiet_when_the_window_shows(window_app, monkeypatch):
    opened = []
    monkeypatch.setattr(guzzionboard.desktop, "open_url", lambda url: opened.append(url) or True)
    window_app.window_watchdog_timeout = 0.05
    window = types.SimpleNamespace(
        events=types.SimpleNamespace(shown=threading.Event())
    )
    window.events.shown.set()
    window_app._start_window_watchdog(window)
    time.sleep(0.2)
    assert window_app.window_watchdog_fired is False
    assert opened == []


def test_the_watchdog_stays_quiet_after_a_fallback(window_app, monkeypatch):
    """A window that already fell back to the browser needs no rescuing."""
    opened = []
    monkeypatch.setattr(guzzionboard.desktop, "open_url", lambda url: opened.append(url) or True)
    window_app.window_watchdog_timeout = 0.05
    window_app.mode = "browser-fallback"
    window = types.SimpleNamespace(
        events=types.SimpleNamespace(shown=threading.Event())
    )
    window_app._start_window_watchdog(window)
    time.sleep(0.2)
    assert window_app.window_watchdog_fired is False
    assert opened == []


def test_a_failed_window_start_falls_back_to_the_browser(window_app, monkeypatch, capsys):
    def no_window():
        raise DesktopError("the Microsoft WebView2 runtime is not installed")

    ran = []
    window_app._start_window = no_window
    window_app._run_browser = lambda: ran.append("browser")
    window_app._run_window()
    assert ran == ["browser"]
    assert window_app.mode == "browser-fallback"
    assert "WebView2 runtime is not installed" in capsys.readouterr().out


def test_the_window_icon_is_the_ico_on_windows_and_the_png_elsewhere(
    bundle, monkeypatch
):
    """0.4.0's silent launch death: the Windows backend loads the icon with
    System.Drawing.Icon, which only accepts .ico files - handing it the .png
    killed the process from the GUI thread (0xE0434352) before a window
    existed. The order here is the fix."""
    icons = bundle / "packaging" / "icons"
    icons.mkdir(parents=True)
    (icons / "guzzionboard.png").write_bytes(b"not really a png")
    (icons / "guzzionboard.ico").write_bytes(b"not really an ico")

    monkeypatch.setattr(guzzionboard.desktop.sys, "platform", "win32")
    assert DesktopApp._icon_path().name == "guzzionboard.ico"

    monkeypatch.setattr(guzzionboard.desktop.sys, "platform", "linux")
    assert DesktopApp._icon_path().name == "guzzionboard.png"


def test_the_icon_survives_a_bundle_with_only_one_kind(bundle, monkeypatch):
    icons = bundle / "packaging" / "icons"
    icons.mkdir(parents=True)
    (icons / "guzzionboard.ico").write_bytes(b"ico")
    monkeypatch.setattr(guzzionboard.desktop.sys, "platform", "win32")
    assert DesktopApp._icon_path().name == "guzzionboard.ico"
    (icons / "guzzionboard.ico").unlink()
    assert DesktopApp._icon_path() is None


def test_the_dotnet_hook_is_a_noop_without_the_clr(window_app, monkeypatch):
    """Off Windows, or without a CLR to hook, launching must not care."""
    monkeypatch.setattr(guzzionboard.desktop.sys, "platform", "linux")
    assert _hook_dotnet_unhandled() is None      # off Windows: instant return
    monkeypatch.setattr(guzzionboard.desktop.sys, "platform", "win32")
    assert _hook_dotnet_unhandled() is None      # no clr here: swallowed, not raised
