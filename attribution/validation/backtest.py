"""
Validation / backtest (PLAN.md Phase 5).

Three checks, all written into validation/REPORT.md:
1. Seasonal shares vs CSE: the mean "transported_smoke" share over a season
   window, compared with CSE's stubble share for that season. Our transported
   smoke is a proxy for stubble (it also catches any upwind fire), so the
   comparison is directional, not like-for-like.
2. Known events (reference/known_events.csv): spike coverage and top source.
3. DSS agreement: DSS has no public API and was suspended in late 2025, so
   there is nothing to fetch. Drop a CSV at reference/dss_outputs.csv with
   columns date,source,share (DSS's daily Delhi source shares, copied from its
   bulletins) and this computes per-source mean absolute difference and
   top-source agreement. Without the file the report says "not run".

Also counts "sub-grid" spikes: windows where the station's excess over the
city background is large while a station within 10 km saw no spike; these
are the events a 10 km grid cannot place. That number backs the headline
"catches X spikes DSS's 10 km grid misses" only once DSS outputs are loaded.
"""

import argparse
import csv
import json
import os
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd

from ..ingest.firms import haversine_km
from ..store import get_store

HERE = os.path.dirname(__file__)
REF = os.path.join(HERE, "reference")


def _load_attr(store, start: str, end: str) -> pd.DataFrame:
    rows = store.select("attributions", {"window_start": f"gte.{start}"})
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["window_start"] = pd.to_datetime(df["window_start"], utc=True, format="ISO8601")
    end_ts = pd.Timestamp(end)
    end_ts = end_ts.tz_localize("UTC") if end_ts.tzinfo is None else end_ts
    df = df.loc[df["window_start"] <= end_ts]
    df["shares"] = df["shares"].map(lambda s: json.loads(s) if isinstance(s, str) else (s or {}))
    return df


def seasonal_vs_cse(attr: pd.DataFrame) -> list[dict]:
    out = []
    with open(os.path.join(REF, "cse_seasonal.csv"), encoding="utf-8") as f:
        for ref in csv.DictReader(f):
            s, e = pd.Timestamp(ref["season_start"], tz="UTC"), pd.Timestamp(ref["season_end"], tz="UTC")
            sub = attr.loc[(attr["window_start"] >= s) & (attr["window_start"] <= e)] if not attr.empty else attr
            if sub.empty:
                out.append({"season": ref["season_start"][:4], "cse": float(ref["share"]), "ours": None,
                            "n": 0, "citation": ref["citation"]})
                continue
            # Weight each window's transported share by its PM2.5 excess.
            w = sub["excess_pm25"].astype(float).clip(lower=0)
            t = sub["shares"].map(lambda d: d.get("transported_smoke", 0.0)).astype(float)
            ours = float((w * t).sum() / w.sum()) if w.sum() > 0 else None
            out.append({"season": ref["season_start"][:4], "cse": float(ref["share"]), "ours": ours,
                        "n": int(len(sub)), "citation": ref["citation"]})
    return out


def known_events(attr: pd.DataFrame, n_stations: int) -> list[dict]:
    out = []
    with open(os.path.join(REF, "known_events.csv"), encoding="utf-8") as f:
        for ev in csv.DictReader(f):
            s, e = pd.Timestamp(ev["start_utc"]), pd.Timestamp(ev["end_utc"])
            sub = attr.loc[(attr["window_start"] >= s) & (attr["window_start"] <= e)] if not attr.empty else attr
            tops = sub["top_source"].value_counts().to_dict() if not sub.empty else {}
            out.append({
                "event": ev["event"], "expected": ev["expected"],
                "windows": int(len(sub)),
                "stations_with_spike": int(sub["station_id"].nunique()) if not sub.empty else 0,
                "stations_total": n_stations,
                "top_sources": tops,
                "citation": ev["citation"],
            })
    return out


def dss_agreement(attr: pd.DataFrame) -> Optional[dict]:
    p = os.path.join(REF, "dss_outputs.csv")
    if not os.path.exists(p) or attr.empty:
        return None
    dss = pd.read_csv(p, parse_dates=["date"])
    attr = attr.assign(date=attr["window_start"].dt.tz_convert("Asia/Kolkata").dt.date)
    rows, agree, total = [], 0, 0
    for date, g in dss.groupby(dss["date"].dt.date):
        ours_g = attr.loc[attr["date"] == date]
        if ours_g.empty:
            continue
        mix: dict[str, float] = {}
        for sh in ours_g["shares"]:
            for k, v in sh.items():
                mix[k] = mix.get(k, 0.0) + v / len(ours_g)
        dss_mix = dict(zip(g["source"], g["share"]))
        common = set(mix) & set(dss_mix)
        for k in common:
            rows.append(abs(mix[k] - dss_mix[k]))
        total += 1
        agree += int(max(mix, key=mix.get) == max(dss_mix, key=dss_mix.get))
    if not total:
        return None
    return {"days": total, "top_source_agreement": agree / total,
            "mean_abs_diff": float(np.mean(rows)) if rows else None}


def subgrid_spikes(attr: pd.DataFrame, stations: dict[str, dict]) -> int:
    """Local spikes with no concurrent spike at any station within 10 km."""
    if attr.empty:
        return 0
    n = 0
    for _, r in attr.iterrows():
        if (r.get("regional_share") or 0) > 0.3:
            continue
        me = stations.get(r["station_id"])
        if not me:
            continue
        near = [sid for sid, s in stations.items() if sid != r["station_id"]
                and haversine_km(me["latitude"], me["longitude"], s["latitude"], s["longitude"]) <= 10]
        if not near:
            continue
        concurrent = attr.loc[attr["station_id"].isin(near)
                              & ((attr["window_start"] - r["window_start"]).abs() <= pd.Timedelta(hours=2))]
        if concurrent.empty:
            n += 1
    return n


def write_report(start: str, end: str, store=None, out_path: Optional[str] = None) -> str:
    store = store or get_store()
    attr = _load_attr(store, start, end)
    stations = {s["id"]: s for s in store.select("kaun_stations")}
    seasons = seasonal_vs_cse(attr)
    events = known_events(attr, len(stations))
    dss = dss_agreement(attr)
    sub = subgrid_spikes(attr, stations)
    conf = attr["confidence"].value_counts().to_dict() if not attr.empty else {}

    L = [f"# Kaun? validation report ({start} to {end})", "",
         f"Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC. Attributions in range: {len(attr)}; "
         f"confidence mix: {conf or 'none'}.", ""]
    L += ["## 1. Seasonal transported smoke vs CSE stubble share", "",
          "| Season | CSE stubble share | Our transported-smoke share | Windows |", "|---|---|---|---|"]
    for s in seasons:
        ours = "no data" if s["ours"] is None else f"{s['ours']:.1%}"
        L.append(f"| {s['season']} | {s['cse']:.1%} | {ours} | {s['n']} |")
    L += ["", "Caveat: transported smoke counts any upwind fire, and is a share of spike EXCESS, not of "
          "season-mean PM2.5. Directional check only.", ""]
    L += ["## 2. Known events", ""]
    for e in events:
        L.append(f"- **{e['event']}**: {e['windows']} spike windows at {e['stations_with_spike']}/"
                 f"{e['stations_total']} stations; top sources {e['top_sources'] or 'none'}. "
                 f"Expected: {e['expected']}. Source: {e['citation']}")
    L += ["", "## 3. DSS agreement", ""]
    if dss is None:
        L.append("Not run: no `attribution/validation/reference/dss_outputs.csv` (DSS has no public API "
                 "and was suspended by CAQM in late 2025; copy its archived bulletins into that file).")
    else:
        L.append(f"Days compared: {dss['days']}; top-source agreement {dss['top_source_agreement']:.0%}; "
                 f"mean absolute share difference {dss['mean_abs_diff']}.")
    L += ["", f"## 4. Sub-grid spikes", "",
          f"{sub} local spikes had no concurrent spike at any station within 10 km: events a 10 km grid "
          "cannot place. Not yet a claim against DSS until DSS outputs are loaded.", ""]
    L += ["## Honest limits", "",
          "- Ratio fingerprints are well supported for CO/PM2.5 (traffic vs biomass smoke). Separating 3+ "
          "sources from station data alone is fuzzy; such splits are capped at medium confidence.",
          "- Wind is modelled (Open-Meteo), not the station mast. Transport uses a straight-line 24 h mean "
          "wind, not HYSPLIT.",
          "- No PMF uncertainties exist for CPCB data; NMF is an approximation and only corroborates.",
          "- Firecrackers have no class of their own; they appear as fine-mode combustion (biomass_burning) "
          "with SO2."]
    text = "\n".join(L) + "\n"
    out_path = out_path or os.path.join(HERE, "REPORT.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(text)
    return out_path


def main():
    ap = argparse.ArgumentParser(description="Kaun backtest report")
    ap.add_argument("--start", default="2025-10-01")
    ap.add_argument("--end", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    args = ap.parse_args()
    print(write_report(args.start, args.end))


if __name__ == "__main__":
    main()
