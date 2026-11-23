"""Pooled keys (all sites) and episode scoring, both tested at IIT Delhi against Rai 2020.

    python -m attribution.validation.ncr
"""

import json
import os

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from ..engine import answer_key as ak
from . import delhi_rai as R
from . import more_keys as M

F = list(ak.FEATURES)
SRC = ("biomass_burning", "traffic")
T = ak.THRESHOLD


def wk(i):
    return pd.Index(i).year * 100 + pd.Index(i).day_of_year // 7


def rows(net, ex, key, site):
    j = net[F].join(ex, how="inner")
    out = []
    for s in SRC:
        if s not in j:
            continue
        e = j[s]
        d = j.loc[(e >= R.UP) | (e <= R.DOWN), F].copy()
        d["y"], d["src"], d["key"], d["site"] = (e.loc[d.index] >= R.UP).astype(int), s, key, site
        out.append(d)
    return pd.concat(out)


def data():
    near = {k: R.STATIONS[k] for k in R.NEAREST}
    iitd = R.network_features(R.fetch_obs(os.path.join(R.CACHE, "cpcb_winters.csv"), near))
    mo = R.fetch_obs(os.path.join(M.CACHE, "cpcb_mriu_hours.csv"), M.MRIU_STATIONS, M.WINTER_2018)
    mriu = R.network_features(mo, stations=tuple(M.MRIU_STATIONS))
    rai = R.family_excess(R.load_factors())
    return pd.concat([rows(iitd, rai, "rai", "iitd"),
                      rows(iitd, M.excess(M.wang("Figure 3")), "wang", "iitd"),
                      rows(iitd, M.excess(M.asap()), "asap", "iitd"),
                      rows(mriu, M.excess(M.wang("Figure 4")), "wang", "mriu")])


def fit(d):
    m = make_pipeline(SimpleImputer(), StandardScaler(), LogisticRegression(class_weight="balanced", max_iter=2000))
    return m.fit(d[F], d["y"])


def oof(df, s, pool):
    """Out-of-fold P(up) on Rai rows; each test week drops weeks w-1..w+1 from training."""
    d = df[df.src == s]
    test = d[d.key == "rai"]
    tr = d if pool else test
    tw, rw = wk(test.index), wk(tr.index)
    p = pd.Series(np.nan, index=test.index)
    for w in np.unique(tw):
        k = (rw < w - 1) | (rw > w + 1)
        if tr[k].y.nunique() < 2:
            continue
        p[tw == w] = fit(tr[k]).predict_proba(test[tw == w][F])[:, 1]
    return pd.DataFrame({"p": p, "y": test.y}).dropna()


def score(p, y):
    c = np.maximum(p, 1 - p) >= T
    ok = (p >= 0.5).astype(int) == y
    w = np.where(y == 1, 1 / max((y == 1).sum(), 1), 1 / max((y == 0).sum(), 1))
    return {"n": int(c.sum()), "precision": round(float((w * ok)[c].sum() / w[c].sum()), 4) if c.any() else None,
            "coverage": round(float(w[c].sum() / w.sum()), 4), "up_called": int((c & (p >= T)).sum()),
            "up_right": int((c & (p >= T) & (y == 1)).sum())}


def episodes(o, ex, s, h):
    """Mean P over h-hour windows; label from the window's mean measured excess."""
    e = ex[s].reindex(o.index)
    g = o.index.floor(f"{h}h")
    w = pd.DataFrame({"p": o.p, "e": e}).groupby(g).agg(p=("p", "mean"), e=("e", "mean"), n=("p", "size"))
    w = w[(w.n >= max(2, h // 2)) & ((w.e >= R.UP) | (w.e <= R.DOWN))]
    return score(w.p.to_numpy(), (w.e >= R.UP).astype(int).to_numpy())


def main():
    df = data()
    rai = R.family_excess(R.load_factors())
    res = {"rows": df.groupby(["key", "site", "src"]).size().to_dict()}
    for s in SRC:
        base, pool = oof(df, s, False), oof(df, s, True)
        res[s] = {"hourly_rai_only": score(base.p.to_numpy(), base.y.to_numpy()),
                  "hourly_pooled": score(pool.p.to_numpy(), pool.y.to_numpy())}
        for h in (3, 6, 12):
            res[s][f"episode_{h}h_rai_only"] = episodes(base, rai, s, h)
            res[s][f"episode_{h}h_pooled"] = episodes(pool, rai, s, h)
    res["rows"] = {"/".join(k): v for k, v in res["rows"].items()}
    L = ["# Pooled keys and episodes, tested at IIT Delhi", "",
         f"Held-out weeks, Rai 2020 labels at IIT Delhi, calls at >= {T}. Precision is class-balanced; "
         "coverage is the share of clear hours (or windows) that get a call.", "",
         "| Source | Variant | Calls | Precision | Coverage | 'Up' right |", "|---|---|---|---|---|---|"]
    for s in SRC:
        for v, r in res[s].items():
            pr = "n/a" if r["precision"] is None else f"{r['precision']:.1%}"
            L.append(f"| {s} | {v} | {r['n']} | {pr} | {r['coverage']:.0%} | {r['up_right']}/{r['up_called']} |")
    L += ["", f"Training rows: {json.dumps(res['rows'])}"]
    t = "\n".join(L)
    with open(os.path.join(R.HERE, "NCR_REPORT.md"), "w", encoding="utf-8") as f:
        f.write(t)
    print(t)


if __name__ == "__main__":
    main()
