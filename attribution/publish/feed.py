"""
Static JSON feed for the public page (public/index.html).

Writes:
    public/data/latest.json    newest attribution per station (last 48 h) + run metadata
    public/data/history.json   all attributions from the last 7 days (trimmed evidence)

Only records with a confidence are published (CLAUDE.md rule). Synthetic
records are refused outright.
"""

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from ..config import DATA_SUBDIR, PUBLIC_DIR

DISCLAIMER = (
    "Observation-driven estimates from station ratios, wind and fire data. "
    "Traffic vs smoke (CO/PM2.5) is the most reliable split; 3+ source separation "
    "from station data alone is fuzzy. Every share carries a confidence; read it."
)


def _trim(rec: dict) -> dict:
    r = {k: v for k, v in rec.items() if k != "evidence"}
    ev = rec.get("evidence") or {}
    if isinstance(ev, str):
        try:
            ev = json.loads(ev)
        except ValueError:
            ev = {}
    r["evidence"] = {k: ev.get(k) for k in ("ratios", "wind", "cbpf_top_sector", "upwind_fires",
                                            "nmf_pm25_shares", "confidence_notes", "hourly")}
    return r


def _validate(rec: dict) -> None:
    if rec.get("confidence") not in ("low", "medium", "high"):
        raise ValueError(f"attribution {rec.get('id')} has no valid confidence; refusing to publish")
    if rec.get("synthetic"):
        raise ValueError("synthetic attribution passed to the public feed")


def _as_dict(v):
    if isinstance(v, str):
        try:
            return json.loads(v)
        except ValueError:
            return {}
    return v or {}


def build(records: list[dict], stations: dict[str, dict], now: Optional[datetime] = None,
          run_meta: Optional[dict] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    recent, history = {}, []
    for rec in records:
        rec = dict(rec)
        rec["shares"] = _as_dict(rec.get("shares"))
        _validate(rec)
        end = datetime.fromisoformat(str(rec["window_end"]))
        if end < now - timedelta(days=7):
            continue
        t = _trim(rec)
        history.append(t)
        if end >= now - timedelta(hours=48):
            prev = recent.get(rec["station_id"])
            if prev is None or str(prev["window_end"]) < str(rec["window_end"]):
                recent[rec["station_id"]] = t
    history.sort(key=lambda r: str(r["window_end"]), reverse=True)
    return {
        "latest": {
            "generated_at": now.isoformat(),
            "disclaimer": DISCLAIMER,
            "run": run_meta or {},
            "stations": [{"id": k, **v} for k, v in sorted(stations.items())],
            "attributions": sorted(recent.values(), key=lambda r: str(r["window_end"]), reverse=True),
        },
        "history": {"generated_at": now.isoformat(), "attributions": history},
    }


def write(feed: dict, root: Optional[str] = None) -> list[str]:
    d = os.path.join(root or PUBLIC_DIR, DATA_SUBDIR)
    os.makedirs(d, exist_ok=True)
    paths = []
    for name in ("latest", "history"):
        p = os.path.join(d, f"{name}.json")
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(feed[name], f, ensure_ascii=False, indent=1, default=str)
        os.replace(tmp, p)
        paths.append(p)
    return paths
