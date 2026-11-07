"""
What the phone line actually says and does. Two tools:

get_air_quality(location, language)
    location -> coordinates -> nearest fresh station in now.json -> AQI,
    category, dominant pollutant, plus the "Kaun?" line (who caused the latest
    nearby spike) and category advice. Templates only, no LLM: well inside the
    2 s VAPI budget.

report_pollution(location, pollution_type, details, language, call_id, caller)
    Saves a citizen report to Supabase citizen_reports (service key, 1.5 s
    timeout). The hourly cron folds these into agency reports
    (reporting/citizen.py), independent of the call.

Standard library only.
"""

import hashlib
import json
import math
import os
import urllib.request
from datetime import datetime, timezone
from typing import Optional

from advisory.fallbacks import fallback_advisory
from attribution.publish.voice import answer as kaun_answer

from . import feeds, geocode

MAX_STATION_KM = 12.0
POLLUTANT_EN = {"pm25": "fine dust, PM2.5", "pm10": "dust, PM10", "no2": "nitrogen dioxide",
                "so2": "sulphur dioxide", "co": "carbon monoxide", "o3": "ozone"}
POLLUTANT_HI = {"pm25": "बारीक धूल, पीएम 2.5", "pm10": "धूल, पीएम 10", "no2": "नाइट्रोजन डाइऑक्साइड",
                "so2": "सल्फर डाइऑक्साइड", "co": "कार्बन मोनोऑक्साइड", "o3": "ओज़ोन"}
CATEGORY_HI = {"Good": "अच्छी", "Satisfactory": "संतोषजनक", "Moderate": "मध्यम", "Poor": "खराब",
               "Very Poor": "बहुत खराब", "Severe": "गंभीर"}
REPORT_TYPES = ("dust", "vehicular", "industrial", "burning", "other")


def _km(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 12742.0 * math.asin(math.sqrt(a))


def _lang(language: Optional[str]) -> str:
    return "hi" if (language or "").lower().startswith("hi") else "en"


def nearest_station(lat: float, lon: float, now_feed: dict) -> Optional[tuple[dict, float]]:
    best = None
    for s in (now_feed or {}).get("stations", []):
        if s.get("aqi") is None or s.get("stale") or s.get("latitude") is None:
            continue
        d = _km(lat, lon, float(s["latitude"]), float(s["longitude"]))
        if best is None or d < best[1]:
            best = (s, d)
    return best


def _sorry(lang: str, what: str) -> str:
    if lang == "hi":
        return {"place": "माफ़ कीजिए, यह जगह नहीं मिली। कृपया पास का कोई बड़ा इलाका या मेट्रो स्टेशन बताइए।",
                "data": "माफ़ कीजिए, अभी हवा का ताज़ा डेटा उपलब्ध नहीं है। थोड़ी देर बाद फिर कोशिश करें।",
                "far": "माफ़ कीजिए, उस जगह के पास कोई चालू निगरानी स्टेशन नहीं है।"}[what]
    return {"place": "Sorry, I could not find that place. Please name a nearby area or metro station.",
            "data": "Sorry, fresh air quality data is not available right now. Please try again shortly.",
            "far": "Sorry, there is no working monitoring station near that place."}[what]


def get_air_quality(location: str, language: str = "en", allow_network: bool = True) -> dict:
    lang = _lang(language)
    now_feed = feeds.load("now.json")
    if not now_feed or not now_feed.get("stations"):
        return {"ok": False, "speech": _sorry(lang, "data")}
    place = geocode.resolve(location, now_feed["stations"], allow_network=allow_network)
    if not place:
        return {"ok": False, "speech": _sorry(lang, "place")}
    hit = nearest_station(place["latitude"], place["longitude"], now_feed)
    if not hit or hit[1] > MAX_STATION_KM:
        return {"ok": False, "speech": _sorry(lang, "far"), "place": place}
    st, dist = hit
    station = geocode.station_short_name(st["name"])
    latest = (feeds.load("latest.json") or {}).get("attributions", [])
    # Phone callers hear only medium/high estimates; low ones are on the map with caveats.
    kaun = kaun_answer(place["latitude"], place["longitude"], lang, records=latest, min_confidence="medium")
    advice = fallback_advisory(st["category"], lang)
    dom = st.get("dominant_pollutant")
    if lang == "hi":
        speech = (f"{place['label']} के पास, {station} स्टेशन पर हवा {CATEGORY_HI.get(st['category'], st['category'])} है, "
                  f"एक्यूआई {st['aqi']}। सबसे ज़्यादा {POLLUTANT_HI.get(dom, dom)}। "
                  f"{kaun or 'पिछले कुछ घंटों में यहां कोई असामान्य उछाल नहीं दिखा।'} {advice}")
    else:
        speech = (f"Near {place['label']}, the {station} station reads AQI {st['aqi']}, which is {st['category']}. "
                  f"The main pollutant is {POLLUTANT_EN.get(dom, dom)}. "
                  f"{kaun or 'No unusual spike nearby in the last few hours.'} {advice}")
    return {
        "ok": True, "speech": " ".join(speech.split()),
        "place": place, "station": st["name"], "distance_km": round(dist, 1),
        "aqi": st["aqi"], "category": st["category"], "dominant_pollutant": dom,
        "kaun": kaun, "data_hour": st.get("latest_hour"),
    }


def _supabase_insert(table: str, row: dict, timeout: float = 1.5) -> bool:
    url, key = os.getenv("SUPABASE_URL", "").rstrip("/"), os.getenv("SUPABASE_KEY", "")
    if not url or not key or table != "citizen_reports":
        return False
    req = urllib.request.Request(
        f"{url}/rest/v1/{table}", data=json.dumps(row).encode("utf-8"), method="POST",
        headers={"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json",
                 "Prefer": "return=minimal"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except OSError:
        return False


def report_pollution(location: str, pollution_type: str, details: str = "", language: str = "en",
                     call_id: Optional[str] = None, caller: Optional[str] = None,
                     allow_network: bool = True) -> dict:
    lang = _lang(language)
    ptype = (pollution_type or "other").strip().lower()
    if ptype not in REPORT_TYPES:  # whitelist: becomes a DB value and an agency routing key
        ptype = "other"
    now_feed = feeds.load("now.json") or {}
    place = geocode.resolve(location, now_feed.get("stations", []), allow_network=allow_network)
    if not place:
        return {"ok": False, "speech": _sorry(lang, "place")}
    row = {
        "call_id": (call_id or "")[:80] or None,
        # Privacy: never store the raw number; a salted hash still lets the
        # cron spot one caller filing ten reports.
        "caller_number": hashlib.sha256(f"vayuvani|{caller}".encode()).hexdigest()[:16] if caller else None,
        "neighborhood": place["label"][:120],
        "latitude": place["latitude"], "longitude": place["longitude"],
        "pollution_type": ptype,
        "description": (details or "")[:500],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    saved = _supabase_insert("citizen_reports", row)
    if lang == "hi":
        speech = (f"धन्यवाद। {place['label']} की आपकी शिकायत दर्ज हो गई है। जांच के बाद यह संबंधित विभाग को भेजी जाएगी।"
                  if saved else "माफ़ कीजिए, अभी शिकायत दर्ज नहीं हो पाई। कृपया थोड़ी देर बाद फिर कोशिश करें।")
    else:
        speech = (f"Thank you. Your report for {place['label']} is recorded. It will be checked and sent to the "
                  f"responsible department." if saved else
                  "Sorry, I could not record the report right now. Please try again shortly.")
    return {"ok": saved, "speech": speech, "place": place, "pollution_type": ptype}
