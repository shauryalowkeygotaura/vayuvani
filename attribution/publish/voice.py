"""
"Kaun?" voice answer: why is the air bad near me?

Deterministic template, no LLM call, so it fits well inside the 2 s VAPI
webhook budget. Reads the newest attribution within radius_km of the caller
(from the published feed or the store) and returns one sentence in Hindi or
English. Low-confidence results are phrased as a guess, not a fact.
"""

import json
import math
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from ..config import PUBLIC_DIR
from ..labels import CONF_HI, LABELS_EN, LABELS_HI, SECTORS_EN, SECTORS_HI

MAX_AGE_HOURS = 12


def _km(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 12742.0 * math.asin(math.sqrt(a))


def load_latest(path: Optional[str] = None) -> list[dict]:
    p = path or os.path.join(PUBLIC_DIR, "data", "latest.json")
    try:
        with open(p, encoding="utf-8") as f:
            return (json.load(f) or {}).get("attributions", [])
    except (OSError, ValueError):
        return []


def nearest(records: list[dict], lat: float, lon: float, radius_km: float = 6.0,
            now: Optional[datetime] = None, min_confidence: str = "low") -> Optional[tuple[dict, float]]:
    now = now or datetime.now(timezone.utc)
    rank = {"low": 0, "medium": 1, "high": 2}
    best = None
    for r in records:
        if rank.get(r.get("confidence"), -1) < rank[min_confidence]:
            continue
        if r.get("latitude") is None or r.get("longitude") is None:
            continue
        try:
            end = datetime.fromisoformat(str(r["window_end"]))
        except (KeyError, ValueError):
            continue
        if now - end > timedelta(hours=MAX_AGE_HOURS):
            continue
        if end > now + timedelta(hours=1):
            continue
        d = _km(lat, lon, float(r["latitude"]), float(r["longitude"]))
        if d > radius_km:
            continue
        # Nearest station first; among equally near, the newest window.
        if (best is None or d < best[1] - 0.05
                or (abs(d - best[1]) <= 0.05 and str(r["window_end"]) > str(best[0]["window_end"]))):
            best = (r, d)
    return best


def answer(lat: float, lon: float, language: str = "en", records: Optional[list[dict]] = None,
           now: Optional[datetime] = None, min_confidence: str = "low") -> Optional[str]:
    """One spoken sentence, or None when there is no recent nearby spike."""
    recs = records if records is not None else load_latest()
    hit = nearest(recs, lat, lon, now=now, min_confidence=min_confidence)
    if not hit:
        return None
    r, dist = hit
    shares = r.get("shares") or {}
    if not shares or r.get("confidence") not in ("low", "medium", "high"):
        return None
    top = max(shares, key=shares.get)
    pct = min(90, int(round(shares[top] * 100 / 10.0) * 10))
    over = shares[top] >= 0.9
    sector = r.get("sector")
    conf = r["confidence"]
    station = str(r.get("station_name", "")).split(",")[0]
    if language == "hi":
        where = f", हवा {SECTORS_HI[sector]} से आ रही है" if sector in SECTORS_HI else ""
        lead = "शायद" if conf == "low" else "अनुमान है कि"
        return (f"{station} के पास हाल में प्रदूषण बढ़ा। {lead} {'ज़्यादातर' if over else f'लगभग {pct} प्रतिशत'} "
                f"{LABELS_HI[top]} से है{where}। भरोसा {CONF_HI[conf]}।")
    where = f", with wind from the {SECTORS_EN[sector]}" if sector in SECTORS_EN else ""
    lead = "Possibly" if conf == "low" else "Our estimate:"
    return (f"Pollution spiked near {station} recently. {lead} {'most of it' if over else f'about {pct} percent'} "
            f"is {LABELS_EN[top]}{where}. Confidence {conf}.")
