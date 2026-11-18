"""Report queue: eligibility, idempotency, approval whitelist."""

import pytest

from reporting import agencies, evidence, queue
from attribution.store import LocalStore


def rec(i="abcdef0123456789", conf="high", top="biomass_burning"):
    return {"id": i, "station_id": "a", "station_name": "Anand Vihar", "confidence": conf,
            "top_source": top, "shares": {top: 1.0}, "summary_en": "spike", "latitude": 28.64, "longitude": 77.31,
            "window_start": "2026-11-01T09:00:00+00:00", "window_end": "2026-11-01T11:00:00+00:00",
            "peak_pm25": 300, "baseline_pm25": 120, "excess_pm25": 180,
            "evidence": {"hourly": [{"hour": "2026-11-01T09:00:00+00:00", "pm25": 300, "base_pm25": 120},
                                    {"hour": "2026-11-01T10:00:00+00:00", "pm25": 280, "base_pm25": 118}]}}


def test_agency_map_single_primary():
    assert agencies.agencies_for("biomass_burning") == ("MCD",)
    assert agencies.agencies_for("dust") == ("DPCC",)
    assert agencies.agencies_for("regional_background") == ()


def test_recipients_only_verified():
    c = {"MCD": {"emails": ["m@x.in"], "verified": False},
         "CPCB": {"emails": ["c@x.in"], "verified": True},
         "DPCC": {"emails": ["d@x.in"], "verified": True}}
    assert agencies.recipients("DPCC", c) == (["d@x.in"], "DPCC")
    assert agencies.recipients("MCD", c) == (["c@x.in"], "CPCB")          # falls back to central intake
    c["CPCB"]["verified"] = False
    assert agencies.recipients("MCD", c) == ([], "MCD")


def test_shipped_contacts_are_unverified():
    """Nothing may be emailed until a human verifies an address."""
    for name, c in agencies.load_contacts().items():
        assert c["verified"] is False, name
        assert c["source_url"].startswith("https://")


def test_enqueue_only_high_local(tmp_path):
    s = LocalStore(str(tmp_path / "db"))
    recs = [rec(), rec("1" * 16, conf="medium"), rec("2" * 16, top="regional_background"),
            rec("3" * 16, top="transported_smoke")]
    rows = queue.enqueue(recs, store=s, root=str(tmp_path))
    assert [r["attribution_id"] for r in rows] == ["abcdef0123456789"]
    assert rows[0]["status"] == "pending" and rows[0]["kind"] == "spike"
    assert (tmp_path / "evidence" / "abcdef0123456789" / "chart.svg").exists()
    assert queue.enqueue(recs, store=s, root=str(tmp_path)) == []        # idempotent


def test_approve_reject_and_whitelist(tmp_path):
    s = LocalStore(str(tmp_path / "db"))
    queue.enqueue([rec()], store=s, root=str(tmp_path))
    with pytest.raises(ValueError):
        queue.approve("abc'; drop table x;--", "Shaurya", store=s)
    with pytest.raises(ValueError):
        queue.approve("abcdef0123456789", "x&y=1", store=s)
    queue.approve("abcdef0123456789", "Shaurya", store=s)
    assert s.select("complaint_queue")[0]["status"] == "approved"
    with pytest.raises(SystemExit):
        queue.reject("abcdef0123456789", "Shaurya", store=s)          # only pending/held can change


def test_chart_svg_empty_and_full():
    assert "<svg" in evidence.chart_svg([])
    assert "polyline" in evidence.chart_svg(rec()["evidence"]["hourly"])


def test_routing_uses_the_local_part_of_the_cause():
    from reporting.agencies import routing_source
    rec = {"top_source": "regional_background",
           "cause": {"local": {"share": 0.45, "top": "industry"}, "regional": {"share": 0.55}}}
    assert routing_source(rec) == "industry"
    rec["cause"]["local"]["share"] = 0.2
    assert routing_source(rec) == "regional_background"
    assert routing_source({"top_source": "traffic"}) == "traffic"
    assert routing_source({"top_source": "dust", "cause": "{not json"}) == "dust"
