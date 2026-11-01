"""
Spike detector.

Per station and pollutant, the baseline for hour t is the median of the same
hour over the previous BASELINE_DAYS days (diurnal cycle removed for free).
A PM2.5 spike is an hour above  median + SPIKE_K * 1.4826 * MAD  AND at least
SPIKE_MIN_ABS ug/m3 above the median. With too few same-hour samples the
baseline falls back to the trailing 24 h median, and the window is tagged so
confidence drops.

Input: a long DataFrame with columns station_id, hour (UTC, tz-aware) and
pollutant columns. Output: same rows plus base_<p>, delta_<p>, is_spike,
baseline_kind.
"""

import warnings

import numpy as np
import pandas as pd

from ..config import (BASELINE_DAYS, MAD_FLOOR, MIN_BASELINE_SAMPLES, POLLUTANTS,
                      SPIKE_K, SPIKE_MIN_ABS)


def _station_baseline(s: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    """s: hourly series on a complete hourly index. Returns (median, mad, n_samples)."""
    lags = np.column_stack([s.shift(24 * d).to_numpy(dtype=float) for d in range(1, BASELINE_DAYS + 1)])
    n = np.sum(~np.isnan(lags), axis=1)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # all-NaN rows -> NaN, expected
        med = np.nanmedian(lags, axis=1)
        mad = np.nanmedian(np.abs(lags - med[:, None]), axis=1)
    return (pd.Series(med, index=s.index), pd.Series(mad, index=s.index), pd.Series(n, index=s.index))


def _fallback_baseline(s: pd.Series) -> tuple[pd.Series, pd.Series]:
    prev = s.shift(1)
    med = prev.rolling(24, min_periods=12).median()
    mad = (prev - med).abs().rolling(24, min_periods=12).median()
    return med, mad


def detect(obs: pd.DataFrame) -> pd.DataFrame:
    if obs.empty:
        return obs.assign(is_spike=pd.Series(dtype=bool))
    obs = obs.copy()
    obs["hour"] = pd.to_datetime(obs["hour"], utc=True)
    out = []
    for sid, g in obs.groupby("station_id", sort=False):
        g = g.drop_duplicates("hour", keep="last").set_index("hour").sort_index()
        full = pd.date_range(g.index.min(), g.index.max(), freq="h", tz="UTC")
        g = g.reindex(full)
        g["station_id"] = sid
        kind = pd.Series("same-hour-7d", index=g.index)
        for p in POLLUTANTS:
            if p not in g.columns:
                g[p] = np.nan
            s = g[p].astype(float)
            med, mad, n = _station_baseline(s)
            fmed, fmad = _fallback_baseline(s)
            use_fb = n < MIN_BASELINE_SAMPLES
            med = med.where(~use_fb, fmed)
            mad = mad.where(~use_fb, fmad)
            g[f"base_{p}"] = med
            g[f"mad_{p}"] = mad
            g[f"delta_{p}"] = s - med
            if p == "pm25":
                kind = kind.where(~use_fb, "trailing-24h")
        thr = g["base_pm25"] + SPIKE_K * 1.4826 * g["mad_pm25"].clip(lower=MAD_FLOOR)
        g["threshold_pm25"] = thr
        g["is_spike"] = (
            g["pm25"].notna() & g["base_pm25"].notna()
            & (g["pm25"] > thr) & (g["delta_pm25"] >= SPIKE_MIN_ABS)
        )
        g["baseline_kind"] = kind.where(g["base_pm25"].notna(), "none")
        g = g.loc[g["pm25"].notna() | g[[p for p in POLLUTANTS]].notna().any(axis=1)]
        out.append(g.rename_axis("hour").reset_index())
    return pd.concat(out, ignore_index=True)


def windows(flagged: pd.DataFrame, max_gap_hours: int = 1) -> list[dict]:
    """Group consecutive spike hours (gaps up to max_gap_hours) into windows."""
    result = []
    spikes = flagged.loc[flagged["is_spike"]].sort_values(["station_id", "hour"])
    for sid, g in spikes.groupby("station_id", sort=False):
        hours = list(g["hour"])
        start = prev = hours[0]
        members = [start]
        for h in hours[1:]:
            if (h - prev) <= pd.Timedelta(hours=max_gap_hours + 1):
                members.append(h)
            else:
                result.append({"station_id": sid, "start": start, "end": prev, "hours": members})
                start, members = h, [h]
            prev = h
        result.append({"station_id": sid, "start": start, "end": prev, "hours": members})
    return result
