"""
Regional vs local split, plus an upwind-fire check.

Regional background for an hour = the REGIONAL_PERCENTILE-th percentile of
PM2.5 across all stations (the cleanest stations see only what the whole
airshed sees). If the background rose as much as the station did, the spike
is regional; the station's excess over the background is local.

Transported smoke: regional excess AND FIRMS fires inside a cone upwind of
Delhi. The "back-trajectory" here is a straight line along the city's mean
wind over the previous 24 h. That is a crude stand-in for HYSPLIT: it ignores
curvature, height and timing, so it can only raise a flag, never prove
transport. Outputs say so.
"""

from typing import Optional

import numpy as np
import pandas as pd

from ..config import MIN_STATIONS_FOR_REGIONAL, REGIONAL_PERCENTILE, UPWIND_HALF_ANGLE_DEG
from .wind_sector import vector_mean

MIN_UPWIND_FIRES = 15


def background_series(obs: pd.DataFrame) -> pd.Series:
    """Hourly city-wide background PM2.5 (NaN where too few stations report)."""
    g = obs.dropna(subset=["pm25"]).groupby("hour")["pm25"]
    bg = g.quantile(REGIONAL_PERCENTILE / 100.0)
    n = g.count()
    return bg.where(n >= MIN_STATIONS_FOR_REGIONAL)


def regional_share(station_delta: float, window_hours, bg: pd.Series) -> Optional[float]:
    """
    Fraction of the station's PM2.5 excess explained by the background rising.
    The background's own baseline is its same-hour median over the prior 7
    days, so the normal diurnal rise is not mistaken for a regional event.
    """
    if bg.empty or station_delta is None or not np.isfinite(station_delta) or station_delta <= 0:
        return None
    rises = []
    for h in pd.DatetimeIndex(window_hours):
        now = bg.get(h, np.nan)
        prior = bg.reindex([h - pd.Timedelta(days=d) for d in range(1, 8)]).dropna()
        if np.isfinite(now) and prior.size >= 4:
            rises.append(now - prior.median())
    if not rises:
        return None
    return float(min(1.0, max(0.0, np.mean(rises) / station_delta)))


def _angle_diff(a: float, b: float) -> float:
    return abs((a - b + 180) % 360 - 180)


def upwind_fires(fires: list[dict], wind: pd.DataFrame, at: pd.Timestamp) -> dict:
    """
    Fires within the upwind cone, using the city-mean wind over the 24 h before
    `at`. Wind direction is where wind blows FROM, which is also the bearing
    from Delhi toward the upwind fires.
    """
    w = wind.loc[(wind["hour"] <= at) & (wind["hour"] > at - pd.Timedelta(hours=24))] if not wind.empty else wind
    if w is None or w.empty:
        return {"upwind_dir_deg": None, "count": 0, "frp_sum": 0.0, "note": "no wind data"}
    mean_dir, r, spd = vector_mean(w["wind_dir"], w["wind_speed"])
    if mean_dir is None:
        return {"upwind_dir_deg": None, "count": 0, "frp_sum": 0.0, "note": "no wind data"}
    recent = []
    for f in fires:
        t = pd.Timestamp(f["acq_time"])
        t = t.tz_localize("UTC") if t.tzinfo is None else t
        if not (at - pd.Timedelta(hours=48) <= t <= at):
            continue
        if _angle_diff(float(f["bearing_from_delhi"]), mean_dir) <= UPWIND_HALF_ANGLE_DEG:
            recent.append(f)
    frp = float(sum((f.get("frp") or 0.0) for f in recent))
    return {
        "upwind_dir_deg": round(mean_dir, 0),
        "wind_steadiness_24h": round(r, 2),
        "mean_speed_ms": round(spd, 2),
        "count": len(recent),
        "frp_sum": round(frp, 1),
        "note": "straight-line 24 h mean wind, not a modelled back-trajectory",
    }


MIN_TRANSPORT_WIND_MS = 2.0
MIN_TRANSPORT_STEADINESS = 0.5


def is_transported(reg_share: Optional[float], fires: dict) -> bool:
    """
    Regional excess + fires upwind + wind that can actually carry smoke: at
    < 2 m/s or swirling wind, smoke from 100-300 km away cannot arrive within
    a day, so a regional rise in stagnant air is called regional, not transported.
    """
    if reg_share is None or reg_share < 0.3 or fires.get("count", 0) < MIN_UPWIND_FIRES:
        return False
    spd, steady = fires.get("mean_speed_ms"), fires.get("wind_steadiness_24h")
    if spd is None or steady is None:
        return False
    return spd >= MIN_TRANSPORT_WIND_MS and steady >= MIN_TRANSPORT_STEADINESS
