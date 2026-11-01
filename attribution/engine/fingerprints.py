"""
Ratio fingerprints: which source class best explains a spike's excess.

Inputs are DELTAS over the station's own baseline (so the regional/background
mix is mostly subtracted). Ratios are compared against the station's own
30-day distribution (percentiles), not against hard literature thresholds,
because sensor calibration differs between Delhi stations and absolute ratio
cut-offs do not transfer. The one physical absolute is the fine fraction
PM2.5/PM10: combustion is fine-dominated, dust is coarse-dominated.

Rules (PLAN.md):
    traffic          high dNO2/dPM2.5 and dCO/dPM2.5
    biomass_burning  high fine fraction, CO/PM2.5 lower than traffic, NO2 low
    industry         elevated SO2 relative to PM
    dust             low fine fraction (coarse dominated)

Honest limit: CO/PM2.5 is the robust discriminator (traffic vs smoke). The
industry and dust calls lean on single species and are fuzzier; confidence
logic caps 3+ way splits at medium.
"""

from typing import Optional

import numpy as np

SOURCES = ("traffic", "biomass_burning", "industry", "dust")


def _pct(value: Optional[float], history: Optional[np.ndarray]) -> float:
    """Percentile (0..1) of value within history; 0.5 when unknown."""
    if value is None or not np.isfinite(value) or history is None or len(history) < 24:
        return 0.5
    return float(np.mean(history <= value))


def _clip01(x: float) -> float:
    return float(min(1.0, max(0.0, x)))


def _ratio(a, b) -> Optional[float]:
    if a is None or b is None or not np.isfinite(a) or not np.isfinite(b) or b <= 0:
        return None
    return a / b


def station_ratio_history(hist) -> dict[str, np.ndarray]:
    """
    Distributions of DELTA ratios (excess over baseline) from a station's
    history, restricted to hours with a real PM2.5 excess, so a window's delta
    ratio is compared like with like.
    """
    out = {}
    if "delta_pm25" not in hist:
        return out
    dpm = hist["delta_pm25"].astype(float).where(hist["delta_pm25"] > 10)
    for name, num in (("no2_pm", "delta_no2"), ("co_pm", "delta_co"), ("so2_pm", "delta_so2")):
        if num in hist:
            r = (hist[num].astype(float) / dpm).to_numpy()
            out[name] = r[np.isfinite(r)]
    return out


def second_signal(source: Optional[str], d: dict, wind_speed: Optional[float]) -> Optional[bool]:
    """
    Independent corroboration for the two single-signal classes (NEXT.md step 5).
      industry: SO2 excess is not just riding a CO (combustion) rise:
                dSO2 [ug/m3] / dCO [mg/m3] >= 20, i.e. a sulphur-rich source
                (coal/oil) rather than biomass or traffic, which carry little SO2.
      dust:     resuspension conditions (wind >= 3 m/s) OR no combustion
                co-signal (dCO <= 0.2 mg/m3 and dNO2 <= 10 ug/m3).
    Returns None for classes that need no second signal. Thresholds are
    engineering choices, not literature values: documented in docs/KAUN.md.
    """
    if source == "industry":
        so2, co = d.get("so2"), d.get("co")
        if so2 is None or not np.isfinite(so2):
            return False
        if co is None or not np.isfinite(co) or co <= 0.05:
            return so2 > 10
        return so2 / co >= 20
    if source == "dust":
        windy = wind_speed is not None and np.isfinite(wind_speed) and wind_speed >= 3.0
        co, no2 = d.get("co"), d.get("no2")
        quiet = (co is None or not np.isfinite(co) or co <= 0.2) and (no2 is None or not np.isfinite(no2) or no2 <= 10)
        return bool(windy or quiet)
    return None


def score(d: dict, totals: dict, ratio_hist: dict, traffic_prior: float = 0.5) -> dict:
    """
    d: mean deltas over the window, keys pm25, pm10, no2, so2, co (CO in mg/m3).
    totals: mean absolute concentrations over the window (for the fine fraction
    when deltas are too small to divide).
    Returns {"scores": {...}, "shares": {...}, "ratios": {...}}.
    """
    dpm = d.get("pm25")
    no2_pm = _ratio(d.get("no2"), dpm)
    co_pm = _ratio(d.get("co"), dpm)
    so2_pm = _ratio(d.get("so2"), dpm)

    fine = _ratio(dpm, d.get("pm10"))
    if fine is None or fine > 1.2:
        fine = _ratio(totals.get("pm25"), totals.get("pm10"))
    fine = None if fine is None else min(fine, 1.0)

    p_no2 = _pct(no2_pm, ratio_hist.get("no2_pm"))
    p_co = _pct(co_pm, ratio_hist.get("co_pm"))
    p_so2 = _pct(so2_pm, ratio_hist.get("so2_pm"))
    has = {k: d.get(k) is not None and np.isfinite(d.get(k)) for k in ("no2", "co", "so2", "pm10")}

    scores = {s: 0.0 for s in SOURCES}

    if has["no2"] or has["co"]:
        parts = [p for p, ok in ((p_no2, has["no2"]), (p_co, has["co"])) if ok]
        t = float(np.mean(parts))
        if has["no2"] and (d.get("no2") or 0) <= 0:
            t *= 0.3
        scores["traffic"] = _clip01((t - 0.4) / 0.5) * (0.8 + 0.4 * traffic_prior)

    if fine is not None:
        comb = _clip01((fine - 0.45) / 0.3)
        low_traffic = 1.0 - 0.6 * (p_no2 if has["no2"] else 0.5)
        co_ok = 1.0 if not has["co"] else (0.6 + 0.4 * (1.0 - abs(p_co - 0.5) * 2))
        scores["biomass_burning"] = comb * low_traffic * co_ok
        scores["dust"] = _clip01((0.5 - fine) / 0.3) if has["pm10"] or totals.get("pm10") else 0.0

    if has["so2"] and (d.get("so2") or 0) > 5.0:
        scores["industry"] = _clip01((p_so2 - 0.6) / 0.35)

    total = sum(scores.values())
    if total <= 0:
        shares = {}
    else:
        shares = {k: v / total for k, v in scores.items() if v / total >= 0.08}
        norm = sum(shares.values())
        shares = {k: v / norm for k, v in shares.items()}

    return {
        "scores": {k: round(v, 3) for k, v in scores.items()},
        "shares": shares,
        "ratios": {
            "dNO2_dPM25": None if no2_pm is None else round(no2_pm, 3),
            "dCO_dPM25_mg_per_ug": None if co_pm is None else round(co_pm, 5),
            "dSO2_dPM25": None if so2_pm is None else round(so2_pm, 3),
            "fine_fraction": None if fine is None else round(fine, 3),
            "pct_no2_pm": round(p_no2, 2), "pct_co_pm": round(p_co, 2), "pct_so2_pm": round(p_so2, 2),
        },
    }
