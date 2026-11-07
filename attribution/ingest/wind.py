"""
Hourly wind per station from Open-Meteo (free, no key).

CPCB stations do measure WS/WD, but neither OpenAQ nor the data.gov.in feed
exposes them, so model wind (Open-Meteo's best-match, 10 m) at each station's
lat/lon is the source. It is a ~1-10 km model field, not the station mast:
good enough for an 8-sector call, not for street-canyon effects.

Also pulls boundary-layer height where available: a shallow night-time PBL
traps emissions and inflates every pollutant together, which the engine uses
to avoid blaming a "spike" that is just dilution collapse.
"""

import logging
from datetime import datetime, timezone

from .. import http

logger = logging.getLogger(__name__)

BASE = "https://api.open-meteo.com/v1/forecast"
ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"  # backfill (ERA5-based)
BATCH = 50  # Open-Meteo accepts comma-separated coordinate lists


def parse(payload, stations: list[dict]) -> list[dict]:
    items = payload if isinstance(payload, list) else [payload]
    if len(items) != len(stations):
        raise http.BadResponse(f"Open-Meteo: {len(items)} results for {len(stations)} stations")
    rows = []
    for st, item in zip(stations, items):
        hourly = item.get("hourly") if isinstance(item, dict) else None
        if not isinstance(hourly, dict) or "time" not in hourly:
            raise http.BadResponse("Open-Meteo: missing hourly.time")
        times = hourly["time"]
        ws = hourly.get("wind_speed_10m") or [None] * len(times)
        wd = hourly.get("wind_direction_10m") or [None] * len(times)
        pbl = hourly.get("boundary_layer_height") or [None] * len(times)
        for t, s, d, h in zip(times, ws, wd, pbl):
            try:
                hour = datetime.fromisoformat(t).replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                continue
            if s is None or d is None:
                continue
            rows.append({
                "station_id": st["id"], "hour": hour,
                "wind_speed": float(s), "wind_dir": float(d) % 360.0,
                "pbl_height": None if h is None else float(h),
                "source": "open-meteo",
            })
    return rows


def fetch(stations: list[dict], past_days: int = 2) -> list[dict]:
    rows: list[dict] = []
    for i in range(0, len(stations), BATCH):
        part = stations[i:i + BATCH]
        payload = http.get_json(BASE, params={
            "latitude": ",".join(f"{s['latitude']:.4f}" for s in part),
            "longitude": ",".join(f"{s['longitude']:.4f}" for s in part),
            "hourly": "wind_speed_10m,wind_direction_10m,boundary_layer_height",
            "wind_speed_unit": "ms",
            "timezone": "UTC",
            "past_days": max(1, min(past_days, 92)),
            "forecast_days": 1,
        })
        rows.extend(parse(payload, part))
    now = datetime.now(timezone.utc)
    rows = [r for r in rows if r["hour"] <= now]
    logger.info(f"Open-Meteo: {len(rows)} station-hours of wind")
    return rows


def fetch_archive(stations: list[dict], start_date: str, end_date: str) -> list[dict]:
    """Backfill wind for validation windows (dates YYYY-MM-DD). ERA5 lags ~5 days."""
    rows: list[dict] = []
    for i in range(0, len(stations), BATCH):
        part = stations[i:i + BATCH]
        payload = http.get_json(ARCHIVE, params={
            "latitude": ",".join(f"{s['latitude']:.4f}" for s in part),
            "longitude": ",".join(f"{s['longitude']:.4f}" for s in part),
            "hourly": "wind_speed_10m,wind_direction_10m,boundary_layer_height",
            "wind_speed_unit": "ms", "timezone": "UTC",
            "start_date": start_date, "end_date": end_date,
        }, timeout=60)
        rows.extend(parse(payload, part))
    return rows
