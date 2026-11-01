"""
Vercel serverless entrypoint for the VAPI webhook (Python runtime, not edge).
All logic lives in voice/vapi.py so it is testable without Vercel.
"""

import json
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from voice.vapi import handle  # noqa: E402

MAX_BODY = 256 * 1024


class handler(BaseHTTPRequestHandler):
    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        if n > MAX_BODY:
            return self._send(413, {"error": "body too large"})
        raw = self.rfile.read(n) if n else b""
        code, payload = handle(raw, dict(self.headers.items()))
        self._send(code, payload)

    def do_GET(self):
        self._send(200, {"ok": True, "service": "vayuvani-vapi-webhook"})
