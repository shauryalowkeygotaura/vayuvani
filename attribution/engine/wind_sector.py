"""
Wind-sector analysis.

Two views:
1. The spike window's own wind: speed-weighted vector mean of the direction
   the wind blows FROM, plus the resultant length R (0 = swirling, 1 = steady).
   Calm (<1 m/s) means the source is close by in any direction.
2. CBPF (conditional bivariate probability function, Uria-Tellaetxe & Carslaw
   2014): over the station's history, P(PM2.5 > 75th percentile | sector,
   speed bin). The sector with the highest probability is where high
   concentrations usually come from at this station.
"""

from typing import Optional

import numpy as np
import pandas as pd

from ..labels import SECTORS_EN, SECTORS_HI  # noqa: F401 (re-exported)

SECTORS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
CALM_MS = 1.0
SPEED_BINS = (0.0, 1.0, 3.0, 6.0, np.inf)


def sector_of(deg: Optional[float]) -> Optional[str]:
    if deg is None or not np.isfinite(deg):
        return None
    return SECTORS[int(((deg % 360) + 22.5) // 45) % 8]


def vector_mean(dirs, speeds) -> tuple[Optional[float], float, float]:
    """(mean_direction_deg, resultant_length_R, mean_speed)."""
    d = np.asarray(dirs, dtype=float)
    s = np.asarray(speeds, dtype=float)
    ok = np.isfinite(d) & np.isfinite(s)
    if not ok.any():
        return None, 0.0, 0.0
    d, s = np.radians(d[ok]), s[ok]
    w = np.where(s > 0, s, 1e-6)
    u, v = np.sum(w * np.sin(d)), np.sum(w * np.cos(d))
    r = float(np.hypot(u, v) / np.sum(w))
    mean = (np.degrees(np.arctan2(u, v)) + 360) % 360
    return float(mean), r, float(np.mean(s))


def window_wind(rows: pd.DataFrame) -> dict:
    if "wind_dir" not in rows or rows["wind_dir"].notna().sum() == 0:
        return {"sector": None, "direction_deg": None, "steadiness": 0.0, "speed_ms": None, "calm": None}
    mean, r, spd = vector_mean(rows["wind_dir"], rows["wind_speed"])
    calm = spd < CALM_MS
    return {
        "sector": None if calm else sector_of(mean),
        "direction_deg": None if mean is None else round(mean, 0),
        "steadiness": round(r, 2),
        "speed_ms": round(spd, 2),
        "calm": bool(calm),
    }


def cbpf(hist: pd.DataFrame, pct: float = 75.0, col: str = "pm25") -> dict:
    """{sector: probability} that `col` exceeds its pct-th percentile, given wind from that sector."""
    if col not in hist or "wind_dir" not in hist:
        return {}
    h = hist.dropna(subset=[col, "wind_dir", "wind_speed"])
    if len(h) < 48:
        return {}
    thr = np.percentile(h[col], pct)
    sec = h["wind_dir"].map(sector_of)
    calm = h["wind_speed"] < CALM_MS
    out = {}
    for s in SECTORS:
        m = (sec == s) & ~calm
        if m.sum() >= 6:
            out[s] = round(float((h.loc[m, col] > thr).mean()), 3)
    return out


def top_sector(probs: dict) -> Optional[str]:
    return max(probs, key=probs.get) if probs else None
