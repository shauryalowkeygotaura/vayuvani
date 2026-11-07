"""
Supabase write layer for VayuVani.
Handles station upserts and AQI reading inserts.
"""

import os
import logging
from typing import Optional
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

_client: Optional[Client] = None


def get_client() -> Client:
    global _client
    if _client is None:
        url = os.environ["SUPABASE_URL"]
        key = os.environ["SUPABASE_KEY"]
        _client = create_client(url, key)
    return _client


def upsert_station(name: str, lat: float, lon: float, source: str) -> Optional[str]:
    """
    Upsert a station by name. Returns station_id (the name, used as PK).
    We use station name as the primary key — simple and human-readable.
    """
    client = get_client()
    try:
        client.table("stations").upsert(
            {
                "id": name,
                "name": name,
                "latitude": lat,
                "longitude": lon,
                "source": source,
                "is_active": True,
            },
            on_conflict="id",
        ).execute()
        return name
    except Exception as e:
        logger.error(f"Station upsert failed for {name}: {e}")
        return None


def insert_reading(record: dict) -> bool:
    """
    Insert one AQI reading. Silently skips duplicates (same station + timestamp).
    """
    client = get_client()
    station_id = upsert_station(
        record["station_name"],
        record["latitude"],
        record["longitude"],
        record["source"],
    )
    if not station_id:
        return False

    try:
        client.table("aqi_readings").upsert(
            {
                "station_id": station_id,
                "ts": record["ts"],
                "aqi": record.get("aqi"),
                "pm25": record.get("pm25"),
                "pm10": record.get("pm10"),
                "no2": record.get("no2"),
                "so2": record.get("so2"),
                "co": record.get("co"),
                "o3": record.get("o3"),
                "nh3": record.get("nh3"),
                "category": record.get("category"),
                "dominant_pollutant": record.get("dominant_pollutant"),
                "source": record.get("source"),
                "raw_data": record.get("raw_data"),
            },
            on_conflict="station_id,ts",
        ).execute()
        return True
    except Exception as e:
        logger.error(f"Reading insert failed for {station_id}: {e}")
        return False


def insert_batch(records: list[dict]) -> int:
    """Insert a batch of cleaned records. Returns count of successful inserts."""
    success = 0
    for rec in records:
        if insert_reading(rec):
            success += 1
    logger.info(f"DB: inserted {success}/{len(records)} readings")
    return success


def get_latest_for_neighborhood(lat: float, lon: float, radius_km: float = 5.0) -> Optional[dict]:
    """
    Get the most recent AQI reading within radius_km of coordinates.
    Uses Supabase PostGIS-style distance filter via RPC.

    Requires this SQL function in Supabase (see supabase/migrations/001_base.sql):
        get_nearest_reading(lat, lon, radius_km)
    """
    client = get_client()
    try:
        result = client.rpc(
            "get_nearest_reading",
            {"p_lat": lat, "p_lon": lon, "p_radius_km": radius_km},
        ).execute()
        data = result.data
        if data:
            return data[0]
        return None
    except Exception as e:
        logger.error(f"get_nearest_reading RPC failed: {e}")
        return None
