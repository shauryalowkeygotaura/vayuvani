"""
Attribution orchestrator: obs + wind + fires -> one record per spike window.

Final shares = local fingerprint shares scaled by (1 - regional share), plus a
regional share labelled "transported_smoke" when fires sit upwind, otherwise
"regional_background". Every record carries a confidence and the evidence
behind it.
"""

import hashlib
import logging
from datetime import timedelta, timezone
from typing import Optional

import numpy as np
import pandas as pd

from ..config import DELTA_VARS, EXTRA_VARS, NMF_WINDOW_DAYS, POLLUTANTS
from ..ingest import traffic
from ..labels import CONF_HI, LABELS_EN, LABELS_HI
from . import confidence, factors, fingerprints, fusion, regional, spikes, wind_sector

logger = logging.getLogger(__name__)

ENGINE_VERSION = "kaun-0.1"
IST = timezone(timedelta(hours=5, minutes=30))

def merge_obs(obs: pd.DataFrame, wind: pd.DataFrame) -> pd.DataFrame:
    obs = obs.copy()
    obs["hour"] = pd.to_datetime(obs["hour"], utc=True)
    if wind is None or wind.empty:
        for c in ("wind_speed", "wind_dir", "pbl_height"):
            obs[c] = np.nan
        return obs
    wind = wind.copy()
    wind["hour"] = pd.to_datetime(wind["hour"], utc=True)
    cols = ["station_id", "hour"] + [c for c in ("wind_speed", "wind_dir", "pbl_height") if c in wind]
    wind = wind[cols].drop_duplicates(["station_id", "hour"], keep="last")
    return obs.merge(wind, on=["station_id", "hour"], how="left")


def _mean(rows: pd.DataFrame, col: str) -> Optional[float]:
    if col not in rows:
        return None
    v = rows[col].astype(float).mean()
    return None if not np.isfinite(v) else float(v)


def _pbl_drop(hist: pd.DataFrame, rows: pd.DataFrame) -> Optional[float]:
    if "pbl_height" not in hist or rows["pbl_height"].notna().sum() == 0:
        return None
    hours_of_day = rows["hour"].dt.hour.unique()
    ref = hist.loc[hist["hour"].dt.hour.isin(hours_of_day), "pbl_height"].dropna()
    now = rows["pbl_height"].dropna().mean()
    if ref.size < 3 or not np.isfinite(now) or ref.median() <= 0:
        return None
    return float(max(0.0, 1.0 - now / ref.median()))


def _excess_ratio(rows: pd.DataFrame) -> Optional[float]:
    base = rows["base_pm25"].astype(float).mean()
    if not np.isfinite(base) or base <= 0:
        return None
    return float(rows["delta_pm25"].astype(float).mean() / base)


def _summary(name: str, start, end, shares: dict, sector: Optional[str], conf: str, calm: bool) -> tuple[str, str]:
    s_ist, e_ist = start.tz_convert(IST), (end + pd.Timedelta(hours=1)).tz_convert(IST)
    when = f"{s_ist:%H:%M}-{e_ist:%H:%M} IST {s_ist:%d %b}"
    if not shares:
        return (f"Spike at {name}, {when}: source unclear, confidence low.",
                f"{name} में {when} प्रदूषण बढ़ा: स्रोत साफ़ नहीं, भरोसा कम।")
    top = max(shares, key=shares.get)
    pct = int(round(shares[top] * 100 / 5.0) * 5)
    pct_txt = "90%+" if shares[top] >= 0.9 else f"~{pct}%"
    regional_top = top in ("regional_background", "transported_smoke", "secondary")
    where_en = (" across the region" if regional_top else " from nearby (calm wind)" if calm else
                f" arriving from the {wind_sector.SECTORS_EN[sector]}" if sector else "")
    where_hi = (" पूरे इलाके में" if regional_top else " पास से (हवा शांत)" if calm else
                f" {wind_sector.SECTORS_HI[sector]} दिशा से" if sector else "")
    en = f"Spike at {name}, {when}: {pct_txt} {LABELS_EN[top]}{where_en}, confidence {conf}."
    hi = f"{name} में {when} प्रदूषण बढ़ा: {pct_txt.replace('~', 'लगभग ')} {LABELS_HI[top]}{where_hi}, भरोसा {CONF_HI[conf]}।"
    return en, hi


def attribution_id(station_id: str, start) -> str:
    return hashlib.sha1(f"{station_id}|{pd.Timestamp(start).isoformat()}".encode()).hexdigest()[:16]


def run(obs: pd.DataFrame, wind: pd.DataFrame, fires: list[dict], stations: dict[str, dict],
        since: Optional[pd.Timestamp] = None, landuse: Optional[dict] = None) -> list[dict]:
    """
    obs: hourly_obs rows (>= 7 days history recommended).
    stations: {station_id: {"name", "latitude", "longitude"}}.
    since: only attribute windows that END at or after this hour (the rest were
    attributed by earlier runs); None = all.
    landuse: {station_id: sector grid} from ingest/landuse.py (optional).
    """
    landuse = landuse or {}
    if obs.empty:
        return []
    data = merge_obs(obs, wind)
    flagged = spikes.detect(data)  # keeps wind columns alongside the pollutants
    wins = spikes.windows(flagged)
    if since is not None:
        wins = [w for w in wins if w["end"] >= since]
    if not wins:
        return []
    bg = regional.background_series(data)
    wind_all = data[["hour", "wind_dir", "wind_speed"]].dropna() if "wind_dir" in data else pd.DataFrame()

    out = []
    models: dict[str, Optional[dict]] = {}
    for w in wins:
        sid = w["station_id"]
        st_rows = flagged.loc[flagged["station_id"] == sid]
        rows = st_rows.loc[st_rows["hour"].isin(w["hours"])]
        hist = st_rows.loc[(st_rows["hour"] < w["start"]) &
                           (st_rows["hour"] >= w["start"] - pd.Timedelta(days=NMF_WINDOW_DAYS))]

        d = {p: _mean(rows, f"delta_{p}") for p in DELTA_VARS}
        totals = {p: _mean(rows, p) for p in POLLUTANTS + EXTRA_VARS}
        species = sum(1 for p in ("pm25", "pm10", "no2", "co", "so2") if totals.get(p) is not None)

        tprior = float(np.mean([traffic.prior(h.to_pydatetime()) for h in rows["hour"]]))
        fp = fingerprints.score(d, totals, fingerprints.station_ratio_history(hist), tprior)

        ww = wind_sector.window_wind(rows)
        cb_all = {p: wind_sector.cbpf(hist, col=p) for p in ("pm25", "pm10", "no2", "so2", "co", "no")}
        cb = cb_all["pm25"]

        if sid not in models:
            models[sid] = factors.fit(st_rows.loc[st_rows["hour"] >= w["start"] - pd.Timedelta(days=NMF_WINDOW_DAYS)])
        nmf = factors.window_contrib(models[sid], w["hours"])
        nmf_top = next((k for k in nmf if k not in ("mixed", "secondary")), None)

        meta = stations.get(sid, {})
        n_fires = fusion.local_fire_count(fires, meta.get("latitude"), meta.get("longitude"), ww, w["end"])
        fused = fusion.fuse({
            "fingerprint": fusion.term_fingerprint(fp["scores"]),
            "secondary_rh": fusion.term_secondary(fp["ratios"], totals.get("rh")),
            "fresh_no": fusion.term_fresh_no(d),
            "time_temp": fusion.term_time_temp(list(rows["hour"]), tprior, totals.get("temp")),
            "upwind_landuse": fusion.term_landuse(landuse.get(sid), ww),
            "pollutant_wind": fusion.term_cbpf(cb_all, ww),
            "factors": fusion.term_nmf(nmf),
            "local_fires": fusion.term_local_fires(n_fires),
        })
        local = fused["shares"]

        reg = regional.regional_share(d.get("pm25"), w["hours"], bg)
        fires_up = regional.upwind_fires(fires, wind_all, w["end"])
        transported = regional.is_transported(reg, fires_up)

        shares = {k: v * (1 - (reg or 0.0)) for k, v in local.items()}
        if reg:
            shares["transported_smoke" if transported else "regional_background"] = reg
        shares = {k: round(v, 3) for k, v in shares.items() if v >= 0.05}
        tot = sum(shares.values())
        if tot > 0:
            shares = {k: round(v / tot, 3) for k, v in shares.items()}
        local_top = fused["top"]

        level, reasons = confidence.grade(
            species_present=species, shares=shares, nmf_top=nmf_top, top=local_top, wind=ww,
            n_hours=len(w["hours"]), baseline_kind=str(rows["baseline_kind"].iloc[0]),
            pbl_drop=_pbl_drop(hist, rows),
            excess_ratio=_excess_ratio(rows),
            second_signal=fingerprints.second_signal(local_top, d, ww.get("speed_ms")),
            agreeing_terms=fused["agreeing_terms"],
        )
        name = meta.get("name", sid)
        en, hi = _summary(name, w["start"], w["end"], shares, ww["sector"], level, bool(ww.get("calm")))
        top = max(shares, key=shares.get) if shares else None
        out.append({
            "id": attribution_id(sid, w["start"]),
            "station_id": sid,
            "station_name": name,
            "latitude": meta.get("latitude"),
            "longitude": meta.get("longitude"),
            "window_start": w["start"].isoformat(),
            "window_end": (w["end"] + pd.Timedelta(hours=1)).isoformat(),
            "n_hours": len(w["hours"]),
            "peak_pm25": round(float(rows["pm25"].max()), 1),
            "baseline_pm25": round(float(rows["base_pm25"].mean()), 1),
            "excess_pm25": round(float(d["pm25"] or 0.0), 1),
            "shares": shares,
            "top_source": top,
            "sector": ww["sector"],
            "regional_share": None if reg is None else round(reg, 3),
            "confidence": level,
            "summary_en": en,
            "summary_hi": hi,
            "evidence": {
                "ratios": fp["ratios"],
                "fingerprint_scores": fp["scores"],
                "local_shares": {k: round(v, 3) for k, v in local.items()},
                "fusion": {k: fused[k] for k in ("posterior", "agreeing_terms", "entropy", "terms")},
                "cbpf_by_pollutant": {k: v for k, v in cb_all.items() if v},
                "extra": {k: (None if totals.get(k) is None else round(totals[k], 2)) for k in EXTRA_VARS},
                "local_fires_30km": n_fires,
                "wind": ww,
                "cbpf": cb,
                "cbpf_top_sector": wind_sector.top_sector(cb),
                "nmf_pm25_shares": nmf,
                "upwind_fires": fires_up,
                "traffic_prior": round(tprior, 2),
                "baseline_kind": str(rows["baseline_kind"].iloc[0]),
                "confidence_notes": reasons,
                "hourly": [
                    {"hour": h.isoformat(), **{p: (None if pd.isna(r[p]) else round(float(r[p]), 3))
                                               for p in POLLUTANTS},
                     "base_pm25": None if pd.isna(r["base_pm25"]) else round(float(r["base_pm25"]), 1)}
                    for h, (_, r) in zip(rows["hour"], rows.iterrows())
                ],
            },
            "engine_version": ENGINE_VERSION,
        })
    logger.info(f"Engine: {len(out)} attributions from {len(wins)} spike windows")
    return out
