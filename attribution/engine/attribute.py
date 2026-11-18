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
from ..ingest import landuse as _landuse
from ..ingest import traffic
from ..labels import CONF_HI, LABELS_EN, LABELS_HI, MECHANISM_EN, MECHANISM_HI
from . import confidence, factors, fingerprints, fusion, regional, spikes, wind_sector

logger = logging.getLogger(__name__)

ENGINE_VERSION = "kaun-0.2"
IST = timezone(timedelta(hours=5, minutes=30))
MIN_LOCAL_SHARE = 0.25   # below this the local part is too small to name a culprit

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


def _pct_txt(v: float, hi: bool = False) -> str:
    if v >= 0.9:
        return "90%+"
    p = int(round(v * 100 / 5.0) * 5)
    return f"लगभग {p}%" if hi else f"~{p}%"


def _mix(shares: dict, labels: dict, n: int = 2, joiner: str = " + ") -> str:
    top = sorted(shares.items(), key=lambda kv: -kv[1])[:n]
    return joiner.join(f"{labels.get(k, k)} {int(round(v * 100))}%" for k, v in top if v >= 0.15) or "mixed"


def build_cause(local: dict, local_top: Optional[str], reg: Optional[float], transported: bool,
                profile: dict, cands: list[dict], wind: dict) -> dict:
    """
    One structure that answers "kaun?" in full:
      local     the station's own excess (1 - regional share): fused source
                shares plus named OSM candidates in the wind sector
      regional  the airshed-wide part: how big, why it rose (mechanism) and
                what it is made of (composition)
      shares    the two folded together; top = the single biggest cause
    """
    reg = float(reg or 0.0)
    comp = profile.get("composition") or {}
    folded: dict[str, float] = {}
    for k, v in local.items():
        folded[k] = folded.get(k, 0.0) + v * (1 - reg)
    if reg > 0:
        if transported:
            folded["transported_smoke"] = folded.get("transported_smoke", 0.0) + reg
        elif comp:
            for k, v in comp.items():
                folded[k] = folded.get(k, 0.0) + v * reg
        else:
            folded["regional_background"] = folded.get("regional_background", 0.0) + reg
    folded = {k: round(v, 3) for k, v in folded.items() if v >= 0.05}
    tot = sum(folded.values())
    folded = {k: round(v / tot, 3) for k, v in folded.items()} if tot > 0 else {}
    top = max(folded, key=folded.get) if folded else None
    local_share = round(1 - reg, 3)
    return {
        "top": top,
        "shares": folded,
        "local": {"share": local_share,
                  "top": local_top if local_share >= MIN_LOCAL_SHARE else None,
                  "candidates": cands if local_share >= MIN_LOCAL_SHARE else [],
                  "sector": wind.get("sector"), "calm": wind.get("calm")},
        "regional": {"share": round(reg, 3), "mechanism": profile.get("mechanism", "unclear"),
                     "composition": comp, "wind_ms": profile.get("wind_ms"),
                     "pbl_ratio": profile.get("pbl_ratio"), "stagnant": profile.get("stagnant"),
                     "upwind_fires": profile.get("upwind_fires", 0), "transported": bool(transported),
                     "n_stations": profile.get("n_stations", 0)},
    }


def _cause_text(cause: dict) -> tuple[str, str]:
    """Plain-language cause, English and Hindi. No confidence here: the summary carries it."""
    loc, regn = cause["local"], cause["regional"]
    parts_en, parts_hi = [], []
    if regn["share"] >= 0.3:
        mech = regn["mechanism"]
        why_en, why_hi = MECHANISM_EN.get(mech, ""), MECHANISM_HI.get(mech, "")
        detail = []
        if mech == "stagnation":
            if regn.get("wind_ms") is not None:
                detail.append(f"wind {regn['wind_ms']:.1f} m/s")
            if regn.get("pbl_ratio") is not None:
                detail.append(f"mixing height {int(round(regn['pbl_ratio'] * 100))}% of normal")
        if mech == "transport":
            detail.append(f"{regn['upwind_fires']} fires upwind")
        made_of = regn.get("composition") or {}
        made_en = f"; the shared air looks like {_mix(made_of, LABELS_EN)}" if made_of and not regn["transported"] else ""
        made_hi = f"; हवा में मुख्यतः {_mix(made_of, LABELS_HI, joiner=' और ')}" if made_of and not regn["transported"] else ""
        parts_en.append(f"{_pct_txt(regn['share'])} region-wide: {why_en}" + (f" ({', '.join(detail)})" if detail else "") + made_en)
        parts_hi.append(f"{_pct_txt(regn['share'], True)} पूरे इलाके में: {why_hi}" + (f" ({', '.join(detail)})" if detail else "") + made_hi)
    if loc["share"] >= MIN_LOCAL_SHARE and loc.get("top"):
        where_en = (" (calm air: close by)" if loc.get("calm") else
                    f" from the {wind_sector.SECTORS_EN[loc['sector']]}" if loc.get("sector") else "")
        where_hi = (" (हवा शांत: पास से)" if loc.get("calm") else
                    f" {wind_sector.SECTORS_HI[loc['sector']]} दिशा से" if loc.get("sector") else "")
        names = ", ".join(f"{c['name']} ({c['type']}, {c['km']:g} km)" for c in loc["candidates"][:2])
        parts_en.append(f"{_pct_txt(loc['share'])} local: {LABELS_EN.get(loc['top'], loc['top'])}{where_en}"
                        + (f"; likely {names}" if names else ""))
        parts_hi.append(f"{_pct_txt(loc['share'], True)} स्थानीय: {LABELS_HI.get(loc['top'], loc['top'])}{where_hi}"
                        + (f"; संभवतः {names}" if names else ""))
    if not parts_en:
        return "source unclear", "स्रोत साफ़ नहीं"
    return "; ".join(parts_en), "; ".join(parts_hi)


def _summary(name: str, start, end, cause: dict, conf: str) -> tuple[str, str]:
    s_ist, e_ist = start.tz_convert(IST), (end + pd.Timedelta(hours=1)).tz_convert(IST)
    when = f"{s_ist:%H:%M}-{e_ist:%H:%M} IST {s_ist:%d %b}"
    text_en, text_hi = _cause_text(cause)
    top = cause.get("top")
    head_en = f"{LABELS_EN[top]} {_pct_txt(cause['shares'][top])}" if top else "source unclear"
    head_hi = f"{LABELS_HI[top]} {_pct_txt(cause['shares'][top], True)}" if top else "स्रोत साफ़ नहीं"
    en = f"Spike at {name}, {when}: {head_en}. {text_en}; confidence {conf}."
    hi = f"{name} में {when} प्रदूषण बढ़ा: {head_hi}. {text_hi}. भरोसा {CONF_HI[conf]}।"
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
    landuse: {station_id: inventory} from ingest/landuse.py (optional).
    """
    grids = landuse or {}
    fleet_near = _landuse.fleet_near_mean(grids)
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
    profiles: dict[tuple, dict] = {}   # regional profile per (start, end): shared by every station in that window
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
            "upwind_landuse": fusion.term_landuse(grids.get(sid), ww, fleet_near),
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
        key = (w["start"], w["end"])
        if key not in profiles:
            profiles[key] = regional.regional_profile(flagged, w["hours"], w["start"], fires_up, transported)
        cands = _landuse.candidates(grids.get(sid), local_top, ww)
        cause = build_cause(local, local_top, reg, transported, profiles[key], cands, ww)
        cause["text_en"], cause["text_hi"] = _cause_text(cause)
        en, hi = _summary(name, w["start"], w["end"], cause, level)
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
            "cause": cause,
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
