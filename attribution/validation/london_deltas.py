"""
A large labelled set of source "deltas" from London, to fit and test Kaun's
traffic-vs-burning discriminator at the hourly level.

Labels by construction (no model involved):
  traffic  kerbside minus nearest urban-background site, same hour (the
           Lenschow increment): what the road adds, and nothing else.
  burning  background sites on Bonfire Night (5 Nov, 17:00-04:00 UTC) minus
           the same hour's median over the previous 7 days: what the bonfires
           and fireworks add.

Features are the ones Kaun's engine reads from a delta: NO2/PM2.5, CO/PM2.5,
PM2.5/PM10 (fine fraction), NO share of NOx by moles, all absolute (units are
fixed: ug/m3, CO mg/m3). A logistic regression is trained on some years and
tested on the others (leave-years-out), and the precision/coverage curve is
reported: the probability threshold above which calls are >= 95% precise,
and what share of deltas still gets a call there.

    python -m attribution.validation.london_deltas
"""

import json
import os

import numpy as np
import pandas as pd

from . import external

HERE = os.path.dirname(__file__)
YEARS = range(2014, 2024)
FEATURES = ("l_no2_pm", "l_co_pm", "fine", "no_frac")


def _hourly(site: str, year: int) -> pd.DataFrame:
    df = external.fetch(site, year)
    out = pd.DataFrame({"hour": pd.to_datetime(df["date"], utc=True)})
    for src, dst in (("PM2.5", "pm25"), ("PM10", "pm10"), ("NO2", "no2"), ("CO", "co"), ("NO", "no"), ("SO2", "so2")):
        out[dst] = pd.to_numeric(df[src], errors="coerce") if src in df else np.nan
    return out.set_index("hour")


MIN_DPM = float(os.getenv("KAUN_LONDON_MIN_DPM", "5"))   # ug/m3; the pre-registered rule (a stricter 10 was tried and did worse)
NIGHT_FROM = int(os.getenv("KAUN_LONDON_BONFIRE_FROM", "17"))  # UTC; 19 (skipping the evening rush) was tried and did worse


def features(d: pd.DataFrame) -> pd.DataFrame:
    """d: deltas with pm25, pm10, no2, co, no. Rows need a PM2.5 excess above instrument noise."""
    d = d.loc[d["pm25"] >= MIN_DPM].copy()
    f = pd.DataFrame(index=d.index)
    f["l_no2_pm"] = np.log10(d["no2"].clip(lower=0.1) / d["pm25"])
    f["l_co_pm"] = np.log10(d["co"].clip(lower=1e-3) / d["pm25"]) if d["co"].notna().any() else np.nan
    f["fine"] = (d["pm25"] / d["pm10"]).clip(0, 1.5).where(d["pm10"] > 2)
    mol_no, mol_no2 = d["no"].clip(lower=0) / 30.01, d["no2"].clip(lower=0) / 46.01
    f["no_frac"] = (mol_no / (mol_no + mol_no2)).where((mol_no + mol_no2) > 0.2)
    f["l_so2_pm"] = np.log10(d["so2"].clip(lower=0.1) / d["pm25"]) if "so2" in d and d["so2"].notna().any() else np.nan
    return f


def build() -> pd.DataFrame:
    external.load_sites()
    rows = []
    for y in YEARS:
        data = {}
        for s in external.SITES:
            try:
                data[s] = _hourly(s, y)
            except Exception as e:  # site not running that year
                continue
        for k in external.TRAFFIC:
            if k not in data:
                continue
            # Per variable, the nearest background site that measured it that
            # year (CO and SO2 are only at a few background sites).
            from ..ingest.firms import haversine_km
            _, la, lo = external.SITES[k]
            bgs = sorted((b for b in external.BACKGROUND if b in data),
                         key=lambda b: haversine_km(la, lo, external.SITES[b][1], external.SITES[b][2]))
            if not bgs:
                continue
            d = pd.DataFrame(index=data[k].index)
            for c in ("pm25", "pm10", "no2", "co", "no", "so2"):
                b = next((b for b in bgs if data[b][c].notna().mean() > 0.5), None)
                d[c] = data[k][c] - data[b][c].reindex(d.index) if b else np.nan
            f = features(d)
            f["label"], f["site"], f["year"] = "traffic", k, y
            rows.append(f)
        b0, b1 = external.bonfire(y)
        for s in external.BACKGROUND:
            if s not in data:
                continue
            h = data[s]
            night = h.loc[(h.index >= b0 + pd.Timedelta(hours=NIGHT_FROM - 17)) & (h.index < b1)]
            base = []
            for t in night.index:
                prior = h.reindex([t - pd.Timedelta(days=dd) for dd in range(1, 8)])
                base.append(prior.median())
            if not base:
                continue
            d = night - pd.DataFrame(base, index=night.index)
            f = features(d)
            f["label"], f["site"], f["year"] = "biomass_burning", s, y
            rows.append(f)
    df = pd.concat(rows)
    return df.reset_index(names="hour")


def fit_eval(df: pd.DataFrame, feats: tuple, test_years: set) -> dict:
    from sklearn.linear_model import LogisticRegression
    d = df.dropna(subset=list(feats))
    train, test = d.loc[~d["year"].isin(test_years)], d.loc[d["year"].isin(test_years)]
    if train["label"].nunique() < 2 or test.empty:
        return {}
    # Balance classes: traffic increments vastly outnumber bonfire hours.
    m = LogisticRegression(class_weight="balanced", max_iter=1000)
    m.fit(train[list(feats)], train["label"] == "biomass_burning")
    p = m.predict_proba(test[list(feats)])[:, 1]
    y = (test["label"] == "biomass_burning").to_numpy()
    out = {"n_train": len(train), "n_test": len(test), "n_test_burning": int(y.sum()),
           "coef": dict(zip(feats, np.round(m.coef_[0], 3))), "intercept": round(float(m.intercept_[0]), 3)}
    # Precision of a call (either class) when confidence max(p, 1-p) >= t, on a
    # class-balanced test (weight traffic rows so both classes count equally).
    w = np.where(y, 1.0, y.sum() / max((~y).sum(), 1))
    curve = []
    for t in (0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95, 0.98, 0.99):
        conf = np.maximum(p, 1 - p)
        k = conf >= t
        if k.sum() == 0:
            continue
        correct = ((p >= 0.5) == y)[k]
        prec = float(np.sum(w[k] * correct) / np.sum(w[k]))
        cov = float(np.sum(w[k]) / np.sum(w))
        curve.append({"threshold": t, "precision": round(prec, 3), "coverage": round(cov, 3), "n": int(k.sum())})
    out["curve"] = curve
    return out


def main():
    df = build()
    df.to_csv(os.path.join(HERE, "london_deltas.csv"), index=False)
    counts = df.groupby("label").size().to_dict()
    lines = ["# London labelled deltas: fit and held-out test", "",
             f"Rows: {json.dumps(counts)}. Train 2014-2019, test 2020-2023 (held out). "
             f"Label rules: PM2.5 increment >= {MIN_DPM:g} ug/m3; Bonfire Night from {NIGHT_FROM}:00 UTC.", ""]
    for feats in (("l_no2_pm", "fine", "no_frac"), ("l_no2_pm", "l_co_pm", "fine", "no_frac"),
                  ("l_no2_pm", "l_co_pm", "fine", "no_frac", "l_so2_pm"), ("l_no2_pm", "l_co_pm")):
        r = fit_eval(df, feats, {2020, 2021, 2022, 2023})
        if not r:
            continue
        lines += [f"## Features: {', '.join(feats)}",
                  f"Train n={r['n_train']}, test n={r['n_test']} (burning {r['n_test_burning']}). "
                  f"Coefficients (positive = burning): {json.dumps(r['coef'])}, intercept {r['intercept']}", "",
                  "| Confidence threshold | Precision (class-balanced) | Coverage | n |", "|---|---|---|---|"]
        lines += [f"| {c['threshold']} | {c['precision']:.1%} | {c['coverage']:.0%} | {c['n']} |" for c in r["curve"]]
        lines.append("")
    text = "\n".join(lines)
    with open(os.path.join(HERE, f"LONDON_DELTAS_REPORT_dpm{MIN_DPM:g}_from{NIGHT_FROM}.md"), "w", encoding="utf-8") as f:
        f.write(text)
    print(text)


if __name__ == "__main__":
    main()
