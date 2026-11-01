"""
Shared constants for "Kaun?", the Delhi pollution attribution engine.

Everything tunable lives here so the engine stays deterministic and auditable:
a reviewer can read one file and see every threshold the attributions depend on.
"""

import os

# Delhi centre (India Gate area) and the FIRMS search box.
DELHI_LAT = 28.6139
DELHI_LON = 77.2090
FIRE_RADIUS_KM = 300.0
# ~300 km box: 1 deg lat = 111 km, 1 deg lon at 28.6N = ~97.5 km.
FIRMS_BBOX = (
    round(DELHI_LON - FIRE_RADIUS_KM / 97.5, 2),   # west
    round(DELHI_LAT - FIRE_RADIUS_KM / 111.0, 2),  # south
    round(DELHI_LON + FIRE_RADIUS_KM / 97.5, 2),   # east
    round(DELHI_LAT + FIRE_RADIUS_KM / 111.0, 2),  # north
)
FIRMS_SOURCES = ("VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT", "MODIS_NRT")
FIRMS_DAY_RANGE = 2

# Pollutant columns tracked hourly. Units: ug/m3, except CO in mg/m3
# (same convention as pipeline/aqi_calc.py and the aqi_readings table).
POLLUTANTS = ("pm25", "pm10", "no2", "so2", "co", "o3")

# Ingest window: a normal hourly run fetches since the checkpoint, capped so a
# long outage cannot turn one run into thousands of calls.
MAX_BACKFILL_HOURS = 72
DEFAULT_LOOKBACK_HOURS = 6

# Spike detector.
BASELINE_DAYS = 7          # same-hour median over this many prior days
MIN_BASELINE_SAMPLES = 4   # fewer same-hour samples -> fall back to a 24 h median
SPIKE_K = 3.0              # threshold = median + K * 1.4826 * MAD
SPIKE_MIN_ABS = 25.0       # and at least this many ug/m3 above baseline
MAD_FLOOR = 5.0            # MAD floor so a flat baseline does not flag noise

# Factor analysis.
NMF_WINDOW_DAYS = 30
NMF_COMPONENTS = 4
NMF_MIN_ROWS = 72

# Regional vs local.
REGIONAL_PERCENTILE = 10   # city-wide background = this percentile across stations
MIN_STATIONS_FOR_REGIONAL = 5
UPWIND_HALF_ANGLE_DEG = 30.0

# Paths.
STATE_DIR = os.getenv("KAUN_STATE_DIR", ".kaun_state")
PUBLIC_DIR = os.getenv("KAUN_PUBLIC_DIR", "public")
REPO_SLUG = os.getenv("GITHUB_REPOSITORY", "shauryalowkeygotaura/vayuvani")
