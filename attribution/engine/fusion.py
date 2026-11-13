"""
Evidence fusion: many weak, physically motivated signals -> source probabilities.

Each term adds a log-likelihood contribution per source; the posterior is a
softmax over the summed contributions (a naive-Bayes / log-linear pool, the
standard way to combine conditionally independent evidence). Every term is
stored, so each attribution can explain itself ("industry +1.2 from upwind
land use, +0.6 from SO2 CBPF...").

Sources: traffic, biomass_burning, industry, dust, secondary.
("secondary" = fine particles formed in the air from gases, favoured by humid,
stagnant air. It has no local owner and is never routed to an agency.)

Terms and the variables they use:
  T1 fingerprint      delta-ratio scores from fingerprints.py (NO2/PM2.5, CO/PM2.5,
                      SO2/PM2.5, fine fraction), station-relative percentiles
  T2 secondary/RH     relative humidity x fine fraction x weak combustion markers
  T3 fresh NO         dNO / (dNO + dNO2) by moles (NO-rich = fresh exhaust close by)
  T4 time/temp        traffic diurnal prior; cold nights favour burning
  T5 upwind land use  OSM inventory in the window's wind sector vs all sectors
  T6 per-pollutant    CBPF of each source's marker pollutant (NO2, SO2, PM10, CO)
     wind signature   in the window's sector, as a z-score across sectors
  T7 factors          NMF factor shares for the window
  T8 local fires      FIRMS points within 30 km upwind in the last 12 h
Weights are engineering priors, not fitted: there is no labelled ground truth
for Delhi. They are deliberately modest so no single term dominates; the
backtest (attribution/validation) is the check. Documented in docs/KAUN.md.
"""

import math
from datetime import timedelta, timezone
from typing import Optional

import numpy as np

from .wind_sector import SECTORS

SOURCES = ("traffic", "biomass_burning", "industry", "dust", "secondary")
IST = timezone(timedelta(hours=5, minutes=30))

LANDUSE_MAP = {  # feature -> {source: weight}
    "roads": {"traffic": 1.0}, "rail": {"traffic": 0.3}, "depot": {"traffic": 0.7},
    "industrial": {"industry": 1.0}, "power": {"industry": 1.0},
    "kiln": {"industry": 0.5, "biomass_burning": 0.5},
    "landfill": {"biomass_burning": 1.0}, "crematorium": {"biomass_burning": 0.4},
    "construction": {"dust": 1.0}, "quarry": {"dust": 0.7},
}
LANDUSE_PSEUDO = {"roads": 2.0}  # smoothing (km of road); other features: 0.5
CALM_LANDUSE_SCALE = 0.8        # calm-air neighbourhood evidence is weaker than an upwind sector
CBPF_MARKERS = {"traffic": ("no2", "no"), "industry": ("so2",), "dust": ("pm10",), "biomass_burning": ("co",)}
W = {"T1": 1.5, "T2": 2.0, "T3": 1.5, "T4": 1.0, "T5": 0.8, "T6": 0.5, "T7": 1.5, "T8": 0.5}


def _clip(x, lo, hi):
    return max(lo, min(hi, x))


def _finite(v) -> bool:
    return v is not None and isinstance(v, (int, float)) and math.isfinite(v)


def _neighbours(sector: str) -> tuple[str, str]:
    i = SECTORS.index(sector)
    return SECTORS[(i - 1) % 8], SECTORS[(i + 1) % 8]


def term_fingerprint(fp_scores: dict) -> dict:
    # Bounded to about -1.2 .. +1.5 so a zero rule score cannot veto the other terms.
    return {s: W["T1"] * math.log((fp_scores.get(s, 0.0) + 0.2) / 0.45)
            for s in ("traffic", "biomass_burning", "industry", "dust")}


def term_secondary(ratios: dict, rh: Optional[float]) -> dict:
    fine = ratios.get("fine_fraction")
    p_co, p_no2 = ratios.get("pct_co_pm", 0.5), ratios.get("pct_no2_pm", 0.5)
    rh_t = _clip((rh - 60.0) / 30.0, 0.0, 1.0) if _finite(rh) else 0.3
    fine_t = _clip((fine - 0.5) / 0.3, 0.0, 1.0) if _finite(fine) else 0.0
    weak_comb = 1.0 - 0.5 * (p_co + p_no2)
    out = {"secondary": W["T2"] * (rh_t * fine_t * weak_comb) - 1.0}
    if _finite(rh):
        out["biomass_burning"] = -1.0 * rh_t * (1.0 - p_co)
    return out


def term_fresh_no(d: dict) -> dict:
    """NO share of the NOx excess, by moles: fresh exhaust is NO-rich, aged air NO2-rich."""
    no, no2 = d.get("no"), d.get("no2")
    if not (_finite(no) and _finite(no2)) or no < 0 or no2 < 0:
        return {}
    mol_no, mol_no2 = no / 30.01, no2 / 46.01
    if mol_no + mol_no2 < 0.2:   # < ~5 ppb of NOx excess: too small to read
        return {}
    frac = mol_no / (mol_no + mol_no2)
    return {"traffic": W["T3"] * (frac - 0.4) * 2.0}


def term_time_temp(hours, traffic_prior: float, temp: Optional[float]) -> dict:
    out = {"traffic": W["T4"] * (traffic_prior - 0.5)}
    night = np.mean([1.0 if (h.astimezone(IST).hour >= 20 or h.astimezone(IST).hour < 6) else 0.0 for h in hours])
    if _finite(temp) and temp < 18 and night > 0.5:
        out["biomass_burning"] = W["T4"] * 0.6 * _clip((18 - temp) / 8, 0, 1)
    return out


def term_landuse(grid: Optional[dict], wind: dict, fleet_near: Optional[dict] = None) -> dict:
    """
    Wind with a direction: inventory in the upwind sector vs the station's
    other sectors. Calm air (the Delhi smog default): the station breathes its
    own neighbourhood, so the inventory within 2 km is compared with the mean
    neighbourhood across all stations (fleet_near, landuse.fleet_near_mean).
    """
    sector = wind.get("sector")
    if not grid:
        return {}
    if not sector or wind.get("calm"):
        near = grid.get("near") if isinstance(grid, dict) else None
        if not isinstance(near, dict) or not fleet_near:
            return {}
        out: dict[str, float] = {}
        for feat, here in near.items():
            if feat not in LANDUSE_MAP or not _finite(here):
                continue
            ref = fleet_near.get(feat, 0.0)
            a = LANDUSE_PSEUDO.get(feat, 0.5)
            if here == 0 and ref == 0:
                continue
            enrich = _clip(math.log((here + a) / (ref + a)), -1.5, 1.5)
            for src, w in LANDUSE_MAP[feat].items():
                out[src] = out.get(src, 0.0) + W["T5"] * CALM_LANDUSE_SCALE * w * enrich
        return out
    out = {}
    for feat, sec in grid.items():
        if feat not in LANDUSE_MAP or not isinstance(sec, dict):
            continue
        a = LANDUSE_PSEUDO.get(feat, 0.5)
        def smooth(s):
            n1, n2 = _neighbours(s)
            return sec.get(s, 0.0) + 0.5 * (sec.get(n1, 0.0) + sec.get(n2, 0.0))
        here = smooth(sector)
        mean = float(np.mean([smooth(s) for s in SECTORS]))
        if here == 0 and mean == 0:
            continue
        enrich = _clip(math.log((here + a) / (mean + a)), -1.5, 1.5)
        for src, w in LANDUSE_MAP[feat].items():
            out[src] = out.get(src, 0.0) + W["T5"] * w * enrich
    return out


def term_cbpf(cbpf_by_pollutant: dict, wind: dict) -> dict:
    sector = wind.get("sector")
    if not sector or wind.get("calm"):
        return {}
    out = {}
    for src, markers in CBPF_MARKERS.items():
        zs = []
        for m in markers:
            probs = cbpf_by_pollutant.get(m) or {}
            if sector in probs and len(probs) >= 3:
                vals = np.array(list(probs.values()))
                zs.append((probs[sector] - vals.mean()) / (vals.std() + 0.05))
        if zs:
            out[src] = W["T6"] * _clip(float(np.mean(zs)), -2.0, 2.0)
    return out


def term_nmf(nmf_shares: dict) -> dict:
    return {k: W["T7"] * v for k, v in (nmf_shares or {}).items() if k in SOURCES}


def term_local_fires(n_local_fires: int) -> dict:
    return {"biomass_burning": W["T8"] * min(n_local_fires, 5) / 5.0} if n_local_fires else {}


def fuse(terms: dict[str, dict]) -> dict:
    """terms: {term_name: {source: logit}} -> posterior + diagnostics."""
    total = {s: 0.0 for s in SOURCES}
    for t in terms.values():
        for s, v in t.items():
            if s in total and _finite(v):
                total[s] += v
    m = max(total.values())
    ex = {s: math.exp(v - m) for s, v in total.items()}
    z = sum(ex.values())
    post = {s: ex[s] / z for s in SOURCES}
    top = max(post, key=post.get)
    agree = sum(1 for t in terms.values() if t and max(t, key=lambda k: t[k]) == top and t[top] > 0)
    shares = {s: p for s, p in post.items() if p >= 0.08}
    n = sum(shares.values())
    shares = {s: round(p / n, 3) for s, p in shares.items()}
    entropy = -sum(p * math.log(p) for p in post.values() if p > 0) / math.log(len(SOURCES))
    return {
        "posterior": {s: round(p, 3) for s, p in post.items()},
        "shares": shares,
        "top": top,
        "agreeing_terms": agree,
        "entropy": round(entropy, 3),
        "terms": {k: {s: round(v, 3) for s, v in t.items()} for k, t in terms.items() if t},
    }


def local_fire_count(fires: list[dict], lat: Optional[float], lon: Optional[float], wind: dict, at) -> int:
    if lat is None or lon is None or not fires:
        return 0
    from ..ingest.firms import bearing_deg, haversine_km
    import pandas as pd
    n = 0
    for f in fires:
        t = pd.Timestamp(f["acq_time"])
        t = t.tz_localize("UTC") if t.tzinfo is None else t
        if not (at - pd.Timedelta(hours=12) <= t <= at):
            continue
        d = haversine_km(lat, lon, float(f["latitude"]), float(f["longitude"]))
        if d > 30:
            continue
        if wind.get("direction_deg") is not None and not wind.get("calm"):
            b = bearing_deg(lat, lon, float(f["latitude"]), float(f["longitude"]))
            if abs((b - wind["direction_deg"] + 180) % 360 - 180) > 45:
                continue
        n += 1
    return n
