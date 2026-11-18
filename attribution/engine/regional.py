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
STAGNANT_WIND_MS = 1.5      # city-mean wind below this cannot ventilate the airshed
STAGNANT_PBL_RATIO = 0.6    # mixing height below 60% of its same-hour norm: emissions trapped


def regional_profile(flagged: pd.DataFrame, hours, start: pd.Timestamp, fires_up: dict,
                     transported: bool, history_days: int = 30) -> dict:
    """
    What the REGIONAL part of a spike is made of, and why it happened.

    The regional share says how much of a station's rise the whole airshed
    shared; this says what that shared rise looks like. Composition: the ratio
    fingerprint (fingerprints.score) applied to the city-median excess of each
    species over the window, against a pooled 30-day ratio history, so the
    result reads "the trapped air is burning-like" or "traffic-like".
    Mechanism: transport (fires upwind, wind that can carry them), stagnation
    (city-mean wind < STAGNANT_WIND_MS or mixing height < STAGNANT_PBL_RATIO
    of its same-hour norm), else a plain regional rise. Stagnation does not
    emit anything: it is the lid under which the city's own emissions pile up,
    which is why composition still matters.
    """
    from . import fingerprints
    from ..config import DELTA_VARS, EXTRA_VARS, POLLUTANTS
    from ..ingest import traffic

    hours = pd.DatetimeIndex(hours)
    rows = flagged.loc[flagged["hour"].isin(hours)]
    n_st = int(rows["station_id"].nunique()) if not rows.empty else 0
    out: dict = {"n_stations": n_st, "mechanism": "unclear", "composition": {}, "ratios": {},
                 "wind_ms": None, "pbl_ratio": None, "stagnant": None, "transported": bool(transported),
                 "upwind_fires": int(fires_up.get("count", 0) or 0)}
    if n_st < MIN_STATIONS_FOR_REGIONAL:
        return out

    def med(col):
        if col not in rows:
            return None
        s = rows[col].astype(float).dropna()
        return None if s.size < MIN_STATIONS_FOR_REGIONAL else float(s.median())

    d = {p: med(f"delta_{p}") for p in DELTA_VARS}
    totals = {p: med(p) for p in POLLUTANTS + EXTRA_VARS}
    hist = flagged.loc[(flagged["hour"] < start) & (flagged["hour"] >= start - pd.Timedelta(days=history_days))]
    tprior = float(np.mean([traffic.prior(h.to_pydatetime()) for h in hours]))
    fp = fingerprints.score(d, totals, fingerprints.station_ratio_history(hist), tprior)
    # Same evidence pool as a station (ratios, humidity, hour and temperature) so
    # "secondary" can show up: humid stagnant nights grow particles from gases,
    # and that part has no chimney to point at.
    from . import fusion
    fused = fusion.fuse({
        "fingerprint": fusion.term_fingerprint(fp["scores"]),
        "secondary_rh": fusion.term_secondary(fp["ratios"], totals.get("rh")),
        "time_temp": fusion.term_time_temp(list(hours), tprior, totals.get("temp")),
    })
    out["composition"] = fused["shares"]
    out["ratios"] = fp["ratios"]

    wind_ms = med("wind_speed")
    out["wind_ms"] = None if wind_ms is None else round(wind_ms, 2)
    pbl_now = med("pbl_height")
    if pbl_now is not None and "pbl_height" in hist:
        ref = hist.loc[hist["hour"].dt.hour.isin(hours.hour.unique())
                       & (hist["hour"] >= start - pd.Timedelta(days=7)), "pbl_height"].dropna()
        if ref.size >= 3 and ref.median() > 0:
            out["pbl_ratio"] = round(float(pbl_now / ref.median()), 2)
    stagnant = ((wind_ms is not None and wind_ms < STAGNANT_WIND_MS)
                or (out["pbl_ratio"] is not None and out["pbl_ratio"] < STAGNANT_PBL_RATIO))
    out["stagnant"] = bool(stagnant) if (wind_ms is not None or out["pbl_ratio"] is not None) else None
    out["mechanism"] = "transport" if transported else "stagnation" if stagnant else "regional_rise"
    return out


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
