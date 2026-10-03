"""
Data fetcher for VayuVani.
Sources: OpenAQ API v3 (no key needed) + CPCB API (requires key).

OpenAQ v3 docs: https://docs.openaq.org/
CPCB API: https://cpcbccr.nic.in (register for key)
"""

import os
import logging
from typing import Optional
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

OPENAQ_BASE = "https://api.openaq.org/v3"
CPCB_BASE = "https://api.cpcbccr.nic.in/caaqms"

# Delhi bounding box (generous)
DELHI_LAT = 28.6139
DELHI_LON = 77.2090
DELHI_RADIUS_M = 25000  # OpenAQ v3 max radius is 25km; we do two sweeps

# OpenAQ parameter name → our column name
OPENAQ_PARAM_MAP = {
    "pm25": "pm25",
    "pm10": "pm10",
    "no2": "no2",
    "so2": "so2",
    "co": "co",
    "o3": "o3",
    "nh3": "nh3",
}


def _openaq_headers() -> dict:
    key = os.getenv("OPENAQ_API_KEY", "")
    if key:
        return {"X-API-Key": key}
    return {}


# ---------------------------------------------------------------------------
# OpenAQ
# ---------------------------------------------------------------------------

def fetch_openaq_delhi_locations() -> list[dict]:
    """
    Return all active monitoring locations within Delhi radius.
    OpenAQ v3 caps radius at 25km, so we sweep two centres that together
    cover all of Delhi NCR and deduplicate by location id.
    """
    # Two centres ~28km apart (N-Delhi and S-Delhi) each with 25km radius
    centres = [
        (28.7041, 77.1025),   # North Delhi / Rohini
        (28.5355, 77.3910),   # South-East Delhi / Noida border
    ]
    seen: set[int] = set()
    all_locations: list[dict] = []

    for lat, lon in centres:
        params = {
            "coordinates": f"{lat},{lon}",
            "radius": DELHI_RADIUS_M,
            "limit": 200,
            "page": 1,
        }
        try:
            resp = requests.get(
                f"{OPENAQ_BASE}/locations",
                params=params,
                headers=_openaq_headers(),
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            for loc in data.get("results", []):
                loc_id = loc.get("id")
                if loc_id and loc_id not in seen:
                    seen.add(loc_id)
                    all_locations.append(loc)
        except requests.RequestException as e:
            logger.error(f"OpenAQ locations fetch failed: {e}")

    logger.info(f"OpenAQ: found {len(all_locations)} Delhi locations")
    return all_locations


def fetch_openaq_latest(location_id: int, sensor_map: dict[int, str] | None = None) -> Optional[dict]:
    """
    Fetch the most recent sensor readings for one location.
    sensor_map: {sensor_id -> param_name} built from the location's sensors list.
    Returns normalized dict: {pm25, pm10, no2, so2, co, o3, timestamp, raw}.
    """
    try:
        resp = requests.get(
            f"{OPENAQ_BASE}/locations/{location_id}/latest",
            headers=_openaq_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", [])
        if not results:
            return None
        return _parse_openaq_latest(location_id, results, sensor_map or {})
    except requests.RequestException as e:
        logger.warning(f"OpenAQ latest fetch failed for location {location_id}: {e}")
        return None


def _parse_openaq_latest(location_id: int, results: list, sensor_map: dict[int, str]) -> dict:
    """
    OpenAQ v3 /latest returns a list of {sensorsId, value, datetime}.
    We use sensor_map (built from the location's sensors list) to resolve param names.
    """
    parsed: dict = {
        "openaq_location_id": location_id,
        "pm25": None,
        "pm10": None,
        "no2": None,
        "so2": None,
        "co": None,
        "o3": None,
        "nh3": None,
        "timestamp": None,
        "raw": results,
    }

    timestamps = []
    for entry in results:
        sensor_id = entry.get("sensorsId")
        param_name = sensor_map.get(sensor_id, "").lower() if sensor_id else ""
        col = OPENAQ_PARAM_MAP.get(param_name)
        if col:
            value = entry.get("value")
            # CO is reported in µg/m³ by OpenAQ — convert to mg/m³ for NAQI
            if col == "co" and value is not None:
                value = value / 1000.0
            parsed[col] = value

        dt_str = entry.get("datetime", {}).get("utc")
        if dt_str:
            try:
                timestamps.append(datetime.fromisoformat(dt_str.replace("Z", "+00:00")))
            except ValueError:
                pass

    if timestamps:
        parsed["timestamp"] = max(timestamps).isoformat()
    else:
        parsed["timestamp"] = datetime.now(timezone.utc).isoformat()

    return parsed


def fetch_all_openaq_delhi() -> list[dict]:
    """
    Full pipeline: get all Delhi locations, fetch latest for each.
    Returns list of normalized reading dicts.
    """
    locations = fetch_openaq_delhi_locations()
    readings = []
    for loc in locations:
        loc_id = loc.get("id")
        if not loc_id:
            continue
        # Build sensor_id → param_name map from this location's sensor list
        sensor_map: dict[int, str] = {}
        for s in loc.get("sensors", []):
            sid = s.get("id")
            pname = s.get("parameter", {}).get("name", "")
            if sid and pname:
                sensor_map[sid] = pname
        reading = fetch_openaq_latest(loc_id, sensor_map)
        if reading:
            # Attach location metadata
            coords = loc.get("coordinates", {})
            reading["location_name"] = loc.get("name", "Unknown")
            reading["latitude"] = coords.get("latitude")
            reading["longitude"] = coords.get("longitude")
            reading["source"] = "openaq"
            readings.append(reading)

    logger.info(f"OpenAQ: fetched {len(readings)} station readings")
    return readings


# ---------------------------------------------------------------------------
# CPCB
# ---------------------------------------------------------------------------

def fetch_cpcb_delhi() -> list[dict]:
    """
    Fetch CPCB CAAQMS data for Delhi stations.
    Requires CPCB_API_KEY in .env (register at cpcbccr.nic.in).

    CPCB API endpoint and exact params are updated periodically.
    Check https://cpcbccr.nic.in/ccr/#/caaqm-dashboard-all/caaqm-landing
    for current station list and endpoint docs.
    """
    api_key = os.getenv("CPCB_API_KEY")
    if not api_key:
        logger.warning("CPCB_API_KEY not set — skipping CPCB fetch")
        return []

    try:
        resp = requests.get(
            f"{CPCB_BASE}/getStationData",
            params={
                "apiKey": api_key,
                "stateId": "Delhi",
                "cityId": "Delhi",
            },
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        return _parse_cpcb_response(data)
    except requests.RequestException as e:
        logger.error(f"CPCB fetch failed: {e}")
        return []


def _parse_cpcb_response(data: dict) -> list[dict]:
    """
    Normalize CPCB response into the same schema as OpenAQ readings.
    CPCB field names vary — update this mapping if CPCB changes their API.
    """
    stations = data.get("stations", data.get("data", []))
    results = []
    for s in stations:
        reading = {
            "source": "cpcb",
            "location_name": s.get("stationName", s.get("station_name", "Unknown")),
            "latitude": s.get("latitude"),
            "longitude": s.get("longitude"),
            "pm25": _safe_float(s.get("PM2.5", s.get("pm25"))),
            "pm10": _safe_float(s.get("PM10", s.get("pm10"))),
            "no2": _safe_float(s.get("NO2", s.get("no2"))),
            "so2": _safe_float(s.get("SO2", s.get("so2"))),
            "co": _safe_float(s.get("CO", s.get("co"))),
            "o3": _safe_float(s.get("Ozone", s.get("O3", s.get("o3")))),
            "nh3": _safe_float(s.get("NH3", s.get("nh3"))),
            "timestamp": s.get("lastUpdated", datetime.now(timezone.utc).isoformat()),
            "raw": s,
        }
        results.append(reading)
    logger.info(f"CPCB: parsed {len(results)} station readings")
    return results


def _safe_float(val) -> Optional[float]:
    try:
        return float(val)
    except (TypeError, ValueError):
        return None
