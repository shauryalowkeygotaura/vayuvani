"""
India National AQI (NAQI) calculator.
Source: CPCB "National Air Quality Index" technical document.

Final AQI = max of all pollutant sub-indices.
Each sub-index uses linear interpolation between breakpoints.
"""

from dataclasses import dataclass
from typing import Optional

# Breakpoints: (C_low, C_high, I_low, I_high)
# Concentration in µg/m³ (or mg/m³ for CO), index value
_BREAKPOINTS = {
    "pm25": [
        (0.0, 30.0, 0, 50),
        (30.0, 60.0, 51, 100),
        (60.0, 90.0, 101, 200),
        (90.0, 120.0, 201, 300),
        (120.0, 250.0, 301, 400),
        (250.0, 500.0, 401, 500),
    ],
    "pm10": [
        (0.0, 50.0, 0, 50),
        (50.0, 100.0, 51, 100),
        (100.0, 250.0, 101, 200),
        (250.0, 350.0, 201, 300),
        (350.0, 430.0, 301, 400),
        (430.0, 600.0, 401, 500),
    ],
    "no2": [
        (0.0, 40.0, 0, 50),
        (40.0, 80.0, 51, 100),
        (80.0, 180.0, 101, 200),
        (180.0, 280.0, 201, 300),
        (280.0, 400.0, 301, 400),
        (400.0, 800.0, 401, 500),
    ],
    "so2": [
        (0.0, 40.0, 0, 50),
        (40.0, 80.0, 51, 100),
        (80.0, 380.0, 101, 200),
        (380.0, 800.0, 201, 300),
        (800.0, 1600.0, 301, 400),
        (1600.0, 2620.0, 401, 500),
    ],
    # CO in mg/m³
    "co": [
        (0.0, 1.0, 0, 50),
        (1.0, 2.0, 51, 100),
        (2.0, 10.0, 101, 200),
        (10.0, 17.0, 201, 300),
        (17.0, 34.0, 301, 400),
        (34.0, 58.0, 401, 500),
    ],
    "o3": [
        (0.0, 50.0, 0, 50),
        (50.0, 100.0, 51, 100),
        (100.0, 168.0, 101, 200),
        (168.0, 208.0, 201, 300),
        (208.0, 748.0, 301, 400),
        (748.0, 1000.0, 401, 500),
    ],
    "nh3": [
        (0.0, 200.0, 0, 50),
        (200.0, 400.0, 51, 100),
        (400.0, 800.0, 101, 200),
        (800.0, 1200.0, 201, 300),
        (1200.0, 1800.0, 301, 400),
        (1800.0, 2400.0, 401, 500),
    ],
}

CATEGORIES = [
    (0, 50, "Good"),
    (51, 100, "Satisfactory"),
    (101, 200, "Moderate"),
    (201, 300, "Poor"),
    (301, 400, "Very Poor"),
    (401, 500, "Severe"),
]


@dataclass
class AQIResult:
    aqi: int
    category: str
    dominant_pollutant: str
    sub_indices: dict[str, int]


def _sub_index(pollutant: str, concentration: float) -> Optional[int]:
    """Linear interpolation within the matching breakpoint range."""
    breakpoints = _BREAKPOINTS.get(pollutant)
    if breakpoints is None or concentration < 0:
        return None
    for c_lo, c_hi, i_lo, i_hi in breakpoints:
        if c_lo <= concentration <= c_hi:
            ratio = (concentration - c_lo) / (c_hi - c_lo)
            return round(i_lo + ratio * (i_hi - i_lo))
    # Above highest breakpoint — cap at 500
    return 500


def _category(aqi: int) -> str:
    for lo, hi, label in CATEGORIES:
        if lo <= aqi <= hi:
            return label
    return "Severe"


def calculate(
    pm25: Optional[float] = None,
    pm10: Optional[float] = None,
    no2: Optional[float] = None,
    so2: Optional[float] = None,
    co: Optional[float] = None,
    o3: Optional[float] = None,
    nh3: Optional[float] = None,
) -> Optional[AQIResult]:
    """
    Returns AQIResult or None if no valid pollutant data provided.
    At least one pollutant must be non-None for a result.
    """
    pollutants = {
        "pm25": pm25,
        "pm10": pm10,
        "no2": no2,
        "so2": so2,
        "co": co,
        "o3": o3,
        "nh3": nh3,
    }

    sub_indices: dict[str, int] = {}
    for name, value in pollutants.items():
        if value is not None:
            idx = _sub_index(name, value)
            if idx is not None:
                sub_indices[name] = idx

    if not sub_indices:
        return None

    max_pollutant = max(sub_indices, key=lambda k: sub_indices[k])
    aqi = sub_indices[max_pollutant]

    return AQIResult(
        aqi=aqi,
        category=_category(aqi),
        dominant_pollutant=max_pollutant,
        sub_indices=sub_indices,
    )
