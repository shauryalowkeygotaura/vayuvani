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
from ..config import EXTRA_VARS, POLLUTANTS, REGION
from .units import station_slug, to_standard

logger = logging.getLogger(__name__)

SWEEP_CENTRES = tuple(REGION["sweeps"])   # attribution/regions.py; Delhi = two 25 km sweeps
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


WIND_PARAMS = ("wind_speed", "wind_direction")
# OpenAQ parameter name -> our column, for the extra evidence variables.
EXTRA_PARAMS = {"no": "no", "relativehumidity": "rh", "temperature": "temp"}  # nox: see config.py


def parse_locations(payloads: list[dict], now: Optional[datetime] = None) -> list[dict]:
    """
    Flatten /locations pages into station dicts.

    Live-API facts this handles (checked 2026-11-01):
    - Dead locations carry datetimeLast = null or a years-old date: dropped.
    - Low-cost sensor sites have isMonitor = false: dropped (reference monitors only).
    - One CPCB station lists 2+ sensors per pollutant (an old ug/m3 one that has
      stopped and a new ppb/ug/m3 one). Sensors are kept per parameter, newest id
      first, and fetch_hourly falls through to the next only if one is empty.
    - Stations also expose wind_speed / wind_direction sensors: kept, so the
      engine can prefer station wind over modelled wind.
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
            if loc.get("isMonitor") is False:
                continue
            last = _parse_dt(loc.get("datetimeLast"))
            if last is None or now - last > timedelta(days=STALE_DAYS):
                continue
            by_param: dict[str, list[dict]] = {}
            for s in loc.get("sensors") or []:
                p = (s.get("parameter") or {})
                pname = (p.get("name") or "").lower()
                pname = EXTRA_PARAMS.get(pname, pname)
                if s.get("id") and (pname in POLLUTANTS or pname in WIND_PARAMS or pname in EXTRA_VARS):
                    by_param.setdefault(pname, []).append({"id": int(s["id"]), "units": p.get("units")})
            if not any(p in by_param for p in POLLUTANTS):
                continue
            for lst in by_param.values():
                lst.sort(key=lambda x: -x["id"])
            seen.add(loc_id)
            out.append({
                "id": station_slug(name),
                "name": name,
                "latitude": float(lat),
                "longitude": float(lon),
                "openaq_location_id": loc_id,
                "sensors": by_param,
            })
    # Two live locations can share a slug (renamed sites): keep the fresher one.
    uniq: dict[str, dict] = {}
    for st in out:
        uniq.setdefault(st["id"], st)
    return list(uniq.values())


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


def _label_hour(start: datetime) -> datetime:
    """
    OpenAQ CPCB hours run :30 to :30 UTC (whole IST hours). Label each by the
    UTC hour nearest its midpoint, so 19:30-20:30 becomes 20:00 and lines up
    with Open-Meteo's instantaneous 20:00 wind.
    """
    return (start + timedelta(minutes=30)).replace(minute=0, second=0, microsecond=0)


def parse_hours(payload: dict, param: str, units: Optional[str]) -> list[tuple[datetime, float]]:
    """(hour_utc, value_in_house_units) pairs from one /sensors/{id}/hours page."""
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        raise http.BadResponse("OpenAQ /hours: missing 'results' list")
    out = []
    for r in results:
        period = r.get("period") or {}
        start = _parse_dt(period.get("datetimeFrom"))
        if start is None:
            continue
        # Partial hours (e.g. 1 of 4 quarter-hour samples) are noisy and bias the
        # newest hour; keep only >= 75% complete when OpenAQ reports coverage.
        pc = (r.get("coverage") or {}).get("percentComplete")
        if isinstance(pc, (int, float)) and pc < 75:
            continue
        u = ((r.get("parameter") or {}).get("units")) or units
        if param in WIND_PARAMS:
            try:
                v = float(r.get("value"))
            except (TypeError, ValueError):
                continue
            if v != v or v < 0 or (param == "wind_direction" and v > 360) or (param == "wind_speed" and v > 60):
                continue
        else:
            v = to_standard(param, r.get("value"), u)
            if v is None:
                continue
        out.append((_label_hour(start), v))
    return out


def _fetch_sensor(sensor_id: int, since: datetime, until: datetime) -> dict:
    return http.get_json(
        f"{OPENAQ_BASE}/sensors/{int(sensor_id)}/hours",
        params={"datetime_from": since.isoformat(), "datetime_to": until.isoformat(), "limit": 1000},
        headers=_headers(),
    )


def fetch_hourly(stations: list[dict], since: datetime, until: datetime) -> tuple[list[dict], list[dict]]:
    """
    Returns (pollutant_rows, station_wind_rows) for [since, until). For each
    parameter, sensors are tried newest first; the first with data wins.
    AuthError/RateLimited propagate so the runner can checkpoint.
    """
    rows: dict[tuple[str, datetime], dict] = {}
    wind: dict[tuple[str, datetime], dict] = {}
    for st in stations:
        for param, sensors in st["sensors"].items():
            for sensor in sensors:
                try:
                    payload = _fetch_sensor(sensor["id"], since, until)
                except (http.AuthError, http.RateLimited):
                    raise
                except http.ExternalError as e:
                    logger.warning(f"OpenAQ sensor {sensor['id']} ({st['name']}): {e}")
                    payload = {"results": []}
                finally:
                    time.sleep(PACE_S)
                parsed = parse_hours(payload, param, sensor["units"])
                if not parsed:
                    continue
                for hour, value in parsed:
                    if param in WIND_PARAMS:
                        w = wind.setdefault((st["id"], hour), {"station_id": st["id"], "hour": hour,
                                                               "source": "station"})
                        w["wind_speed" if param == "wind_speed" else "wind_dir"] = value
                    else:
                        r = rows.setdefault((st["id"], hour), {"station_id": st["id"], "hour": hour,
                                                               "source": "openaq"})
                        r[param] = value
                break
    wind_rows = [w for w in wind.values() if "wind_speed" in w and "wind_dir" in w]
    logger.info(f"OpenAQ: {len(rows)} station-hours, {len(wind_rows)} station-wind hours, "
                f"{since:%Y-%m-%d %H:%M} to {until:%H:%M} UTC")
    return list(rows.values()), wind_rows
