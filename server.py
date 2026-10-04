"""Dependency-free prototype server for GuzziOnBoard.

The API is intentionally simulator-only. It is a seam for a future local desktop
shell and does not open serial ports or send ECU frames.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
from guzzionboard_core import SimulatorTransport, VehicleIdentity, identity_dict

ROOT = Path(__file__).parent
transport = SimulatorTransport()
identity = VehicleIdentity("Moto Guzzi", "V85 TT", 2021, "IAW 7SM", "7643A102")

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_): pass
    def send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status); self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store"); self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        if self.path == "/api/status":
            self.send_json({"mode": "simulator", "connected": transport.connected,
                            "ecu": f"{identity.ecu_family} (simulated)",
                            "vehicle": f"{identity.make} {identity.model} (simulated)",
                            "identity": identity_dict(identity),
                            "values": transport.values().json_values(),
                            "faults": [f.__dict__ for f in transport.faults]}); return
        if self.path == "/api/live": self.send_json(transport.values().json_values()); return
        path = (ROOT / self.path.lstrip("/")) if self.path != "/" else ROOT / "index.html"
        if path.is_file():
            data = path.read_bytes(); self.send_response(200)
            self.send_header("Content-Type", {".html":"text/html", ".js":"text/javascript", ".css":"text/css"}.get(path.suffix, "application/octet-stream"))
            self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data); return
        self.send_error(404)
    def do_POST(self):
        if self.path == "/api/connect": transport.connect(); self.send_json({"ok": True}); return
        if self.path == "/api/disconnect": transport.disconnect(); self.send_json({"ok": True}); return
        if self.path == "/api/clear-faults": transport.clear_faults(); self.send_json({"ok": True}); return
        if self.path == "/api/export": self.send_json({"ok": True, "message": "Report prepared in simulator mode"}); return
        self.send_json({"ok": False, "error": "Operation unavailable in simulator"}, 403)

if __name__ == "__main__":
    print("GuzziOnBoard prototype listening on http://0.0.0.0:8000")
    ThreadingHTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
