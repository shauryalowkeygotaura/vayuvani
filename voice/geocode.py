"""
Turn what a caller says ("Anand Vihar", "आनंद विहार", "near ITO", "110092")
into coordinates.

Order:
1. Local gazetteer: the neighbourhood list from supabase/migrations/001_base.sql
   (Hindi names included) plus every monitoring station in the live feed.
   Exact, then alias, then fuzzy (difflib) match. No network, ~1 ms.
2. Nominatim (OpenStreetMap), restricted to a Delhi-NCR box, 1.2 s timeout.
   Usage policy: max 1 req/s and an identifying User-Agent
   (https://operations.osmfoundation.org/policies/nominatim/). Call volume for
   a phone line is far below that.
Standard library only (runs inside the Vercel webhook).
"""

import difflib
import json
import re
import unicodedata
import urllib.parse
import urllib.request
from typing import Optional

# From supabase/migrations/001_base.sql (neighborhoods seed).
NEIGHBOURHOODS = [
    ("Anand Vihar", "आनंद विहार", 28.6466, 77.3152),
    ("Chandni Chowk", "चांदनी चौक", 28.6506, 77.2304),
    ("Connaught Place", "कनॉट प्लेस", 28.6315, 77.2167),
    ("Dwarka", "द्वारका", 28.5921, 77.0460),
    ("ITO", "आईटीओ", 28.6275, 77.2436),
    ("Jahangirpuri", "जहांगीरपुरी", 28.7251, 77.1645),
    ("Lodhi Road", "लोधी रोड", 28.5975, 77.2217),
    ("Mandir Marg", "मंदिर मार्ग", 28.6404, 77.1987),
    ("Mayur Vihar", "मयूर विहार", 28.6092, 77.2938),
    ("NSIT Dwarka", "एनएसआईटी द्वारका", 28.6089, 77.0339),
    ("Okhla", "ओखला", 28.5500, 77.2700),
    ("Punjabi Bagh", "पंजाबी बाग", 28.6700, 77.1300),
    ("RK Puram", "आरके पुरम", 28.5644, 77.1765),
    ("Rohini", "रोहिणी", 28.7354, 77.1148),
    ("Saket", "साकेत", 28.5244, 77.2066),
    ("Shadipur", "शादीपुर", 28.6481, 77.1472),
    ("Siri Fort", "सिरी फोर्ट", 28.5486, 77.2169),
    ("Vasundhara Enclave", "वसुंधरा एन्क्लेव", 28.6265, 77.3098),
    ("Wazirpur", "वज़ीरपुर", 28.6956, 77.1676),
]
ALIASES = {"cp": "connaught place", "rajiv chowk": "connaught place", "r k puram": "rk puram",
           "sirifort": "siri fort", "dwarka sector 8": "dwarka"}

# Delhi NCR viewbox for Nominatim: left, top, right, bottom.
NCR_VIEWBOX = "76.80,28.95,77.60,28.35"
USER_AGENT = "VayuVani/0.2 (Delhi air quality phone line; https://github.com/shauryalowkeygotaura/vayuvani)"
FILLER = re.compile(r"\b(near|nearby|area|the|in|at|delhi|new|sector|colony|ke paas|mein|main|ka|ki|के|पास|में|दिल्ली)\b")


def _norm(text: str) -> str:
    t = unicodedata.normalize("NFC", text or "").lower().strip()
    t = re.sub(r"[^\w\sऀ-ॿ]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _strip(text: str) -> str:
    return re.sub(r"\s+", " ", FILLER.sub(" ", _norm(text))).strip()


def station_short_name(name: str) -> str:
    """'Anand Vihar, New Delhi - DPCC' -> 'Anand Vihar'."""
    return re.split(r"[,(]| - ", name)[0].strip()


def build_index(stations: list[dict]) -> dict[str, tuple[str, float, float, str]]:
    idx: dict[str, tuple[str, float, float, str]] = {}
    for name, name_hi, lat, lon in NEIGHBOURHOODS:
        idx[_norm(name)] = (name, lat, lon, "gazetteer")
        idx[_norm(name_hi)] = (name, lat, lon, "gazetteer")
    for s in stations:
        if s.get("latitude") is None or s.get("longitude") is None:
            continue
        short = station_short_name(s.get("name", ""))
        if short and _norm(short) not in idx:
            idx[_norm(short)] = (short, float(s["latitude"]), float(s["longitude"]), "station")
    return idx


def local(text: str, stations: list[dict]) -> Optional[dict]:
    idx = build_index(stations)
    q = _norm(text)
    for cand in (q, _strip(text), ALIASES.get(q), ALIASES.get(_strip(text))):
        if cand and cand in idx:
            n, lat, lon, how = idx[cand]
            return {"label": n, "latitude": lat, "longitude": lon, "method": how}
    s = _strip(text)
    for key, (n, lat, lon, how) in idx.items():
        if s and len(s) >= 4 and (s in key or key in s):
            return {"label": n, "latitude": lat, "longitude": lon, "method": how + "-partial"}
    hit = difflib.get_close_matches(s or q, list(idx), n=1, cutoff=0.8)
    if hit:
        n, lat, lon, how = idx[hit[0]]
        return {"label": n, "latitude": lat, "longitude": lon, "method": how + "-fuzzy"}
    return None


def nominatim(text: str, timeout: float = 1.2) -> Optional[dict]:
    q = (text or "").strip()[:120]
    if not q:
        return None
    params = urllib.parse.urlencode({
        "q": f"{q}, Delhi", "format": "jsonv2", "limit": 1, "countrycodes": "in",
        "viewbox": NCR_VIEWBOX, "bounded": 1,
    })
    req = urllib.request.Request(f"https://nominatim.openstreetmap.org/search?{params}",
                                 headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            data = json.loads(resp.read().decode("utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, list) or not data:
        return None
    try:
        lat, lon = float(data[0]["lat"]), float(data[0]["lon"])
    except (KeyError, TypeError, ValueError):
        return None
    label = str(data[0].get("name") or q).strip() or q
    return {"label": label, "latitude": lat, "longitude": lon, "method": "nominatim"}


def resolve(text: str, stations: list[dict], allow_network: bool = True) -> Optional[dict]:
    return local(text, stations) or (nominatim(text) if allow_network else None)
