"""Tests for the HTTP helper, checkpoint, store, and the hourly runner wiring."""

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from attribution import http, run, synthetic
from attribution.checkpoint import Checkpoint
from attribution.store import LocalStore, clean_rows


class FakeResp:
    def __init__(self, code, text=""):
        self.status_code, self.text = code, text

    def json(self):
        import json
        return json.loads(self.text)


class FakeSession:
    def __init__(self, *resps):
        self.resps = list(resps)
        self.calls = 0

    def get(self, *a, **k):
        self.calls += 1
        return self.resps.pop(0)


def test_http_status_mapping(monkeypatch):
    monkeypatch.setattr(http.time, "sleep", lambda s: None)
    with pytest.raises(http.AuthError):
        http.get("u", session=FakeSession(FakeResp(401)))
    with pytest.raises(http.RateLimited):
        http.get("u", session=FakeSession(FakeResp(429)))
    with pytest.raises(http.RateLimited):
        http.get("u", session=FakeSession(FakeResp(451)))
    with pytest.raises(http.BadResponse):
        http.get("u", session=FakeSession(FakeResp(404, "nope")))
    s = FakeSession(FakeResp(503), FakeResp(200, '{"ok": 1}'))
    assert http.get_json("u", session=s) == {"ok": 1} and s.calls == 2
    with pytest.raises(http.BadResponse):
        http.get_json("u", session=FakeSession(FakeResp(200, "<html>")))
    with pytest.raises(http.BadResponse):
        http.get_json("u", session=FakeSession(FakeResp(200, "  ")))


def test_checkpoint_roundtrip_and_corruption(tmp_path):
    p = tmp_path / "c.json"
    c = Checkpoint(str(p))
    t = datetime(2026, 11, 1, 5, tzinfo=timezone.utc)
    c.set("ingest", t)
    assert Checkpoint(str(p)).get("ingest") == t
    p.write_text("{broken")
    assert Checkpoint(str(p)).get("ingest") is None


def test_local_store_idempotent_upsert_and_whitelist(tmp_path):
    s = LocalStore(str(tmp_path))
    h = datetime(2026, 11, 1, tzinfo=timezone.utc)
    s.upsert("hourly_obs", [{"station_id": "a", "hour": h, "pm25": 10.0}])
    s.upsert("hourly_obs", [{"station_id": "a", "hour": h, "pm25": 12.0}])
    rows = s.select("hourly_obs")
    assert len(rows) == 1 and rows[0]["pm25"] == 12.0
    assert s.select("hourly_obs", {"hour": f"gte.{(h + timedelta(hours=1)).isoformat()}"}) == []
    with pytest.raises(ValueError):
        s.upsert("users; drop table x", [{"a": 1}])


def test_clean_rows_strips_nan_recursively():
    out = clean_rows([{"a": float("nan"), "ev": {"x": [float("nan"), 1.0]}}])
    assert out == [{"a": None, "ev": {"x": [None, 1.0]}}]


def test_merge_sources_prefers_openaq():
    h = datetime(2026, 11, 1, tzinfo=timezone.utc)
    oa = [{"station_id": "a", "hour": h, "pm25": 100.0, "so2": None, "source": "openaq"}]
    cp = [{"station_id": "a", "hour": h, "pm25": 999.0, "so2": 8.0, "source": "cpcb"},
          {"station_id": "b", "hour": h, "pm25": 50.0, "source": "cpcb"}]
    m = {r["station_id"]: r for r in run.merge_sources(oa, cp)}
    assert m["a"]["pm25"] == 100.0 and m["a"]["so2"] == 8.0 and m["a"]["source"] == "openaq+cpcb"
    assert m["b"]["pm25"] == 50.0


def test_hourly_end_to_end_offline(tmp_path, monkeypatch):
    """Runner wiring: ingest (stubbed) -> attribute -> queue -> publish, checkpoints advance."""
    monkeypatch.setenv("KAUN_STORE", "local")
    monkeypatch.setattr("attribution.store.STATE_DIR", str(tmp_path))
    monkeypatch.setattr("attribution.checkpoint.STATE_DIR", str(tmp_path))
    monkeypatch.setattr("attribution.publish.feed.PUBLIC_DIR", str(tmp_path / "public"))
    monkeypatch.setattr("attribution.publish.now.PUBLIC_DIR", str(tmp_path / "public"))
    monkeypatch.setattr("reporting.evidence.STATE_DIR", str(tmp_path))

    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    obs, wind = synthetic.generate(end=now)

    def fake_ingest(store, ckpt, since, until, archive=False):
        store.upsert("kaun_stations", [{"id": k, **v, "active": True} for k, v in synthetic.STATIONS.items()])
        store.upsert("hourly_obs", obs.to_dict("records"))
        store.upsert("wind_obs", wind.to_dict("records"))
        return {"obs": len(obs)}

    monkeypatch.setattr(run, "ingest", fake_ingest)
    monkeypatch.setattr(run, "DEFAULT_LOOKBACK_HOURS", 72)  # synthetic spikes are 1-2 days back; keep them in the window at any hour
    monkeypatch.setattr("attribution.ingest.landuse.refresh", lambda store, stations, **k: 0)  # no network in tests
    args = type("A", (), {"skip_preflight": True})()
    assert run.hourly(args) == 0

    import json
    feed = json.loads((tmp_path / "public" / "data" / "latest.json").read_text())
    assert feed["attributions"], "expected recent attributions in the feed"
    assert all(a["confidence"] in ("low", "medium", "high") for a in feed["attributions"])
    now_feed = json.loads((tmp_path / "public" / "data" / "now.json").read_text())
    assert now_feed["stations"] and all(s["aqi"] for s in now_feed["stations"])
    ck = Checkpoint(str(tmp_path / "checkpoint.json"))
    assert ck.get("ingest") == now and ck.get("publish") == now
    q = LocalStore(str(tmp_path / "db")).select("complaint_queue")
    assert q and all(r["status"] == "pending" for r in q)


def test_hourly_rate_limit_keeps_checkpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("KAUN_STORE", "local")
    monkeypatch.setattr("attribution.store.STATE_DIR", str(tmp_path))
    monkeypatch.setattr("attribution.checkpoint.STATE_DIR", str(tmp_path))

    def boom(*a, **k):
        raise http.RateLimited("429")

    monkeypatch.setattr(run, "ingest", boom)
    args = type("A", (), {"skip_preflight": True})()
    assert run.hourly(args) == run.EXIT_RATE
    assert Checkpoint(str(tmp_path / "checkpoint.json")).get("ingest") is None


def _offline_preflight(monkeypatch):
    """FIRMS/OpenAQ probes stubbed out so only the Supabase branch is exercised."""
    from attribution import preflight
    monkeypatch.setattr(preflight.http, "get_json", lambda *a, **k: {})
    return preflight


def test_preflight_skips_supabase_with_local_store(monkeypatch):
    preflight = _offline_preflight(monkeypatch)
    monkeypatch.setenv("KAUN_STORE", "local")
    monkeypatch.setenv("SUPABASE_URL", "https://nonexistent-ref.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "x")

    def no_network(*a, **k):
        raise AssertionError("Supabase must not be probed when KAUN_STORE=local")

    monkeypatch.setattr(preflight, "SupabaseStore", no_network)
    assert preflight.check(require_firms=False) == []


def test_preflight_reports_unresolvable_supabase(monkeypatch):
    import requests
    preflight = _offline_preflight(monkeypatch)
    monkeypatch.delenv("KAUN_STORE", raising=False)
    monkeypatch.setenv("SUPABASE_URL", "https://nonexistent-ref.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "x")

    class DeadStore:
        def select(self, *a, **k):
            raise requests.exceptions.ConnectionError("Failed to resolve host")

    monkeypatch.setattr(preflight, "SupabaseStore", DeadStore)
    problems = preflight.check(require_firms=False)
    assert len(problems) == 1 and "unreachable" in problems[0]


def test_http_sends_identifying_user_agent(monkeypatch):
    seen = {}

    class Resp:
        status_code = 200
        text = "{}"

        def json(self):
            return {}

    def fake_get(url, params=None, headers=None, timeout=None):
        seen.update(headers or {})
        return Resp()

    monkeypatch.setattr(http.requests, "get", fake_get)
    http.get("https://example.org", headers={"X-API-Key": "k"}, retries=1)
    assert seen["User-Agent"].startswith("VayuVani-Kaun/")
    assert seen["X-API-Key"] == "k"
