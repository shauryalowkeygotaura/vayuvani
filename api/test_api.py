"""The Vercel handler wires HTTP to voice.vapi.handle."""

import io
import json

from api import vapi as entry


class FakeHandler(entry.handler):
    def __init__(self, body: bytes, headers: dict):
        self.rfile, self.wfile = io.BytesIO(body), io.BytesIO()
        self.headers = {"Content-Length": str(len(body)), **headers}
        self.sent = []

    def send_response(self, code, message=None):
        self.sent.append(code)

    def send_header(self, *a):
        pass

    def end_headers(self):
        pass


def test_post_roundtrip():
    body = json.dumps({"message": {"type": "status-update"}}).encode()
    h = FakeHandler(body, {})
    h.do_POST()
    assert h.sent == [200] and json.loads(h.wfile.getvalue()) == {}


def test_body_limit():
    h = FakeHandler(b"", {})
    h.headers["Content-Length"] = str(entry.MAX_BODY + 1)
    h.do_POST()
    assert h.sent == [413]
