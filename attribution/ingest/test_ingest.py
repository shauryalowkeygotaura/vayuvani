"""Parser tests for every ingest source, including the malformed-response paths."""

from datetime import datetime, timezone

import pytest

from attribution import http
from attribution.ingest import cpcb, firms, openaq, traffic, wind
from attribution.ingest.units import station_slug, to_standard


def test_units():
    assert to_standard("co", 1500, "µg/m³") == pytest.approx(1.5)
    assert to_standard("co", 1.0, "ppm") == pytest.approx(28.01 / 24.45)
    assert to_standard("no2", 10, "ppb") == pytest.approx(10 * 46.01 / 24.45)
    # OpenAQ CPCB CO sensors: "ppb" tag on mg/m3 values (1.47 ppb is impossible air).
    assert to_standard("co", 1.47, "ppb") == pytest.approx(1.47)
    assert to_standard("co", 1200, "ppb") == pytest.approx(1200 * 28.01 / 24.45 / 1000)
    assert to_standard("pm25", 80, "µg/m³") == 80
    assert to_standard("pm25", 80, "ppm") is None          # nonsense unit rejected
    assert to_standard("so2", -3, "µg/m³") is None         # negative rejected
    assert to_standard("o3", "x", "µg/m³") is None


def test_slug_matches_across_sources():
    assert station_slug("Anand Vihar, Delhi - DPCC") == station_slug("anand vihar, delhi - dpcc")
    assert station_slug("R K Puram, Delhi - DPCC") == "r-k-puram-delhi-dpcc"


NOW = datetime(2026, 11, 1, 6, tzinfo=timezone.utc)


FIX = __import__("os").path.join(__import__("os").path.dirname(__file__), "fixtures")


def _fixture(name):
    import json, os
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return json.load(f) if name.endswith(".json") else f.read()


def test_openaq_locations_real_response():
    """Real /locations payload (2026-11-01): dead, duplicate and low-cost sites dropped."""
    st = openaq.parse_locations([_fixture("openaq_locations_2026-11-01.json")], now=NOW)
    assert [s["name"] for s in st] == ["R K Puram, Delhi - DPCC"]
    sensors = st[0]["sensors"]
    assert set(sensors) >= {"pm25", "pm10", "no2", "co", "so2", "o3", "wind_speed", "wind_direction"}
    ids = [x["id"] for x in sensors["pm25"]]
    assert ids == sorted(ids, reverse=True) and len(ids) == 2      # newest sensor tried first
    with pytest.raises(http.BadResponse):
        openaq.parse_locations([{"detail": "error"}])


def test_openaq_hours_real_response_ppb_and_labels():
    rows = openaq.parse_hours(_fixture("openaq_hours_no2_ppb_2026-11-01.json"), "no2", "ppb")
    assert rows
    hour, value = rows[0]
    # 19:30-20:30 UTC period -> labelled 20:00; 57 ppb NO2 -> ~107 ug/m3
    assert hour == datetime(2026, 10, 31, 20, tzinfo=timezone.utc)
    assert value == pytest.approx(57.0 * 46.01 / 24.45, rel=1e-3)


def test_openaq_hours_parse_edge_cases():
    payload = {"results": [
        {"value": 1200, "parameter": {"units": "µg/m³"},
         "period": {"datetimeFrom": {"utc": "2026-11-01T04:30:00Z"}}},
        {"value": None, "period": {"datetimeFrom": {"utc": "2026-11-01T05:30:00Z"}}},
        {"value": 5, "period": {}},
    ]}
    rows = openaq.parse_hours(payload, "co", "µg/m³")
    assert rows == [(datetime(2026, 11, 1, 5, tzinfo=timezone.utc), pytest.approx(1.2))]
    assert openaq.parse_hours({"results": [{"value": 400, "period": {"datetimeFrom": {"utc": "2026-11-01T04:30:00Z"}}}]},
                              "wind_direction", "deg") == []
    partial = {"results": [{"value": 90, "coverage": {"percentComplete": 25.0},
                            "period": {"datetimeFrom": {"utc": "2026-11-01T04:30:00Z"}}}]}
    assert openaq.parse_hours(partial, "pm25", "µg/m³") == []
    with pytest.raises(http.BadResponse):
        openaq.parse_hours({"oops": 1}, "co", None)


def test_openaq_fetch_hourly_falls_through_dead_sensor(monkeypatch):
    calls = []

    def fake(sensor_id, since, until):
        calls.append(sensor_id)
        if sensor_id == 2:
            return {"results": []}
        return {"results": [{"value": 100, "parameter": {"units": "µg/m³"},
                             "period": {"datetimeFrom": {"utc": "2026-11-01T04:30:00Z"}}}]}

    monkeypatch.setattr(openaq, "_fetch_sensor", fake)
    monkeypatch.setattr(openaq.time, "sleep", lambda s: None)
    st = [{"id": "a", "name": "A", "sensors": {"pm25": [{"id": 2, "units": "µg/m³"}, {"id": 1, "units": "µg/m³"}],
                                               "pm10": [{"id": 3, "units": "µg/m³"}, {"id": 4, "units": "µg/m³"}]}}]
    rows, wind_rows = openaq.fetch_hourly(st, NOW, NOW)
    assert calls == [2, 1, 3]                     # pm25 fell through; pm10 stopped at first hit
    assert rows[0]["pm25"] == 100 and wind_rows == []


def test_cpcb_parse():
    recs = [
        {"state": "Delhi", "station": "Anand Vihar, Delhi - DPCC", "last_update": "01-11-2026 11:00:00",
         "latitude": "28.6468", "longitude": "77.316", "pollutant_id": "PM2.5", "pollutant_avg": "250"},
        {"state": "Delhi", "station": "Anand Vihar, Delhi - DPCC", "last_update": "01-11-2026 11:00:00",
         "latitude": "28.6468", "longitude": "77.316", "pollutant_id": "CO", "pollutant_avg": "2.1"},
        {"state": "Delhi", "station": "Anand Vihar, Delhi - DPCC", "last_update": "01-11-2026 11:00:00",
         "pollutant_id": "NH3", "pollutant_avg": "9"},
        {"state": "Delhi", "station": "X", "last_update": "garbage", "pollutant_id": "PM10", "pollutant_avg": "1"},
        {"state": "Haryana", "station": "Y", "last_update": "01-11-2026 11:00:00", "pollutant_id": "PM10",
         "pollutant_avg": "1"},
        {"state": "Delhi", "station": "Z", "last_update": "01-11-2026 11:00:00", "pollutant_id": "PM10",
         "pollutant_avg": "NA"},
    ]
    rows, stations = cpcb.parse_records(recs)
    assert len(rows) == 1 and len(stations) == 1
    r = rows[0]
    # 10:00-11:00 IST average -> midpoint 05:00 UTC
    assert r["hour"] == datetime(2026, 11, 1, 5, tzinfo=timezone.utc)
    assert r["pm25"] == 250 and r["co"] == pytest.approx(2.1)


def test_cpcb_cross_check():
    h = datetime(2026, 11, 1, tzinfo=timezone.utc)
    oa = [{"station_id": "a", "hour": h, "pm25": 100.0}]
    assert cpcb.cross_check([{"station_id": "a", "hour": h, "pm25": 105.0}], oa) == pytest.approx(1.05)
    assert cpcb.cross_check([{"station_id": "b", "hour": h, "pm25": 1.0}], oa) is None


VIIRS = """latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_ti5,frp,daynight
30.5,75.8,330.1,0.4,0.4,2026-10-31,805,N,VIIRS,n,2.0NRT,290.1,12.3,D
29.9,76.9,320.0,0.4,0.4,2026-10-31,0757,N,VIIRS,h,2.0NRT,291.0,4.0,D
10.0,70.0,320.0,0.4,0.4,2026-10-31,0757,N,VIIRS,h,2.0NRT,291.0,4.0,D
"""


def test_firms_parse():
    rows = firms.parse_csv(VIIRS, "VIIRS_SNPP_NRT")
    assert len(rows) == 2                                    # far-away point dropped
    assert rows[0]["acq_time"] == datetime(2026, 10, 31, 8, 5, tzinfo=timezone.utc)
    assert rows[0]["confidence"] == "nominal" and rows[1]["confidence"] == "high"
    assert 270 < rows[0]["bearing_from_delhi"] < 360         # Punjab is north-west of Delhi
    assert firms.parse_csv("", "X") == []
    with pytest.raises(http.BadResponse):
        firms.parse_csv("Invalid MAP_KEY.", "VIIRS_SNPP_NRT")


def test_firms_real_response():
    rows = firms.parse_csv(_fixture("firms_viirs_snpp_2026-11-01.csv"), "VIIRS_SNPP_NRT")
    assert rows and all(r["dist_km"] <= 300 for r in rows)
    assert all(r["confidence"] in ("low", "nominal", "high") for r in rows)


def test_wind_real_response():
    rows = wind.parse(_fixture("openmeteo_2stations_2026-11-01.json"), [{"id": "a"}, {"id": "b"}])
    assert rows and {r["station_id"] for r in rows} == {"a", "b"}
    assert all(0 <= r["wind_dir"] < 360 for r in rows)


def test_firms_geometry():
    assert firms.haversine_km(28.6, 77.2, 28.6, 77.2) == 0
    assert firms.bearing_deg(28.6, 77.2, 29.6, 77.2) == pytest.approx(0, abs=0.5)
    assert firms.bearing_deg(28.6, 77.2, 28.6, 78.2) == pytest.approx(90, abs=1)


def test_wind_parse():
    st = [{"id": "a"}, {"id": "b"}]
    item = {"hourly": {"time": ["2026-11-01T00:00", "2026-11-01T01:00"],
                       "wind_speed_10m": [2.0, None], "wind_direction_10m": [370.0, 10.0],
                       "boundary_layer_height": [300.0, 250.0]}}
    rows = wind.parse([item, item], st)
    assert len(rows) == 2 and rows[0]["wind_dir"] == 10.0
    assert rows[0]["hour"] == datetime(2026, 11, 1, tzinfo=timezone.utc)
    with pytest.raises(http.BadResponse):
        wind.parse([item], st)
    with pytest.raises(http.BadResponse):
        wind.parse([{"error": True}, {"error": True}], st)


def test_traffic_prior_peaks():
    morning = traffic.prior(datetime(2026, 11, 1, 4, tzinfo=timezone.utc))   # 09:30 IST
    night = traffic.prior(datetime(2026, 11, 1, 21, tzinfo=timezone.utc))    # 02:30 IST
    assert morning > 0.9 and night < 0.4
