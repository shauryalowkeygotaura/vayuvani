"""NAQI 'now' feed: averaging windows and minimum-data rules."""

from datetime import datetime, timedelta, timezone

import pandas as pd

from attribution.publish import now as now_feed

NOW = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)


def frame(hours=24, **vals):
    h = [NOW - timedelta(hours=i) for i in range(hours)]
    return pd.DataFrame({"station_id": "a", "hour": h, **{k: v for k, v in vals.items()}})


def test_full_station():
    out = now_feed.station_naqi(frame(pm25=150.0, pm10=250.0, no2=60.0, co=2.0), NOW)
    # CPCB worked example gives 323 (300 + 30*100/130); the band table here starts at 301, so 324.
    assert out["aqi"] in (323, 324) and out["dominant_pollutant"] == "pm25"
    assert out["category"] == "Very Poor" and not out["stale"]


def test_needs_16_hours_and_three_pollutants():
    out = now_feed.station_naqi(frame(hours=10, pm25=150.0, pm10=250.0, no2=60.0), NOW)
    assert out["aqi"] is None and "insufficient" in out["note"]
    out = now_feed.station_naqi(frame(pm25=150.0, pm10=250.0), NOW)
    assert out["aqi"] is None


def test_stale_and_city_summary():
    df = frame(pm25=150.0, pm10=250.0, no2=60.0)
    df["hour"] = df["hour"] - timedelta(hours=5)
    out = now_feed.station_naqi(df, NOW)
    assert out["stale"]
    feed = now_feed.build(frame(pm25=90.0, pm10=200.0, no2=40.0), {"a": {"name": "A", "latitude": 1, "longitude": 2}}, now=NOW)
    assert feed["city"]["stations_reporting"] == 1 and feed["stations"][0]["name"] == "A"
