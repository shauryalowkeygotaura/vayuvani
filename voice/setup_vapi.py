"""
Create or update the VayuVani assistant on VAPI from voice/assistant.json.

    VAPI_API_KEY=... WEBHOOK_URL=https://<vercel-domain>/api/vapi \
      VAPI_VOICE_ID=<11labs voice> python -m voice.setup_vapi [--assistant-id ID]

Pre-flight: refuses to run with a placeholder webhook URL or voice id, or
without VAPI_API_KEY. Prints the assistant id; attach a phone number to it in
the VAPI dashboard (buy one there, or import a Twilio number).
The server secret is set from VAPI_SERVER_SECRET so only VAPI can call the webhook.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

API = "https://api.vapi.ai"
HERE = os.path.dirname(__file__)


def build_config() -> dict:
    with open(os.path.join(HERE, "assistant.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    url = os.environ.get("WEBHOOK_URL", "")
    voice = os.environ.get("VAPI_VOICE_ID", "")
    if not url.startswith("https://") or "REPLACE" in url:
        sys.exit("WEBHOOK_URL must be the deployed https://<domain>/api/vapi")
    if not voice:
        sys.exit("VAPI_VOICE_ID not set: pick a Hindi-capable voice in the VAPI/ElevenLabs dashboard")
    secret = os.environ.get("VAPI_SERVER_SECRET", "")
    for tool in cfg["model"]["tools"]:
        tool["server"] = {"url": url, **({"secret": secret} if secret else {})}
    cfg["voice"]["voiceId"] = voice
    return cfg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--assistant-id")
    args = ap.parse_args()
    key = os.environ.get("VAPI_API_KEY", "")
    if not key:
        sys.exit("VAPI_API_KEY not set: dashboard.vapi.ai -> API Keys (private key)")
    cfg = build_config()
    method, path = ("PATCH", f"/assistant/{args.assistant_id}") if args.assistant_id else ("POST", "/assistant")
    req = urllib.request.Request(f"{API}{path}", data=json.dumps(cfg).encode(), method=method,
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            out = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        sys.exit(f"VAPI {e.code}: {e.read().decode()[:500]}")
    print(f"assistant id: {out.get('id')}")


if __name__ == "__main__":
    main()
