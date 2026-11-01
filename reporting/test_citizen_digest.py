"""Citizen clusters and daily digests: the autonomous reporting path."""

from datetime import datetime, timedelta, timezone

import pytest

from attribution.store import LocalStore
from reporting import citizen, digest

NOW = datetime(2026, 11, 1, 6, tzinfo=timezone.utc)


def report(i, ptype="burning", lat=28.5500, lon=77.2700, caller=None, minutes=60):
    return {"id": f"r{i}", "call_id": f"c{i}", "caller_number": caller or f"h{i}", "neighborhood": "Okhla",
            "latitude": lat, "longitude": lon, "pollution_type": ptype, "description": f"smoke {i}",
            "timestamp": (NOW - timedelta(minutes=minutes)).isoformat()}


def test_cluster_needs_three_distinct_callers(tmp_path):
    s = LocalStore(str(tmp_path))
    s.upsert("citizen_reports", [report(1), report(2, caller="h1"), report(3, caller="h1")])
    assert citizen.enqueue_clusters(store=s, now=NOW, attributions=[]) == []   # one caller x3
    s.upsert("citizen_reports", [report(4), report(5, lat=28.556)])
    rows = citizen.enqueue_clusters(store=s, now=NOW, attributions=[])
    assert len(rows) == 1 and rows[0]["agencies"] == ["MCD"] and rows[0]["kind"] == "citizen"
    assert citizen.enqueue_clusters(store=s, now=NOW, attributions=[]) == []   # idempotent


def test_single_report_corroborated_by_station(tmp_path):
    s = LocalStore(str(tmp_path))
    s.upsert("citizen_reports", [report(1), report(2, ptype="other"), report(3, ptype="dust", lat=28.7)])
    attr = [{"station_id": "okhla", "latitude": 28.5308, "longitude": 77.2713,
             "window_end": NOW.isoformat(), "shares": {"biomass_burning": 0.6}, "summary_en": "spike"}]
    rows = citizen.enqueue_clusters(store=s, now=NOW, attributions=attr)
    assert len(rows) == 1 and "station data agrees" in rows[0]["summary"]


def _queue(s, status="pending", conf="high", agency="DPCC", i="a" * 16, created=NOW):
    s.upsert("complaint_queue", [{"attribution_id": i, "kind": "spike", "agencies": [agency],
                                  "top_source": "industry", "confidence": conf, "latitude": 28.53,
                                  "longitude": 77.27, "summary": "SO2 spike at Okhla", "evidence_md": "x",
                                  "status": status, "created_at": created.isoformat(),
                                  "approved_by": "Shaurya" if status == "approved" else None}])


VERIFIED = {"DPCC": {"emails": ["d@x.in"], "verified": True}, "CPCB": {"emails": ["c@x.in"], "verified": False}}


def test_manual_mode_sends_only_approved(tmp_path, monkeypatch):
    monkeypatch.delenv("KAUN_AUTO_SEND", raising=False)
    s = LocalStore(str(tmp_path))
    _queue(s)
    sent = []
    cfg = {"SMTP_HOST": "h", "SMTP_USER": "u", "SMTP_PASSWORD": "p"}
    monkeypatch.setattr(digest, "smtp_config", lambda: {**cfg, "SMTP_PORT": 465, "REPORT_FROM": "u"})
    out = digest.run(store=s, now=NOW, outbox=str(tmp_path / "o"), contacts=VERIFIED,
                     sender=lambda c, to, sub, body: sent.append(to) or "<id>")
    assert sent == [] and out["sent"] == []
    _queue(s, status="approved", i="b" * 16)
    out = digest.run(store=s, now=NOW, outbox=str(tmp_path / "o"), contacts=VERIFIED,
                     sender=lambda c, to, sub, body: sent.append((to, body)) or "<id>")
    assert len(sent) == 1 and sent[0][0] == ["d@x.in"] and "VV-" + "b" * 16 in sent[0][1]
    assert "VV-" + "a" * 16 not in sent[0][1]


def test_auto_mode_caps_and_no_double_send(tmp_path, monkeypatch):
    monkeypatch.setenv("KAUN_AUTO_SEND", "1")
    s = LocalStore(str(tmp_path))
    for k in range(15):
        _queue(s, i=f"{k:016x}")
    _queue(s, conf="medium", i="f" * 16)
    sent = []
    monkeypatch.setattr(digest, "smtp_config", lambda: {"SMTP_HOST": "h", "SMTP_USER": "u", "SMTP_PASSWORD": "p",
                                                        "SMTP_PORT": 465, "REPORT_FROM": "u"})
    snd = lambda c, to, sub, body: sent.append(body) or "<id>"
    out = digest.run(store=s, now=NOW, outbox=str(tmp_path / "o"), contacts=VERIFIED, sender=snd)
    assert len(sent) == 1 and sent[0].count("Reference: VV-") == digest.MAX_ITEMS
    assert "f" * 16 not in sent[0]                                   # medium never auto-sent
    out = digest.run(store=s, now=NOW, outbox=str(tmp_path / "o"), contacts=VERIFIED, sender=snd)
    assert len(sent) == 1 and out["skipped"][0]["reason"] == "already sent today"


def test_auto_mode_unverified_holds(tmp_path, monkeypatch):
    monkeypatch.setenv("KAUN_AUTO_SEND", "1")
    s = LocalStore(str(tmp_path))
    _queue(s, agency="MCD")
    monkeypatch.setattr(digest, "smtp_config", lambda: {"SMTP_HOST": "h", "SMTP_USER": "u", "SMTP_PASSWORD": "p",
                                                        "SMTP_PORT": 465, "REPORT_FROM": "u"})
    out = digest.run(store=s, now=NOW, outbox=str(tmp_path / "o"), contacts=VERIFIED,
                     sender=lambda *a: pytest.fail("must not send"))
    assert out["held"] and s.select("complaint_queue")[0]["status"] == "held"


def test_auto_mode_without_smtp_fails_loudly(tmp_path, monkeypatch):
    monkeypatch.setenv("KAUN_AUTO_SEND", "1")
    monkeypatch.setattr(digest, "smtp_config", lambda: None)
    with pytest.raises(SystemExit):
        digest.run(store=LocalStore(str(tmp_path)), now=NOW, outbox=str(tmp_path / "o"), contacts=VERIFIED)


def test_pause_and_dry_run(tmp_path, monkeypatch):
    monkeypatch.setenv("KAUN_AUTO_SEND", "1")
    monkeypatch.setenv("KAUN_REPORTS_PAUSED", "1")
    s = LocalStore(str(tmp_path))
    _queue(s)
    out = digest.run(store=s, now=NOW, outbox=str(tmp_path / "o"), contacts=VERIFIED,
                     sender=lambda *a: pytest.fail("paused"))
    assert out["skipped"][0]["reason"] == "paused"
    assert (tmp_path / "o").exists()


def test_stale_items_dropped(tmp_path, monkeypatch):
    monkeypatch.setenv("KAUN_AUTO_SEND", "1")
    s = LocalStore(str(tmp_path))
    _queue(s, created=NOW - timedelta(days=5))
    monkeypatch.setattr(digest, "smtp_config", lambda: {"SMTP_HOST": "h", "SMTP_USER": "u", "SMTP_PASSWORD": "p",
                                                        "SMTP_PORT": 465, "REPORT_FROM": "u"})
    out = digest.run(store=s, now=NOW, outbox=str(tmp_path / "o"), contacts=VERIFIED,
                     sender=lambda *a: pytest.fail("stale"))
    assert out["sent"] == []
