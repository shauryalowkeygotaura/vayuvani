"""
Current NAQI per station -> public/data/now.json (what the phone line reads).

Averaging follows the NAQI convention: 24 h means for PM2.5, PM10, NO2, SO2;
8 h means for CO and O3. A sub-index needs >= 16 of the 24 hours (6 of 8 for
the 8 h pollutants). The overall AQI needs >= 3 pollutants, one of them PM2.5
or PM10; otherwise the station is listed with aqi = null and the reason.
Sources: IES Arthapedia, National Air Quality Index
(https://ies.gov.in/arthapedia/concept/national-air-quality-index).

Also carries the latest raw hour, so a caller can hear "right now" values next
to the official-style index.
"""

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np
import pandas as pd

from pipeline.aqi_calc import calculate

from ..config import DATA_SUBDIR, PUBLIC_DIR

WINDOWS = {"pm25": 24, "pm10": 24, "no2": 24, "so2": 24, "co": 8, "o3": 8}
MIN_HOURS = {24: 16, 8: 6}
STALE_HOURS = 4  # OpenAQ hourly data lands 2-3.5 h late (measured 2026-11-01)


def station_naqi(rows: pd.DataFrame, now: datetime) -> dict:
    """rows: one station's hourly obs (hour UTC). Returns the NAQI block."""
    rows = rows.sort_values("hour")
    means: dict[str, Optional[float]] = {}
    for p, w in WINDOWS.items():
        if p not in rows:
            means[p] = None
            continue
        win = rows.loc[rows["hour"] > now - timedelta(hours=w), p].astype(float).dropna()
        means[p] = round(float(win.mean()), 2) if len(win) >= MIN_HOURS[w] else None
    present = [p for p, v in means.items() if v is not None]
    reason = None
    if len(present) < 3 or not ({"pm25", "pm10"} & set(present)):
        res = None
        reason = f"insufficient data ({len(present)} pollutants with enough hours)"
    else:
        res = calculate(**{p: means[p] for p in present})
    last = rows.dropna(subset=["pm25"]).tail(1) if "pm25" in rows else rows.tail(0)
    last_hour = rows["hour"].max()
    latest = {}
    if not rows.empty:
        lr = rows.loc[rows["hour"] == last_hour].iloc[0]
        latest = {p: (None if p not in lr or pd.isna(lr[p]) else round(float(lr[p]), 2)) for p in WINDOWS}
    return {
        "aqi": res.aqi if res else None,
        "category": res.category if res else None,
        "dominant_pollutant": res.dominant_pollutant if res else None,
        "sub_indices": res.sub_indices if res else {},
        "averages": means,
        "latest_hour": None if pd.isna(last_hour) else pd.Timestamp(last_hour).isoformat(),
        "latest": latest,
        "stale": bool(pd.isna(last_hour) or now - pd.Timestamp(last_hour).to_pydatetime() > timedelta(hours=STALE_HOURS)),
        "note": reason,
    }


def build(obs: pd.DataFrame, stations: dict[str, dict], now: Optional[datetime] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    out = []
    if not obs.empty:
        obs = obs.copy()
        obs["hour"] = pd.to_datetime(obs["hour"], utc=True, format="ISO8601")
        obs = obs.loc[obs["hour"] > now - timedelta(hours=25)]
        for sid, g in obs.groupby("station_id"):
            meta = stations.get(sid)
            if not meta:
                continue
            out.append({"id": sid, "name": meta.get("name", sid),
                        "latitude": meta.get("latitude"), "longitude": meta.get("longitude"),
                        **station_naqi(g, now)})
    out.sort(key=lambda s: (s["aqi"] is None, -(s["aqi"] or 0)))
    valid = [s["aqi"] for s in out if s["aqi"] is not None and not s["stale"]]
    return {
        "generated_at": now.isoformat(),
        "method": "NAQI: 24 h means (PM2.5, PM10, NO2, SO2), 8 h means (CO, O3); >= 3 pollutants incl. PM",
        "city": {"stations_reporting": len(valid),
                 "median_aqi": int(np.median(valid)) if valid else None,
                 "max_aqi": max(valid) if valid else None},
        "stations": out,
    }


def write(payload: dict, root: Optional[str] = None) -> str:
    d = os.path.join(root or PUBLIC_DIR, DATA_SUBDIR)
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "now.json")
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1, default=str)
    os.replace(tmp, p)
    return p
