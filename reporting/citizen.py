"""
Turn phone-line citizen reports into agency reports, independent of the call.

A cluster = reports of the same type within CLUSTER_KM of each other in the
last 24 h. A cluster is reportable when:
  - >= MIN_REPORTS distinct callers (or distinct calls when the number is
    hidden) reported it, OR
  - >= 1 report AND a Kaun attribution within CORROBORATE_KM / 6 h agrees on
    the source class (e.g. "burning" call + biomass_burning spike).
One caller repeating themselves never counts twice (hashed number).
"other" reports are never auto-routed: there is no owning agency.
"""

import hashlib
import json
import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Optional

from attribution.labels import CITIZEN_TYPE_TO_SOURCE
from attribution.store import get_store

from .agencies import agencies_for
from .queue import APPROVE_URL, existing_ids

logger = logging.getLogger(__name__)

CLUSTER_KM = 1.5
CORROBORATE_KM = 4.0
MIN_REPORTS = 3
WINDOW_H = 24


def _km(a, b) -> float:
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    x = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(b[1] - a[1]) / 2) ** 2)
    return 12742.0 * math.asin(math.sqrt(x))


def _ts(v) -> Optional[datetime]:
    try:
        t = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def clusters(reports: list[dict]) -> list[list[dict]]:
    """Greedy single-link clustering by type and distance."""
    out: list[list[dict]] = []
    for r in sorted(reports, key=lambda r: str(r.get("timestamp"))):
        if r.get("latitude") is None or r.get("longitude") is None:
            continue
        p = (float(r["latitude"]), float(r["longitude"]))
        for c in out:
            if c[0]["pollution_type"] == r["pollution_type"] and any(
                    _km(p, (float(x["latitude"]), float(x["longitude"]))) <= CLUSTER_KM for x in c):
                c.append(r)
                break
        else:
            out.append([r])
    return out


def _distinct_callers(c: list[dict]) -> int:
    return len({r.get("caller_number") or r.get("call_id") or r.get("id") for r in c})


def _corroborating(c: list[dict], attributions: list[dict]) -> Optional[dict]:
    source = CITIZEN_TYPE_TO_SOURCE.get(c[0]["pollution_type"])
    centre = (sum(float(r["latitude"]) for r in c) / len(c), sum(float(r["longitude"]) for r in c) / len(c))
    first = min(_ts(r["timestamp"]) for r in c)
    for a in attributions:
        shares = a.get("shares") or {}
        if isinstance(shares, str):
            shares = json.loads(shares)
        if a.get("latitude") is None or shares.get(source, 0) < 0.3:
            continue
        end = _ts(a.get("window_end"))
        if end is None or abs((end - first).total_seconds()) > 6 * 3600:
            continue
        if _km(centre, (float(a["latitude"]), float(a["longitude"]))) <= CORROBORATE_KM:
            return a
    return None


def enqueue_clusters(store=None, now: Optional[datetime] = None, attributions: Optional[list[dict]] = None) -> list[dict]:
    store = store or get_store()
    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(hours=WINDOW_H)).isoformat()
    reports = [r for r in store.select("citizen_reports", {"timestamp": f"gte.{since}"})
               if r.get("pollution_type") in CITIZEN_TYPE_TO_SOURCE and _ts(r.get("timestamp"))]
    if attributions is None:
        attributions = store.select("attributions", {"window_start": f"gte.{(now - timedelta(hours=30)).isoformat()}"})
    seen = existing_ids(store)
    rows = []
    for c in clusters(reports):
        n = _distinct_callers(c)
        corr = _corroborating(c, attributions)
        if n < MIN_REPORTS and not corr:
            continue
        ptype = c[0]["pollution_type"]
        source = CITIZEN_TYPE_TO_SOURCE[ptype]
        first = min(_ts(r["timestamp"]) for r in c)
        key = f"citizen|{ptype}|{round(float(c[0]['latitude']), 2)}|{round(float(c[0]['longitude']), 2)}|{first:%Y-%m-%d}"
        item_id = hashlib.sha1(key.encode()).hexdigest()[:16]
        if item_id in seen:
            continue
        places = sorted({r.get("neighborhood") or "?" for r in c})
        conf = "high" if corr and n >= 2 else "medium"
        lines = [f"# Citizen reports: {ptype} near {', '.join(places)}", "",
                 f"- Reports: {len(c)} from {n} distinct callers, first at {first:%Y-%m-%d %H:%M} UTC",
                 f"- Location (approx.): {float(c[0]['latitude']):.4f}, {float(c[0]['longitude']):.4f}"]
        for r in c[:10]:
            if r.get("description"):
                lines.append(f"  - \"{str(r['description'])[:200]}\"")
        if corr:
            lines.append(f"- Corroborated by station data: {corr.get('summary_en', '')}")
        rows.append({
            "attribution_id": item_id, "kind": "citizen", "station_id": corr.get("station_id") if corr else None,
            "agencies": list(agencies_for(source)), "top_source": source, "confidence": conf,
            "latitude": float(c[0]["latitude"]), "longitude": float(c[0]["longitude"]),
            "window_start": first.isoformat(),
            "summary": f"{len(c)} caller reports of {ptype} near {', '.join(places)}"
                       + (" (station data agrees)" if corr else ""),
            "evidence_md": "\n".join(lines), "status": "pending", "approve_url": APPROVE_URL,
            "created_at": now.isoformat(),
        })
    if rows:
        store.upsert("complaint_queue", rows)
    logger.info(f"Citizen: {len(reports)} reports -> {len(rows)} new queued clusters")
    return rows
