"""
Data cleaner for VayuVani.
Takes raw fetcher output → validated + AQI-calculated records ready for Supabase.
"""

import logging
from datetime import datetime, timezone
from typing import Optional
from .aqi_calc import calculate as calc_aqi

logger = logging.getLogger(__name__)

# Sanity bounds for pollutant values (µg/m³, except CO in mg/m³)
# Readings outside these are sensor errors — drop the specific pollutant, not the whole record.
BOUNDS = {
    "pm25": (0.0, 999.0),
    "pm10": (0.0, 1200.0),
    "no2": (0.0, 1000.0),
    "so2": (0.0, 3000.0),
    "co": (0.0, 100.0),
    "o3": (0.0, 1200.0),
    "nh3": (0.0, 3000.0),
}


def clean(raw: dict) -> Optional[dict]:
    """
    Validate and enrich one raw reading.
    Returns a dict ready for Supabase upsert, or None if record is unusable.
    """
    # Must have a location name
    name = raw.get("location_name", "").strip()
    if not name:
        logger.debug("Dropping record with no location name")
        return None

    lat = raw.get("latitude")
    lon = raw.get("longitude")
    if lat is None or lon is None:
        logger.debug(f"Dropping {name}: missing coordinates")
        return None

    # Validate individual pollutant values
    pollutants: dict[str, Optional[float]] = {}
    for field, (lo, hi) in BOUNDS.items():
        val = raw.get(field)
        if val is not None:
            if lo <= val <= hi:
                pollutants[field] = val
            else:
                logger.debug(f"{name}: {field}={val} out of bounds [{lo},{hi}] — discarded")
                pollutants[field] = None
        else:
            pollutants[field] = None

    # Need at least PM2.5 or PM10 to produce a useful record
    if pollutants["pm25"] is None and pollutants["pm10"] is None:
        logger.debug(f"Dropping {name}: no PM data")
        return None

    # Calculate AQI
    aqi_result = calc_aqi(**pollutants)

    # Parse timestamp — normalize to UTC ISO string
    ts_raw = raw.get("timestamp")
    try:
        if isinstance(ts_raw, str):
            ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
        elif isinstance(ts_raw, datetime):
            ts = ts_raw
        else:
            ts = datetime.now(timezone.utc)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        ts = datetime.now(timezone.utc)

    return {
        # Station identity — used as upsert key alongside timestamp
        "station_name": name,
        "latitude": float(lat),
        "longitude": float(lon),
        "source": raw.get("source", "unknown"),
        # Pollutants
        **{k: v for k, v in pollutants.items()},
        # AQI
        "aqi": aqi_result.aqi if aqi_result else None,
        "category": aqi_result.category if aqi_result else None,
        "dominant_pollutant": aqi_result.dominant_pollutant if aqi_result else None,
        # Metadata
        "ts": ts.isoformat(),
        "raw_data": raw.get("raw"),
    }


def clean_batch(raw_readings: list[dict]) -> list[dict]:
    """Clean a list of raw readings. Drops invalid records silently."""
    cleaned = []
    for raw in raw_readings:
        result = clean(raw)
        if result:
            cleaned.append(result)
    logger.info(f"Cleaned {len(cleaned)}/{len(raw_readings)} records")
    return cleaned
