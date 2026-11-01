"""
VAPI server-URL webhook: tool-call in, spoken result out.

Request (VAPI "tool-calls" server message): {"message": {"type": "tool-calls",
"toolCallList": [{"id", "function": {"name", "arguments"}}], "call": {...}}}.
Sources disagree on toolCallList vs toolCalls and on name/arguments nesting
(https://docs.vapi.ai/tools/custom-tools, support threads), so all shapes are
accepted. Response: {"results": [{"toolCallId", "result"}]}, result a single
line string, one entry per tool call.

Auth: if VAPI_SERVER_SECRET is set, the X-Vapi-Secret header must match.
"""

import hmac
import json
import os
from typing import Any

from . import service

TOOLS = {"get_air_quality", "report_pollution"}


def _args(call: dict) -> dict:
    fn = call.get("function") or {}
    raw = fn.get("arguments", call.get("arguments", {}))
    if isinstance(raw, str):
        try:
            raw = json.loads(raw or "{}")
        except ValueError:
            raw = {}
    return raw if isinstance(raw, dict) else {}


def _name(call: dict) -> str:
    return str((call.get("function") or {}).get("name") or call.get("name") or "")


def _one_line(text: str) -> str:
    return " ".join(str(text).split())


def run_tool(name: str, args: dict, message: dict, allow_network: bool = True) -> str:
    call = message.get("call") or {}
    customer = call.get("customer") or message.get("customer") or {}
    if name == "get_air_quality":
        out = service.get_air_quality(str(args.get("location", "")), str(args.get("language", "en")),
                                      allow_network=allow_network)
    elif name == "report_pollution":
        out = service.report_pollution(
            str(args.get("location", "")), str(args.get("pollution_type", "other")),
            str(args.get("details", "")), str(args.get("language", "en")),
            call_id=call.get("id"), caller=customer.get("number"), allow_network=allow_network)
    else:
        return "Unknown tool."
    return _one_line(out["speech"])


def handle(body: Any, headers: dict, allow_network: bool = True) -> tuple[int, dict]:
    secret = os.getenv("VAPI_SERVER_SECRET", "")
    if secret:
        got = next((v for k, v in headers.items() if k.lower() == "x-vapi-secret"), "")
        if not hmac.compare_digest(str(got), secret):
            return 401, {"error": "bad secret"}
    if isinstance(body, (bytes, str)):
        try:
            body = json.loads(body or "{}")
        except ValueError:
            return 400, {"error": "invalid JSON"}
    if not isinstance(body, dict):
        return 400, {"error": "expected JSON object"}
    message = body.get("message") or {}
    if message.get("type") not in ("tool-calls", "function-call", None):
        return 200, {}  # status updates, transcripts, end-of-call: acknowledge and ignore
    calls = (message.get("toolCallList") or message.get("toolCalls")
             or [tc.get("toolCall", tc) for tc in message.get("toolWithToolCallList") or []])
    results = []
    for c in calls or []:
        if not isinstance(c, dict):
            continue
        name = _name(c)
        try:
            text = run_tool(name, _args(c), message, allow_network) if name in TOOLS else "Unknown tool."
        except Exception:  # never drop a call: say something useful
            text = "Sorry, something went wrong on our side. Please try again."
        results.append({"toolCallId": str(c.get("id", "")), "result": text})
    return 200, {"results": results}
