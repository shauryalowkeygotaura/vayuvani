"""
A Delhi answer key: hourly measured source factors at IIT Delhi (Rai et al. 2020,
Sci. Total Environ. 742, 140332; data: https://zenodo.org/records/3907250, CC-BY).

Rai et al. ran an Xact XRF (hourly elements, PM10) at IIT Delhi in winter 2018
(20 Jan - 11 Mar, 2-hourly) and winter 2019 (15 Jan - 9 Feb, hourly) and split
the elements with PMF into nine factors. Those factor time series are measured
source activity, made with instruments Kaun never sees:
  Dust, Non-exhaust (brake/tyre/road: traffic), SFC1 + SFC2 (solid fuel
  combustion: burning), S-rich (regional secondary), and four industrial plume
  factors (Cr-Ni-Mn, Cu-Cd-Pb, Pb-Sn-Se, Cl-Br-Se).

This module pairs those hours with CPCB/DPCC monitors within ~8 km of IIT Delhi
(CPCB CCR hourly data), builds each monitor's local increment (the hour minus that station's
same-hour median of the previous 7 days, as the engine does), labels the hour by
which source family rose most at IIT Delhi, and asks: can CPCB chemistry alone
name it? Trained on one block of days, tested on the others (blocked CV, never
on neighbouring hours), with a precision/coverage curve so Kaun can abstain.

    doppler run -- python -m attribution.validation.delhi_rai

Times in the Rai file are local (IST): its diurnal profiles peak for burning at
21-23 h and for non-exhaust at night, which only fits local time.
"""

import json
import os

import numpy as np
import pandas as pd

from .. import http
from ..engine import answer_key
from ..config import STATE_DIR

HERE = os.path.dirname(__file__)
CACHE = os.path.join(STATE_DIR, "external", "rai2020")
XLSX = os.path.join(CACHE, "rai.xlsx")
ZENODO = "https://zenodo.org/records/3907250/files/Scitotenv.2020.140332.xlsx?download=1"
SITE = (28.545, 77.193)   # IIT Delhi, from the file's Figure 3 sheet
WINTERS = (("2018-01-12", "2018-03-12"), ("2019-01-07", "2019-02-10"))
FAMILIES = {"dust": ["Dust"], "traffic": ["Non-exhaust"], "biomass_burning": ["SFC1", "SFC2"],
            "industry": ["Cr-Ni-Mn", "Cu-Cd-Pb", "Pb-Sn-Se", "Cl-Br-Se"], "secondary": ["S-rich"]}


# ---------------------------------------------------------------- answer key
def load_factors() -> pd.DataFrame:
    """Hourly PM10 factor contributions, UTC-indexed, both winters."""
    os.makedirs(CACHE, exist_ok=True)
    if not os.path.exists(XLSX):
        resp = http.get(ZENODO, timeout=180)
        if len(resp.content) < 100_000:
            raise http.BadResponse("Rai 2020 file: unexpectedly small download")
        with open(XLSX, "wb") as f:
            f.write(resp.content)
    raw = pd.read_excel(XLSX, sheet_name="Figure 5", header=None)
    names = [str(x) for x in raw.iloc[0, 2:11]]
    blocks = []
    for c0, tag in ((1, None), (12, "PM10")):
        b = raw.iloc[1:, c0:c0 + 10].copy()
        b.columns = ["t"] + names
        if tag:
            b = b.loc[raw.iloc[1:, 23].astype(str).str.upper() == tag]
        b["t"] = pd.to_datetime(b["t"], errors="coerce")
        b = b.dropna(subset=["t"])
        blocks.append(b)
    f = pd.concat(blocks)
    for n in names:
        f[n] = pd.to_numeric(f[n], errors="coerce")
    # IST -> UTC, then onto the engine's hour-ending labels (floor to the hour).
    f["hour"] = (f["t"] - pd.Timedelta(hours=5, minutes=30)).dt.tz_localize("UTC").dt.floor("h")
    return f.drop(columns="t").groupby("hour").mean()


def family_excess(f: pd.DataFrame) -> pd.DataFrame:
    """Each source family's level over its own median for that winter (1.0 = typical)."""
    out = pd.DataFrame(index=f.index)
    winter = f.index.year
    for fam, cols in FAMILIES.items():
        s = f[cols].sum(axis=1, min_count=1)
        med = s.groupby(winter).transform("median")
        out[fam] = s / med.replace(0, np.nan)
    return out


MIN_RISE = float(os.getenv("KAUN_RAI_MIN_RISE", "1.5"))   # family must be >= 1.5x its median
DOMINANCE = float(os.getenv("KAUN_RAI_DOMINANCE", "1.25"))  # and 1.25x the runner-up


def label_hours(ex: pd.DataFrame) -> pd.Series:
    """The family that rose most, if it rose clearly and clearly beat the rest; else None."""
    lab = pd.Series(None, index=ex.index, dtype=object)
    vals = ex.to_numpy()
    for i, row in enumerate(vals):
        if np.isnan(row).all():
            continue
        order = np.argsort(-np.nan_to_num(row, nan=-1))
        top, second = row[order[0]], row[order[1]]
        if top >= MIN_RISE and (np.isnan(second) or top >= DOMINANCE * second):
            lab.iloc[i] = ex.columns[order[0]]
    return lab


# ---------------------------------------------------------------- CPCB side
# CPCB CCR hourly station data 2015-2020 (the widely used "Air Quality Data in
# India" compilation), mirrored at huggingface.co/datasets/khush-thakkar-09/station_hour.
# OpenAQ's API and archive have almost none of these winters, so this is the source.
MIRROR = "https://huggingface.co/datasets/khush-thakkar-09/station_hour/resolve/main/station_hour.csv.gz"
STATIONS = {"DL036": "Sri Aurobindo Marg (DPCC)", "DL031": "R K Puram (DPCC)", "DL034": "Sirifort (CPCB)",
            "DL004": "Aya Nagar (IMD)", "DL016": "JLN Stadium (DPCC)", "DL017": "Lodhi Road (IMD)",
            "DL024": "Nehru Nagar (DPCC)", "DL018": "Dhyan Chand Stadium (DPCC)", "DL007": "CRRI Mathura Rd (IMD)",
            "DL026": "Okhla Ph-2 (DPCC)", "DL019": "Mandir Marg (DPCC)", "DL014": "ITO (CPCB)"}
COLMAP = {"PM2.5": "pm25", "PM10": "pm10", "NO": "no", "NO2": "no2", "CO": "co", "SO2": "so2", "O3": "o3",
          "NH3": "nh3", "Benzene": "benzene", "Toluene": "toluene"}


def fetch_obs() -> pd.DataFrame:
    path = os.path.join(CACHE, "cpcb_winters.csv")
    if not os.path.exists(path):
        src = os.path.join(CACHE, "station_hour.csv.gz")
        if not os.path.exists(src):
            resp = http.get(MIRROR, timeout=600)
            if len(resp.content) < 10_000_000:
                raise http.BadResponse("station_hour mirror: unexpectedly small download")
            with open(src, "wb") as f:
                f.write(resp.content)
        parts = [c[c["StationId"].isin(list(STATIONS))] for c in pd.read_csv(src, chunksize=500_000)]
        d = pd.concat(parts)
        t = pd.to_datetime(d["Datetime"])
        keep = np.zeros(len(d), bool)
        for a, b in WINTERS:
            keep |= ((t >= a) & (t < b)).to_numpy()
        d.loc[keep].to_csv(path, index=False)
    d = pd.read_csv(path)
    out = pd.DataFrame({"station_id": d["StationId"],
                        # IST -> UTC on the same floor-to-hour convention as the factors
                        "hour": (pd.to_datetime(d["Datetime"]) - pd.Timedelta(hours=5, minutes=30))
                        .dt.tz_localize("UTC").dt.floor("h") - pd.Timedelta(hours=1)})
    # The -1 h: lagged rank correlations (SFC vs CO/benzene, Dust vs coarse PM)
    # peak at -1 h at all three nearest stations, i.e. CPCB stamps hour-start.
    for src, dst in COLMAP.items():
        v = pd.to_numeric(d[src], errors="coerce")
        out[dst] = v.where(v > 0)                      # CPCB writes 0 for "missing" on some gases
    return out


def increments(obs: pd.DataFrame) -> pd.DataFrame:
    """Hour minus the station's same-hour median over the previous 7 days (the engine's baseline)."""
    out = []
    cols = [c for c in ("pm25", "pm10", "no2", "co", "so2", "o3", "no", "nh3", "benzene", "toluene") if c in obs]
    for sid, g in obs.groupby("station_id"):
        g = g.set_index("hour").sort_index()[cols]
        g = g[~g.index.duplicated()].asfreq("h")
        base = pd.concat([g.shift(24 * d) for d in range(1, 8)]).groupby(level=0).median()
        d = (g - base).add_prefix("d_")
        lvl = g.add_prefix("v_")
        x = pd.concat([d, lvl], axis=1)
        x["station_id"] = sid
        out.append(x.reset_index())
    return pd.concat(out, ignore_index=True)


def features(x: pd.DataFrame, min_dpm: float = 5.0) -> pd.DataFrame:
    """The engine's live chemistry features (engine/answer_key.py) plus the CPCB-only markers."""
    f = answer_key.chem_features(x)
    pos = lambda s, lo: s.clip(lower=lo)
    # Markers CPCB measures at many Delhi stations but OpenAQ does not carry:
    f["l_tb"] = np.log10(pos(x["v_toluene"], 0.05) / pos(x["v_benzene"], 0.05))   # traffic ~3-4, burning ~1-1.5
    f["l_dbz_dpm"] = np.log10(pos(x["d_benzene"], 0.02) / pos(x["d_pm25"], 0.5))
    f["l_nh3_pm"] = np.log10(pos(x["v_nh3"], 0.5) / pos(x["v_pm25"], 1))
    return f.loc[x["d_pm25"] >= min_dpm]


CHEM = ("l_dno2_dpm", "l_dco_dpm", "l_dso2_dpm", "d_fine", "fine", "l_no2_pm", "l_co_pm", "l_so2_pm",
        "l_o3", "no_frac", "l_dpm")
BTX = CHEM + ("l_tb", "l_dbz_dpm", "l_nh3_pm")


def build() -> pd.DataFrame:
    fac = load_factors()
    ex = family_excess(fac)
    lab = label_hours(ex).rename("label")
    x = increments(fetch_obs())
    f = features(x)
    f["station_id"], f["hour"] = x.loc[f.index, "station_id"], pd.to_datetime(x.loc[f.index, "hour"], utc=True)
    f = f.merge(lab, left_on="hour", right_index=True, how="inner")
    f = f.merge(ex.add_prefix("ex_"), left_on="hour", right_index=True, how="left")
    f["block"] = f["hour"].dt.strftime("%Y") + "-w" + (f["hour"].dt.dayofyear // 7).astype(str)
    return f


# ---------------------------------------------------------------- scoring
def curve(p: np.ndarray, classes: np.ndarray, y: np.ndarray) -> list[dict]:
    """Class-balanced precision of the top call vs coverage, at confidence thresholds."""
    top = p.argmax(1)
    conf = p.max(1)
    correct = classes[top] == y
    w = pd.Series(y).map(1 / pd.Series(y).value_counts()).to_numpy()
    out = []
    for t in (0.0, 0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95):
        k = conf >= t
        if k.sum() < 5:
            continue
        out.append({"threshold": t, "precision": float((w[k] * correct[k]).sum() / w[k].sum()),
                    "coverage": float(w[k].sum() / w.sum()), "n": int(k.sum())})
    return out


def cv_eval(df: pd.DataFrame, feats: tuple, model: str = "hgb", classes_keep=None) -> dict:
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.impute import SimpleImputer
    from sklearn.preprocessing import StandardScaler
    d = df.dropna(subset=["label"])
    if classes_keep:
        d = d.loc[d["label"].isin(classes_keep)]
    d = d.reset_index(drop=True)
    blocks = sorted(d["block"].unique())
    probs = np.zeros((len(d), d["label"].nunique()))
    classes = np.array(sorted(d["label"].unique()))
    # Blocked CV: hold out one ISO-week block at a time, train on the rest minus
    # the adjacent blocks (so no neighbouring-hour leakage).
    for i, b in enumerate(blocks):
        test = d["block"] == b
        near = set(blocks[max(0, i - 1):i + 2])
        train = ~d["block"].isin(near)
        if train.sum() < 50 or d.loc[train, "label"].nunique() < len(classes):
            probs[test.to_numpy()] = np.nan
            continue
        if model == "hgb":
            m = HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=200,
                                               class_weight="balanced", random_state=0)
        else:
            m = make_pipeline(SimpleImputer(), StandardScaler(),
                              LogisticRegression(class_weight="balanced", max_iter=2000))
        m.fit(d.loc[train, list(feats)], d.loc[train, "label"])
        pr = m.predict_proba(d.loc[test, list(feats)])
        probs[test.to_numpy()] = pr[:, [list(m.classes_).index(c) for c in classes]]
    ok = ~np.isnan(probs).any(1)
    return {"n": int(ok.sum()), "counts": d.loc[ok, "label"].value_counts().to_dict(),
            "curve": curve(probs[ok], classes, d.loc[ok, "label"].to_numpy())}


NEAREST = ("DL036", "DL034", "DL031")      # Sri Aurobindo Marg 1.5 km, Sirifort 2.3, R K Puram 2.1
UP, DOWN = 1.5, 1.0                        # elevated vs not (the band between is dropped as ambiguous)


def network_features(obs: pd.DataFrame, stations=NEAREST) -> pd.DataFrame:
    """Per hour: the median over the nearest stations of each station's chemistry features."""
    x = increments(obs.loc[obs["station_id"].isin(stations)])
    f = features(x, min_dpm=-1e9)                 # every hour; the task is "what is up now", not spikes only
    f["hour"] = pd.to_datetime(x.loc[f.index, "hour"], utc=True)
    g = f.groupby("hour").median(numeric_only=True)
    pm = x.assign(hour=pd.to_datetime(x["hour"], utc=True)).groupby("hour")[["v_pm25", "v_pm10"]].median()
    g["l_pm25"] = np.log10(pm["v_pm25"].clip(lower=1))
    g["l_coarse"] = np.log10((pm["v_pm10"] - pm["v_pm25"]).clip(lower=1))
    ist = (g.index + pd.Timedelta(hours=5, minutes=30)).hour
    g["clock_s"], g["clock_c"] = np.sin(2 * np.pi * ist / 24), np.cos(2 * np.pi * ist / 24)
    return g


def binary_eval(df: pd.DataFrame, target: str, feats: tuple, model: str) -> dict:
    """Is family `target` elevated (>= UP x median) vs not (<= DOWN x median)? Blocked weekly CV."""
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    e = df[f"ex_{target}"]
    d = df.loc[(e >= UP) | (e <= DOWN)].copy()
    d["y"] = np.where(d[f"ex_{target}"] >= UP, "up", "not")
    d["block"] = d.index.strftime("%Y") + "-w" + (d.index.dayofyear // 7).astype(str)
    blocks = sorted(d["block"].unique())
    p = np.full(len(d), np.nan)
    for i, b in enumerate(blocks):
        test = (d["block"] == b).to_numpy()
        train = ~d["block"].isin(blocks[max(0, i - 1):i + 2]).to_numpy()
        if d.loc[train, "y"].nunique() < 2:
            continue
        m = (HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=200,
                                            class_weight="balanced", random_state=0) if model == "hgb" else
             make_pipeline(SimpleImputer(), StandardScaler(), LogisticRegression(class_weight="balanced", max_iter=2000)))
        m.fit(d.loc[train, list(feats)], d.loc[train, "y"])
        p[test] = m.predict_proba(d.loc[test, list(feats)])[:, list(m.classes_).index("up")]
    ok = ~np.isnan(p)
    probs = np.c_[1 - p[ok], p[ok]]
    return {"n": int(ok.sum()), "counts": d.loc[ok, "y"].value_counts().to_dict(),
            "curve": curve(probs, np.array(["not", "up"]), d.loc[ok, "y"].to_numpy())}


def export_model(df: pd.DataFrame) -> dict:
    """Fit the live model (logit, OpenAQ-carried features) on every labelled hour; write engine/answer_key_model.json."""
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    feats = list(answer_key.FEATURES)
    out = {"version": "rai2020-logit-v1", "trained_on": "IIT Delhi Xact PMF factors (Rai et al. 2020, Zenodo 3907250) "
           "vs CPCB hourly at Sri Aurobindo Marg, Sirifort, R K Puram; winters 2018-19",
           "threshold": answer_key.THRESHOLD, "sources": {}, "validated": [], "held_out": {}}
    for target in ("biomass_burning", "traffic", "dust", "industry"):
        cv = binary_eval(df, target, tuple(feats), "logit")
        at = next((c for c in cv["curve"] if c["threshold"] == answer_key.THRESHOLD), None)
        out["held_out"][target] = at
        if at and at["precision"] >= 0.95:
            out["validated"].append(target)
        e = df[f"ex_{target}"]
        d = df.loc[(e >= UP) | (e <= DOWN)]
        y = (d[f"ex_{target}"] >= UP).to_numpy()
        imp = SimpleImputer().fit(d[feats])
        xi = imp.transform(d[feats])
        sc = StandardScaler().fit(xi)
        m = LogisticRegression(class_weight="balanced", max_iter=2000).fit(sc.transform(xi), y)
        out["sources"][target] = {"features": feats, "coef": m.coef_[0].round(5).tolist(),
                                  "intercept": round(float(m.intercept_[0]), 5),
                                  "mean": sc.mean_.round(5).tolist(), "scale": sc.scale_.round(5).tolist(),
                                  "impute": imp.statistics_.round(5).tolist()}
    with open(answer_key.MODEL_PATH, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1)
    return out


def main():
    fac = load_factors()
    ex = family_excess(fac)
    net = network_features(fetch_obs())
    df = net.join(ex.add_prefix("ex_"), how="inner")
    df.to_csv(os.path.join(CACHE, "delhi_rai_hours.csv"))
    chem = tuple(c for c in CHEM if c != "l_dpm") + ("l_pm25", "l_coarse")
    sets = {"OpenAQ-like chemistry": chem,
            "+ BTX, NH3 and clock": chem + ("l_tb", "l_dbz_dpm", "l_nh3_pm", "clock_s", "clock_c")}
    L = ["# Kaun vs a Delhi answer key (Rai et al. 2020, IIT Delhi, winters 2018-19)", "",
         "Answer key: hourly PMF source factors measured at IIT Delhi with an Xact XRF "
         "(https://zenodo.org/records/3907250). Kaun side: CPCB hourly data at the three stations within "
         "2.5 km (Sri Aurobindo Marg, Sirifort, R K Puram), median of their features per hour. "
         f"Task per source: is it elevated (>= {UP}x its winter median) or not (<= {DOWN}x)? "
         "Blocked weekly CV, adjacent weeks dropped from training; precision is class-balanced.", "",
         f"Hours paired: {len(df)}.", ""]
    for target in ("biomass_burning", "traffic", "dust", "industry"):
        for setname, feats in sets.items():
            for model in ("logit", "hgb"):
                r = binary_eval(df, target, feats, model)
                L += [f"## {target} elevated? {setname} ({model})", f"n={r['n']}, {json.dumps(r['counts'])}", "",
                      "| Confidence >= | Precision | Coverage | n |", "|---|---|---|---|"]
                L += [f"| {c['threshold']} | {c['precision']:.1%} | {c['coverage']:.0%} | {c['n']} |" for c in r["curve"]]
                L.append("")
    text = "\n".join(L)
    with open(os.path.join(HERE, "DELHI_RAI_REPORT.md"), "w", encoding="utf-8") as f:
        f.write(text)
    print(text)


if __name__ == "__main__":
    import sys
    if "--export" in sys.argv:
        _df = network_features(fetch_obs()).join(family_excess(load_factors()).add_prefix("ex_"), how="inner")
        _m = export_model(_df)
        print(json.dumps({"validated": _m["validated"], "held_out": _m["held_out"]}, indent=1))
    else:
        main()
