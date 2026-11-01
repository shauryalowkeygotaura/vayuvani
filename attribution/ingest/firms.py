"""
NASA FIRMS active fire points (VIIRS x3 + MODIS) within ~300 km of Delhi.

API: https://firms.modaps.eosdis.nasa.gov/api/area/csv/{MAP_KEY}/{SOURCE}/{W,S,E,N}/{DAYS}
Key: free MAP_KEY in FIRMS_MAP_KEY. FIRMS answers some errors with HTTP 200 and
a plain-text body ("Invalid MAP_KEY."), so the CSV header is validated, not
just the status code.
"""

import csv
import io
import logging
import math
import os
from datetime import datetime, timezone
from typing import Optional

from .. import http
from ..config import DELHI_LAT, DELHI_LON, FIRE_RADIUS_KM, FIRMS_BBOX, FIRMS_DAY_RANGE, FIRMS_SOURCES

logger = logging.getLogger(__name__)

BASE = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
STATUS_URL = "https://firms.modaps.eosdis.nasa.gov/mapserver/mapkey_status/"
REQUIRED_COLS = {"latitude", "longitude", "acq_date", "acq_time", "frp", "confidence"}


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def bearing_deg(lat1, lon1, lat2, lon2) -> float:
    """Initial bearing from point 1 to point 2, degrees clockwise from north."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def _confidence(raw: str) -> Optional[str]:
    """VIIRS gives n/l/h; MODIS gives 0-100. Normalise to low/nominal/high."""
    raw = (raw or "").strip().lower()
    if raw in ("l", "low"):
        return "low"
    if raw in ("n", "nominal"):
        return "nominal"
    if raw in ("h", "high"):
        return "high"
    try:
        v = float(raw)
    except ValueError:
        return None
    return "low" if v < 30 else "high" if v >= 80 else "nominal"


def parse_csv(text: str, source: str) -> list[dict]:
    if not text.strip():
        return []
    reader = csv.DictReader(io.StringIO(text))
    cols = set(reader.fieldnames or [])
    if not REQUIRED_COLS.issubset(cols):
        raise http.BadResponse(f"FIRMS {source}: unexpected body: {text[:160]!r}")
    out = []
    for r in reader:
        try:
            lat, lon = float(r["latitude"]), float(r["longitude"])
            t = r["acq_time"].strip().zfill(4)
            acq = datetime.strptime(f"{r['acq_date']} {t}", "%Y-%m-%d %H%M").replace(tzinfo=timezone.utc)
            frp = float(r["frp"]) if r.get("frp") not in (None, "") else None
        except (KeyError, ValueError):
            continue
        dist = haversine_km(DELHI_LAT, DELHI_LON, lat, lon)
        if dist > FIRE_RADIUS_KM:
            continue
        out.append({
            "source": source, "latitude": lat, "longitude": lon, "acq_time": acq,
            "frp": frp, "confidence": _confidence(r.get("confidence", "")),
            "daynight": (r.get("daynight") or "").strip() or None,
            "dist_km": round(dist, 1),
            "bearing_from_delhi": round(bearing_deg(DELHI_LAT, DELHI_LON, lat, lon), 1),
        })
    return out


def check_key(key: str) -> dict:
    """Pre-flight: FIRMS reports the key's transaction quota. Raises on a bad key."""
    data = http.get_json(STATUS_URL, params={"MAP_KEY": key})
    if not isinstance(data, dict) or "transaction_limit" not in data:
        raise http.AuthError(f"FIRMS MAP_KEY rejected: {str(data)[:160]}")
    return data


ARCHIVE_SOURCES = ("VIIRS_SNPP_SP", "MODIS_SP")  # standard-processing archive for backfill


def fetch(day_range: int = FIRMS_DAY_RANGE, date: Optional[str] = None,
          sources: tuple = FIRMS_SOURCES) -> list[dict]:
    """date: optional YYYY-MM-DD start for historical pulls (use ARCHIVE_SOURCES)."""
    key = os.environ.get("FIRMS_MAP_KEY", "").strip()
    if not key:
        raise http.AuthError("FIRMS_MAP_KEY not set")
    bbox = ",".join(str(v) for v in FIRMS_BBOX)
    fires: list[dict] = []
    if date is not None:
        datetime.strptime(date, "%Y-%m-%d")  # whitelist: must be a real date
    suffix = f"/{date}" if date else ""
    for src in sources:
        try:
            text = http.get_text(f"{BASE}/{key}/{src}/{bbox}/{int(day_range)}{suffix}")
        except (http.AuthError, http.RateLimited):
            raise
        except http.ExternalError as e:
            logger.warning(f"FIRMS {src}: {e}")
            continue
        if "invalid" in text[:80].lower() and "map_key" in text[:80].lower():
            raise http.AuthError(f"FIRMS rejected MAP_KEY: {text[:80]!r}")
        fires.extend(parse_csv(text, src))
    logger.info(f"FIRMS: {len(fires)} fire points within {FIRE_RADIUS_KM:.0f} km")
    return fires
