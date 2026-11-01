"""
CPCB real-time feed via data.gov.in (resource "Real time Air Quality Index
from various locations", id 3b01bcb8-0b14-4abf-b6f2-c1bfd384ba69).

Needs a free data.gov.in API key in DATA_GOV_IN_API_KEY (CPCB_API_KEY is also
accepted). Without one this source is skipped and OpenAQ (which mirrors CPCB)
carries the run.

Verified (search, 2026-11-01): fields are country, state, city, station,
last_update, latitude, longitude, pollutant_id, pollutant_min, pollutant_max,
pollutant_avg; granularity listed as hourly.
NOT verified: whether pollutant_avg is a concentration or a sub-index, and its
averaging window. Treat as concentration (ug/m3, CO mg/m3) but run
`cross_check()` against OpenAQ before trusting it; the runner logs divergence.
The filter field is spelled `polutant_id` in some clients; we filter on state
only and parse pollutant_id client-side to sidestep that.
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from .. import http
from .units import station_slug, to_standard

logger = logging.getLogger(__name__)

RESOURCE_ID = "3b01bcb8-0b14-4abf-b6f2-c1bfd384ba69"
BASE = f"https://api.data.gov.in/resource/{RESOURCE_ID}"
IST = timezone(timedelta(hours=5, minutes=30))

# pollutant_id values -> our columns (whitelist; NH3 and unknowns dropped).
POLLUTANT_MAP = {"PM2.5": "pm25", "PM10": "pm10", "NO2": "no2", "SO2": "so2", "CO": "co", "OZONE": "o3"}
FEED_UNITS = {"co": "mg/m3"}  # everything else ug/m3


def api_key() -> Optional[str]:
    return os.getenv("DATA_GOV_IN_API_KEY") or os.getenv("CPCB_API_KEY") or None


def _parse_last_update(raw: str) -> Optional[datetime]:
    for fmt in ("%d-%m-%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d-%m-%Y %H:%M"):
        try:
            return datetime.strptime(raw.strip(), fmt).replace(tzinfo=IST)
        except (ValueError, AttributeError):
            continue
    return None


def parse_records(records: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    Returns (hourly_rows, stations). `last_update` is the end of the averaging
    hour in IST; rows are labelled by the UTC hour nearest the averaging
    midpoint (end - 30 min), the same convention as OpenAQ ingest.
    """
    rows: dict[tuple[str, datetime], dict] = {}
    stations: dict[str, dict] = {}
    for rec in records:
        if not isinstance(rec, dict):
            continue
        if (rec.get("state") or "").strip().lower() != "delhi":
            continue
        name = (rec.get("station") or "").strip()
        col = POLLUTANT_MAP.get((rec.get("pollutant_id") or "").strip().upper())
        ts = _parse_last_update(rec.get("last_update") or "")
        if not name or not col or ts is None:
            continue
        avg = rec.get("pollutant_avg", rec.get("avg_value"))
        if avg in (None, "", "NA"):
            continue
        value = to_standard(col, avg, FEED_UNITS.get(col, "ug/m3"))
        if value is None:
            continue
        sid = station_slug(name)
        try:
            lat, lon = float(rec.get("latitude")), float(rec.get("longitude"))
            stations[sid] = {"id": sid, "name": name, "latitude": lat, "longitude": lon}
        except (TypeError, ValueError):
            pass
        hour = (ts.astimezone(timezone.utc) - timedelta(minutes=30)).replace(minute=0, second=0, microsecond=0)
        row = rows.setdefault((sid, hour), {"station_id": sid, "hour": hour, "source": "cpcb"})
        row[col] = value
    return list(rows.values()), list(stations.values())


def fetch() -> tuple[list[dict], list[dict]]:
    key = api_key()
    if not key:
        logger.info("CPCB: no DATA_GOV_IN_API_KEY/CPCB_API_KEY, skipping (OpenAQ mirrors CPCB)")
        return [], []
    records: list[dict] = []
    offset = 0
    while True:
        payload = http.get_json(BASE, params={
            "api-key": key, "format": "json", "limit": 500, "offset": offset,
            "filters[state]": "Delhi",
        })
        if not isinstance(payload, dict):
            raise http.BadResponse("data.gov.in: expected JSON object")
        if payload.get("status") == "error" or "records" not in payload:
            raise http.BadResponse(f"data.gov.in: {str(payload.get('message', payload))[:200]}")
        batch = payload.get("records") or []
        records.extend(batch)
        total = int(payload.get("total") or 0)
        offset += len(batch)
        if not batch or offset >= total:
            break
    rows, stations = parse_records(records)
    logger.info(f"CPCB: {len(records)} records -> {len(rows)} station-hours, {len(stations)} stations")
    return rows, stations


def cross_check(cpcb_rows: list[dict], openaq_rows: list[dict], param: str = "pm25") -> Optional[float]:
    """
    Median ratio CPCB/OpenAQ for matching (station, hour). ~1.0 means the feed
    is concentrations; far off means pollutant_avg is something else (e.g. a
    sub-index) and CPCB rows must not be mixed in.
    """
    oa = {(r["station_id"], r["hour"]): r.get(param) for r in openaq_rows}
    ratios = sorted(
        r[param] / oa[(r["station_id"], r["hour"])]
        for r in cpcb_rows
        if r.get(param) and oa.get((r["station_id"], r["hour"]))
    )
    if not ratios:
        return None
    return ratios[len(ratios) // 2]
