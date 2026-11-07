"""Feed and voice tests."""

import json
from datetime import datetime, timezone

import pytest

from attribution.publish import feed, voice

NOW = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)


def rec(**kw):
    base = {"id": "abcdef0123456789", "station_id": "a", "station_name": "Anand Vihar, Delhi - DPCC",
            "latitude": 28.6468, "longitude": 77.316,
            "window_start": "2026-11-01T09:00:00+00:00", "window_end": "2026-11-01T11:00:00+00:00",
            "shares": {"biomass_burning": 0.6, "regional_background": 0.4}, "top_source": "biomass_burning",
            "sector": "E", "confidence": "medium", "summary_en": "x", "summary_hi": "y",
            "evidence": {"ratios": {}, "hourly": []}}
    base.update(kw)
    return base


def test_feed_refuses_missing_confidence():
    with pytest.raises(ValueError):
        feed.build([rec(confidence=None)], {}, now=NOW)
    with pytest.raises(ValueError):
        feed.build([rec(synthetic=True)], {}, now=NOW)


def test_feed_latest_per_station_and_write(tmp_path):
    older = rec(id="1" * 16, window_start="2026-11-01T01:00:00+00:00", window_end="2026-11-01T02:00:00+00:00")
    stale = rec(id="2" * 16, window_start="2026-10-01T01:00:00+00:00", window_end="2026-10-01T02:00:00+00:00")
    f = feed.build([older, rec(), stale], {"a": {"name": "A", "latitude": 1, "longitude": 2}}, now=NOW)
    assert len(f["latest"]["attributions"]) == 1
    assert f["latest"]["attributions"][0]["window_end"].startswith("2026-11-01T11")
    assert len(f["history"]["attributions"]) == 2
    paths = feed.write(f, root=str(tmp_path))
    assert json.loads(open(paths[0], encoding="utf-8").read())["disclaimer"]


def test_feed_accepts_json_string_shares():
    f = feed.build([rec(shares=json.dumps({"dust": 1.0}), evidence=json.dumps({"ratios": {}}))], {}, now=NOW)
    assert f["latest"]["attributions"][0]["shares"] == {"dust": 1.0}


def test_voice_answer_en_hi():
    en = voice.answer(28.65, 77.31, "en", records=[rec()], now=NOW)
    assert "60 percent" in en and "biomass" in en and "east" in en and "medium" in en
    hi = voice.answer(28.65, 77.31, "hi", records=[rec()], now=NOW)
    assert "पूर्व" in hi and "मध्यम" in hi


def test_voice_low_confidence_hedged_and_out_of_range():
    assert voice.answer(28.65, 77.31, "en", records=[rec(confidence="low")], now=NOW).count("Possibly") == 1
    assert voice.answer(28.40, 76.90, "en", records=[rec()], now=NOW) is None      # far away
    late = datetime(2026, 11, 2, 12, tzinfo=timezone.utc)
    assert voice.answer(28.65, 77.31, "en", records=[rec()], now=late) is None      # too old


def test_voice_fast_enough():
    import time
    recs = [rec(id=f"{i:016x}", latitude=28.5 + i * 0.001) for i in range(2000)]
    t = time.perf_counter()
    voice.answer(28.6, 77.3, "hi", records=recs, now=NOW)
    assert time.perf_counter() - t < 0.5  # VAPI webhook budget is 2 s end to end


def test_advisory_appends_kaun_line(monkeypatch):
    from advisory import generator
    monkeypatch.setattr("attribution.publish.voice.load_latest", lambda path=None: [rec()])
    monkeypatch.setattr("attribution.publish.voice.datetime",
                        type("D", (datetime,), {"now": staticmethod(lambda tz=None: NOW)}))
    out = generator.with_kaun("Air is poor.", 28.65, 77.31, "en")
    assert out.startswith("Air is poor. ") and "biomass" in out
    assert generator.with_kaun("Air is poor.", None, None, "en") == "Air is poor."
