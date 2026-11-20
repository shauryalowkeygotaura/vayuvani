"""
The answer-key check: a model trained on sources MEASURED in Delhi, used to say
"this source is up" only when it is at least 95% sure, and "unsure" otherwise.

Training (attribution/validation/delhi_rai.py): hourly PMF source factors from an
Xact XRF at IIT Delhi (Rai et al. 2020, https://zenodo.org/records/3907250),
winters 2018 and 2019, against CPCB hourly chemistry at the three stations within
2.5 km. One logistic model per source: is it elevated (>= 1.5x its winter
median) or not (<= 1.0x)? Held-out weeks, calls at >= 0.95 confidence, with
the live (OpenAQ) features: burning 97.4%, traffic 97.0%, dust 93.7%, industry
85.8%. Only sources whose held-out precision clears 95% (the model file's
"validated" list: burning and traffic) are ever named on a card; dust and
industry probabilities are kept in the evidence but never called.

Scope, stated on every card: validated for the area around IIT Delhi (5 km).
Later checks on keys it never saw (attribution/validation/more_keys.py): a VOC
instrument at IIT Delhi agreed on 84/84 traffic and 79/79 burning calls; at MRIU
Faridabad (monitors 6-10 km away) burning held (18/20) but traffic did not
(75/127). So outside 5 km only burning is ever named, and the card says so.

Features use only what OpenAQ carries live (PM2.5, PM10, NO2, CO, SO2, O3, NO):
the hour's levels and its increment over the station's same-hour 7-day median,
the same baseline the spike detector uses.
"""

import json
import os
from typing import Optional

import numpy as np
import pandas as pd

from ..ingest.firms import haversine_km

MODEL_PATH = os.path.join(os.path.dirname(__file__), "answer_key_model.json")
THRESHOLD = 0.95
SITE = (28.545, 77.193)          # IIT Delhi, where the answer key was measured
VALIDATED_KM = 5.0               # stations this close are inside the validated area
NEIGHBOUR_KM = 3.0               # training used the median over stations within ~2.5 km
FEATURES = ("l_dno2_dpm", "l_dco_dpm", "l_dso2_dpm", "d_fine", "fine", "l_no2_pm", "l_co_pm", "l_so2_pm",
            "l_o3", "no_frac", "l_pm25", "l_coarse")
LABEL_EN = {"biomass_burning": "burning", "traffic": "traffic", "dust": "dust", "industry": "industrial emissions"}
LABEL_HI = {"biomass_burning": "जलाना", "traffic": "वाहन", "dust": "धूल", "industry": "उद्योग"}


def _col(x: pd.DataFrame, c: str) -> pd.Series:
    return x[c] if c in x else pd.Series(np.nan, index=x.index)


def chem_features(x: pd.DataFrame) -> pd.DataFrame:
    """x has d_<p> (increment) and v_<p> (level) columns. Missing species give NaN features."""
    pos = lambda s, lo: s.clip(lower=lo)
    d, v = (lambda c: _col(x, f"d_{c}")), (lambda c: _col(x, f"v_{c}"))
    dpm = d("pm25")
    f = pd.DataFrame(index=x.index)
    f["l_dno2_dpm"] = np.log10(pos(d("no2"), 0.5) / pos(dpm, 0.5))
    f["l_dco_dpm"] = np.log10(pos(d("co"), 0.005) / pos(dpm, 0.5))
    f["l_dso2_dpm"] = np.log10(pos(d("so2"), 0.2) / pos(dpm, 0.5))
    f["d_fine"] = (dpm / d("pm10")).where(d("pm10") > 5).clip(-1, 2)
    f["fine"] = (v("pm25") / v("pm10")).clip(0, 1.5)
    f["l_no2_pm"] = np.log10(pos(v("no2"), 0.5) / pos(v("pm25"), 1))
    f["l_co_pm"] = np.log10(pos(v("co"), 0.01) / pos(v("pm25"), 1))
    f["l_so2_pm"] = np.log10(pos(v("so2"), 0.5) / pos(v("pm25"), 1))
    f["l_o3"] = np.log10(pos(v("o3"), 0.5))
    mol_no, mol_no2 = pos(v("no"), 0) / 30.01, pos(v("no2"), 0) / 46.01
    f["no_frac"] = (mol_no / (mol_no + mol_no2)).where((mol_no + mol_no2) > 0.2)
    f["l_dpm"] = np.log10(pos(dpm, 0.5))
    return f


def network(per_station: pd.DataFrame) -> pd.Series:
    """Median over stations of their features for one hour, plus PM levels (as in training)."""
    f = chem_features(per_station).median(numeric_only=True)
    pm25, pm10 = _col(per_station, "v_pm25").median(), _col(per_station, "v_pm10").median()
    f["l_pm25"] = np.log10(max(pm25, 1)) if pd.notna(pm25) else np.nan
    f["l_coarse"] = np.log10(max(pm10 - pm25, 1)) if pd.notna(pm10) and pd.notna(pm25) else np.nan
    return f


_MODEL: Optional[dict] = None


def load() -> Optional[dict]:
    global _MODEL
    if _MODEL is None and os.path.exists(MODEL_PATH):
        with open(MODEL_PATH, encoding="utf-8") as fh:
            _MODEL = json.load(fh)
    return _MODEL


def predict(feat: pd.Series, model: dict) -> dict[str, float]:
    """P(source elevated) per source from the exported logistic models."""
    out = {}
    for src, m in model["sources"].items():
        z = m["intercept"]
        for name, c, mu, sd, fill in zip(m["features"], m["coef"], m["mean"], m["scale"], m["impute"]):
            val = feat.get(name)
            val = fill if val is None or not np.isfinite(val) else float(val)
            z += c * (val - mu) / (sd or 1.0)
        out[src] = float(1 / (1 + np.exp(-z)))
    return out


def neighbours(sid: str, stations: dict) -> list[str]:
    me = stations.get(sid) or {}
    la, lo = me.get("latitude"), me.get("longitude")
    if la is None or lo is None:
        return [sid]
    near = [k for k, s in stations.items()
            if s.get("latitude") is not None and s.get("longitude") is not None
            and haversine_km(la, lo, s["latitude"], s["longitude"]) <= NEIGHBOUR_KM]
    return near or [sid]


def check(flagged: pd.DataFrame, sid: str, hours: list, stations: dict, model: Optional[dict] = None) -> Optional[dict]:
    """
    The answer-key verdict for one spike window: mean P(elevated) over its hours,
    computed on the station and its neighbours within NEIGHBOUR_KM.
    """
    model = model or load()
    if not model:
        return None
    near = neighbours(sid, stations)
    rows = flagged.loc[flagged["station_id"].isin(near) & flagged["hour"].isin(hours)]
    if rows.empty:
        return None
    probs = []
    for _, g in rows.groupby("hour"):
        x = pd.DataFrame(index=g.index)
        for p in ("pm25", "pm10", "no2", "co", "so2", "o3", "no"):
            x[f"v_{p}"] = _col(g, p)
            x[f"d_{p}"] = _col(g, f"delta_{p}")
        probs.append(predict(network(x), model))
    p = {k: round(float(np.mean([q[k] for q in probs])), 3) for k in probs[0]}
    me = stations.get(sid) or {}
    km = (haversine_km(SITE[0], SITE[1], me["latitude"], me["longitude"])
          if me.get("latitude") is not None and me.get("longitude") is not None else None)
    inside = km is not None and km <= VALIDATED_KM
    # Away from IIT Delhi only what transferred to the second site (MRIU Faridabad) is named:
    # burning 18/20 there, traffic 75/127 (traffic is too local for monitors 6-10 km away).
    validated = set(model.get("validated", []))
    if not inside:
        validated &= set(model.get("outside_validated", []))
    calls = [k for k, v in sorted(p.items(), key=lambda kv: -kv[1]) if v >= THRESHOLD and k in validated]
    return {"model": model.get("version"), "threshold": THRESHOLD, "p_elevated": p, "calls": calls,
            "unsure": not calls, "validated_area": inside, "km_from_answer_key_site": None if km is None else round(km, 1),
            "n_stations": len(set(rows["station_id"])), "n_hours": len(probs)}


def text(ak: Optional[dict]) -> tuple[str, str]:
    """One sentence for the card, English and Hindi."""
    if not ak:
        return "", ""
    scope_en = ("validated near IIT Delhi" if ak["validated_area"]
                else "not validated at this station; burning was right 18 of 20 times at a second site")
    scope_hi = ("IIT दिल्ली के पास जाँचा गया" if ak["validated_area"]
                else "इस स्टेशन पर जाँचा नहीं गया; दूसरी जगह जलाने की पहचान 20 में 18 बार सही रही")
    if ak["calls"]:
        en = f"Measured-source check (95%+ sure, {scope_en}): {', '.join(LABEL_EN[c] for c in ak['calls'])} elevated."
        hi = f"मापे गए स्रोतों से जाँच (95%+ निश्चित, {scope_hi}): {', '.join(LABEL_HI[c] for c in ak['calls'])} बढ़ा हुआ।"
    else:
        en = f"Measured-source check: unsure, no source reaches 95% ({scope_en})."
        hi = f"मापे गए स्रोतों से जाँच: निश्चित नहीं, कोई स्रोत 95% तक नहीं पहुँचा ({scope_hi})।"
    return en, hi
