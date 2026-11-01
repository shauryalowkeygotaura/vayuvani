"""
Synthetic Delhi-like data for tests and offline dry runs. NOT real data.

Generates hourly obs for a handful of stations with a diurnal cycle, noise,
and injected spikes of known type, so the engine can be checked end to end
without network access. Anything produced from this module is tagged
synthetic and must never be published as an attribution.
"""

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

STATIONS = {
    "anand-vihar-delhi-dpcc": {"name": "Anand Vihar, Delhi - DPCC", "latitude": 28.6468, "longitude": 77.3160},
    "r-k-puram-delhi-dpcc": {"name": "R K Puram, Delhi - DPCC", "latitude": 28.5633, "longitude": 77.1869},
    "punjabi-bagh-delhi-dpcc": {"name": "Punjabi Bagh, Delhi - DPCC", "latitude": 28.6740, "longitude": 77.1310},
    "okhla-phase-2-delhi-dpcc": {"name": "Okhla Phase-2, Delhi - DPCC", "latitude": 28.5308, "longitude": 77.2713},
    "mundka-delhi-dpcc": {"name": "Mundka, Delhi - DPCC", "latitude": 28.6842, "longitude": 77.0767},
    "lodhi-road-delhi-imd": {"name": "Lodhi Road, Delhi - IMD", "latitude": 28.5918, "longitude": 77.2273},
}

# station -> (day offset from end, IST hour, n hours, type)
SPIKES = {
    "anand-vihar-delhi-dpcc": (1, 19, 3, "biomass_burning"),
    "r-k-puram-delhi-dpcc": (1, 9, 2, "traffic"),
    "mundka-delhi-dpcc": (1, 14, 3, "dust"),
    "okhla-phase-2-delhi-dpcc": (1, 3, 3, "industry"),
}


def generate(days: int = 12, end: datetime | None = None, seed: int = 1) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    end = (end or datetime(2026, 11, 1, 0, tzinfo=timezone.utc)).replace(minute=0, second=0, microsecond=0)
    hours = pd.date_range(end - timedelta(days=days), end - timedelta(hours=1), freq="h", tz="UTC")
    ist_h = ((hours.hour + 5) % 24).to_numpy()  # IST hour, ignoring the half-hour
    diurnal = 1.0 + 0.35 * np.cos((ist_h - 22) / 24 * 2 * np.pi)
    obs, wind = [], []
    for sid in STATIONS:
        n = len(hours)
        pm25 = 110 * diurnal * rng.lognormal(0, 0.08, n)
        pm10 = pm25 / 0.55 * rng.lognormal(0, 0.06, n)
        no2 = 55 * diurnal * rng.lognormal(0, 0.1, n)
        co = 1.6 * diurnal * rng.lognormal(0, 0.1, n)
        so2 = 12 * rng.lognormal(0, 0.15, n)
        o3 = 30 * (2 - diurnal) * rng.lognormal(0, 0.15, n)
        ws = np.clip(2.5 + rng.normal(0, 0.4, n), 0.3, None)
        wd = (300 + rng.normal(0, 15, n)) % 360

        if sid in SPIKES:
            day_off, h_ist, length, kind = SPIKES[sid]
            target_day = (end - timedelta(days=day_off)).date()
            idx = [i for i, h in enumerate(hours)
                   if (h + timedelta(hours=5, minutes=30)).date() == target_day
                   and h_ist <= (h + timedelta(hours=5, minutes=30)).hour < h_ist + length]
            for i in idx:
                if kind == "biomass_burning":
                    pm25[i] += 180; pm10[i] += 200; co[i] += 0.9; no2[i] += 2; wd[i] = 90
                elif kind == "traffic":
                    pm25[i] += 70; pm10[i] += 90; no2[i] += 110; co[i] += 2.5
                elif kind == "dust":
                    pm25[i] += 60; pm10[i] += 420
                elif kind == "industry":
                    pm25[i] += 80; pm10[i] += 110; so2[i] += 90; co[i] += 0.3
        for i, h in enumerate(hours):
            obs.append({"station_id": sid, "hour": h, "pm25": pm25[i], "pm10": pm10[i], "no2": no2[i],
                        "so2": so2[i], "co": co[i], "o3": o3[i], "source": "synthetic"})
            wind.append({"station_id": sid, "hour": h, "wind_speed": ws[i], "wind_dir": wd[i],
                         "pbl_height": 800.0 * (2.2 - diurnal[i]), "source": "synthetic"})
    return pd.DataFrame(obs), pd.DataFrame(wind)
