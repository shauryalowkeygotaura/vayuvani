"""Traffic switched off: share of hours the live model calls traffic up, lockdown 2020 vs same dates 2019, every NCR station.

    python -m attribution.validation.lockdown
"""

import os

import pandas as pd

from ..engine import answer_key as ak
from . import delhi_rai as R

C = os.path.join(R.CACHE, "..", "more")
W = (("2019-03-18", "2019-04-15"), ("2020-03-18", "2020-04-15"))
CITIES = ("Delhi", "Gurugram", "Noida", "Ghaziabad", "Faridabad")


def calls(o, sid, m):
    g = R.network_features(o, stations=(sid,))
    g = g[(g.index.month == 3) & (g.index.day >= 25) | (g.index.month == 4) & (g.index.day <= 14)]
    if len(g) < 100:
        return None
    p = pd.DataFrame([ak.predict(r, m) for _, r in g[list(ak.FEATURES)].iterrows()], index=g.index)
    return p.ge(ak.THRESHOLD).groupby(p.index.year).mean()


def main():
    s = pd.read_csv(os.path.join(R.CACHE, "stations.csv"))
    st = dict(s.loc[s.City.isin(CITIES), ["StationId", "StationName"]].values)
    o = R.fetch_obs(os.path.join(C, "cpcb_lockdown.csv"), st, W)
    m = ak.load()
    out = []
    for sid in sorted(set(o.station_id)):
        r = calls(o[o.station_id == sid], sid, m)
        if r is None or 2019 not in r.index or 2020 not in r.index:
            continue
        out.append({"station": st[sid], "traffic_2019": r.loc[2019, "traffic"], "traffic_2020": r.loc[2020, "traffic"],
                    "burning_2019": r.loc[2019, "biomass_burning"], "burning_2020": r.loc[2020, "biomass_burning"]})
    d = pd.DataFrame(out)
    dn = (d.traffic_2020 < d.traffic_2019).sum()
    L = ["# Lockdown check (25 Mar to 14 Apr, 2020 vs 2019)", "",
         f"Stations with both years: {len(d)}. Traffic calls fell at {dn} of {len(d)}. "
         f"Median share of hours called traffic-up: {d.traffic_2019.median():.1%} in 2019, "
         f"{d.traffic_2020.median():.1%} in lockdown. Burning: {d.burning_2019.median():.1%} vs "
         f"{d.burning_2020.median():.1%}.", "",
         "A direction check, not a precision score: there is no measured traffic share here.", "",
         d.round(3).to_string(index=False)]
    t = "\n".join(L)
    with open(os.path.join(R.HERE, "LOCKDOWN_REPORT.md"), "w", encoding="utf-8") as f:
        f.write(t)
    print(t)


if __name__ == "__main__":
    main()
