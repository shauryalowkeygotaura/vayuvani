"""
OpenAQ v3 hourly ingest: all six pollutants per Delhi-NCR station, per hour.

Extends pipeline/fetcher.py (which only keeps the latest value) to hourly
history via /v3/sensors/{id}/hours, so the spike detector has a real baseline.
Reuses the fetcher's base URL and the same two 25 km sweep centres.

Rate limit: OpenAQ's free tier is 60 requests/minute, so calls are paced.
"""

import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from pipeline.fetcher import OPENAQ_BASE

from .. import http
from ..config import POLLUTANTS
from .units import station_slug, to_standard

logger = logging.getLogger(__name__)

SWEEP_CENTRES = ((28.7041, 77.1025), (28.5355, 77.3910))
RADIUS_M = 25000
PACE_S = 1.05
STALE_DAYS = 7


def _headers() -> dict:
    key = os.getenv("OPENAQ_API_KEY", "")
    return {"X-API-Key": key} if key else {}


def _parse_dt(raw) -> Optional[datetime]:
    if isinstance(raw, dict):
        raw = raw.get("utc")
    if not raw or not isinstance(raw, str):
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def parse_locations(payloads: list[dict], now: Optional[datetime] = None) -> list[dict]:
    """
    Flatten /locations pages into station dicts with a sensor map, dropping
    duplicates, locations without coordinates, and stations silent for a week.
    """
    now = now or datetime.now(timezone.utc)
    seen: set = set()
    out: list[dict] = []
    for payload in payloads:
        results = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(results, list):
            raise http.BadResponse("OpenAQ /locations: missing 'results' list")
        for loc in results:
            loc_id = loc.get("id")
            coords = loc.get("coordinates") or {}
            lat, lon = coords.get("latitude"), coords.get("longitude")
            name = (loc.get("name") or "").strip()
            if not loc_id or loc_id in seen or lat is None or lon is None or not name:
                continue
            last = _parse_dt(loc.get("datetimeLast"))
            if last and now - last > timedelta(days=STALE_DAYS):
                continue
            sensors = {}
            for s in loc.get("sensors") or []:
                p = (s.get("parameter") or {})
                pname = (p.get("name") or "").lower()
                if s.get("id") and pname in POLLUTANTS:
                    sensors[s["id"]] = {"param": pname, "units": p.get("units")}
            if not sensors:
                continue
            seen.add(loc_id)
            out.append({
                "id": station_slug(name),
                "name": name,
                "latitude": float(lat),
                "longitude": float(lon),
                "openaq_location_id": loc_id,
                "sensors": sensors,
            })
    return out


def fetch_locations() -> list[dict]:
    pages = []
    for lat, lon in SWEEP_CENTRES:
        pages.append(http.get_json(
            f"{OPENAQ_BASE}/locations",
            params={"coordinates": f"{lat},{lon}", "radius": RADIUS_M, "limit": 1000},
            headers=_headers(),
        ))
        time.sleep(PACE_S)
    stations = parse_locations(pages)
    logger.info(f"OpenAQ: {len(stations)} active Delhi-NCR stations")
    return stations


def parse_hours(payload: dict, param: str, units: Optional[str]) -> list[tuple[datetime, float]]:
    """(hour_start_utc, value_in_house_units) pairs from one /sensors/{id}/hours page."""
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        raise http.BadResponse("OpenAQ /hours: missing 'results' list")
    out = []
    for r in results:
        period = r.get("period") or {}
        start = _parse_dt(period.get("datetimeFrom"))
        if start is None:
            continue
        u = ((r.get("parameter") or {}).get("units")) or units
        v = to_standard(param, r.get("value"), u)
        if v is None:
            continue
        out.append((start.replace(minute=0, second=0, microsecond=0), v))
    return out


def fetch_hourly(stations: list[dict], since: datetime, until: datetime) -> list[dict]:
    """
    Hourly rows for every station in [since, until). One row per station-hour,
    pollutants merged across sensors. Raises AuthError/RateLimited upward so the
    runner can checkpoint; other per-sensor failures are logged and skipped.
    """
    rows: dict[tuple[str, datetime], dict] = {}
    for st in stations:
        for sensor_id, meta in st["sensors"].items():
            try:
                payload = http.get_json(
                    f"{OPENAQ_BASE}/sensors/{int(sensor_id)}/hours",
                    params={
                        "datetime_from": since.isoformat(),
                        "datetime_to": until.isoformat(),
                        "limit": 1000,
                    },
                    headers=_headers(),
                )
            except (http.AuthError, http.RateLimited):
                raise
            except http.ExternalError as e:
                logger.warning(f"OpenAQ sensor {sensor_id} ({st['name']}): {e}")
                continue
            finally:
                time.sleep(PACE_S)
            for hour, value in parse_hours(payload, meta["param"], meta["units"]):
                key = (st["id"], hour)
                row = rows.setdefault(key, {"station_id": st["id"], "hour": hour, "source": "openaq"})
                row[meta["param"]] = value
    logger.info(f"OpenAQ: {len(rows)} station-hours between {since:%Y-%m-%d %H:%M} and {until:%H:%M} UTC")
    return list(rows.values())
