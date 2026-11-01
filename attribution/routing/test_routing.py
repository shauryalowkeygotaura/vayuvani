"""Complaint queue: only human-approved items ever reach the outbox."""

import pytest

from attribution.routing import agencies, evidence, queue
from attribution.store import LocalStore


def rec(i="abcdef0123456789", conf="high", top="biomass_burning"):
    return {"id": i, "station_id": "a", "station_name": "Anand Vihar", "confidence": conf,
            "top_source": top, "shares": {top: 1.0}, "summary_en": "spike",
            "window_start": "2026-11-01T09:00:00+00:00", "window_end": "2026-11-01T11:00:00+00:00",
            "peak_pm25": 300, "baseline_pm25": 120, "excess_pm25": 180,
            "evidence": {"hourly": [{"hour": "2026-11-01T09:00:00+00:00", "pm25": 300, "base_pm25": 120},
                                    {"hour": "2026-11-01T10:00:00+00:00", "pm25": 280, "base_pm25": 118}]}}


def test_agency_map():
    assert agencies.agencies_for("biomass_burning") == ("MCD",)
    assert agencies.agencies_for("dust") == ("DPCC", "MCD")
    assert agencies.agencies_for("regional_background") == ()


def test_enqueue_only_high_local(tmp_path):
    s = LocalStore(str(tmp_path / "db"))
    recs = [rec(), rec("1" * 16, conf="medium"), rec("2" * 16, top="regional_background"),
            rec("3" * 16, top="transported_smoke")]
    rows = queue.enqueue(recs, store=s, root=str(tmp_path))
    assert [r["attribution_id"] for r in rows] == ["abcdef0123456789"]
    assert rows[0]["status"] == "pending"
    assert (tmp_path / "evidence" / "abcdef0123456789" / "chart.svg").exists()
    assert queue.enqueue(recs, store=s, root=str(tmp_path)) == []        # idempotent


def test_nothing_sent_without_approval(tmp_path):
    s = LocalStore(str(tmp_path / "db"))
    queue.enqueue([rec()], store=s, root=str(tmp_path))
    assert queue.send_approved(store=s, outbox=str(tmp_path / "out")) == []
    queue.approve("abcdef0123456789", "Shaurya", store=s)
    out = queue.send_approved(store=s, outbox=str(tmp_path / "out"))
    assert len(out) == 1
    text = open(out[0], encoding="utf-8").read()
    assert "Approved by: Shaurya" in text and "<verify contact for MCD>" in text
    assert s.select("complaint_queue")[0]["status"] == "ready_to_send"


def test_approve_whitelist(tmp_path):
    s = LocalStore(str(tmp_path / "db"))
    with pytest.raises(ValueError):
        queue.approve("abc'; drop table x;--", "Shaurya", store=s)
    with pytest.raises(ValueError):
        queue.approve("abcdef0123456789", "x&y=1", store=s)


def test_chart_svg_empty_and_full():
    assert "<svg" in evidence.chart_svg([])
    assert "polyline" in evidence.chart_svg(rec()["evidence"]["hourly"])
