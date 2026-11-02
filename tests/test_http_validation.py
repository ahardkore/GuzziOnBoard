"""Exercise malformed requests through the real HTTP handler."""
import http.client
import json
import threading
from http.server import ThreadingHTTPServer

import pytest

from guzzionboard.server import make_handler
from guzzionboard.workstation import Workstation


@pytest.fixture
def server():
    ws = Workstation(record=False)
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(ws))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()
    thread.join()
    ws.disconnect()


@pytest.mark.parametrize("body,headers,status", [
    (b"{}", {"Content-Length": "-1"}, 400),
    (b"{}", {"Content-Length": "no"}, 400),
    (b"", {"Content-Length": str(17 * 1024 * 1024)}, 413),
    (b"null", {}, 400),
    (b"[]", {}, 400),
    (b'"text"', {}, 400),
    (b"\xff", {}, 400),
    (b'{"value": NaN}', {}, 400),
    (b"{}", {"Transfer-Encoding": "chunked"}, 400),
])
def test_invalid_request_is_rejected(server, body, headers, status):
    conn = http.client.HTTPConnection(*server.server_address, timeout=3)
    try:
        conn.request("POST", "/api/disconnect", body=body, headers=headers)
        response = conn.getresponse()
        assert response.status == status
        assert b"error" in response.read()
    finally:
        conn.close()


def test_the_map_library_route_lists_the_bundled_definitions(server):
    """GET /api/maps/library is read-only and needs no vehicle or adapter."""
    conn = http.client.HTTPConnection(*server.server_address, timeout=30)
    try:
        conn.request("GET", "/api/maps/library")
        response = conn.getresponse()
        payload = json.loads(response.read())
    finally:
        conn.close()
    assert response.status == 200
    assert payload["definitions"] == len(payload["xdfs"]) >= 121
    assert payload["tables"] >= 4000
    first = payload["xdfs"][0]
    assert first["brand"] and first["tables"]
    assert {"title", "address", "rows", "cols"} <= set(first["tables"][0])
