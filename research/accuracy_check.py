"""
Week 5 — Advisory accuracy validation.

Compares VayuVani's LLM-generated advisory category against CPCB's official
advisory for the same station and timestamp.

Metric: Category match rate (Good/Satisfactory/Moderate/Poor/Very Poor/Severe)
Target: >90% match (deviation = off-by-one category or worse is a failure)

Usage:
    python -m research.accuracy_check --days 7
    python -m research.accuracy_check --export accuracy_report.csv
"""

import argparse
import csv
import sys
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

load_dotenv()

# pylint: disable=wrong-import-position
from pipeline.db import get_client

CATEGORIES = ["Good", "Satisfactory", "Moderate", "Poor", "Very Poor", "Severe"]


def category_distance(a: str, b: str) -> int:
    """
    Distance between two categories on the NAQI scale.
    0 = exact match, 1 = off by one step, etc.
    """
    try:
        return abs(CATEGORIES.index(a) - CATEGORIES.index(b))
    except ValueError:
        return 99


def fetch_advisory_logs(days: int) -> list[dict]:
    """Fetch VayuVani advisory logs from Supabase."""
    client = get_client()
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    result = (
        client.table("advisory_logs")
        .select("*")
        .gte("timestamp", since)
        .order("timestamp", desc=True)
        .execute()
    )
    return result.data or []


def fetch_cpcb_category(neighborhood: str, timestamp: str) -> str | None:
    """
    Fetch the CPCB-calculated category for the nearest station at a given time.
    Uses the aqi_readings table (which is sourced from CPCB).
    """
    client = get_client()
    # Find advisory_logs that matched this neighborhood → get coords from neighborhoods table
    coords_result = (
        client.table("neighborhoods")
        .select("latitude, longitude")
        .or_(f"name.ilike.{neighborhood},name_hi.ilike.{neighborhood}")
        .limit(1)
        .execute()
    )
    coords = coords_result.data[0] if coords_result.data else None
    if not coords:
        return None

    # Find nearest reading within ±15 minutes of the advisory timestamp
    ts = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    ts_low = (ts - timedelta(minutes=15)).isoformat()
    ts_high = (ts + timedelta(minutes=15)).isoformat()

    # Get nearest station
    rpc_result = client.rpc(
        "get_nearest_reading",
        {"p_lat": coords["latitude"], "p_lon": coords["longitude"], "p_radius_km": 10},
    ).execute()

    if not rpc_result.data:
        return None

    station_id = rpc_result.data[0].get("station_name")

    # Get reading at that time
    reading_result = (
        client.table("aqi_readings")
        .select("category")
        .eq("station_id", station_id)
        .gte("timestamp", ts_low)
        .lte("timestamp", ts_high)
        .order("timestamp")
        .limit(1)
        .execute()
    )

    if reading_result.data:
        return reading_result.data[0]["category"]
    return None


def run_accuracy_check(days: int = 7, export_path: str | None = None):
    print(f"Fetching advisory logs from last {days} days...")
    logs = fetch_advisory_logs(days)

    if not logs:
        print("No advisory logs found.")
        return

    print(f"Found {len(logs)} advisories. Comparing against CPCB readings...")

    results = []
    exact_matches = 0
    off_by_one = 0
    failures = 0
    no_cpcb_data = 0

    for log in logs:
        cpcb_cat = fetch_cpcb_category(log["neighborhood"], log["timestamp"])

        if cpcb_cat is None:
            no_cpcb_data += 1
            results.append({**log, "cpcb_category": "N/A", "distance": "N/A", "verdict": "no_data"})
            continue

        dist = category_distance(log["category"], cpcb_cat)
        if dist == 0:
            verdict = "exact_match"
            exact_matches += 1
        elif dist == 1:
            verdict = "off_by_one"
            off_by_one += 1
        else:
            verdict = "FAILURE"
            failures += 1

        results.append({
            **log,
            "cpcb_category": cpcb_cat,
            "distance": dist,
            "verdict": verdict,
        })

    comparable = len(logs) - no_cpcb_data
    if comparable == 0:
        print("No comparable data found (CPCB readings may not have loaded yet).")
        return

    exact_pct = exact_matches / comparable * 100
    off_by_one_pct = off_by_one / comparable * 100
    failure_pct = failures / comparable * 100

    print(f"\n{'='*50}")
    print(f"ACCURACY REPORT — last {days} days")
    print(f"{'='*50}")
    print(f"Total advisories:     {len(logs)}")
    print(f"Comparable (CPCB data available): {comparable}")
    print(f"Exact category match: {exact_matches} ({exact_pct:.1f}%)")
    print(f"Off by one step:      {off_by_one} ({off_by_one_pct:.1f}%)")
    print(f"Failures (≥2 steps):  {failures} ({failure_pct:.1f}%)")
    print(f"No CPCB data:         {no_cpcb_data}")
    print(f"\nTarget: >90% exact match. Current: {exact_pct:.1f}%")

    if failures > 0:
        print(f"\nFAILURES:")
        for r in results:
            if r.get("verdict") == "FAILURE":
                print(
                    f"  {r['timestamp'][:16]} | {r['neighborhood']:20} | "
                    f"VayuVani={r['category']:12} | CPCB={r['cpcb_category']}"
                )

    if export_path:
        with open(export_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=results[0].keys())
            writer.writeheader()
            writer.writerows(results)
        print(f"\nFull results exported to {export_path}")

    return {"exact_pct": exact_pct, "off_by_one_pct": off_by_one_pct, "failure_pct": failure_pct}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--export", type=str, help="Export CSV path")
    args = parser.parse_args()
    result = run_accuracy_check(days=args.days, export_path=args.export)
    if result and result["exact_pct"] < 90:
        print("\nWARNING: Below 90% accuracy target. Review failure cases above.")
        sys.exit(1)
