"""
What lies upwind: OpenStreetMap source inventory around each station, binned
by wind sector and distance.

For every station, one Overpass query fetches, within RADIUS_M:
    industrial   landuse=industrial                       -> industry
    power        power=plant | power=generator(+fossil)   -> industry
    kiln         man_made=kiln | industrial=brickyard     -> industry, biomass
    landfill     landuse=landfill | amenity=waste_transfer_station -> biomass_burning (garbage fires)
    construction landuse=construction | building=construction -> dust
    quarry       landuse=quarry                           -> dust
    rail         landuse=railway (yards)                  -> traffic (diesel)
    roads        highway=motorway|trunk|primary (length)  -> traffic
Each feature is reduced to a point (centre) with a weight (area proxy or road
length in km), then summed into 8 sectors x 3 distance bands (0-2, 2-5, 5-10 km)
with weights 1, 0.5, 0.25 (closer counts more).

The query is built only from the whitelisted selectors below (CLAUDE.md:
whitelist anything that becomes a query); station coordinates are floats
formatted by us. Inventory is static, so it is cached per station and
refreshed after REFRESH_DAYS, a few stations per hourly run to stay polite to
the public Overpass server.

Fixture-only so far: overpass-api.de was unreachable from the build session.
"""

import json
import logging
import math
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from .. import http
from ..engine.wind_sector import SECTORS, sector_of
from .firms import bearing_deg, haversine_km

logger = logging.getLogger(__name__)

OVERPASS = "https://overpass-api.de/api/interpreter"
RADIUS_M = 10000
BANDS = ((0.0, 2.0, 1.0), (2.0, 5.0, 0.5), (5.0, 10.0, 0.25))
REFRESH_DAYS = 30
PER_RUN = 8

# (feature, Overpass selector). Whitelist: nothing else is ever sent.
SELECTORS = (
    ("industrial", 'way["landuse"="industrial"]'),
    ("industrial", 'relation["landuse"="industrial"]'),
    ("power", 'nwr["power"="plant"]'),
    ("kiln", 'nwr["man_made"="kiln"]'),
    ("kiln", 'nwr["industrial"="brickyard"]'),
    ("landfill", 'nwr["landuse"="landfill"]'),
    ("landfill", 'nwr["amenity"="waste_transfer_station"]'),
    ("construction", 'way["landuse"="construction"]'),
    ("construction", 'way["building"="construction"]'),
    ("quarry", 'way["landuse"="quarry"]'),
    ("rail", 'way["landuse"="railway"]'),
)
ROAD_SELECTOR = 'way["highway"~"^(motorway|trunk|primary)$"]'
FEATURES = ("industrial", "power", "kiln", "landfill", "construction", "quarry", "rail", "roads")


def build_query(lat: float, lon: float, radius_m: int = RADIUS_M) -> str:
    lat, lon, r = float(lat), float(lon), int(radius_m)
    if not (27.5 <= lat <= 29.8 and 76.0 <= lon <= 78.5) or not (100 <= r <= 20000):
        raise ValueError("station outside Delhi NCR or radius out of range")
    around = f"(around:{r},{lat:.5f},{lon:.5f})"
    parts = [f"{sel}{around};" for _, sel in SELECTORS]
    return (f"[out:json][timeout:60];({''.join(parts)})->.src;.src out tags center;"
            f"{ROAD_SELECTOR}{around};out tags geom;")


def _feature_of(tags: dict) -> Optional[str]:
    t = {k: str(v) for k, v in (tags or {}).items()}
    if t.get("highway") in ("motorway", "trunk", "primary"):
        return "roads"
    if t.get("power") == "plant":
        return "power"
    if t.get("man_made") == "kiln" or t.get("industrial") == "brickyard":
        return "kiln"
    if t.get("landuse") == "landfill" or t.get("amenity") == "waste_transfer_station":
        return "landfill"
    if t.get("landuse") == "industrial":
        return "industrial"
    if t.get("landuse") == "construction" or t.get("building") == "construction":
        return "construction"
    if t.get("landuse") == "quarry":
        return "quarry"
    if t.get("landuse") == "railway":
        return "rail"
    return None


def _segments(geom: list[dict]):
    for a, b in zip(geom, geom[1:]):
        try:
            yield (float(a["lat"]), float(a["lon"])), (float(b["lat"]), float(b["lon"]))
        except (KeyError, TypeError, ValueError):
            continue


def summarise(payload: dict, lat: float, lon: float) -> dict:
    """{feature: {sector: weighted amount}} plus totals. Roads in km, others in feature counts."""
    elements = payload.get("elements") if isinstance(payload, dict) else None
    if not isinstance(elements, list):
        raise http.BadResponse("Overpass: missing 'elements'")
    grid = {f: {s: 0.0 for s in SECTORS} for f in FEATURES}
    seen = set()
    for el in elements:
        key = (el.get("type"), el.get("id"))
        if key in seen:
            continue
        seen.add(key)
        feat = _feature_of(el.get("tags"))
        if feat is None:
            continue
        if feat == "roads":
            for (la1, lo1), (la2, lo2) in _segments(el.get("geometry") or []):
                mla, mlo = (la1 + la2) / 2, (lo1 + lo2) / 2
                d = haversine_km(lat, lon, mla, mlo)
                w = next((bw for lo_, hi_, bw in BANDS if lo_ <= d < hi_), 0.0)
                if w:
                    grid["roads"][sector_of(bearing_deg(lat, lon, mla, mlo))] += w * haversine_km(la1, lo1, la2, lo2)
            continue
        c = el.get("center") or ({"lat": el.get("lat"), "lon": el.get("lon")} if "lat" in el else None)
        if not c:
            continue
        try:
            fla, flo = float(c["lat"]), float(c["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        d = haversine_km(lat, lon, fla, flo)
        w = next((bw for lo_, hi_, bw in BANDS if lo_ <= d < hi_), 0.0)
        if w:
            grid[feat][sector_of(bearing_deg(lat, lon, fla, flo))] += w
    return {f: {s: round(v, 3) for s, v in sec.items()} for f, sec in grid.items()}


def fetch_station(lat: float, lon: float) -> dict:
    resp = http.get_json(OVERPASS, params={"data": build_query(lat, lon)}, timeout=90, retries=2)
    return summarise(resp, lat, lon)


def refresh(store, stations: list[dict], now: Optional[datetime] = None, per_run: int = PER_RUN) -> int:
    """Fill/refresh the station_landuse cache for up to per_run stations."""
    now = now or datetime.now(timezone.utc)
    have = {r["station_id"]: r for r in store.select("station_landuse")}
    todo = []
    for st in stations:
        r = have.get(st["id"])
        try:
            fresh = r and now - datetime.fromisoformat(str(r["updated_at"])) < timedelta(days=REFRESH_DAYS)
        except ValueError:
            fresh = False
        if not fresh:
            todo.append(st)
    done = 0
    for st in todo[:per_run]:
        try:
            grid = fetch_station(st["latitude"], st["longitude"])
        except (http.AuthError, http.RateLimited):
            break
        except (http.ExternalError, ValueError) as e:
            logger.warning(f"Overpass {st['id']}: {e}")
            continue
        store.upsert("station_landuse", [{"station_id": st["id"], "grid": grid, "updated_at": now.isoformat()}])
        done += 1
        time.sleep(2)
    logger.info(f"Land use: refreshed {done} stations ({len(todo) - done} still due)")
    return done


def load(store) -> dict[str, dict]:
    out = {}
    for r in store.select("station_landuse"):
        g = r.get("grid")
        if isinstance(g, str):
            try:
                g = json.loads(g)
            except ValueError:
                continue
        if isinstance(g, dict):
            out[r["station_id"]] = g
    return out
