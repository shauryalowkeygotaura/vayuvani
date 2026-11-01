"""
Unit normalisation and station-id helpers shared by the ingest sources.

Target units match pipeline/aqi_calc.py: ug/m3 for gases and PM, mg/m3 for CO.
Gas conversions assume 25 C and 1 atm (molar volume 24.45 L), the convention
CPCB's NAQI document uses.
"""

import re
from typing import Optional

MOLAR_VOLUME = 24.45
MW = {"no2": 46.01, "so2": 64.07, "o3": 48.00, "co": 28.01}

_UNIT_ALIASES = {
    "µg/m³": "ugm3", "μg/m³": "ugm3", "ug/m3": "ugm3", "µg/m3": "ugm3", "μg/m3": "ugm3",
    "mg/m³": "mgm3", "mg/m3": "mgm3",
    "ppm": "ppm", "ppb": "ppb",
}


def normalise_unit(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    return _UNIT_ALIASES.get(raw.strip().lower().replace(" ", ""), _UNIT_ALIASES.get(raw.strip()))


def to_standard(param: str, value: Optional[float], unit: Optional[str]) -> Optional[float]:
    """
    Convert one reading to the house unit. Returns None for unknown units or
    negative values (sensor error), so a bad unit can never be silently stored
    1000x off.
    """
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v != v or v < 0:
        return None
    u = normalise_unit(unit)
    if param in ("pm25", "pm10"):
        return v if u in ("ugm3", None) else None
    if param == "co":
        if u == "mgm3":
            return v
        if u == "ugm3":
            return v / 1000.0
        if u == "ppm":
            return v * MW["co"] / MOLAR_VOLUME
        if u == "ppb":
            return v * MW["co"] / MOLAR_VOLUME / 1000.0
        return None
    if param in ("no2", "so2", "o3"):
        if u == "ugm3":
            return v
        if u == "ppm":
            return v * MW[param] * 1000.0 / MOLAR_VOLUME
        if u == "ppb":
            return v * MW[param] / MOLAR_VOLUME
        return None
    return None


def station_slug(name: str) -> str:
    """
    Stable station id from a name, so OpenAQ ("Anand Vihar, Delhi - DPCC") and
    CPCB rows for the same site land on one key.
    """
    s = name.lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:80]
