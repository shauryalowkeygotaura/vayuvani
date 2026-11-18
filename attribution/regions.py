"""
Regions: where Kaun runs. Delhi NCR is the default; the rest of the table is
the expansion path (one region per run, selected with KAUN_REGION).

Each region gives the engine everything that used to be a Delhi constant:
    centre     city centre, the origin for fire bearings and the FIRMS box
    sweeps     OpenAQ /locations search centres (25 km radius each)
    bbox       (south, west, north, east): sanity box for station coordinates
               before they go into an Overpass query (whitelist rule)
Station ids, feeds and checkpoints are kept apart per region so two regions
can share one Supabase project without mixing their airsheds.

Coordinates are the usual city-centre values (Wikipedia / OSM); the sweeps
are hand-placed to cover each metro's CPCB station cluster.
"""

import os

REGIONS: dict[str, dict] = {
    "delhi-ncr": {"name": "Delhi NCR", "lat": 28.6139, "lon": 77.2090,
                  "sweeps": ((28.7041, 77.1025), (28.5355, 77.3910))},
    "mumbai": {"name": "Mumbai MMR", "lat": 19.0760, "lon": 72.8777,
               "sweeps": ((19.0760, 72.8777), (19.2183, 72.9781))},
    "kolkata": {"name": "Kolkata", "lat": 22.5726, "lon": 88.3639, "sweeps": ((22.5726, 88.3639),)},
    "bengaluru": {"name": "Bengaluru", "lat": 12.9716, "lon": 77.5946, "sweeps": ((12.9716, 77.5946),)},
    "chennai": {"name": "Chennai", "lat": 13.0827, "lon": 80.2707, "sweeps": ((13.0827, 80.2707),)},
    "hyderabad": {"name": "Hyderabad", "lat": 17.3850, "lon": 78.4867, "sweeps": ((17.3850, 78.4867),)},
    "ahmedabad": {"name": "Ahmedabad", "lat": 23.0225, "lon": 72.5714, "sweeps": ((23.0225, 72.5714),)},
    "pune": {"name": "Pune", "lat": 18.5204, "lon": 73.8567, "sweeps": ((18.5204, 73.8567),)},
    "lucknow": {"name": "Lucknow", "lat": 26.8467, "lon": 80.9462, "sweeps": ((26.8467, 80.9462),)},
    "kanpur": {"name": "Kanpur", "lat": 26.4499, "lon": 80.3319, "sweeps": ((26.4499, 80.3319),)},
    "patna": {"name": "Patna", "lat": 25.5941, "lon": 85.1376, "sweeps": ((25.5941, 85.1376),)},
    "jaipur": {"name": "Jaipur", "lat": 26.9124, "lon": 75.7873, "sweeps": ((26.9124, 75.7873),)},
    "chandigarh": {"name": "Chandigarh Tricity", "lat": 30.7333, "lon": 76.7794, "sweeps": ((30.7333, 76.7794),)},
    "varanasi": {"name": "Varanasi", "lat": 25.3176, "lon": 82.9739, "sweeps": ((25.3176, 82.9739),)},
}
DEFAULT = "delhi-ncr"
BOX_LAT, BOX_LON = 1.2, 1.3   # degrees around the centre a station may sit in


def current_id() -> str:
    rid = os.getenv("KAUN_REGION", DEFAULT).strip().lower()
    if rid not in REGIONS:   # whitelist: the id ends up in paths and filters
        raise ValueError(f"KAUN_REGION={rid!r} is not one of {sorted(REGIONS)}")
    return rid


def current() -> dict:
    rid = current_id()
    r = dict(REGIONS[rid])
    r["id"] = rid
    r["bbox"] = (r["lat"] - BOX_LAT, r["lon"] - BOX_LON, r["lat"] + BOX_LAT, r["lon"] + BOX_LON)
    return r


def inside(region: dict, lat: float, lon: float) -> bool:
    s, w, n, e = region["bbox"]
    return s <= float(lat) <= n and w <= float(lon) <= e
