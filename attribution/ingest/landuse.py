"""
What lies around and upwind: OpenStreetMap source inventory per station.

For every station, one Overpass query fetches, within RADIUS_M:
    industrial   landuse=industrial, man_made=works, industrial=*   -> industry
    power        power=plant                                        -> industry
    kiln         man_made=kiln, industrial=brickyard/brickworks     -> industry, biomass
    landfill     landuse=landfill, waste transfer stations          -> biomass_burning (garbage fires)
    crematorium  amenity=crematorium                                -> biomass_burning (small)
    construction landuse/building/highway=construction              -> dust
    quarry       landuse=quarry                                     -> dust
    rail         landuse=railway (yards)                            -> traffic (diesel)
    depot        amenity=bus_station, truck stops                   -> traffic
    roads        highway=motorway|trunk|primary (length)            -> traffic
Each feature is reduced to a point (centre) with a weight (count, or road
length in km), then summed three ways:
    grid      8 wind sectors x 3 distance bands (0-2, 2-5, 5-10 km) weighted
              1, 0.5, 0.25: used when the wind has a direction
    near      everything within NEAR_KM in any direction: used in calm air,
              when a station samples its own neighbourhood
    features  the named features themselves (name, type, km, bearing): so a
              card can say "Bawana Industrial Area, 3 km NW" instead of
              "industry, somewhere"
The query is built only from the whitelisted selectors below (CLAUDE.md:
whitelist anything that becomes a query); station coordinates are floats
formatted by us and must sit inside the region's box. Inventory is static,
so it is cached per station (store table station_landuse, plus a committed
snapshot under fixtures/ for offline runs) and refreshed after REFRESH_DAYS.

Overpass: the public servers are overloaded for much of the day, so several
endpoints are tried in turn with POST (long queries, no URL limit).
"""

import argparse
import json
import logging
import math
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from .. import http
from ..config import REGION
from ..engine.wind_sector import SECTORS, sector_of
from .firms import bearing_deg, haversine_km

logger = logging.getLogger(__name__)

VERSION = 2
ENDPOINTS = (
    "https://z.overpass-api.de/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
)
RADIUS_M = 10000
NEAR_KM = 2.0
BANDS = ((0.0, 2.0, 1.0), (2.0, 5.0, 0.5), (5.0, 10.0, 0.25))
REFRESH_DAYS = 30
PER_RUN = 8
MAX_NAMED = 60
FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")

# (feature, Overpass selector). Whitelist: nothing else is ever sent.
SELECTORS = (
    ("industrial", 'way["landuse"="industrial"]'),
    ("industrial", 'relation["landuse"="industrial"]'),
    ("industrial", 'nwr["man_made"="works"]'),
    ("industrial", 'nwr["industrial"]'),
    ("power", 'nwr["power"="plant"]'),
    ("kiln", 'nwr["man_made"="kiln"]'),
    ("kiln", 'nwr["product"="bricks"]'),
    ("landfill", 'nwr["landuse"="landfill"]'),
    ("landfill", 'nwr["amenity"="waste_transfer_station"]'),
    ("crematorium", 'nwr["amenity"="crematorium"]'),
    ("construction", 'way["landuse"="construction"]'),
    ("construction", 'nwr["building"="construction"]'),
    ("construction", 'way["highway"="construction"]'),
    ("quarry", 'nwr["landuse"="quarry"]'),
    ("rail", 'way["landuse"="railway"]'),
    ("depot", 'nwr["amenity"="bus_station"]'),
    ("depot", 'nwr["amenity"="truck_stop"]'),
)
ROAD_SELECTOR = 'way["highway"~"^(motorway|trunk|primary)$"]'
FEATURES = ("industrial", "power", "kiln", "landfill", "crematorium", "construction", "quarry",
            "rail", "depot", "roads")
# Which features can be "the" named source for an engine source class.
FEATURES_FOR_SOURCE = {
    "industry": ("power", "industrial", "kiln"),
    "biomass_burning": ("landfill", "kiln", "crematorium"),
    "dust": ("construction", "quarry"),
    "traffic": ("depot", "rail"),
}
FEATURE_LABEL = {
    "industrial": "industrial area", "power": "power plant", "kiln": "brick kiln",
    "landfill": "landfill / waste site", "crematorium": "crematorium",
    "construction": "construction site", "quarry": "quarry", "rail": "rail yard",
    "depot": "bus / truck depot", "roads": "arterial road",
}


def build_query(lat: float, lon: float, radius_m: int = RADIUS_M) -> str:
    lat, lon, r = float(lat), float(lon), int(radius_m)
    s, w, n, e = REGION["bbox"]
    if not (s <= lat <= n and w <= lon <= e) or not (100 <= r <= 20000):
        raise ValueError(f"station outside {REGION['name']} or radius out of range")
    around = f"(around:{r},{lat:.5f},{lon:.5f})"
    parts = [f"{sel}{around};" for _, sel in SELECTORS]
    return (f"[out:json][timeout:90];({''.join(parts)})->.src;.src out tags center;"
            f"{ROAD_SELECTOR}{around};out tags geom;")


def _feature_of(tags: dict) -> Optional[str]:
    t = {k: str(v) for k, v in (tags or {}).items()}
    if t.get("highway") in ("motorway", "trunk", "primary"):
        return "roads"
    if t.get("highway") == "construction":
        return "construction"
    if t.get("power") == "plant":
        return "power"
    if t.get("man_made") == "kiln" or t.get("industrial") in ("brickyard", "brickworks") or t.get("product") == "bricks":
        return "kiln"
    if t.get("industrial") == "depot" or t.get("amenity") in ("bus_station", "truck_stop"):
        return "depot"
    if t.get("landuse") == "landfill" or t.get("amenity") == "waste_transfer_station":
        return "landfill"
    if t.get("amenity") == "crematorium":
        return "crematorium"
    if t.get("landuse") == "industrial" or t.get("man_made") == "works" or "industrial" in t:
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


def _name(tags: dict) -> Optional[str]:
    for k in ("name:en", "name", "official_name", "operator"):
        v = (tags or {}).get(k)
        if isinstance(v, str) and 2 <= len(v.strip()) <= 80:
            return v.strip()
    return None


def summarise(payload: dict, lat: float, lon: float) -> dict:
    """
    {feature: {sector: weighted amount}} (roads in km, others in counts) plus
    "near" (within NEAR_KM, any direction), "features" (named, nearest first)
    and "version".
    """
    elements = payload.get("elements") if isinstance(payload, dict) else None
    if not isinstance(elements, list):
        raise http.BadResponse("Overpass: missing 'elements'")
    grid = {f: {s: 0.0 for s in SECTORS} for f in FEATURES}
    near = {f: 0.0 for f in FEATURES}
    named: list[dict] = []
    seen = set()
    for el in elements:
        key = (el.get("type"), el.get("id"))
        if key in seen:
            continue
        seen.add(key)
        tags = el.get("tags") or {}
        feat = _feature_of(tags)
        if feat is None:
            continue
        if feat == "roads":
            for (la1, lo1), (la2, lo2) in _segments(el.get("geometry") or []):
                mla, mlo = (la1 + la2) / 2, (lo1 + lo2) / 2
                d = haversine_km(lat, lon, mla, mlo)
                w = next((bw for lo_, hi_, bw in BANDS if lo_ <= d < hi_), 0.0)
                km = haversine_km(la1, lo1, la2, lo2)
                if w:
                    grid["roads"][sector_of(bearing_deg(lat, lon, mla, mlo))] += w * km
                if d < NEAR_KM:
                    near["roads"] += km
            continue
        c = el.get("center") or ({"lat": el.get("lat"), "lon": el.get("lon")} if "lat" in el else None)
        if not c:
            continue
        try:
            fla, flo = float(c["lat"]), float(c["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        d = haversine_km(lat, lon, fla, flo)
        b = bearing_deg(lat, lon, fla, flo)
        w = next((bw for lo_, hi_, bw in BANDS if lo_ <= d < hi_), 0.0)
        if w:
            grid[feat][sector_of(b)] += w
        if d < NEAR_KM:
            near[feat] += 1.0
        name = _name(tags)
        if name and d < RADIUS_M / 1000.0:
            named.append({"name": name, "feature": feat, "km": round(d, 1), "bearing": round(b),
                          "sector": sector_of(b), "lat": round(fla, 5), "lon": round(flo, 5)})
    named.sort(key=lambda f: f["km"])
    out = {f: {s: round(v, 3) for s, v in sec.items()} for f, sec in grid.items()}
    out["near"] = {f: round(v, 3) for f, v in near.items()}
    out["features"] = named[:MAX_NAMED]
    out["version"] = VERSION
    return out


def fetch_station(lat: float, lon: float) -> dict:
    query = build_query(lat, lon)
    last: Optional[Exception] = None
    for url in ENDPOINTS:
        try:
            resp = http.post_json(url, data={"data": query}, timeout=120, retries=1)
            return summarise(resp, lat, lon)
        except (http.AuthError, http.RateLimited):
            raise
        except http.ExternalError as e:
            last = e
            logger.warning(f"Overpass {url}: {e}")
    raise http.BadResponse(f"all Overpass endpoints failed: {last}")


def _is_fresh(row: Optional[dict], now: datetime) -> bool:
    if not row:
        return False
    g = row.get("grid")
    if isinstance(g, str):
        try:
            g = json.loads(g)
        except ValueError:
            return False
    if not isinstance(g, dict) or g.get("version") != VERSION:
        return False
    try:
        return now - datetime.fromisoformat(str(row["updated_at"])) < timedelta(days=REFRESH_DAYS)
    except (KeyError, ValueError, TypeError):
        return False


def refresh(store, stations: list[dict], now: Optional[datetime] = None, per_run: int = PER_RUN,
            pause_s: float = 2.0) -> int:
    """Fill/refresh the station_landuse cache for up to per_run stations (all if per_run is None)."""
    now = now or datetime.now(timezone.utc)
    have = {r["station_id"]: r for r in store.select("station_landuse")}
    todo = [st for st in stations if not _is_fresh(have.get(st["id"]), now)]
    done = 0
    for st in todo if per_run is None else todo[:per_run]:
        try:
            grid = fetch_station(st["latitude"], st["longitude"])
        except (http.AuthError, http.RateLimited):
            break
        except (http.ExternalError, ValueError) as e:
            logger.warning(f"Overpass {st['id']}: {e}")
            continue
        store.upsert("station_landuse", [{"station_id": st["id"], "grid": grid, "updated_at": now.isoformat()}])
        done += 1
        near = ", ".join(f"{k} {v:g}" for k, v in (grid.get("near") or {}).items() if v)
        logger.info(f"Land use {st['id']}: {len(grid.get('features') or [])} named features, near: {near or 'nothing'}")
        time.sleep(pause_s)
    logger.info(f"Land use: refreshed {done} stations ({len(todo) - done} still due)")
    return done


def snapshot_path(region_id: Optional[str] = None) -> str:
    return os.path.join(FIXTURES, f"landuse_{region_id or REGION['id']}.json")


def load_snapshot(path: Optional[str] = None) -> dict[str, dict]:
    p = path or snapshot_path()
    if not os.path.exists(p):
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        logger.warning(f"land-use snapshot unreadable: {e}")
        return {}
    grids = data.get("stations") if isinstance(data, dict) else None
    return {k: v for k, v in (grids or {}).items() if isinstance(v, dict)}


def load(store) -> dict[str, dict]:
    """Store rows first; the committed snapshot fills stations the store lacks."""
    out = load_snapshot()
    for r in store.select("station_landuse"):
        g = r.get("grid")
        if isinstance(g, str):
            try:
                g = json.loads(g)
            except ValueError:
                continue
        if isinstance(g, dict) and (g.get("version") == VERSION or r["station_id"] not in out):
            out[r["station_id"]] = g
    return out


def fleet_near_mean(grids: dict[str, dict]) -> dict[str, float]:
    """Mean near-inventory per feature across stations: the calm-air reference."""
    acc: dict[str, list[float]] = {f: [] for f in FEATURES}
    for g in grids.values():
        near = g.get("near") if isinstance(g, dict) else None
        if not isinstance(near, dict):
            continue
        for f in FEATURES:
            v = near.get(f)
            if isinstance(v, (int, float)) and math.isfinite(v):
                acc[f].append(float(v))
    return {f: (sum(v) / len(v) if v else 0.0) for f, v in acc.items()}


def candidates(grid: Optional[dict], source: Optional[str], wind: dict, n: int = 3) -> list[dict]:
    """
    Named features that could be the source: in the window's wind sector (and
    its two neighbours) when the wind has a direction, within 2 x NEAR_KM in any
    direction when it is calm. Nearest first. Never more than a hint: the
    inventory is OSM, which is incomplete and sometimes stale.
    """
    feats = (grid or {}).get("features") if isinstance(grid, dict) else None
    kinds = FEATURES_FOR_SOURCE.get(source or "")
    if not isinstance(feats, list) or not kinds:
        return []
    sector = wind.get("sector")
    calm = bool(wind.get("calm")) or not sector
    if calm:
        ok = [f for f in feats if f.get("feature") in kinds and f.get("km", 99) <= 2 * NEAR_KM]
    else:
        i = SECTORS.index(sector)
        allowed = {SECTORS[(i - 1) % 8], sector, SECTORS[(i + 1) % 8]}
        ok = [f for f in feats if f.get("feature") in kinds and f.get("sector") in allowed]
    ok.sort(key=lambda f: (0 if f.get("sector") == sector else 1, f.get("km", 99)))
    return [{"name": f["name"], "type": FEATURE_LABEL.get(f["feature"], f["feature"]),
             "km": f["km"], "sector": f["sector"], "lat": f.get("lat"), "lon": f.get("lon")} for f in ok[:n]]


def main():
    """python -m attribution.ingest.landuse snapshot: fetch every station, write the fixture, fill the store."""
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description="Kaun land-use inventory")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("snapshot")
    s.add_argument("--out", default=None, help="snapshot path (default fixtures/landuse_<region>.json)")
    s.add_argument("--force", action="store_true", help="refetch stations that are already fresh")
    args = ap.parse_args()
    from ..run import load_stations
    from ..store import get_store
    store = get_store()
    stations = list(load_stations(store).values())
    if not stations:
        raise SystemExit("no stations in the store; run the hourly job once first")
    if args.force:
        for st in stations:
            try:
                grid = fetch_station(st["latitude"], st["longitude"])
            except http.ExternalError as e:
                logger.warning(f"Overpass {st['id']}: {e}")
                continue
            store.upsert("station_landuse", [{"station_id": st["id"], "grid": grid,
                                              "updated_at": datetime.now(timezone.utc).isoformat()}])
            time.sleep(1.0)
    else:
        refresh(store, stations, per_run=None, pause_s=1.0)
    grids = {k: v for k, v in load(store).items() if v.get("version") == VERSION}
    out = args.out or snapshot_path()
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"region": REGION["id"], "version": VERSION, "generated_at": datetime.now(timezone.utc).isoformat(),
                   "source": "OpenStreetMap via Overpass (ODbL)", "stations": grids}, f, ensure_ascii=False, indent=1)
    print(f"snapshot: {len(grids)} of {len(stations)} stations -> {out}")


if __name__ == "__main__":
    main()
