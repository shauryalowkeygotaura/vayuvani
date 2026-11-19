"""
External test: run Kaun's chemistry-only engine on a city where the answer is known.

London, UK government AURN network (hourly, open, Defra UK-AIR openair files):
  TRAFFIC sites (kerbside/roadside: Marylebone Road, Camden, Haringey, Farringdon
  Street, A406): a spike the nearest urban background site does not share is
  road traffic by construction.
  BACKGROUND sites (North Kensington, Bloomsbury, Westminster, ...).
Known burning: Bonfire Night, 5 November, 17:00 to 04:00 UTC, every year:
bonfires and fireworks across the city (biomass smoke plus firework metals).

Labels (independent of everything the blind engine reads):
  burning  any spike window overlapping Bonfire Night
  traffic  a TRAFFIC-site window on a weekday, 06-19 UTC, with no overlapping
           spike at its nearest background site (so the excess is local to
           the road), outside Bonfire Night

Scores the chemistry-only local call (validation/blind.py chemistry_only):
precision and recall for burning and traffic, and the confusion table.
London is not Delhi: a pass here says the discriminator works, it is not a
Delhi accuracy number and must never be quoted as one.

    python -m attribution.validation.external --years 2016-2023

Data: https://uk-air.defra.gov.uk/openair/R_data/<SITE>_<YEAR>.RData (Crown
copyright, Open Government Licence). Needs `pyreadr`.
"""

import argparse
import json
import os
from collections import Counter

import numpy as np
import pandas as pd

from .. import http
from ..config import STATE_DIR
from ..engine import attribute as engine
from .blind import chemistry_only, local_top

HERE = os.path.dirname(__file__)
BASE = "https://uk-air.defra.gov.uk/openair/R_data"
TRAFFIC = ("MY1", "CA1", "HG1", "LOFS", "LONC")          # kerbside / roadside
BACKGROUND = ("KC1", "CLL2", "HORS", "HG4", "BEX", "HIL", "LON6", "TED")
SITES: dict[str, tuple[str, float, float]] = {}           # filled from Defra metadata
COLS = {"PM2.5": "pm25", "PM10": "pm10", "NO2": "no2", "SO2": "so2", "CO": "co", "O3": "o3",
        "NO": "no", "temp": "temp"}
CACHE = os.path.join(STATE_DIR, "external")


def load_sites() -> dict:
    """Name and coordinates for TRAFFIC + BACKGROUND from Defra's AURN metadata file."""
    import pyreadr
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, "AURN_metadata.RData")
    if not os.path.exists(path):
        resp = http.get(f"{BASE}/AURN_metadata.RData", timeout=120)
        with open(path, "wb") as f:
            f.write(resp.content)
    meta = list(pyreadr.read_r(path).values())[0]
    out = {}
    for code in TRAFFIC + BACKGROUND:
        m = meta.loc[meta["site_id"] == code]
        if not m.empty:
            out[code] = (str(m["site_name"].iloc[0]), float(m["latitude"].iloc[0]), float(m["longitude"].iloc[0]))
    SITES.update(out)
    return out


def nearest_background(code: str) -> str:
    from ..ingest.firms import haversine_km
    _, la, lo = SITES[code]
    bg = [b for b in BACKGROUND if b in SITES]
    return min(bg, key=lambda b: haversine_km(la, lo, SITES[b][1], SITES[b][2]))


def fetch(site: str, year: int) -> pd.DataFrame:
    import pyreadr
    if site not in SITES or not (2000 <= int(year) <= 2100):   # whitelist: goes into a URL
        raise ValueError(f"unknown site/year {site} {year}")
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, f"{site}_{int(year)}.RData")
    if not os.path.exists(path):
        resp = http.get(f"{BASE}/{site}_{int(year)}.RData", timeout=120)
        if len(resp.content) < 1000:
            raise http.BadResponse(f"{site} {year}: tiny file")
        with open(path, "wb") as f:
            f.write(resp.content)
    frames = pyreadr.read_r(path)
    key = f"{site}_{int(year)}"
    if key not in frames:
        raise http.BadResponse(f"{site} {year}: no hourly table in file")
    return frames[key]


def to_engine(site: str, df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    hour = pd.to_datetime(df["date"], utc=True)
    obs = pd.DataFrame({"station_id": site, "hour": hour})
    for src, dst in COLS.items():
        obs[dst] = pd.to_numeric(df[src], errors="coerce") if src in df else np.nan
    wind = pd.DataFrame({"station_id": site, "hour": hour,
                         "wind_speed": pd.to_numeric(df.get("ws"), errors="coerce"),
                         "wind_dir": pd.to_numeric(df.get("wd"), errors="coerce"),
                         "pbl_height": np.nan})
    return obs, wind.dropna(subset=["wind_speed", "wind_dir"])


def bonfire(year: int) -> tuple[pd.Timestamp, pd.Timestamp]:
    return pd.Timestamp(f"{year}-11-05T17:00Z"), pd.Timestamp(f"{year}-11-06T04:00Z")


def run_year(year: int) -> list[dict]:
    obs, wind = [], []
    for s in SITES:
        try:
            o, w = to_engine(s, fetch(s, year))
        except (http.ExternalError, KeyError) as e:   # site not running that year
            print(f"  {s} {year}: {e}")
            continue
        obs.append(o)
        wind.append(w)
    obs = pd.concat(obs, ignore_index=True)
    wind = pd.concat(wind, ignore_index=True)
    # Oct-Nov: 30 days of history before the scored month.
    obs = obs.loc[(obs["hour"] >= f"{year}-09-25") & (obs["hour"] < f"{year}-12-01")]
    wind = wind.loc[(wind["hour"] >= f"{year}-09-25") & (wind["hour"] < f"{year}-12-01")]
    stations = {k: {"name": v[0], "latitude": v[1], "longitude": v[2]} for k, v in SITES.items()}
    stations = {k: v for k, v in stations.items() if k in set(obs["station_id"])}
    with chemistry_only():
        recs = engine.run(obs, wind, [], stations, since=pd.Timestamp(f"{year}-10-25T00:00Z"))
    return recs


def label(recs: list[dict]) -> list[dict]:
    out = []
    wins: dict[str, list] = {}
    for r in recs:
        wins.setdefault(r["station_id"], []).append((pd.Timestamp(r["window_start"]), pd.Timestamp(r["window_end"])))
    for r in recs:
        s, e = pd.Timestamp(r["window_start"]), pd.Timestamp(r["window_end"])
        b0, b1 = bonfire(s.year)
        lab = None
        if s < b1 and e > b0:
            lab = "biomass_burning"
        elif r["station_id"] in TRAFFIC and s.weekday() < 5 and 6 <= s.hour <= 19:
            bg = wins.get(nearest_background(r["station_id"]), [])
            if not any(a < e and s < b for a, b in bg):
                lab = "traffic"
        out.append({"id": r["id"], "station": r["station_id"], "start": s.isoformat(),
                    "label": lab, "call": local_top(r), "confidence": r["confidence"],
                    "posterior": ((r.get("evidence") or {}).get("fusion") or {}).get("posterior"),
                    **{f"r_{k}": v for k, v in ((r.get("evidence") or {}).get("ratios") or {}).items()}})
    return out


def score(rows: list[dict]) -> dict:
    lab = [r for r in rows if r["label"]]
    res = {"n_labelled": len(lab), "confusion": {}}
    for cls in ("biomass_burning", "traffic"):
        called = [r for r in lab if r["call"] == cls]
        truth = [r for r in lab if r["label"] == cls]
        tp = sum(1 for r in called if r["label"] == cls)
        res[cls] = {"n_true": len(truth), "n_called": len(called),
                    "precision": tp / len(called) if called else None,
                    "recall": tp / len(truth) if truth else None}
    for r in lab:
        k = f"{r['label']} -> {r['call']}"
        res["confusion"][k] = res["confusion"].get(k, 0) + 1
    return res


def main():
    ap = argparse.ArgumentParser(description="Kaun external test, London (AURN)")
    ap.add_argument("--years", default="2016-2023")
    ap.add_argument("--out", default=os.path.join(HERE, "EXTERNAL_REPORT.md"))
    args = ap.parse_args()
    a, _, b = args.years.partition("-")
    years = range(int(a), int(b or a) + 1)
    load_sites()
    rows = []
    for y in years:
        try:
            rows += label(run_year(y))
        except (http.ExternalError, ValueError, KeyError) as e:
            print(f"{y}: skipped ({e})")
    res = score(rows)

    def pct(v):
        return "n/a" if v is None else f"{v:.0%}"

    L = ["# Kaun external test: London (AURN)", "",
         f"Years {args.years}, {len(SITES)} London AURN sites ({len([t for t in TRAFFIC if t in SITES])} kerbside/roadside, "
         f"{len([b for b in BACKGROUND if b in SITES])} background). "
         "Chemistry-only engine (map, clock and fire terms off). Labels: Bonfire Night = burning; weekday "
         "daytime spikes at a kerbside site not shared by its nearest background site = traffic. London is not Delhi: this tests the discriminator, "
         "it is not a Delhi accuracy number.", "",
         "| Class | True windows | Called | Precision | Recall |", "|---|---|---|---|---|"]
    for cls in ("biomass_burning", "traffic"):
        c = res[cls]
        L.append(f"| {cls} | {c['n_true']} | {c['n_called']} | {pct(c['precision'])} | {pct(c['recall'])} |")
    L += ["", f"Labelled windows: {res['n_labelled']}. Confusion (label -> call): "
          f"{json.dumps(dict(sorted(res['confusion'].items(), key=lambda kv: -kv[1])))}",
          f"All calls on all windows: {json.dumps(Counter(r['call'] for r in rows))}"]
    text = "\n".join(L) + "\n"
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(text)
    pd.DataFrame(rows).to_csv(os.path.splitext(args.out)[0] + ".csv", index=False)
    print(text)


if __name__ == "__main__":
    main()
