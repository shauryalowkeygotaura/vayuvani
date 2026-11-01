"""
Kaun? runner: ingest -> attribute -> publish -> queue, with checkpoints.

    python -m attribution.run hourly              # what the cron runs
    python -m attribution.run backfill --start 2025-10-01 --end 2025-11-30
    python -m attribution.run demo                # synthetic, offline, never published

Exit codes: 0 ok, 1 auth/config failure (fix needed), 75 rate-limited
(temporary: the next run resumes from the checkpoint).
"""

import argparse
import logging
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

import pandas as pd

from . import http
from .checkpoint import Checkpoint
from .config import DEFAULT_LOOKBACK_HOURS, MAX_BACKFILL_HOURS, NMF_WINDOW_DAYS, PUBLIC_DIR
from .store import LocalStore, get_store

logger = logging.getLogger("kaun")

EXIT_AUTH, EXIT_RATE = 1, 75


def _floor_hour(dt: datetime) -> datetime:
    return dt.replace(minute=0, second=0, microsecond=0)


def merge_sources(openaq_rows: list[dict], cpcb_rows: list[dict]) -> list[dict]:
    """OpenAQ values win; CPCB fills pollutants OpenAQ lacks for the same station-hour."""
    merged = {(r["station_id"], r["hour"]): dict(r) for r in openaq_rows}
    for r in cpcb_rows:
        key = (r["station_id"], r["hour"])
        if key not in merged:
            merged[key] = dict(r)
            continue
        m = merged[key]
        filled = False
        for k, v in r.items():
            if k not in ("station_id", "hour", "source") and m.get(k) is None and v is not None:
                m[k] = v
                filled = True
        if filled:
            m["source"] = "openaq+cpcb"
    return list(merged.values())


def merge_wind(station_rows: list[dict], model_rows: list[dict]) -> list[dict]:
    """
    Station-measured wind wins (it is the mast at the monitor); Open-Meteo fills
    hours and stations without it, and always supplies boundary-layer height.
    """
    merged = {(r["station_id"], r["hour"]): dict(r) for r in model_rows}
    for r in station_rows:
        key = (r["station_id"], r["hour"])
        m = merged.setdefault(key, {"station_id": r["station_id"], "hour": r["hour"], "pbl_height": None})
        m["wind_speed"], m["wind_dir"] = r["wind_speed"], r["wind_dir"]
        m["source"] = "station"
    return list(merged.values())


def ingest(store, ckpt: Checkpoint, since: datetime, until: datetime, archive: bool = False) -> dict:
    from .ingest import cpcb, firms, openaq, wind

    stations = openaq.fetch_locations()
    oa_rows, station_wind = openaq.fetch_hourly(stations, since, until)

    cp_rows, cp_stations = ([], []) if archive else cpcb.fetch()
    if cp_rows:
        ratio = cpcb.cross_check(cp_rows, oa_rows)
        ckpt.note("cpcb_pm25_ratio_vs_openaq", ratio)
        if ratio is not None and not (0.7 <= ratio <= 1.4):
            logger.error(f"CPCB pm25/OpenAQ median ratio {ratio:.2f}: feed is not plain concentrations; "
                         f"CPCB rows dropped this run")
            cp_rows, cp_stations = [], []
        elif ratio is None:
            logger.warning("CPCB: no overlapping station-hours with OpenAQ to cross-check units")
    known = {s["id"] for s in stations}
    all_stations = stations + [s for s in cp_stations if s["id"] not in known]

    store.upsert("kaun_stations", [
        {"id": s["id"], "name": s["name"], "latitude": s["latitude"], "longitude": s["longitude"],
         "openaq_location_id": s.get("openaq_location_id"), "active": True}
        for s in all_stations])
    obs = merge_sources(oa_rows, cp_rows)
    obs = [r for r in obs if since <= r["hour"] < until]
    store.upsert("hourly_obs", obs)

    if archive:
        w = wind.fetch_archive(all_stations, since.strftime("%Y-%m-%d"), (until - timedelta(hours=1)).strftime("%Y-%m-%d"))
    else:
        w = wind.fetch(all_stations, past_days=max(1, (until - since).days + 1))
    w = merge_wind(station_wind, [r for r in w if since <= r["hour"] < until])
    store.upsert("wind_obs", w)

    if archive:
        fires = firms.fetch(day_range=min(5, max(1, (until - since).days)), date=since.strftime("%Y-%m-%d"),
                            sources=firms.ARCHIVE_SOURCES)
    else:
        fires = firms.fetch()
    store.upsert("fire_points", fires)
    return {"stations": len(all_stations), "obs": len(obs), "wind": len(w), "fires": len(fires)}


def _frame(rows: list[dict], col: str = "hour") -> pd.DataFrame:
    df = pd.DataFrame(rows)
    if not df.empty and col in df:
        df[col] = pd.to_datetime(df[col], utc=True, format="ISO8601")
    return df


def load_stations(store) -> dict[str, dict]:
    return {s["id"]: s for s in store.select("kaun_stations") if not str(s["id"]).startswith("_")}


def attribute(store, now: datetime, since: datetime) -> list[dict]:
    from .engine import attribute as engine

    start = (now - timedelta(days=NMF_WINDOW_DAYS + 1)).isoformat()
    obs = _frame(store.select("hourly_obs", {"hour": f"gte.{start}"}))
    wind = _frame(store.select("wind_obs", {"hour": f"gte.{start}"}))
    fires = store.select("fire_points", {"acq_time": f"gte.{(now - timedelta(days=3)).isoformat()}"})
    for f in fires:
        if "bearing_from_delhi" not in f or f["bearing_from_delhi"] is None:
            from .config import DELHI_LAT, DELHI_LON
            from .ingest.firms import bearing_deg
            f["bearing_from_delhi"] = bearing_deg(DELHI_LAT, DELHI_LON, float(f["latitude"]), float(f["longitude"]))
    from .ingest import landuse
    recs = engine.run(obs, wind, fires, load_stations(store), since=pd.Timestamp(since),
                      landuse=landuse.load(store))
    store.upsert("attributions", recs)
    return recs


def publish(store, now: datetime, run_meta: dict, root: str = None) -> list[str]:
    from .publish import feed
    from .publish import now as now_feed

    stations = load_stations(store)
    rows = store.select("attributions", {"window_start": f"gte.{(now - timedelta(days=8)).isoformat()}"})
    paths = feed.write(feed.build(rows, stations, now=now, run_meta=run_meta), root=root)
    obs = _frame(store.select("hourly_obs", {"hour": f"gte.{(now - timedelta(hours=26)).isoformat()}"}))
    paths.append(now_feed.write(now_feed.build(obs, stations, now=now), root=root))
    return paths


def hourly(args) -> int:
    from .preflight import check
    from reporting import citizen, queue

    now = datetime.now(timezone.utc)
    until = _floor_hour(now)
    ckpt = Checkpoint()
    if not args.skip_preflight:
        problems = check()
        if problems:
            print("Kaun pre-flight FAILED:\n" + "\n".join(problems), file=sys.stderr)
            return EXIT_AUTH
    store = get_store()

    last = ckpt.get("ingest")
    since = last if last else until - timedelta(hours=DEFAULT_LOOKBACK_HOURS)
    # Overlap 3 h: CPCB/OpenAQ backfill late hours, and upserts are idempotent.
    since = max(since - timedelta(hours=3), until - timedelta(hours=MAX_BACKFILL_HOURS))
    meta = {"started_at": now.isoformat(), "ingest_from": since.isoformat(), "ingest_to": until.isoformat()}
    try:
        meta["ingest"] = ingest(store, ckpt, since, until)
        ckpt.set("ingest", until)
        try:  # static OSM inventory; a few stations per run, never blocks attribution
            from .ingest import landuse
            meta["landuse_refreshed"] = landuse.refresh(store, list(load_stations(store).values()))
        except Exception as e:
            logger.warning(f"Land-use refresh skipped: {e}")

        a_last = ckpt.get("attribute") or since
        recs = attribute(store, now, a_last - timedelta(hours=6))
        meta["attributions_this_run"] = len(recs)
        ckpt.set("attribute", until)

        meta["queued"] = len(queue.enqueue(recs, store=store))
        meta["queued_citizen"] = len(citizen.enqueue_clusters(store=store, now=now))
        publish(store, now, meta)
        ckpt.set("publish", until)
    except http.RateLimited as e:
        logger.error(f"Rate limited, stopping; next run resumes from checkpoint: {e}")
        return EXIT_RATE
    except http.AuthError as e:
        logger.error(f"Auth/scope failure: {e}")
        return EXIT_AUTH
    logger.info(f"Run complete: {meta}")
    return 0


def backfill(args) -> int:
    ckpt = Checkpoint()
    store = get_store()
    start = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end = datetime.strptime(args.end, "%Y-%m-%d").replace(tzinfo=timezone.utc) + timedelta(days=1)
    cur = max(start, ckpt.get("backfill") or start)
    step = timedelta(days=args.chunk_days)
    try:
        while cur < end:
            nxt = min(cur + step, end)
            logger.info(f"Backfill {cur:%Y-%m-%d} -> {nxt:%Y-%m-%d}")
            ingest(store, ckpt, cur, nxt, archive=True)
            ckpt.set("backfill", nxt)
            cur = nxt
        recs = attribute(store, end, start)
        logger.info(f"Backfill attributed {len(recs)} windows")
    except http.RateLimited as e:
        logger.error(f"Rate limited at {cur:%Y-%m-%d}; rerun to resume: {e}")
        return EXIT_RATE
    except http.AuthError as e:
        logger.error(f"Auth/scope failure: {e}")
        return EXIT_AUTH
    return 0


def demo(args) -> int:
    """Synthetic end-to-end run in a temp dir. Output is marked synthetic and never published."""
    from . import synthetic
    from .engine import attribute as engine
    from .publish import voice
    from reporting import evidence

    root = args.out or tempfile.mkdtemp(prefix="kaun-demo-")
    store = LocalStore(os.path.join(root, "db"))
    obs, wind = synthetic.generate()
    store.upsert("kaun_stations", [{"id": k, **v, "active": True} for k, v in synthetic.STATIONS.items()])
    store.upsert("hourly_obs", obs.to_dict("records"))
    store.upsert("wind_obs", wind.to_dict("records"))
    recs = engine.run(obs, wind, [], synthetic.STATIONS)
    for r in recs:
        print(f"[{r['confidence']:>6}] {r['summary_en']}")
    best = next((r for r in recs if r["confidence"] == "high"), None)
    if best:
        print("\nEvidence pack:", evidence.build(best, root=root)["dir"])
        lat, lon = best["latitude"], best["longitude"]
        now = datetime.fromisoformat(best["window_end"])
        print("Voice (en):", voice.answer(lat, lon, "en", records=recs, now=now))
        print("Voice (hi):", voice.answer(lat, lon, "hi", records=recs, now=now))
    print(f"\nSYNTHETIC demo output in {root} (not real data, not published)")
    return 0


def main():
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"),
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description="Kaun? pollution attribution")
    sub = ap.add_subparsers(dest="cmd", required=True)
    h = sub.add_parser("hourly")
    h.add_argument("--skip-preflight", action="store_true")
    b = sub.add_parser("backfill")
    b.add_argument("--start", required=True)
    b.add_argument("--end", required=True)
    b.add_argument("--chunk-days", type=int, default=3)
    d = sub.add_parser("demo")
    d.add_argument("--out")
    args = ap.parse_args()
    sys.exit({"hourly": hourly, "backfill": backfill, "demo": demo}[args.cmd](args))


if __name__ == "__main__":
    main()
