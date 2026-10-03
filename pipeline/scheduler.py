"""
VayuVani data pipeline scheduler.
Runs the full fetch → clean → store cycle every 15 minutes.

Usage:
    python pipeline/scheduler.py             # runs forever
    python pipeline/scheduler.py --once      # single run, then exit (good for testing)
"""

import sys
import logging
import argparse
from datetime import datetime, timezone

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

from .fetcher import fetch_all_openaq_delhi, fetch_cpcb_delhi
from .cleaner import clean_batch
from .db import insert_batch

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("vayuvani.scheduler")


def run_pipeline():
    start = datetime.now(timezone.utc)
    logger.info(f"Pipeline run started at {start.isoformat()}")

    # Fetch from both sources
    openaq_raw = fetch_all_openaq_delhi()
    cpcb_raw = fetch_cpcb_delhi()
    all_raw = openaq_raw + cpcb_raw

    if not all_raw:
        logger.warning("No data fetched — both sources returned empty")
        return

    # Clean and validate
    cleaned = clean_batch(all_raw)

    # Write to Supabase
    inserted = insert_batch(cleaned)

    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    logger.info(
        f"Pipeline done: {len(all_raw)} fetched → {len(cleaned)} cleaned → "
        f"{inserted} inserted ({elapsed:.1f}s)"
    )


def main():
    parser = argparse.ArgumentParser(description="VayuVani data pipeline")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    parser.add_argument("--interval", type=int, default=15, help="Interval in minutes (default: 15)")
    args = parser.parse_args()

    if args.once:
        run_pipeline()
        return

    scheduler = BlockingScheduler(timezone="UTC")
    scheduler.add_job(
        run_pipeline,
        trigger=IntervalTrigger(minutes=args.interval),
        id="aqi_pipeline",
        name="AQI data pipeline",
        replace_existing=True,
        # Run immediately on start, then every interval
        next_run_time=datetime.now(timezone.utc),
    )

    logger.info(f"Scheduler started — pipeline runs every {args.interval} minutes")
    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("Scheduler stopped")


if __name__ == "__main__":
    # Allow running as: python -m pipeline.scheduler
    main()
