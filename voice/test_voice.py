"""Phone line: geocoding, spoken answers, VAPI webhook shapes, citizen reports."""

import json
import time
from datetime import datetime, timedelta, timezone

import pytest

from voice import feeds, geocode, service, vapi

NOW = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
STATIONS = [
    {"id": "anand-vihar-new-delhi-dpcc", "name": "Anand Vihar, New Delhi - DPCC", "latitude": 28.6468,
     "longitude": 77.3160, "aqi": 412, "category": "Severe", "dominant_pollutant": "pm25", "stale": False,
     "latest_hour": NOW.isoformat()},
    {"id": "r-k-puram-delhi-dpcc", "name": "R K Puram, Delhi - DPCC", "latitude": 28.5633,
     "longitude": 77.1869, "aqi": 280, "category": "Poor", "dominant_pollutant": "pm10", "stale": False,
     "latest_hour": NOW.isoformat()},
    {"id": "dead", "name": "Dead station", "latitude": 28.65, "longitude": 77.31, "aqi": 50,
     "category": "Good", "dominant_pollutant": "pm25", "stale": True},
]
ATTR = [{"station_id": "anand-vihar-new-delhi-dpcc", "station_name": "Anand Vihar, New Delhi - DPCC",
         "latitude": 28.6468, "longitude": 77.3160, "window_start": (NOW - timedelta(hours=3)).isoformat(),
         "window_end": (NOW - timedelta(hours=1)).isoformat(), "shares": {"biomass_burning": 0.7, "regional_background": 0.3},
         "top_source": "biomass_burning", "sector": "E", "confidence": "medium"}]


@pytest.fixture(autouse=True)
def feeds_stub(monkeypatch):
    feeds.clear_cache()
    data = {"now.json": {"stations": STATIONS}, "latest.json": {"attributions": ATTR}}
    monkeypatch.setattr(feeds, "load", lambda name, timeout=1.0: data.get(name))
    yield


@pytest.mark.parametrize("said,label", [
    ("Anand Vihar", "Anand Vihar"), ("आनंद विहार", "Anand Vihar"), ("near anand vihar area", "Anand Vihar"),
    ("CP", "Connaught Place"), ("r k puram", "R K Puram"), ("Anand Vihaar", "Anand Vihar"),
    ("Okhla", "Okhla"), ("Mundka", None),
])
def test_local_geocode(said, label):
    hit = geocode.local(said, STATIONS)
    assert (hit or {}).get("label") == label


def test_station_names_join_gazetteer():
    st = [{"name": "Mundka, Delhi - DPCC", "latitude": 28.68, "longitude": 77.08}]
    assert geocode.local("mundka", st)["method"] == "station"


def test_air_quality_english_with_source():
    out = service.get_air_quality("Anand Vihar", "en", allow_network=False)
    assert out["ok"] and out["aqi"] == 412
    s = out["speech"]
    assert "AQI 412" in s and "Severe" in s and "biomass" in s and "east" in s and "\n" not in s


def test_air_quality_hindi_no_spike():
    out = service.get_air_quality("आरके पुरम", "hi", allow_network=False)
    assert out["ok"] and out["aqi"] == 280
    assert "खराब" in out["speech"] and "असामान्य" in out["speech"]


def test_low_confidence_not_spoken(monkeypatch):
    low = [dict(ATTR[0], confidence="low")]
    monkeypatch.setattr(feeds, "load", lambda name, timeout=1.0: {"now.json": {"stations": STATIONS},
                                                                   "latest.json": {"attributions": low}}.get(name))
    out = service.get_air_quality("Anand Vihar", "en", allow_network=False)
    assert "biomass" not in out["speech"] and "No unusual spike" in out["speech"]


def test_air_quality_failures():
    assert not service.get_air_quality("Xyzzyville", "en", allow_network=False)["ok"]


def test_air_quality_fast():
    t = time.perf_counter()
    for _ in range(50):
        service.get_air_quality("Anand Vihar", "hi", allow_network=False)
    assert (time.perf_counter() - t) / 50 < 0.05


def test_report_whitelists_type_and_hashes_number(monkeypatch):
    saved = {}
    monkeypatch.setattr(service, "_supabase_insert", lambda t, row, timeout=1.5: saved.update(row) or True)
    out = service.report_pollution("Okhla", "burning'; drop", "smoke from dump", "en",
                                   call_id="c1", caller="+919999999999", allow_network=False)
    assert out["ok"] and saved["pollution_type"] == "other"
    assert saved["caller_number"] != "+919999999999" and len(saved["caller_number"]) == 16
    out = service.report_pollution("Okhla", "burning", "", "hi", allow_network=False)
    assert saved["pollution_type"] == "burning" and "धन्यवाद" in out["speech"]


def test_report_db_down_is_honest(monkeypatch):
    monkeypatch.setattr(service, "_supabase_insert", lambda *a, **k: False)
    out = service.report_pollution("Okhla", "dust", "", "en", allow_network=False)
    assert not out["ok"] and "could not" in out["speech"]


def _msg(calls, key="toolCallList"):
    return {"message": {"type": "tool-calls", key: calls, "call": {"id": "call1", "customer": {"number": "+91"}}}}


def test_vapi_webhook_shapes():
    c1 = {"id": "t1", "type": "function", "function": {"name": "get_air_quality",
                                                       "arguments": {"location": "Anand Vihar", "language": "en"}}}
    c2 = {"id": "t2", "function": {"name": "get_air_quality", "arguments": json.dumps({"location": "CP", "language": "hi"})}}
    for key in ("toolCallList", "toolCalls"):
        code, out = vapi.handle(json.dumps(_msg([c1, c2], key)), {}, allow_network=False)
        assert code == 200 and [r["toolCallId"] for r in out["results"]] == ["t1", "t2"]
        assert all(isinstance(r["result"], str) and "\n" not in r["result"] for r in out["results"])
    code, out = vapi.handle(_msg([{"id": "x", "name": "rm_rf", "arguments": {}}]), {}, allow_network=False)
    assert out["results"][0]["result"] == "Unknown tool."


def test_vapi_ignores_other_events_and_bad_json():
    assert vapi.handle({"message": {"type": "status-update"}}, {}) == (200, {})
    assert vapi.handle(b"{nope", {})[0] == 400


def test_vapi_secret(monkeypatch):
    monkeypatch.setenv("VAPI_SERVER_SECRET", "s3cret")
    assert vapi.handle(_msg([]), {})[0] == 401
    assert vapi.handle(_msg([]), {"X-Vapi-Secret": "s3cret"})[0] == 200


def test_vapi_tool_crash_still_answers(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(service, "get_air_quality", boom)
    c = {"id": "t1", "function": {"name": "get_air_quality", "arguments": {"location": "x"}}}
    code, out = vapi.handle(_msg([c]), {}, allow_network=False)
    assert code == 200 and "Sorry" in out["results"][0]["result"]


def test_webhook_imports_stay_stdlib():
    import subprocess, sys
    code = ("import sys; import voice.vapi; "
            "bad=[m for m in ('numpy','pandas','requests','groq','supabase','dotenv') if m in sys.modules]; "
            "print(','.join(bad)); sys.exit(1 if bad else 0)")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=__import__("os").path.dirname(__file__) + "/..")
    assert r.returncode == 0, r.stdout + r.stderr
