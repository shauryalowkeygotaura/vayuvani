"""
Read the published feeds (now.json for AQI, latest.json for Kaun attributions).

The webhook never touches the database for reads: the hourly cron publishes
static JSON to GitHub Pages, and this module fetches it with a 5-minute
in-memory cache (warm serverless instances reuse it). Local files under
public/data are used when FEED_BASE_URL is unset (dev and tests).
"""

import json
import os
import time
import urllib.request
from typing import Optional

DEFAULT_BASE = "https://shauryalowkeygotaura.github.io/vayuvani/data"
TTL_S = 300
_cache: dict[str, tuple[float, dict]] = {}


def _base() -> str:
    return os.getenv("FEED_BASE_URL", "").rstrip("/")


def _local_path(name: str) -> str:
    root = os.getenv("KAUN_PUBLIC_DIR", os.path.join(os.path.dirname(__file__), "..", "public"))
    return os.path.join(root, "data", name)


def load(name: str, timeout: float = 1.0) -> Optional[dict]:
    """name: 'now.json' or 'latest.json'. Returns None if unavailable."""
    hit = _cache.get(name)
    if hit and time.monotonic() - hit[0] < TTL_S:
        return hit[1]
    data = None
    base = _base()
    if base:
        try:
            req = urllib.request.Request(f"{base}/{name}", headers={"Cache-Control": "no-cache"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
        except (OSError, ValueError):
            data = None
    else:
        try:
            with open(_local_path(name), encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = None
    if isinstance(data, dict):
        _cache[name] = (time.monotonic(), data)
        return data
    return hit[1] if hit else None  # serve stale over nothing


def clear_cache() -> None:
    _cache.clear()
