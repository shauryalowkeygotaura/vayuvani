"""
One-time script: discover all Delhi OpenAQ stations and seed into Supabase.
Run this once before starting the scheduler.

Usage:
    python -m pipeline.seed_stations
"""

import logging
from .fetcher import fetch_openaq_delhi_locations
from .db import upsert_station

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("vayuvani.seed")


def seed():
    logger.info("Seeding Delhi stations from OpenAQ...")
    locations = fetch_openaq_delhi_locations()

    seeded = 0
    for loc in locations:
        name = loc.get("name", "").strip()
        coords = loc.get("coordinates", {})
        lat = coords.get("latitude")
        lon = coords.get("longitude")

        if not name or lat is None or lon is None:
            logger.debug(f"Skipping incomplete location: {loc.get('id')}")
            continue

        result = upsert_station(name, lat, lon, "openaq")
        if result:
            seeded += 1
            logger.info(f"  ✓ {name} ({lat:.4f}, {lon:.4f})")

    logger.info(f"\nSeeded {seeded}/{len(locations)} stations")


if __name__ == "__main__":
    seed()
