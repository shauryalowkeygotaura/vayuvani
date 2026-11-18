"""
Blind test: does Kaun's chemistry agree with evidence it never saw?

There is no answer key for Delhi (DSS was suspended in late 2025), so this
checks the engine against three independent witnesses instead:

  fires    NASA FIRMS hot spots within 30 km in the 12 h before a spike
  clock    the hour of day (rush hours, night)
  map      what OpenStreetMap says is around the station (landfills and
           crematoria, bus depots and arterial roads, industrial land)

To keep it honest, the engine is re-run "blind": the evidence terms that
read those witnesses are switched off (land use, local fires, the time and
temperature term, and the traffic clock prior inside the fingerprint). What
is left is pure station chemistry: pollutant ratios, NO freshness, humidity,
factor analysis and the station's own pollutant-by-wind history. If the
chemistry-only calls still line up with fires, clock and map more often than
chance, the method is reading something real.

Each check reports the observed rate, the base rate and a one-sided
permutation p-value (labels shuffled 5,000 times). Small samples, one week,
one season: a pass is "consistent with", never "proven".

    python -m attribution.validation.blind --days 6
"""

import argparse
import contextlib
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np
import pandas as pd

from ..engine import attribute as engine
from ..engine import fusion
from ..ingest import landuse, traffic
from ..ingest.firms import haversine_km

HERE = os.path.dirname(__file__)
IST = timezone(timedelta(hours=5, minutes=30))
RUSH = set(range(8, 12)) | set(range(18, 23))     # IST hours
NIGHT = set(range(20, 24)) | set(range(0, 6))
SEED = 7


@contextlib.contextmanager
def chemistry_only():
    """Switch off every term that reads the map, the clock or fire data."""
    saved = {n: getattr(fusion, n) for n in ("term_landuse", "term_local_fires", "term_time_temp")}
    saved_prior = traffic.prior
    fusion.term_landuse = lambda *a, **k: {}
    fusion.term_local_fires = lambda *a, **k: {}
    fusion.term_time_temp = lambda *a, **k: {}
    traffic.prior = lambda *a, **k: 0.5
    try:
        yield
    finally:
        for n, f in saved.items():
            setattr(fusion, n, f)
        traffic.prior = saved_prior


def local_top(rec: dict) -> Optional[str]:
    """The engine's local source call (before the regional split)."""
    ls = (rec.get("evidence") or {}).get("local_shares") or {}
    return max(ls, key=ls.get) if ls else None


def fires_near(rec: dict, fires: list[dict], km: float = 30.0, hours: int = 12) -> int:
    end = pd.Timestamp(rec["window_end"])
    lat, lon = rec.get("latitude"), rec.get("longitude")
    if lat is None or lon is None:
        return 0
    n = 0
    for f in fires:
        t = pd.Timestamp(f["acq_time"])
        t = t.tz_localize("UTC") if t.tzinfo is None else t
        if end - pd.Timedelta(hours=hours) <= t <= end and \
                haversine_km(lat, lon, float(f["latitude"]), float(f["longitude"])) <= km:
            n += 1
    return n


def station_traits(grid: Optional[dict]) -> dict:
    """Independent map labels for a station, from the OSM inventory."""
    feats = (grid or {}).get("features") or []
    near = (grid or {}).get("near") or {}

    def within(kinds, km):
        return sum(1 for f in feats if f.get("feature") in kinds and f.get("km", 99) <= km)

    return {
        "burn_site_3km": within(("landfill", "crematorium", "kiln"), 3.0) > 0,
        "transport_hub_1km": within(("depot", "rail"), 1.0) > 0 or (near.get("roads") or 0) >= 12.0,
        "industrial_2km": within(("industrial", "power"), 2.0) >= 3,
    }


def perm_test(flag: np.ndarray, group: np.ndarray, n: int = 5000) -> tuple[float, float, float]:
    """Rate of `flag` inside `group` vs outside; one-sided p that inside > outside by chance."""
    flag, group = flag.astype(bool), group.astype(bool)
    if group.sum() == 0 or (~group).sum() == 0:
        return float("nan"), float("nan"), float("nan")
    obs = flag[group].mean() - flag[~group].mean()
    rng = np.random.default_rng(SEED)
    hits = 0
    for _ in range(n):
        g = rng.permutation(group)
        if flag[g].mean() - flag[~g].mean() >= obs:
            hits += 1
    return float(flag[group].mean()), float(flag[~group].mean()), (hits + 1) / (n + 1)


def build_table(recs: list[dict], fires: list[dict], grids: dict) -> pd.DataFrame:
    rows = []
    for r in recs:
        start = pd.Timestamp(r["window_start"]).tz_convert(IST)
        traits = station_traits(grids.get(r["station_id"]))
        rows.append({
            "id": r["id"], "station": r["station_name"], "top": local_top(r),
            "confidence": r["confidence"], "hour_ist": start.hour,
            "local_share": 1 - float(r.get("regional_share") or 0.0),
            "station_id": r["station_id"], "lat": r.get("latitude"), "lon": r.get("longitude"),
            "start": pd.Timestamp(r["window_start"]), "end": pd.Timestamp(r["window_end"]),
            "fires_30km": fires_near(r, fires), **traits,
        })
    return pd.DataFrame(rows)


def checks(df: pd.DataFrame) -> list[dict]:
    out = []

    def add(name, witness, flag, group, expect):
        inside, outside, p = perm_test(flag.to_numpy(), group.to_numpy())
        out.append({"check": name, "witness": witness, "n_group": int(group.sum()), "n_rest": int((~group).sum()),
                    "rate_group": inside, "rate_rest": outside, "p": p, "expect": expect,
                    "pass": bool(np.isfinite(p) and p < 0.05)})

    burn, trafc, ind = df["top"].eq("biomass_burning"), df["top"].eq("traffic"), df["top"].eq("industry")
    add("Burning calls have more satellite fires within 30 km", "fires",
        df["fires_30km"] > 0, burn, "burning windows see fires more often")
    add("Traffic calls fall in rush hours (8-11, 18-22 IST)", "clock",
        df["hour_ist"].isin(RUSH), trafc, "traffic windows sit in rush hours more often")
    add("Burning calls fall at night (20-06 IST)", "clock",
        df["hour_ist"].isin(NIGHT), burn, "burning windows sit at night more often")
    add("Stations within 3 km of a landfill/crematorium get more burning calls", "map",
        burn, df["burn_site_3km"], "burning share higher near burn sites")
    add("Stations at a depot/rail hub or dense arterial roads get more traffic calls", "map",
        trafc, df["transport_hub_1km"], "traffic share higher at transport hubs")
    add("Stations inside industrial land get more industry calls", "map",
        ind, df["industrial_2km"], "industry share higher in industrial areas")
    return out


def twin_check(df: pd.DataFrame, km: float = 3.0) -> dict:
    """
    Neighbouring stations (< km apart) that spike in overlapping hours breathe
    much the same air, so their chemistry-only calls should agree more often
    than calls from random station pairs at the same hours. This witness is
    valid for a baseline-relative method (the clock and map checks are weak,
    because each station's usual hours and surroundings sit in its baseline).
    """
    rows = df.dropna(subset=["top", "lat", "lon"]).reset_index(drop=True)
    near, far = [], []
    for i in range(len(rows)):
        a = rows.iloc[i]
        for j in range(i + 1, len(rows)):
            b = rows.iloc[j]
            if a["station_id"] == b["station_id"] or a["end"] <= b["start"] or b["end"] <= a["start"]:
                continue
            d = haversine_km(a["lat"], a["lon"], b["lat"], b["lon"])
            (near if d < km else far).append(a["top"] == b["top"])
    if not near or not far:
        return {"n_near": len(near), "n_far": len(far), "near": float("nan"), "far": float("nan"), "p": float("nan")}
    flag = np.array(near + far)
    group = np.array([True] * len(near) + [False] * len(far))
    inside, outside, p = perm_test(flag, group)
    return {"n_near": len(near), "n_far": len(far), "near": inside, "far": outside, "p": p}


def report(df: pd.DataFrame, res: list[dict], agree: Optional[float], meta: dict) -> str:
    L = ["# Kaun blind test", "",
         f"Generated {meta['generated']}. Spike windows: {len(df)} ({meta['window']}). "
         "Engine re-run with the map, clock and fire terms switched off; each check compares the "
         "chemistry-only call with a witness the engine did not see. p = one-sided permutation p-value.", "",
         "| Check | Witness | Group n | Rate in group | Rate elsewhere | p | Result |",
         "|---|---|---|---|---|---|---|"]
    for r in res:
        rg = "n/a" if not np.isfinite(r["rate_group"]) else f"{r['rate_group']:.0%}"
        rr = "n/a" if not np.isfinite(r["rate_rest"]) else f"{r['rate_rest']:.0%}"
        p = "n/a" if not np.isfinite(r["p"]) else f"{r['p']:.3f}"
        verdict = "PASS" if r["pass"] else ("too few" if r["n_group"] < 5 else "not shown")
        L.append(f"| {r['check']} | {r['witness']} | {r['n_group']} | {rg} | {rr} | {p} | {verdict} |")
    tw = twin_check(df)
    if np.isfinite(tw["p"]):
        verdict = "PASS" if tw["p"] < 0.05 else "not shown"
        L.append(f"| Neighbouring stations (< 3 km) agree more than distant ones, same hours | twins | "
                 f"{tw['n_near']} pairs | {tw['near']:.0%} | {tw['far']:.0%} | {tw['p']:.3f} | {verdict} |")
    L += ["", f"Calls by source (chemistry only): {json.dumps(df['top'].value_counts().to_dict())}"]
    if agree is not None:
        L.append(f"Full engine vs chemistry only, same local source: {agree:.0%} of windows "
                 "(the rest is where map/clock/fires changed the call).")
    L += ["", "Read it right: PASS = the chemistry agrees with an independent witness more than chance "
          "would give (p < 0.05). 'Not shown' is not proof of 'wrong': FIRMS misses small garbage fires, "
          "and spikes are measured against each station's own same-hour baseline, so a station's usual "
          "rush hour or neighbourhood is already in its baseline (the clock and map checks are weak "
          "for that reason; the twins check is not). A week is a small sample. "
          "Ground truth still needs on-site checks of named sites."]
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser(description="Kaun blind test against fires, clock and map")
    ap.add_argument("--days", type=int, default=6, help="attribute windows from the last N days")
    ap.add_argument("--out", default=os.path.join(HERE, "BLIND_REPORT.md"))
    args = ap.parse_args()

    from ..run import _frame, _this_region, load_stations
    from ..store import get_store
    store = get_store()
    now = datetime.now(timezone.utc)
    stations = load_stations(store)
    start = (now - timedelta(days=args.days + 8)).isoformat()
    obs = _this_region(_frame(store.select("hourly_obs", {"hour": f"gte.{start}"})), stations)
    wind = _this_region(_frame(store.select("wind_obs", {"hour": f"gte.{start}"})), stations)
    fires = store.select("fire_points", {"acq_time": f"gte.{(now - timedelta(days=args.days + 1)).isoformat()}"})
    from ..config import DELHI_LAT, DELHI_LON
    from ..ingest.firms import bearing_deg
    for f in fires:
        if f.get("bearing_from_delhi") is None:
            f["bearing_from_delhi"] = bearing_deg(DELHI_LAT, DELHI_LON, float(f["latitude"]), float(f["longitude"]))
    grids = landuse.load(store)
    since = pd.Timestamp(now - timedelta(days=args.days))

    full = engine.run(obs, wind, fires, stations, since=since, landuse=grids)
    with chemistry_only():
        blind = engine.run(obs, wind, fires, stations, since=since, landuse=grids)

    df = build_table(blind, fires, grids)
    full_top = {r["id"]: local_top(r) for r in full}
    same = [full_top.get(r["id"]) == local_top(r) for r in blind if r["id"] in full_top]
    agree = float(np.mean(same)) if same else None
    res = checks(df)
    meta = {"generated": now.strftime("%Y-%m-%d %H:%M UTC"),
            "window": f"{since:%d %b} to {now:%d %b %Y}"}
    text = report(df, res, agree, meta)
    # The local source is only routed to an agency when the local part is at
    # least 40% of the excess (reporting/agencies.py); test that subset too.
    loc = df.loc[df["local_share"] >= 0.4].reset_index(drop=True)
    if len(loc) >= 20:
        sub = report(loc, checks(loc), None, {**meta, "window": meta["window"] + ", local part >= 40% only"})
        text += "\n" + sub.replace("# Kaun blind test", "## Same checks, spikes where the local part is at least 40%")
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(text)
    df.to_csv(os.path.splitext(args.out)[0] + ".csv", index=False)
    print(text)


if __name__ == "__main__":
    main()
