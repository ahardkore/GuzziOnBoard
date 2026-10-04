"""Dependency-free prototype server for GuzziOnBoard.

The API is intentionally simulator-only. It is a seam for a future local desktop
shell and does not open serial ports or send ECU frames.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json, random, time

ROOT = Path(__file__).parent
START = time.time()
rng = random.Random(42)
state = {"connected": False, "faults": [
    {"code": "P0130", "title": "Lambda sensor circuit", "status": "stored", "severity": "warning"},
    {"code": "P0505", "title": "Idle control system", "status": "historic", "severity": "info"},
]}


def payload():
    t = time.time() - START
    return {
        "timestamp": time.time(), "rpm": round(1180 + 35 * __import__('math').sin(t * 1.4)),
        "coolant": round(78 + 1.8 * __import__('math').sin(t / 4), 1),
        "battery": round(13.9 + .08 * __import__('math').sin(t / 3), 2),
        "throttle": round(3.2 + .25 * __import__('math').sin(t * 1.1), 2),
        "air": round(31 + 1.2 * __import__('math').sin(t / 5), 1),
        "lambda": round(.98 + .025 * __import__('math').sin(t * 2.1), 3),
    }

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_): pass
    def send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status); self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store"); self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        if self.path == "/api/status":
            self.send_json({"mode": "simulator", "connected": state["connected"], "ecu": "IAW 7SM (simulated)", "vehicle": "Moto Guzzi V85 TT (simulated)", "values": payload(), "faults": state["faults"]}); return
        if self.path == "/api/live": self.send_json(payload()); return
        path = (ROOT / self.path.lstrip("/")) if self.path != "/" else ROOT / "index.html"
        if path.is_file():
            data = path.read_bytes(); self.send_response(200)
            self.send_header("Content-Type", {".html":"text/html", ".js":"text/javascript", ".css":"text/css"}.get(path.suffix, "application/octet-stream"))
            self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data); return
        self.send_error(404)
    def do_POST(self):
        if self.path == "/api/connect": state["connected"] = True; self.send_json({"ok": True}); return
        if self.path == "/api/disconnect": state["connected"] = False; self.send_json({"ok": True}); return
        if self.path == "/api/clear-faults": state["faults"] = []; self.send_json({"ok": True}); return
        if self.path == "/api/export":
            self.send_json({"ok": True, "message": "Report prepared in simulator mode"}); return
        self.send_json({"ok": False, "error": "Operation unavailable in simulator"}, 403)

if __name__ == "__main__":
    print("GuzziOnBoard prototype listening on http://0.0.0.0:8000")
    ThreadingHTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
